import logging
import uuid
from datetime import datetime

# pyrefly: ignore [missing-import]
from apscheduler.schedulers.blocking import BlockingScheduler
# pyrefly: ignore [missing-import]
from apscheduler.triggers.cron import CronTrigger
import pytz

from config.settings import TIMEZONE, DRY_RUN, STATE_EMPTY, STATE_HOLDING
from config.settings import (
    TP_ATR_MULTIPLIER,
    TP_BREAKEVEN_ATR_MULT,
    TP_SCORE_DROP_THRESH,
    TP_SL_ATR_MULT,
    TP_BE_FLOOR_OFFSET,
    SIGNAL_THRESHOLD,
    GATE_SPREAD_NORM_MAX,
    FORCE_SELL_BAR_TIMES_BKK,
    convert_atr_usd_to_thb,
)
from core.candle_builder import build_candles
from core.feature_engine import compute_features
from core.model_inference import run_inference
from core.signal_gate import evaluate_signal_gate
from core.signal_recorder import build_signal_record
from core.state_manager import get_current_state, set_state
from core.dynamic_tp_manager import DynamicTPManager
from db.supabase_writer import (
    insert_signal,
    insert_bar_log,
    get_open_trade,
    get_latest_pending_sell_signal,
    mark_signal_execution,
    expire_stale_pending_signals,
)
from notifier.discord_notifier import (
    notify_buy_signal,
    notify_sell_pending,
    notify_heartbeat,
    notify_error,
    notify_dynamic_tp,
    notify_sl_recovered,
    notify_hold,
)
from notifier.trade_log_api import send_trade_log
from rationale.generator import build_trade_payload

TZ = pytz.timezone(TIMEZONE)
system_log = logging.getLogger("system")
trading_log = logging.getLogger("trading")

_last_bar_time: str = "N/A"
_last_score: float = 0.0
_last_state: str = STATE_EMPTY

tp_manager = DynamicTPManager(
    atr_multiplier=TP_ATR_MULTIPLIER,
    breakeven_atr_mult=TP_BREAKEVEN_ATR_MULT,
    score_drop_threshold=TP_SCORE_DROP_THRESH,
    be_floor_offset=TP_BE_FLOOR_OFFSET
)

# Jom logic: recover in-memory TP state from disk if DynamicTPManager supports it.
# Rich logic still keeps DB active_trade as the source of truth for manual-confirm entries.
try:
    if hasattr(tp_manager, "restore_from_file"):
        _tp_restored = tp_manager.restore_from_file()
        if _tp_restored:
            system_log.info("[TP] ✅ TP state recovered from disk — restart protection active.")
except Exception as e:
    system_log.warning(f"[TP] TP state restore from disk skipped: {e}")


def _save_tp_state_if_supported() -> None:
    """Persist TP state only when the current DynamicTPManager implementation supports it."""
    try:
        if hasattr(tp_manager, "save_to_file") and tp_manager.is_active:
            tp_manager.save_to_file()
    except Exception as e:
        trading_log.warning(f"[TP] save_to_file skipped: {e}")


def sync_tp_state_from_db(features_row: dict | None = None) -> None:
    """
    Rich manual-confirm bridge:
    - If DB state is EMPTY, TP manager must not remain active.
    - If DB state is HOLDING but TP manager is inactive, recover from v3_active_trades.
    - If DB state is HOLDING but NO OPEN trade exists (stale from unconfirmed BUY),
      auto-heal state back to EMPTY to prevent premature SELL attempts.

    This keeps manual-confirm active_trade compatible with Jom's TP manager persistence.
    """
    state = get_current_state()

    if state == STATE_EMPTY:
        if tp_manager.is_active:
            tp_manager.reset()
            trading_log.info("[TP Sync] Reset TP manager because DB state is EMPTY")
        return

    if state == STATE_HOLDING and not tp_manager.is_active:
        active_trade = get_open_trade()
        if not active_trade:
            # ── Desync detected: state=HOLDING but no OPEN trade ─────────────
            # Do NOT auto-reset here — the user may be about to confirm via UI.
            # The UI's confirm_buy() now handles desync recovery gracefully.
            # Just warn and skip TP activation for this bar.
            trading_log.warning(
                "[TP Sync] ⚠️ DB state=HOLDING but NO OPEN trade in v3_active_trades. "
                "Skipping TP activation this bar. "
                "If this persists, re-confirm via the UI to create the missing trade."
            )
            return

        entry_ask = float(active_trade["entry_ask"])
        entry_score = float(active_trade["entry_score"])
        initial_bid = float(active_trade.get("entry_bid_at_signal") or entry_ask)

        atr_thb = 0.0
        if features_row and features_row.get("F_ATR_48"):
            atr_thb = convert_atr_usd_to_thb(
                float(features_row["F_ATR_48"]),
                float(features_row.get("usd_close", 32.4)),
            )

        sl_price = None
        if atr_thb > 0:
            sl_price = entry_ask - (atr_thb * TP_SL_ATR_MULT)

        tp_manager.activate(
            entry_ask=entry_ask,
            entry_score=entry_score,
            initial_bid=initial_bid,
            sl_price=sl_price,
        )
        _save_tp_state_if_supported()
        trading_log.info("[TP Sync] TP manager activated from active trade")


