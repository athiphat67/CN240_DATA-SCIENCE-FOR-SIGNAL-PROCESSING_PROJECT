# db/supabase_writer.py
import json
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Any
from supabase import create_client, Client
from config.settings import (
    DRY_RUN, SUPABASE_URL, SUPABASE_KEY,
    SIGNALS_TABLE, ACTIVE_TRADES_TABLE, SYSTEM_STATE_TABLE,
    BAR_LOGS_TABLE
)

logger = logging.getLogger("trading")
_client: Client | None = None

def get_supabase_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client

def _safe_upsert(table: str, data: dict, conflict_col: str = "id") -> bool:
    """INSERT/UPSERT พร้อม Retry 3 ครั้ง + Fallback JSONL"""
    if DRY_RUN:
        logger.info(f"[DRY_RUN] Would UPSERT into {table}: {data.get('id', data.get('bar_time'))}")
        return True

    for attempt in range(3):
        try:
            res = get_supabase_client().table(table).upsert(data, on_conflict=conflict_col).execute()
            
            # ตรวจสอบ Error ที่อาจแฝงมาใน Response Object
            if hasattr(res, 'error') and res.error is not None:
                raise Exception(f"Supabase API Error: {res.error}")
            
            # เพิ่ม Success Log เพื่อให้รู้ว่าโค้ดวิ่งมาถึงและยิงลง DB จริงๆ
            logger.info(f"[DB] ✅ UPSERT {table} Success: {data.get('id', data.get('bar_time'))}")
            return True
            
        except Exception as e:
            logger.warning(f"[DB] ⚠️ {table} upsert attempt {attempt+1} failed: {e}")
            if attempt == 2:
                _write_fallback(table, data, str(e))
                return False
            time.sleep(2 ** attempt)
    return False

def _write_fallback(table: str, data: dict, error: str) -> None:
    Path("fallback").mkdir(exist_ok=True)
    with open("fallback/pending_inserts.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({
            "table": table, "data": data, "error": error,
            "ts": datetime.utcnow().isoformat()
        }, default=str) + "\n")
    logger.error(f"[DB] Fallback written to fallback/pending_inserts.jsonl")

def insert_signal(signal: dict) -> bool:
    return _safe_upsert(SIGNALS_TABLE, signal)

def insert_bar_log(log: dict) -> bool:
    return _safe_upsert(BAR_LOGS_TABLE, log, conflict_col="bar_time")

# def update_state(new_state: str) -> None:
#     """อัปเดต v3_system_state — เรียกหลัง INSERT v3_signal ที่ passed=True เสมอ"""
#     if DRY_RUN:
#         logger.info(f"[DRY_RUN] Would UPDATE {SYSTEM_STATE_TABLE} → {new_state}")
#         return
#     try:
#         get_supabase_client().table(SYSTEM_STATE_TABLE).update({
#             "current_position": new_state,
#             "updated_at": "now()"
#         }).eq("id", 1).execute()
#     except Exception as e:
#         logger.error(f"[DB] Failed to update state: {e}")

def get_signal_by_id(signal_id: str) -> dict | None:
    if DRY_RUN:
        logger.info(f"[DRY_RUN] Would fetch signal {signal_id}")
        return None
    res = get_supabase_client().table(SIGNALS_TABLE).select("*").eq("id", signal_id).limit(1).execute()
    return res.data[0] if res.data else None

def get_latest_pending_buy_signal() -> dict | None:
    if DRY_RUN:
        return None
    res = (
        get_supabase_client()
        .table(SIGNALS_TABLE)
        .select("*")
        .eq("signal_type", "BUY")
        .eq("passed", True)
        .in_("execution_status", ["PENDING_CONFIRM", "SIGNAL_ONLY"])
        .order("bar_time", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None

def mark_signal_execution(signal_id: str, status: str, price: float | None = None, note: str | None = None) -> bool:
    if DRY_RUN:
        logger.info(f"[DRY_RUN] Would mark signal {signal_id} → {status}")
        return True

    payload = {
        "execution_status": status,
        "updated_at": "now()",
    }
    if price is not None:
        payload["confirmed_price"] = float(price)
    if note:
        payload["confirm_note"] = note
    if status in ("CONFIRMED", "AUTO_EXITED", "CANCELLED"):
        payload["confirmed_at"] = "now()"

    try:
        get_supabase_client().table(SIGNALS_TABLE).update(payload).eq("id", signal_id).execute()
        return True
    except Exception as e:
        logger.error(f"[DB] mark_signal_execution failed: {e}")
        return False

def get_open_trade() -> dict | None:
    if DRY_RUN:
        return None
    res = (
        get_supabase_client()
        .table(ACTIVE_TRADES_TABLE)
        .select("*")
        .eq("status", "OPEN")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None

def open_trade_from_signal(signal: dict, executed_ask: float, note: str | None = None) -> bool:
    if DRY_RUN:
        logger.info(f"[DRY_RUN] Would open trade from signal {signal.get('id')} @ {executed_ask}")
        return True

    try:
        # ── Safety Guard: prevent duplicate OPEN trades ───────────────────
        existing = get_open_trade()
        if existing:
            logger.warning(
                f"[DB] Cannot open trade: another OPEN trade already exists "
                f"| trade_id={existing.get('id')} "
                f"| entry_signal_id={existing.get('entry_signal_id')}"
            )
            return False

        if not signal.get("id"):
            logger.error("[DB] Cannot open trade: signal has no id")
            return False

        if executed_ask <= 0:
            logger.error(f"[DB] Cannot open trade: invalid executed_ask={executed_ask}")
            return False

        payload = {
            "status": "OPEN",
            "entry_signal_id": signal["id"],
            "entry_bar_time": signal.get("bar_time"),
            "entry_ask": float(executed_ask),
            "entry_bid_at_signal": signal.get("hsh_bid_price"),
            "entry_score": signal.get("ranker_score"),
            "entry_note": note,
            "created_at": "now()",
            "updated_at": "now()",
        }

        get_supabase_client().table(ACTIVE_TRADES_TABLE).insert(payload).execute()
        logger.info(
            f"[DB] ✅ OPEN trade created | signal_id={signal['id']} | entry_ask={executed_ask}"
        )
        return True

    except Exception as e:
        logger.error(f"[DB] open_trade_from_signal failed: {e}")
        return False

def close_open_trade(exit_bid: float, exit_signal_id: str | None = None, exit_score: float | None = None, reason: str = "MANUAL_SELL", note: str | None = None) -> bool:
    if DRY_RUN:
        logger.info(f"[DRY_RUN] Would close open trade @ {exit_bid} | reason={reason}")
        return True

    trade = get_open_trade()
    if not trade:
        logger.warning("[DB] No OPEN trade to close")
        return False

    entry_ask = float(trade["entry_ask"])
    pnl = float(exit_bid) - entry_ask

    payload = {
        "status": "CLOSED",
        "exit_signal_id": exit_signal_id,
        "exit_time": "now()",
        "exit_bid": float(exit_bid),
        "exit_score": exit_score,
        "exit_reason": reason,
        "exit_note": note,
        "pnl_thb": pnl,
        "updated_at": "now()",
    }
    try:
        get_supabase_client().table(ACTIVE_TRADES_TABLE).update(payload).eq("id", trade["id"]).execute()
        return True
    except Exception as e:
        logger.error(f"[DB] close_open_trade failed: {e}")
        return False