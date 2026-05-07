# main.py
import logging
from logger_setup import setup_logging
from scheduler.orchestrator import start_scheduler
from config.settings import DRY_RUN
from core.state_manager import get_current_state
from notifier.discord_notifier import send_discord

setup_logging()
log = logging.getLogger("system")

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
        gi
    start_scheduler()