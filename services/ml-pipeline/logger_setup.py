# logger_setup.py
import logging
import logging.handlers
from pathlib import Path
from config.settings import LOG_LEVEL

def setup_logging():
    Path("logs").mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    system_handler = logging.handlers.TimedRotatingFileHandler("logs/system.log", when="midnight", backupCount=30, encoding="utf-8")
    system_handler.setFormatter(fmt)

    trading_handler = logging.handlers.TimedRotatingFileHandler("logs/trading.log", when="midnight", backupCount=90, encoding="utf-8")
    trading_handler.setFormatter(fmt)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)

    sys_log = logging.getLogger("system")
    trd_log = logging.getLogger("trading")

    sys_log.addHandler(system_handler)
    sys_log.addHandler(console_handler)
    sys_log.setLevel(LOG_LEVEL)

    trd_log.addHandler(trading_handler)
    trd_log.addHandler(console_handler)
    trd_log.setLevel(LOG_LEVEL)