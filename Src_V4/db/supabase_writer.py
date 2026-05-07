# db/supabase_writer.py
import json
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Any
from supabase import create_client, Client
from config.settings import DRY_RUN, SUPABASE_URL, SUPABASE_KEY

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
            get_supabase_client().table(table).upsert(data, on_conflict=conflict_col).execute()
            return True
        except Exception as e:
            logger.warning(f"[DB] {table} upsert attempt {attempt+1} failed: {e}")
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

def insert_signal(signal: dict) -> None:
    _safe_upsert("v3_signals", signal)

def insert_bar_log(log: dict) -> None:
    _safe_upsert("v3_bar_logs", log, conflict_col="bar_time")

def update_state(new_state: str) -> None:
    """อัปเดต v3_system_state — เรียกหลัง INSERT v3_signal ที่ passed=True เสมอ"""
    if DRY_RUN:
        logger.info(f"[DRY_RUN] Would UPDATE v3_system_state → {new_state}")
        return
    try:
        get_supabase_client().table("v3_system_state").update({
            "current_position": new_state,
            "updated_at": "now()"
        }).eq("id", 1).execute()
    except Exception as e:
        logger.error(f"[DB] Failed to update state: {e}")