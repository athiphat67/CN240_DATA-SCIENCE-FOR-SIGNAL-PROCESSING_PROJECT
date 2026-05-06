"""
db/supabase_writer.py — Phase 8: Supabase Writer

Singleton Supabase client + all DB write/read operations for HSH ML Trader.

Public API:
  get_supabase_client()                    — singleton client (used by candle_builder too)
  insert_signal(signal)                    — upsert to signals table
  insert_position(order)                   — upsert to positions table
  insert_bar_log(features_row, signal)     — upsert to bar_logs table (debug/retrain)
  close_position(position_id, close_event) — UPDATE positions → CLOSED
  count_open_positions()                   — int (0 in DRY_RUN)
  fetch_open_positions_from_supabase()     — list[dict] ([] in DRY_RUN)

DRY_RUN:
  • All writes → log INFO only, no DB mutation
  • count_open_positions() → 0
  • fetch_open_positions_from_supabase() → []

Retry policy:
  _safe_upsert: 3 attempts with exponential backoff (1s, 2s, 4s)
  On final failure → write to fallback/pending_inserts.jsonl (never raises)

Column mapping:
  positions table uses 'id' as PRIMARY KEY → mapped from order['position_id']
  bar_logs table uses 'bar_time' as UNIQUE → upsert on conflict bar_time
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pytz

from config.settings import (
    DRY_RUN,
    SUPABASE_KEY,
    SUPABASE_URL,
    TIMEZONE,
)

logger = logging.getLogger("trading")
TZ = pytz.timezone(TIMEZONE)

# ─── Singleton Supabase Client ────────────────────────────────────────────────

_supabase_client = None


def get_supabase_client():
    """
    Return singleton Supabase client.
    Raises RuntimeError if SUPABASE_URL / SUPABASE_KEY not set.
    Called by main.py for connection validation and by candle_builder.
    """
    global _supabase_client
    if _supabase_client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError(
                "[supabase_writer] SUPABASE_URL / SUPABASE_KEY ไม่ถูกตั้งค่า — ตรวจสอบ .env"
            )
        try:
            from supabase import create_client
        except ImportError as exc:
            raise RuntimeError(
                "[supabase_writer] supabase-py ไม่ได้ติดตั้ง — รัน: pip install supabase==2.4.0"
            ) from exc
        _supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
        logger.debug("[supabase_writer] Supabase client initialized")
    return _supabase_client


# ─── Fallback Writer ──────────────────────────────────────────────────────────

def _write_fallback(table: str, data: dict, error: str) -> None:
    """
    Write failed insert to local JSONL file when Supabase fails after all retries.
    Never raises — fallback write failure is logged but does not crash the system.
    """
    try:
        Path("fallback").mkdir(exist_ok=True)
        record = {
            "table": table,
            "data": data,
            "error": error,
            "ts": datetime.utcnow().isoformat(),
        }
        with open("fallback/pending_inserts.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        logger.warning(
            f"[supabase_writer] Fallback written: table={table} "
            f"id={data.get('id', data.get('bar_time', '?'))}"
        )
    except Exception as fb_exc:
        logger.error(f"[supabase_writer] Fallback write also failed: {fb_exc}")


# ─── Core Upsert with Retry ───────────────────────────────────────────────────

def _safe_upsert(
    table: str,
    data: dict[str, Any],
    conflict_col: str = "id",
    max_retries: int = 3,
) -> bool:
    """
    INSERT OR UPDATE with exponential-backoff retry.

    DRY_RUN → log only, return True immediately.
    On final failure → write to fallback JSONL, return False (never raises).

    Parameters
    ----------
    table        : Supabase table name
    data         : dict of column → value  (serializable)
    conflict_col : column to upsert on (PRIMARY KEY or UNIQUE)
    max_retries  : number of attempts before fallback
    """
    if DRY_RUN:
        logger.info(
            f"[supabase_writer][DRY_RUN] Would upsert → {table} "
            f"id={data.get('id', data.get('bar_time', '?'))}"
        )
        return True

    sb = get_supabase_client()

    for attempt in range(max_retries):
        try:
            sb.table(table).upsert(data, on_conflict=conflict_col).execute()
            logger.debug(
                f"[supabase_writer] upsert OK → {table} "
                f"id={data.get('id', data.get('bar_time', '?'))}"
            )
            return True
        except Exception as exc:
            wait = 2 ** attempt  # 1s, 2s, 4s
            if attempt < max_retries - 1:
                logger.warning(
                    f"[supabase_writer] upsert {table} attempt {attempt + 1}/{max_retries} "
                    f"failed ({exc}), retrying in {wait}s"
                )
                time.sleep(wait)
            else:
                logger.error(
                    f"[supabase_writer] upsert {table} failed after {max_retries} attempts: {exc}"
                )
                _write_fallback(table, data, str(exc))
                return False

    return False  # unreachable but satisfies type checker


# ─── Public Write Functions ───────────────────────────────────────────────────

def insert_signal(signal: dict) -> None:
    """
    Upsert signal record to signals table.

    Maps: signal['signal_id'] → id (PRIMARY KEY)
    Stores gates_passed as JSONB, features_snap as JSONB.

    Parameters
    ----------
    signal : dict — output of evaluate_signal_gate() (Phase 4)
    """
    row = {
        "id"           : signal["signal_id"],
        "bar_time"     : signal["bar_time"],
        "session"      : signal["session"],
        "signal_type"  : signal.get("signal_type", "BUY"),
        "ranker_score" : signal["ranker_score"],
        "passed"       : signal["passed"],
        "reject_reason": signal.get("reject_reason"),
        "dry_run"      : signal.get("dry_run", DRY_RUN),
        "features_snap": signal.get("features_snap", {}),
    }
    _safe_upsert("signals", row, conflict_col="id")


def insert_position(order: dict) -> None:
    """
    Upsert position record to positions table.

    Maps: order['position_id'] → id (PRIMARY KEY)
    Includes all fields from Phase 5 (simulate_buy) + Phase 6 (calculate_tp_sl).

    Parameters
    ----------
    order : dict — output of calculate_tp_sl() (Phase 6) — merged with signal_id
    """
    row = {
        "id"               : order["position_id"],
        "signal_id"        : order.get("signal_id"),
        "status"           : order.get("status", "OPEN"),

        "entry_ask_price"  : order["entry_ask_price"],
        "entry_bid_price"  : order["entry_bid_price"],
        "hsh_spread"       : order["hsh_spread"],
        "entry_time"       : order["entry_time"],
        "investment_thb"   : order["investment_thb"],
        "gold_weight"      : order["gold_weight"],
        "actual_cost_thb"  : order["actual_cost_thb"],
        "spread_cost_thb"  : order["spread_cost_thb"],
        "breakeven_bid"    : order["breakeven_bid"],
        "atr_used"         : order.get("atr_used"),

        "tp_bid_price"     : order.get("tp_bid_price"),
        "sl_bid_price"     : order.get("sl_bid_price"),
        "tp_distance_thb"  : order.get("tp_distance_thb"),
        "sl_distance_thb"  : order.get("sl_distance_thb"),
        "tp_pnl_thb"       : order.get("tp_pnl_thb"),
        "sl_pnl_thb"       : order.get("sl_pnl_thb"),
        "risk_reward_ratio": order.get("risk_reward_ratio"),

        "dry_run"          : order.get("dry_run", DRY_RUN),
    }
    _safe_upsert("positions", row, conflict_col="id")


def insert_bar_log(features_row: dict, signal: dict) -> None:
    """
    Upsert bar-level log for debugging and retraining.
    bar_time is UNIQUE in bar_logs — safe to call every bar (idempotent).

    Parameters
    ----------
    features_row : dict / FeaturesRow — output of compute_features() (Phase 2)
    signal       : dict — output of evaluate_signal_gate() (Phase 4)
    """
    row = {
        "bar_time"     : features_row["bar_time"],
        "session"      : features_row.get("session"),
        "ranker_score" : signal.get("ranker_score"),
        "signal_passed": signal.get("passed"),
        "hsh_close_ask": features_row.get("hsh_close_ask"),
        "hsh_close_bid": features_row.get("hsh_close_bid"),
        "atr_48"       : features_row.get("F_ATR_48"),
        "features_snap": dict(features_row),
    }
    _safe_upsert("bar_logs", row, conflict_col="bar_time")


def close_position(position_id: str, close_event: dict) -> None:
    """
    UPDATE positions SET status='CLOSED' + close fields.

    DRY_RUN → log only.

    Parameters
    ----------
    position_id : str — Supabase PRIMARY KEY (= order['position_id'])
    close_event : dict — output element from monitor_positions() (Phase 7)
        Required keys: close_bid_price, close_at, close_reason,
                       realized_pnl_thb, pnl_pct
    """
    if DRY_RUN:
        logger.info(
            f"[supabase_writer][DRY_RUN] Would CLOSE position {position_id}: "
            f"{close_event.get('close_reason')} "
            f"pnl={close_event.get('realized_pnl_thb', 0):+.4f} THB"
        )
        return

    # Normalise close_at to ISO string if it comes in as datetime
    close_at = close_event["close_at"]
    if isinstance(close_at, datetime):
        close_at = close_at.isoformat()

    sb = get_supabase_client()
    try:
        sb.table("positions").update({
            "status"           : "CLOSED",
            "close_bid_price"  : close_event["close_bid_price"],
            "close_at"         : close_at,
            "close_reason"     : close_event["close_reason"],
            "realized_pnl_thb" : close_event["realized_pnl_thb"],
            "pnl_pct"          : close_event["pnl_pct"],
            "updated_at"       : datetime.now(TZ).isoformat(),
        }).eq("id", position_id).execute()

        logger.info(
            f"[supabase_writer] position CLOSED: {position_id} "
            f"reason={close_event['close_reason']} "
            f"pnl={close_event['realized_pnl_thb']:+.4f} THB"
        )
    except Exception as exc:
        logger.error(
            f"[supabase_writer] close_position failed for {position_id}: {exc}"
        )
        _write_fallback(
            "positions_close",
            {"id": position_id, **close_event},
            str(exc),
        )


# ─── Public Read Functions ────────────────────────────────────────────────────

def count_open_positions() -> int:
    """
    Count OPEN positions in Supabase.
    Returns 0 in DRY_RUN (paper trading has no real open positions).
    Returns 0 on DB error (fail-safe: better to miss a signal than double-trade).
    """
    if DRY_RUN:
        return 0

    sb = get_supabase_client()
    try:
        res = (
            sb.table("positions")
            .select("id", count="exact")
            .eq("status", "OPEN")
            .execute()
        )
        return res.count or 0
    except Exception as exc:
        logger.error(f"[supabase_writer] count_open_positions failed: {exc}")
        return 0  # fail-safe: treat as "no open positions" to avoid blocking


def fetch_open_positions_from_supabase() -> list[dict]:
    """
    Fetch all OPEN position records.
    Returns [] in DRY_RUN.
    Returns [] on DB error (logged).

    Note: Supabase returns column 'id' as PRIMARY KEY.
    Position Monitor (Phase 7) uses pos['id'] for close_position() calls.
    """
    if DRY_RUN:
        return []

    sb = get_supabase_client()
    try:
        res = (
            sb.table("positions")
            .select("*")
            .eq("status", "OPEN")
            .execute()
        )
        return res.data or []
    except Exception as exc:
        logger.error(f"[supabase_writer] fetch_open_positions failed: {exc}")
        return []