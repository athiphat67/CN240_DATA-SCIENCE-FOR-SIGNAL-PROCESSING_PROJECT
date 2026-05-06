"""
main.py — Entry point for HSH ML Trader

Startup sequence:
  1. setup_logging()
  2. Validate Supabase connection
  3. Load model (startup import)
  4. Send Discord startup notification
  5. Start scheduler (blocking)

Usage:
  DRY_RUN=true python main.py   # paper trading
  python main.py                # live
"""

import logging
import sys

from logger_setup import setup_logging  # root-level module

setup_logging()
logger = logging.getLogger("system")


def main() -> None:
    from config.settings import DRY_RUN

    mode = "DRY RUN (Paper Trading)" if DRY_RUN else "LIVE"
    logger.info(f"{'='*60}")
    logger.info(f"  HSH ML Trader — Starting [{mode}]")
    logger.info(f"{'='*60}")

    # ─── 1. Import & validate model ──────────────────────────────────────────
    try:
        from core.model_inference import FEATURE_COLS, MODEL_VERSION  # noqa: F401
        logger.info(f"Model loaded: {MODEL_VERSION} · {len(FEATURE_COLS)} features")
    except Exception as exc:
        logger.exception(f"Model load failed — aborting: {exc}")
        sys.exit(1)

    # ─── 2. Validate Supabase connection ─────────────────────────────────────
    try:
        from db.supabase_writer import get_supabase_client
        sb = get_supabase_client()
        sb.table("signals").select("id").limit(1).execute()
        logger.info("Supabase connection ✅")
    except Exception as exc:
        logger.exception(f"Supabase connection failed — aborting: {exc}")
        sys.exit(1)

    # ─── 3. Startup Discord notification ─────────────────────────────────────
    try:
        from notifier.discord_notifier import send_discord
        send_discord(
            f"🚀 **HSH ML Trader Started** [{mode}]\n"
            f"Model: `{MODEL_VERSION}` · Features: {len(FEATURE_COLS)}"
        )
    except Exception as exc:
        logger.warning(f"Discord startup notification failed (non-critical): {exc}")

    # ─── 4. Start scheduler ───────────────────────────────────────────────────
    logger.info("Starting scheduler...")
    from scheduler.orchestrator import scheduler
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped — HSH ML Trader shutting down.")


if __name__ == "__main__":
    main()