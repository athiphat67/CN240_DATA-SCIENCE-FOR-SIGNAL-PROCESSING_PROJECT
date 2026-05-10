# main.py
import logging
from logger_setup import setup_logging
from scheduler.orchestrator import start_scheduler
from config.settings import DRY_RUN
from core.state_manager import get_current_state
from notifier.discord_notifier import send_discord
from scheduler.orchestrator import tp_manager
from db.supabase_writer import get_supabase_client

setup_logging()
log = logging.getLogger("system")

def recover_tp_state() -> None:
    if DRY_RUN or get_current_state() != "HOLDING":
        return
    try:
        from db.supabase_writer import get_open_trade
        active_trade = get_open_trade()
        if active_trade and not tp_manager.is_active:
            tp_manager.activate(
                entry_ask=float(active_trade["entry_ask"]),
                entry_score=float(active_trade["entry_score"]),
                initial_bid=float(active_trade.get("entry_bid_at_signal") or active_trade["entry_ask"])
            )
            log.info("[Startup] TP Manager recovered from active trade")
    except Exception as e:
        log.warning(f"[Startup] TP state recovery failed: {e}")

if __name__ == "__main__":
    log.info("=" * 60)
    log.info("HSH ML Trader v3.0 — Signal Generator Mode")
    log.info(f"DRY_RUN = {DRY_RUN}")
    log.info("=" * 60)
    
    try:
        state = get_current_state()
        log.info(f"Current state on startup: {state}")
        send_discord(f"🚀 HSH Trader v3.0 started | State: `{state}` | DRY_RUN: `{DRY_RUN}`")
    except Exception as e:
        log.warning(f"Startup state check failed: {e}")

    recover_tp_state()  # 🆕 Restore TP state before scheduler starts
    start_scheduler()