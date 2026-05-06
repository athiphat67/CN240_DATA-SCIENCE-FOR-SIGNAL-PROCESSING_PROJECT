"""
scheduler/orchestrator.py — Phase 10: Scheduler Orchestrator

Three APScheduler jobs that wire all phases into a live trading system:

  Job A — Signal Pipeline  (cron: every 10 min at :00 :10 :20 :30 :40 :50)
    candle_builder → feature_engine → model_inference → signal_gate
    → order_simulator → tp_sl_calculator → supabase_writer → discord

  Job B — Position Monitor (interval: every 1 minute)
    fetch_latest_bid → monitor_positions → close_position → discord

  Job C — Heartbeat        (cron: every hour at :00)
    Status ping during market hours → discord

Startup:
  scheduler = BlockingScheduler(timezone=TIMEZONE)
  Import this module in main.py and call scheduler.start()

Idempotency & safety:
  • Signal IDs are PRIMARY KEY in Supabase — duplicate runs are harmless
  • Job A skips on session="Closed" (early-return after feature computation)
  • Job A skips on tp_sl_valid=False (ATR too small/large for safe trading)
  • Job B skips when no open positions exist (zero-cost check)
  • All exceptions are caught per-job — one failure never stops the scheduler

DRY_RUN:
  • All Supabase writes are no-ops (logged only)
  • Discord messages are prefixed "[DRY RUN]"
  • count_open_positions() always returns 0 → gate always passes
"""

from __future__ import annotations

import logging
from datetime import datetime

import pytz
from apscheduler.schedulers.blocking import BlockingScheduler

from config.settings import (
    DISCORD_MENTION_ID,
    DRY_RUN,
    TIMEZONE,
)

logger  = logging.getLogger("system")
TZ      = pytz.timezone(TIMEZONE)

# ─── Module-level state ───────────────────────────────────────────────────────

_bars_run: int = 0  # total signal-pipeline runs since startup (for heartbeat)

# ─── Scheduler instance (imported by main.py) ─────────────────────────────────

scheduler = BlockingScheduler(timezone=TIMEZONE)


# ─── Job A: Signal Pipeline ───────────────────────────────────────────────────

@scheduler.scheduled_job(
    "cron",
    minute="0,10,20,30,40,50",
    id="signal_pipeline",
    max_instances=1,          # prevent overlap if pipeline takes > 10 min
    coalesce=True,            # skip missed fires (e.g. after sleep/restart)
)
def run_signal_pipeline() -> None:
    """
    Full signal pipeline — runs at every M10 bar boundary.

    Flow:
      1. Build M10 candles              (Phase 1)
      2. Compute features               (Phase 2)
      3. Run model inference            (Phase 3)
      4. Evaluate signal gate           (Phase 4)
      5. Log bar + signal to Supabase   (Phase 8)
      6. If signal passed:
         a. Simulate buy order          (Phase 5)
         b. Calculate TP/SL             (Phase 6)
         c. Validate tp_sl_valid        (Phase 6)
         d. Insert position             (Phase 8)
         e. Send Discord BUY alert      (Phase 9)
    """
    global _bars_run

    # ── Lazy imports (avoid circular at module level) ─────────────────────────
    from core.candle_builder import build_m10_candles
    from core.feature_engine import compute_features
    from core.model_inference import run_inference
    from core.signal_gate import evaluate_signal_gate
    from core.order_simulator import simulate_buy
    from core.tp_sl_calculator import calculate_tp_sl
    from db.supabase_writer import insert_signal, insert_position, insert_bar_log
    from notifier.discord_notifier import (
        send_discord,
        send_discord_buy_alert,
        send_discord_error,
    )

    try:
        # ── 1. Build candles ──────────────────────────────────────────────────
        candles_df = build_m10_candles()

        # ── 2. Compute features ───────────────────────────────────────────────
        features_row = compute_features(candles_df)

        # ── Early-return on closed market (gate will also catch this,
        #    but skip model inference + DB write to save compute) ──────────────
        if features_row["session"] == "Closed":
            logger.debug("[orchestrator] Market closed — skipping pipeline")
            return

        _bars_run += 1

        # ── 3. Model inference ────────────────────────────────────────────────
        inference_result = run_inference(features_row)

        # ── 4. Signal gate ────────────────────────────────────────────────────
        signal = evaluate_signal_gate(inference_result, features_row)

        # ── 5. Persist bar log + signal (every bar, regardless of passed) ─────
        insert_bar_log(features_row, signal)
        insert_signal(signal)

        # ── 6. Open position only if signal passed ────────────────────────────
        if not signal["passed"]:
            logger.info(
                f"[orchestrator] Signal REJECTED: {signal['reject_reason']} "
                f"score={signal['ranker_score']:.4f} bar={signal['bar_time']}"
            )
            return

        # ── 6a. Simulate buy ──────────────────────────────────────────────────
        order = simulate_buy(
            ask_price      = features_row["hsh_close_ask"],
            bid_price      = features_row["hsh_close_bid"],
            signal_id      = signal["signal_id"],
            entry_time     = datetime.now(TZ),
        )

        # ── 6b. Calculate TP/SL ───────────────────────────────────────────────
        order = calculate_tp_sl(order, features_row["F_ATR_48"])

        # ── 6c. Validate TP/SL ────────────────────────────────────────────────
        if not order["tp_sl_valid"]:
            logger.info(
                f"[orchestrator] Position skipped — invalid TP/SL: "
                f"ATR={features_row['F_ATR_48']:.2f} pos={order['position_id']}"
            )
            return

        # ── 6d. Persist position ──────────────────────────────────────────────
        insert_position(order)

        # ── 6e. Discord BUY alert ─────────────────────────────────────────────
        send_discord_buy_alert(order, signal)

        logger.info(
            f"[orchestrator] ✅ Position OPENED: {order['position_id']} "
            f"ask={order['entry_ask_price']:,.2f} "
            f"TP={order['tp_bid_price']:,.2f} SL={order['sl_bid_price']:,.2f}"
        )

    except Exception as exc:
        logger.exception(f"[orchestrator] Job A (signal_pipeline) failed: {exc}")
        try:
            from notifier.discord_notifier import send_discord_error
            send_discord_error(str(exc))
        except Exception:
            pass  # Discord alert failure must never crash the scheduler


