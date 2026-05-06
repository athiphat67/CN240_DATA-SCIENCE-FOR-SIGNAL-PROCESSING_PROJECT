"""
logger_setup.py — Dual-logger setup for HSH ML Trader
  • system.log  → lifecycle, errors, scheduler events
  • trading.log → signals, trades, TP/SL, P&L, gate decisions
"""

import logging
import logging.handlers
from pathlib import Path
from config.settings import LOG_LEVEL


def setup_logging() -> None:
    """
    Initialize both loggers. Call once at startup in main.py.
    After this, use:
        logging.getLogger("system")  — for infra events
        logging.getLogger("trading") — for trading events
    """
    Path("logs").mkdir(exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ─── system.log — lifecycle, errors, scheduler ────────────────────────────
    system_handler = logging.handlers.TimedRotatingFileHandler(
        "logs/system.log",
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    system_handler.setFormatter(fmt)

    # ─── trading.log — signals, trades, P&L ──────────────────────────────────
    trading_handler = logging.handlers.TimedRotatingFileHandler(
        "logs/trading.log",
        when="midnight",
        backupCount=90,
        encoding="utf-8",
    )
    trading_handler.setFormatter(fmt)

    # ─── Console (shared, shows everything) ───────────────────────────────────
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)

    # ─── Assign loggers ───────────────────────────────────────────────────────
    system_logger = logging.getLogger("system")
    system_logger.setLevel(LOG_LEVEL)
    system_logger.addHandler(system_handler)
    system_logger.addHandler(console_handler)
    system_logger.propagate = False  # ป้องกัน root logger รับซ้ำ

    trading_logger = logging.getLogger("trading")
    trading_logger.setLevel(LOG_LEVEL)
    trading_logger.addHandler(trading_handler)
    trading_logger.addHandler(console_handler)
    trading_logger.propagate = False