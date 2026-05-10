import logging
from config.settings import (
    STATE_EMPTY,
    STATE_HOLDING,
    DRY_RUN,
    SUPABASE_URL,
    SUPABASE_KEY,
    SYSTEM_STATE_TABLE,
)
from supabase import create_client, Client

logger = logging.getLogger("trading")
_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def get_current_state() -> str:
    """อ่านสถานะปัจจุบันจาก DB หรือ mock เป็น EMPTY ถ้า DRY_RUN"""
    if DRY_RUN:
        return STATE_EMPTY

    try:
        client = _get_client()
        res = (
            client
            .table(SYSTEM_STATE_TABLE)
            .select("current_position")
            .eq("id", 1)
            .execute()
        )

        if not res.data:
            raise RuntimeError(
                f"[State] {SYSTEM_STATE_TABLE} table is empty. Run init_state() first."
            )

        current_position = res.data[0]["current_position"]

        if current_position not in (STATE_EMPTY, STATE_HOLDING):
            raise RuntimeError(f"[State] Invalid current_position in DB: {current_position}")

        return current_position

    except Exception as e:
        logger.error(f"[State] Failed to read state from {SYSTEM_STATE_TABLE}: {e}")
        raise


def set_state(new_state: str) -> None:
    """อัปเดตสถานะ → EMPTY หรือ HOLDING"""
    if new_state not in (STATE_EMPTY, STATE_HOLDING):
        raise ValueError(f"[State] Invalid state: {new_state}")

    if DRY_RUN:
        logger.info(f"[DRY_RUN] Would SET state → {new_state}")
        return

    try:
        client = _get_client()
        client.table(SYSTEM_STATE_TABLE).update({
            "current_position": new_state,
            "updated_at": "now()",
        }).eq("id", 1).execute()

        logger.info(f"[State] Updated → {new_state}")

    except Exception as e:
        logger.error(f"[State] Failed to update state in {SYSTEM_STATE_TABLE}: {e}")
        raise


def init_state(initial: str = STATE_EMPTY) -> None:
    """ตั้งค่า State ครั้งแรก หรือ Reset หลัง Manual Trade"""
    if initial not in (STATE_EMPTY, STATE_HOLDING):
        raise ValueError(f"[State] Invalid initial state: {initial}")

    if DRY_RUN:
        logger.info(f"[DRY_RUN] Would INIT state → {initial}")
        return

    try:
        client = _get_client()
        client.table(SYSTEM_STATE_TABLE).upsert({
            "id": 1,
            "current_position": initial,
        }, on_conflict="id").execute()

        logger.info(f"[State] Initialized → {initial}")

    except Exception as e:
        logger.error(f"[State] Failed to init state in {SYSTEM_STATE_TABLE}: {e}")
        raise