# ─── Job B: Position Monitor ──────────────────────────────────────────────────

@scheduler.scheduled_job(
    "interval",
    minutes=1,
    id="position_monitor",
    max_instances=1,
    coalesce=True,
)
def run_position_monitor() -> None:
    """
    Position monitor — runs every 1 minute.

    Flow:
      1. Fetch open positions (skip if none)
      2. Fetch latest bid
      3. Check TP / SL / SESSION_END conditions
      4. Close triggered positions in Supabase
      5. Send Discord close alert
    """
    from db.supabase_writer import (
        fetch_open_positions_from_supabase,
        close_position,
    )
    from core.candle_builder import fetch_latest_bid
    from core.position_monitor import monitor_positions
    from notifier.discord_notifier import send_discord_close_alert

    try:
        # Quick path: no open positions → nothing to do
        open_positions = fetch_open_positions_from_supabase()
        if not open_positions:
            return

        # Build a lookup dict for Discord alert (needs entry_time etc.)
        pos_map: dict[str, dict] = {p["id"]: p for p in open_positions}

        current_bid  = fetch_latest_bid()
        current_time = datetime.now(TZ)

        close_events = monitor_positions(current_bid, current_time)

        for event in close_events:
            position_id = event["position_id"]
            pos_record  = pos_map.get(position_id, {})

            # ── Update Supabase ───────────────────────────────────────────────
            close_position(position_id, event)

            # ── Discord close alert ───────────────────────────────────────────
            send_discord_close_alert(event, pos_record)

            logger.info(
                f"[orchestrator] Position CLOSED: {position_id} "
                f"reason={event['close_reason']} "
                f"pnl={event['realized_pnl_thb']:+.4f} THB"
            )

    except Exception as exc:
        logger.exception(f"[orchestrator] Job B (position_monitor) failed: {exc}")
        # Position monitor failures are NOT sent to Discord to avoid noise
        # (bid fetch errors are transient; system will retry next minute)


# ─── Job C: Heartbeat ─────────────────────────────────────────────────────────

@scheduler.scheduled_job(
    "cron",
    minute=0,
    id="heartbeat",
    max_instances=1,
)
def run_heartbeat() -> None:
    """
    Hourly heartbeat during market hours.

    Sends a lightweight Discord ping so the team knows the system is alive.
    Silent when market is closed (no ping during off-hours).

    Format:
      💚 HSH Trader [LIVE/DRY RUN] — HH:MM · Session · X bars run · N open positions
    """
    from core.position_monitor import is_market_hours, get_current_session
    from db.supabase_writer import count_open_positions
    from notifier.discord_notifier import send_discord

    try:
        now = datetime.now(TZ)

        if not is_market_hours(now):
            logger.debug("[orchestrator] Heartbeat: market closed — skipping")
            return

        session  = get_current_session(now)
        open_ct  = count_open_positions()
        mode     = "DRY RUN" if DRY_RUN else "LIVE"
        pos_str  = "No open position" if open_ct == 0 else f"{open_ct} open position(s)"

        send_discord(
            f"💚 HSH Trader [{mode}] — {now:%H:%M} · {session} · "
            f"{_bars_run} bars run · {pos_str}"
        )
        logger.info(
            f"[orchestrator] Heartbeat: {session} {now:%H:%M} "
            f"bars={_bars_run} open={open_ct}"
        )

    except Exception as exc:
        logger.exception(f"[orchestrator] Job C (heartbeat) failed: {exc}")