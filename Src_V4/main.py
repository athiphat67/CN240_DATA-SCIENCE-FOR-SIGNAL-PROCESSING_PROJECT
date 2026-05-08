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
        client = get_supabase_client()
        res = client.table("signals").select("hsh_ask_price, hsh_bid_price, ranker_score")\
            .eq("signal_type", "BUY").eq("passed", True).order("created_at", desc=True).limit(1).execute()
        if res.data and not tp_manager.is_active:
            last_buy = res.data[0]
            tp_manager.activate(
                entry_ask=float(last_buy["hsh_ask_price"]),
                entry_score=float(last_buy["ranker_score"]),
                initial_bid=float(last_buy["hsh_bid_price"])
            )
            log.info("[Startup] TP Manager recovered from last BUY signal")
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