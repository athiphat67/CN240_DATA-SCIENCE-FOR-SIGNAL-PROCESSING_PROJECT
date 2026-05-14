# db/supabase_writer.py
import json
import time
import logging
import supabase
from pathlib import Path
from datetime import datetime
from typing import Any, Tuple
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

def update_state(new_state: str) -> None:
    """
    อัปเดต system state table

    ใช้ retry 3 ครั้ง + raise error ถ้า update ไม่สำเร็จ
    เพื่อป้องกัน state ใน DB กับ logic หลักเพี้ยนกัน
    """
    if DRY_RUN:
        logger.info(f"[DRY_RUN] Would UPDATE {SYSTEM_STATE_TABLE} → {new_state}")
        return

    for attempt in range(3):
        try:
            get_supabase_client().table(SYSTEM_STATE_TABLE).update({
                "current_position": new_state,
                "updated_at": "now()"
            }).eq("id", 1).execute()

            logger.info(f"[DB] ✅ State updated → {new_state}")
            return

        except Exception as e:
            logger.warning(f"[DB] ⚠️ update_state attempt {attempt + 1} failed: {e}")
            if attempt == 2:
                logger.error(f"[DB] ❌ update_state failed after 3 attempts: {e}")
                raise
            time.sleep(2 ** attempt)


def get_signal_by_id(signal_id: str) -> dict | None:
    if DRY_RUN:
        logger.info(f"[DRY_RUN] Would fetch signal {signal_id}")
        return None

    res = (
        get_supabase_client()
        .table(SIGNALS_TABLE)
        .select("*")
        .eq("id", signal_id)
        .limit(1)
        .execute()
    )
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


def get_latest_pending_sell_signal() -> dict | None:
    if DRY_RUN:
        return None

    res = (
        get_supabase_client()
        .table(SIGNALS_TABLE)
        .select("*")
        .eq("signal_type", "SELL")
        .eq("passed", True)
        .in_("execution_status", ["PENDING_CONFIRM", "PENDING_AUTO_EXIT", "SIGNAL_ONLY"])
        .order("bar_time", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def mark_signal_execution(
    signal_id: str,
    status: str,
    price: float | None = None,
    note: str | None = None
) -> bool:
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


def open_trade_from_signal(signal: dict, confirmed_price: float) -> Tuple[bool, str]:
    if DRY_RUN:
        logger.info(f"[DRY_RUN] Would open trade from signal {signal.get('id')} @ {confirmed_price}")
        return True, ""

    try:
        # ── Solution A: Auto-Cleanup Orphaned Trades ─────────────────────
        # If the state is EMPTY but an OPEN trade exists, cancel it first
        # to prevent the unique constraint violation.
        existing_trade = get_open_trade()
        if existing_trade:
            logger.warning(f"[open_trade] Found orphaned OPEN trade {existing_trade['id']}. Auto-cancelling.")
            get_supabase_client().table(ACTIVE_TRADES_TABLE).update({
                "status": "CANCELLED",
                "exit_reason": "AUTO_CANCEL_ORPHANED_ON_NEW_BUY",
                "exit_note": "Cancelled automatically to allow new trade"
            }).eq("id", existing_trade["id"]).execute()

        row = {
            "status": "OPEN",
            "entry_signal_id": signal["id"],
            "entry_ask": confirmed_price,
            "entry_bid_at_signal": signal.get("hsh_bid_price"),
            "entry_score": signal.get("ranker_score"),
            "entry_bar_time": signal.get("bar_time"),
            "entry_note": f"Confirmed via UI at {confirmed_price}",
        }
        res = get_supabase_client().table(ACTIVE_TRADES_TABLE).insert(row).execute()
        if res.data:
            logger.info(f"[DB] ✅ Active trade opened | signal={signal.get('id')} | ask={confirmed_price}")
            return True, ""
        logger.error(f"[open_trade] Insert returned no data: {res}")
        return False, "Insert returned no data."
    except Exception as e:
        logger.error(f"[open_trade] Failed: {e}")
        return False, str(e)

def close_open_trade(exit_signal_id, exit_bid, exit_score=None, reason=None) -> bool:
    if DRY_RUN:
        logger.info(f"[DRY_RUN] Would close open trade | exit_signal={exit_signal_id} | bid={exit_bid}")
        return True

    from datetime import timezone as _tz  # avoid shadowing top-level import
    try:
        # Step 1: ดึง entry_ask จาก OPEN trade ก่อน เพื่อคำนวณ pnl_thb
        pnl_thb = None
        open_trade = get_open_trade()
        if open_trade:
            try:
                entry_ask = float(open_trade["entry_ask"])
                pnl_thb = round(float(exit_bid) - entry_ask, 2)
            except (TypeError, KeyError, ValueError) as calc_err:
                logger.warning(f"[close_trade] pnl_thb calc skipped: {calc_err}")

        # Step 2: Update row
        update_payload = {
            "status": "CLOSED",
            "exit_signal_id": exit_signal_id,
            "exit_bid": exit_bid,
            "exit_score": exit_score,
            "exit_reason": reason,
            "exit_time": datetime.now(_tz.utc).isoformat(),
        }
        if pnl_thb is not None:
            update_payload["pnl_thb"] = pnl_thb

        res = (
            get_supabase_client()
            .table(ACTIVE_TRADES_TABLE)
            .update(update_payload)
            .eq("status", "OPEN")
            .execute()
        )
        if res.data:
            logger.info(
                f"[DB] ✅ Active trade closed | reason={reason} | bid={exit_bid} | pnl={pnl_thb} THB"
            )
            return True
        logger.warning("[close_trade] No OPEN trade found to close (returned empty)")
        return False
    except Exception as e:
        logger.error(f"[close_trade] Failed: {e}")
        return False