def _is_force_sell_bar(bar_time_iso: str) -> bool:
    """Return True if bar_time (BKK ISO like '2026-05-15T11:50:00+07:00')
    matches any configured session-end force-sell time."""
    try:
        return bar_time_iso[11:16] in FORCE_SELL_BAR_TIMES_BKK
    except Exception:
        return False


def _send_model_signal_trade_log(gate_result: dict, inference_result: dict) -> None:
    """Post gate output (BUY / SELL / HOLD) to the external trade log API each bar."""
    st = gate_result.get("signal_type") or "HOLD"
    if st == "BUY":
        price = gate_result["hsh_ask"]
    elif st == "SELL":
        price = gate_result["hsh_bid"]
    else:
        price = gate_result["hsh_bid"]
    passed = gate_result.get("passed", False)
    rr = gate_result.get("reject_reason") or ""
    sid = gate_result.get("signal_id", "")
    score = float(inference_result.get("ranker_score", 0.0))
    reason = f"MODEL_{st}|passed={passed}|score={score:.4f}|id={sid}"
    if rr:
        reason += f"|gate={rr}"
    send_trade_log(st, price, reason)


def run_signal_pipeline() -> None:
    global _last_bar_time, _last_score, _last_state

    now = datetime.now(TZ)
    system_log.info(f"[Job A] Pipeline started at {now.strftime('%H:%M:%S')}")

    # House-keeping: roll off pending signals older than PENDING_FRESHNESS_HOURS
    # so the DB never accumulates ghost PENDING_CONFIRM rows that are no longer
    # surfaced by get_latest_pending_*().
    try:
        expire_stale_pending_signals()
    except Exception as _e:
        system_log.warning(f"[Job A] expire_stale_pending_signals skipped: {_e}")

    try:
        candles_df = build_candles()
        features_row = compute_features(candles_df)

        if features_row["session"] == "Closed":
            system_log.info("[Job A] Market closed — skipping")
            return

        inference_result = run_inference(features_row)
        _last_bar_time = features_row["bar_time"]
        _last_score = inference_result["ranker_score"]

        gate_result = evaluate_signal_gate(inference_result, features_row)
        _last_state = gate_result["state_before"]

        # ─── TP Manager: sync manual-confirm DB state and evaluate only while HOLDING ───
        current_state = get_current_state()
        sync_tp_state_from_db(features_row)
        current_state = get_current_state()

        # ── Manual-confirm SELL guard ─────────────────────────────────────────
        # If a pending SELL already exists (from gate SELL or forced exit on a
        # previous bar that the user has not yet confirmed), skip TP evaluation
        # and skip generating new SELL signals this bar. State stays HOLDING
        # until the user confirms via confirm_trade_ui.py.
        existing_pending_sell = None
        if current_state == STATE_HOLDING:
            existing_pending_sell = get_latest_pending_sell_signal()
            if existing_pending_sell:
                trading_log.info(
                    f"[SELL] Pending SELL awaiting confirm "
                    f"(id={existing_pending_sell.get('id')}, "
                    f"status={existing_pending_sell.get('execution_status')}) — "
                    f"TP eval and new SELL signals suppressed this bar."
                )

        # ── SL Recovery: score bounce check ──────────────────────────────────
        # Runs only when a FORCED pending SELL (SL_HIT or TRAIL_HIT) is waiting.
        # If model score recovers above entry_score - margin → cancel pending, hold on.
        # All actual exits require user confirmation via the web UI.
        if (
            existing_pending_sell is not None
            and current_state == STATE_HOLDING
            and tp_manager.is_active
        ):
            pending_trigger = existing_pending_sell.get("reject_reason", "")
            if pending_trigger in ("FORCED_BY_SL_HIT", "FORCED_BY_TRAIL_HIT"):
                current_score = inference_result["ranker_score"]
                current_bid   = features_row["hsh_close_bid"]
                pending_id    = existing_pending_sell.get("id", "UNKNOWN")

                if tp_manager.should_cancel_pending_sell(current_score):
                    trading_log.info(
                        f"[SL Recovery] ✅ Score recovered to {current_score:.4f} — "
                        f"cancelling pending SELL {pending_id}"
                    )
                    mark_signal_execution(
                        pending_id, "CANCELLED",
                        note=f"Score recovered to {current_score:.4f}",
                    )
                    notify_sl_recovered(
                        features_row["bar_time"], pending_id, current_score, current_bid
                    )
                    existing_pending_sell = None  # allow normal pipeline to continue

        tp_trigger, tp_price, trail_level = "NONE", None, 0.0

        # NOTE: Always run TP eval while HOLDING — even when a pending SELL exists.
        # This lets us detect SL_HIT/TRAIL_HIT every bar so the forced-exit
        # block can re-notify (Discord + TradeLog SELL) as long as bid stays
        # past the SL/Trail threshold. If bid recovers, the trigger drops back
        # to TP_UPDATED/NONE and the user sees HOLD again.
        if current_state == STATE_HOLDING and tp_manager.is_active:
            atr_thb = convert_atr_usd_to_thb(
                float(features_row.get("F_ATR_48", 0.0)),
                float(features_row.get("usd_close", 32.4)),
            )

            tp_trigger, tp_price, trail_level = tp_manager.update(
                current_bid=features_row["hsh_close_bid"],
                atr_48=atr_thb,
                current_score=inference_result["ranker_score"],
            )
            _save_tp_state_if_supported()

            # ── HOLDING CHECK: full gate + TP diagnostic panel ───────────────
            entry_ask    = float(tp_manager.entry_ask or 0.0)
            current_bid  = float(features_row["hsh_close_bid"])
            current_ask  = float(features_row["hsh_close_ask"])
            current_score = float(inference_result["ranker_score"])
            sl_price     = float(tp_manager.sl_price or 0.0)
            pnl_thb      = (current_bid - entry_ask) if entry_ask else 0.0
            pnl_pct      = (pnl_thb / entry_ask * 100.0) if entry_ask else 0.0
            pnl_icon     = "🟢" if pnl_thb >= 0 else "🔴"
            sl_buffer    = current_bid - sl_price if sl_price else 0.0

            noise        = float(features_row.get("F_XAU_Spread_Norm", 0.0))
            session_lbl  = features_row.get("session", "?")
            g_market     = session_lbl != "Closed"
            g_noise      = noise < GATE_SPREAD_NORM_MAX
            g_score      = current_score < SIGNAL_THRESHOLD
            g_profit     = current_bid > entry_ask if entry_ask else False

            def _m(ok: bool) -> str:
                return "✅" if ok else "❌"

            pending_label = (
                f"YES (id={existing_pending_sell.get('id')}, "
                f"reason={existing_pending_sell.get('reject_reason')})"
                if existing_pending_sell else "no"
            )

            trading_log.info(
                "\n" + "━" * 70 + "\n"
                f"  📊 [HOLDING CHECK] bar={features_row['bar_time']} | session={session_lbl}\n"
                + "━" * 70 + "\n"
                f"  💰 Entry Ask  : {entry_ask:,.2f} THB\n"
                f"  💵 Now Bid    : {current_bid:,.2f} THB   (Ask {current_ask:,.2f})\n"
                f"  {pnl_icon} P&L       : {pnl_thb:+,.2f} THB  ({pnl_pct:+.2f}%)\n"
                "  ─\n"
                f"  🎯 SL price   : {sl_price:,.2f}    (buffer {sl_buffer:+,.2f})\n"
                f"  📉 Trail      : {trail_level:,.2f}\n"
                f"  🏔️  High Bid   : {tp_manager.highest_bid:,.2f}\n"
                f"  🔒 BE Locked  : {tp_manager._breakeven_locked}\n"
                f"  ⚙️  TP Trigger : {tp_trigger}\n"
                "  ─\n"
                "  🚪 SELL Gate Checklist (ทั้ง 4 ต้องผ่านถึงจะ pending SELL):\n"
                f"     {_m(g_market)} market_open       session = {session_lbl}\n"
                f"     {_m(g_noise)}  noise_gate        spread  = {noise:.3f}  < {GATE_SPREAD_NORM_MAX}\n"
                f"     {_m(g_score)}  score_below_thr   score   = {current_score:.4f}  < {SIGNAL_THRESHOLD}\n"
                f"     {_m(g_profit)} profit_ok         bid {current_bid:,.2f} > entry {entry_ask:,.2f}\n"
                "  ─\n"
                f"  📬 Pending SELL: {pending_label}\n"
                + "━" * 70
            )

            if tp_trigger == "BREAKEVEN_LOCK":
                trading_log.info(
                    f"[TP EVENT] 🔒 Breakeven Locked! "
                    f"Trail floored at {(tp_price or 0):,.2f} THB — downside risk removed."
                )
            elif tp_trigger == "TP_UPDATED":
                trading_log.info(
                    f"[TP EVENT] 📈 Trailing Stop ratcheted up to {trail_level:,.2f} THB"
                )
            elif tp_trigger == "SCORE_FADE":
                trading_log.warning(
                    f"[TP EVENT] ⚠️ Score Fading "
                    f"({inference_result['ranker_score']:.4f}) — "
                    f"Trail at {trail_level:,.2f} THB. Watch for organic exit."
                )

            if tp_trigger != "NONE":
                notify_dynamic_tp(
                    tp_trigger,
                    tp_price,
                    trail_level,
                    inference_result["ranker_score"],
                    features_row["F_ATR_48"],
                )

        # ── Session-end forced SELL ──────────────────────────────────────────
        # At configured BKK bar times (FORCE_SELL_BAR_TIMES_BKK, e.g. "11:50"),
        # emit a PENDING SELL regardless of TP/SL state to flatten before the
        # session transition. Skipped if a pending SELL already exists.
        if (
            current_state == STATE_HOLDING
            and tp_manager.is_active
            and not existing_pending_sell
            and tp_trigger not in ("TRAIL_HIT", "SL_HIT")
            and _is_force_sell_bar(features_row["bar_time"])
        ):
            tp_trigger = "SESSION_END_FORCE"
            trading_log.warning(
                f"[Session End] 🕒 Force SELL triggered at bar {features_row['bar_time']} "
                f"(matched FORCE_SELL_BAR_TIMES_BKK)"
            )

        # 🚨 FORCED EXIT → PENDING SELL: SL Hit / Trail Hit / Session-end force
        # Manual-confirm mode: forced SELL creates a PENDING_CONFIRM signal
        # instead of auto-closing. User must confirm via UI.
        if tp_trigger in ("TRAIL_HIT", "SL_HIT", "SESSION_END_FORCE"):
            if current_state != STATE_HOLDING or not tp_manager.is_active:
                trading_log.warning(
                    f"[TP] Ignored {tp_trigger} because state={current_state}, "
                    f"tp_active={tp_manager.is_active}"
                )
                return

            reason_text = {
                "TRAIL_HIT": "Trailing Stop Hit",
                "SL_HIT": "Stop Loss Hit",
                "SESSION_END_FORCE": "Session-End Force Sell (before noon break)",
            }[tp_trigger]
            exit_bid_price = features_row["hsh_close_bid"]

            # ── Repeat-notify path ──────────────────────────────────────────
            # Pending SELL already exists and price is STILL past SL/Trail
            # (or session-end re-triggered). Don't insert a duplicate signal;
            # just re-emit Discord + TradeLog SELL each bar so the user keeps
            # seeing the exit signal until they confirm at the UI.
            if existing_pending_sell and tp_trigger in ("TRAIL_HIT", "SL_HIT"):
                pending_id = existing_pending_sell.get("id", "UNKNOWN")
                insert_bar_log({
                    "bar_time": features_row["bar_time"],
                    "session": features_row["session"],
                    "state_at_bar": STATE_HOLDING,
                    "ranker_score": inference_result["ranker_score"],
                    "signal_passed": True,
                    "signal_type": "SELL",
                    "hsh_close_ask": features_row["hsh_close_ask"],
                    "hsh_close_bid": exit_bid_price,
                    "atr_48": features_row["F_ATR_48"],
                    "features_snap": inference_result["features_snap"],
                })
                repeat_gate_result = {
                    "bar_time": features_row["bar_time"],
                    "session": features_row["session"],
                    "ranker_score": inference_result["ranker_score"],
                    "hsh_bid": exit_bid_price,
                    "xau_close": features_row["xau_close"],
                }
                repeat_rationale = {
                    "rationale_text": (
                        f"🔁 **Still past {reason_text}** @ `{exit_bid_price:,.2f}` THB — "
                        f"pending SELL `{pending_id}` still awaiting your confirmation at the UI."
                    )
                }
                notify_sell_pending(
                    repeat_gate_result,
                    repeat_rationale,
                    trigger=f"REPEAT_{tp_trigger}",
                    signal_id=pending_id,
                )
                send_trade_log(
                    "SELL",
                    exit_bid_price,
                    f"REPEAT_{tp_trigger}|score={inference_result['ranker_score']:.4f}|pending_id={pending_id}",
                )
                trading_log.warning(
                    f"[Repeat SELL] 🔁 Still past {tp_trigger} @ {exit_bid_price:,.2f} — "
                    f"re-notifying pending {pending_id}"
                )
                return

            forced_signal_id = (
                f"tp_{features_row['bar_time'][:19].replace('-', '').replace(':', '').replace('T', '_')}_"
                f"{uuid.uuid4().hex[:6]}"
            )

            system_log.info(
                f"[TP] {reason_text} @ {exit_bid_price:.2f}. Creating PENDING SELL signal."
            )

            # 1. Build rationale so DB record contains explanation.
            rationale_payload = build_trade_payload(
                signal_type="SELL",
                ranker_score=inference_result["ranker_score"],
                shap_values=inference_result.get("shap_values", []),
                feature_names=inference_result.get("feature_names", []),
                current_ask=features_row["hsh_close_ask"],
                current_bid=exit_bid_price,
                state_before=STATE_HOLDING,
            )
            rationale_payload["rationale_text"] = (
                f"🤖 **Auto-Exit Trigger:** {reason_text} @ `{exit_bid_price:,.2f}` THB "
                f"— WAITING FOR USER CONFIRM\n\n"
                f"{rationale_payload.get('rationale_text', '')}"
            )
            rationale_payload["execution_price"] = exit_bid_price

            # 2. Insert PENDING_CONFIRM SELL signal. Do NOT close trade or flip state.
            forced_sell_record = {
                "id": forced_signal_id,
                "bar_time": features_row["bar_time"],
                "session": features_row["session"],
                "signal_type": "SELL",
                "ranker_score": inference_result["ranker_score"],
                "state_before": STATE_HOLDING,
                "hsh_ask_price": features_row["hsh_close_ask"],
                "hsh_bid_price": exit_bid_price,
                "xau_price": features_row["xau_close"],
                "atr_at_signal": features_row["F_ATR_48"],
                "passed": True,
                "reject_reason": f"FORCED_BY_{tp_trigger}",
                "dry_run": DRY_RUN,
                "features_snap": inference_result["features_snap"],
                "rationale_text": rationale_payload.get("rationale_text"),
                "top_shap_features": rationale_payload.get("top_shap_features", {}),
                "created_at": datetime.now(TZ).isoformat(),
                "execution_status": "PENDING_CONFIRM",
            }

            ok_insert = insert_signal(forced_sell_record)
            if not ok_insert:
                trading_log.error(
                    f"[TP] Failed to insert pending SELL signal {forced_signal_id}."
                )
                notify_error(
                    "Forced SELL",
                    f"Failed to insert pending SELL signal {forced_signal_id}.",
                )
                return

            # 3. Forced exit bar log. Bar exits while still HOLDING.
            insert_bar_log({
                "bar_time": features_row["bar_time"],
                "session": features_row["session"],
                "state_at_bar": STATE_HOLDING,
                "ranker_score": inference_result["ranker_score"],
                "signal_passed": True,
                "signal_type": "SELL",
                "hsh_close_ask": features_row["hsh_close_ask"],
                "hsh_close_bid": exit_bid_price,
                "atr_48": features_row["F_ATR_48"],
                "features_snap": inference_result["features_snap"],
            })

            # 4. Notify user. State stays HOLDING; TP manager stays active.
            # The pending-SELL guard at the top of the pipeline will suppress
            # duplicate TP triggers on subsequent bars until user confirms.
            forced_gate_result = {
                "bar_time": features_row["bar_time"],
                "session": features_row["session"],
                "ranker_score": inference_result["ranker_score"],
                "hsh_bid": exit_bid_price,
                "xau_close": features_row["xau_close"],
            }
            notify_sell_pending(
                forced_gate_result,
                rationale_payload,
                trigger=f"FORCED_{tp_trigger}",
                signal_id=forced_signal_id,
            )
            send_trade_log(
                "SELL",
                exit_bid_price,
                f"PENDING_FORCED_{tp_trigger}|score={inference_result['ranker_score']:.4f}|id={forced_signal_id}",
            )

            trading_log.warning(
                f"\n{'=' * 60}\n"
                f"  🟡 [PENDING SELL] FORCED — {tp_trigger}\n"
                f"  Bid Price : {exit_bid_price:,.2f} THB\n"
                f"  Score     : {inference_result['ranker_score']:.4f}\n"
                f"  Bar Time  : {features_row['bar_time']}\n"
                f"  Signal ID : {forced_signal_id}\n"
                f"  Status    : WAITING USER CONFIRM\n"
                f"{'=' * 60}"
            )
            return

        # ─── P5: Build Signal Record ──────────────────────────────────────────
        rationale_payload = build_trade_payload(
            signal_type=gate_result["signal_type"],
            ranker_score=inference_result["ranker_score"],
            shap_values=inference_result.get("shap_values", {}),
            feature_names=inference_result.get("feature_names", []),
            current_ask=gate_result["hsh_ask"],
            current_bid=gate_result["hsh_bid"],
            state_before=gate_result["state_before"],
        )
        signal_record = build_signal_record(gate_result, rationale_payload)

        if gate_result["passed"] and gate_result["signal_type"] == "BUY":
            # Rich manual-confirm: BUY signal does not change state yet.
            signal_record["execution_status"] = "PENDING_CONFIRM"
        elif gate_result["passed"] and gate_result["signal_type"] == "SELL":
            # Manual-confirm: SELL also waits for user confirmation.
            signal_record["execution_status"] = "PENDING_CONFIRM"

        # Dedup: pending SELL was already checked at top of pipeline. If one exists,
        # skip writing a duplicate gate SELL signal (still log the bar as HOLD).
        if existing_pending_sell and gate_result["passed"] and gate_result["signal_type"] == "SELL":
            insert_bar_log({
                "bar_time": features_row["bar_time"],
                "session": features_row["session"],
                "state_at_bar": gate_result["state_before"],
                "ranker_score": inference_result["ranker_score"],
                "signal_passed": gate_result["passed"],
                "signal_type": "HOLD",
                "hsh_close_ask": features_row["hsh_close_ask"],
                "hsh_close_bid": features_row["hsh_close_bid"],
                "atr_48": features_row["F_ATR_48"],
                "features_snap": signal_record["features_snap"],
            })
            send_trade_log(
                "HOLD",
                features_row["hsh_close_bid"],
                f"DEDUP_PENDING_SELL|score={inference_result['ranker_score']:.4f}|"
                f"pending_id={existing_pending_sell.get('id')}",
            )
            notify_hold(
                bar_time=features_row["bar_time"],
                state=gate_result["state_before"],
                score=inference_result["ranker_score"],
                reject_reason="dedup_pending_sell",
                hsh_bid=features_row["hsh_close_bid"],
                hsh_ask=features_row["hsh_close_ask"],
                pending_sell_id=existing_pending_sell.get("id"),
            )
            return

        # ─── P6: Write to Supabase ────────────────────────────────────────────
        ok_signal_insert = insert_signal(signal_record)
        insert_bar_log({
            "bar_time": features_row["bar_time"],
            "session": features_row["session"],
            "state_at_bar": gate_result["state_before"],
            "ranker_score": inference_result["ranker_score"],
            "signal_passed": gate_result["passed"],
            "signal_type": gate_result["signal_type"],
            "hsh_close_ask": features_row["hsh_close_ask"],
            "hsh_close_bid": features_row["hsh_close_bid"],
            "atr_48": features_row["F_ATR_48"],
            "features_snap": signal_record["features_snap"],
        })
        _send_model_signal_trade_log(gate_result, inference_result)

        # ─── Action & State Update ────────────────────────────────────────────
        if gate_result["passed"] and gate_result["signal_type"]:
            signal_type = gate_result["signal_type"]

            if signal_type == "BUY":
                # Manual confirm mode: do not set HOLDING here.
                notify_buy_signal(gate_result, rationale_payload)
                signal_id = signal_record.get("id", gate_result.get("signal_id", "UNKNOWN"))
                trading_log.info(
                    f"BUY signal sent — WAITING_CONFIRM | score={_last_score:.4f} | signal_id={signal_id}"
                )

            elif signal_type == "SELL":
                # Manual-confirm mode: do NOT close active trade or flip state here.
                # State stays HOLDING and TP manager stays active until user confirms
                # via confirm_trade_ui.py. The forced-exit guard above prevents
                # duplicate pending SELL signals from being inserted each bar.
                if not ok_signal_insert:
                    trading_log.error(
                        "[SELL] insert_signal failed — pending SELL was NOT created."
                    )
                    notify_error(
                        "Model SELL",
                        "Failed to insert pending SELL signal.",
                    )
                    return

                # Guard: if state=HOLDING but no open trade exists (BUY never confirmed),
                # warn but don't touch state — user must reconcile via UI.
                open_trade_check = get_open_trade()
                if not open_trade_check:
                    trading_log.warning(
                        "[SELL] ⚠️ Pending SELL generated but NO OPEN trade found in "
                        "v3_active_trades. State=HOLDING but no position. "
                        "Please reconcile via UI (Force Reset or re-confirm BUY)."
                    )

                signal_id = signal_record.get("id")
                notify_sell_pending(
                    gate_result,
                    rationale_payload,
                    trigger="GATE_SELL",
                    signal_id=signal_id,
                )
                trading_log.info(
                    f"SELL signal sent — WAITING_CONFIRM | score={_last_score:.4f} | "
                    f"signal_id={signal_id}"
                )

        else:
            trading_log.info(
                f"HOLD | state={_last_state} | score={_last_score:.4f} "
                f"| reject={gate_result.get('reject_reason')}"
            )
            notify_hold(
                bar_time=features_row["bar_time"],
                state=gate_result["state_before"],
                score=inference_result["ranker_score"],
                reject_reason=gate_result.get("reject_reason") or "",
                hsh_bid=features_row["hsh_close_bid"],
                hsh_ask=features_row["hsh_close_ask"],
            )

    except Exception as e:
        system_log.error(f"[Job A] Pipeline error: {e}", exc_info=True)
        notify_error("Job A — signal_pipeline", str(e))


def run_heartbeat() -> None:
    global _last_state
    try:
        state = get_current_state()
        _last_state = state
        notify_heartbeat(state, _last_bar_time, _last_score)
        system_log.info(f"[Job C] Heartbeat sent | state={state}")
    except Exception as e:
        system_log.warning(f"[Job C] Heartbeat error: {e}")


def start_scheduler() -> None:
    scheduler = BlockingScheduler(timezone=TZ)
    scheduler.add_job(
        run_signal_pipeline,
        CronTrigger(
            minute="0,10,20,30,40,50",
            hour="0,1,6-23",
            day_of_week="mon-fri",
            timezone=TZ,
        ),
        id="signal_pipeline",
        name="M10 Signal Pipeline",
        max_instances=1,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        run_heartbeat,
        CronTrigger(
            minute=0,
            hour="0,1,6-23",
            day_of_week="mon-fri",
            timezone=TZ,
        ),
        id="heartbeat",
        name="System Heartbeat",
    )
    system_log.info(f"Scheduler started | DRY_RUN={DRY_RUN} | Coverage: 06:00-01:59 BKK")
    scheduler.start()
