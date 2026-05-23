# main.py
import logging

from logger_setup import setup_logging
from scheduler.orchestrator import start_scheduler, tp_manager
from config.settings import DRY_RUN, STATE_HOLDING
from core.state_manager import get_current_state
from notifier.discord_notifier import send_discord

setup_logging()
log = logging.getLogger("system")


def recover_tp_state() -> None:
    """
    Restore in-memory TP manager from DB active trade on startup.

    ใช้สำหรับ Manual Confirm flow:
    - ถ้า state = HOLDING
    - และยังมี active trade ที่ status = OPEN
    - และ TP manager ยังไม่ active จาก tp_state.json
    → ค่อย activate TP manager จาก active trade

    หมายเหตุ:
    orchestrator.py ของฝั่งโจมอาจ restore TP จาก tp_state.json ตอน import แล้ว
    ดังนั้น function นี้เป็น fallback ชั้นที่ 2 เท่านั้น
    """
    if DRY_RUN:
        return

    try:
        current_state = get_current_state()
        if current_state != STATE_HOLDING:
            return

        if tp_manager.is_active:
            log.info("[Startup] TP Manager already active; DB recovery skipped")
            return

        from db.supabase_writer import get_open_trade

        active_trade = get_open_trade()
        if not active_trade:
            log.warning("[Startup] State is HOLDING but no OPEN active trade was found")
            return

        tp_manager.activate(
            entry_ask=float(active_trade["entry_ask"]),
            entry_score=float(active_trade["entry_score"]),
            initial_bid=float(active_trade.get("entry_bid_at_signal") or active_trade["entry_ask"]),
        )

        if hasattr(tp_manager, "save_to_file"):
            tp_manager.save_to_file()

        log.info("[Startup] TP Manager recovered from DB active trade")

    except Exception as e:
        log.warning(f"[Startup] TP state recovery skipped: {e}")


if __name__ == "__main__":
    log.info("=" * 60)
    log.info("HSH ML Trader v3.0 — Signal Generator Mode")
    log.info(f"DRY_RUN = {DRY_RUN}")
    log.info("=" * 60)

    try:
        state = get_current_state()
        log.info(f"Current state on startup: {state}")
        send_discord(
            f"🚀 HSH Trader v3.0 started | State: `{state}` | DRY_RUN: `{DRY_RUN}`"
        )
    except Exception as e:
        log.warning(f"Startup state check failed: {e}")

    recover_tp_state()
    start_scheduler()