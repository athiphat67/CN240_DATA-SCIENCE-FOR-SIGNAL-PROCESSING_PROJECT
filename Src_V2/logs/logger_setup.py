"""
logs/logger_setup.py — นักขุดทอง v2
======================================

สร้าง sys_logger และ llm_logger ที่ใช้ทั้งระบบ

หลักการออกแบบ:
    - File log  → verbose เต็ม (timestamp + level + module:func + message)
                  เก็บไว้ debug ย้อนหลัง, rotate 5 MB × 3 ไฟล์
    - Console   → สะอาด อ่านง่าย (เวลา + สี + emoji + message เท่านั้น)
                  DEBUG ซ่อนบน console แต่ยังเขียนลงไฟล์
                  ไม่มี module/function path รกหน้าจอ

ตัวอย่าง console output หลังแก้:
    15:20:33 · fetching market_state via orchestrator
    15:20:39 ✓ XGBoostPredictor loaded (features=26)
    15:20:43 ✓ Decision: final=HOLD notify=False
    15:20:43 ⚠ WatcherEngine init failed: ... → sleep-only mode
    15:20:44 ✗ save_run failed: connection timeout

--- Changelog ---

[v1.1]
  - แยก Console formatter ออกจาก File formatter
    Console: เวลาสั้น (HH:MM:SS) + สี ANSI + emoji ต่อ level + message ล้วนๆ
    File:    format เดิมครบถ้วน (ไม่กระทบ log ที่เก็บไว้)
  - Console กรอง DEBUG ออก (แสดงเฉพาะ INFO ขึ้นไป)
    DEBUG ยังคงเขียนลงไฟล์ครบ
  - ColorConsoleFormatter รองรับ terminal ที่ไม่มีสี (NO_COLOR / non-TTY)
    → ถ้าไม่มีสี จะ strip ANSI ออกอัตโนมัติ ไม่แสดงตัวอักษรขยะ
  - เพิ่ม CONSOLE_LEVEL env var ให้ปรับระดับ console log ได้จากภายนอก
    เช่น CONSOLE_LEVEL=DEBUG python main.py

[v1.2]
  - configure_all_loggers() — ตั้งค่า root logger + suppress noisy libs
    ครอบคลุมทุก logging.getLogger() ในระบบ (ToolRegistry, fetch_price, Orchestrator ฯลฯ)
    โดยไม่ต้องแก้แต่ละไฟล์
  - Suppress third-party loggers ที่ verbose เกินไป:
    yfinance, urllib3, requests, httpx, asyncio → WARNING เท่านั้น
  - Suppress internal data-engine DEBUG ที่ไม่จำเป็นบน console:
    ToolRegistry, fetch_price, fetch_indicators, fetch_news, Orchestrator
    → INFO ขึ้นไปเท่านั้น (DEBUG ยังเขียนไฟล์)
  - เรียก configure_all_loggers() อัตโนมัติตอน import module นี้
"""

import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from logging.handlers import RotatingFileHandler

# ─────────────────────────────────────────────────────────────
# 1. Log directory
# ─────────────────────────────────────────────────────────────
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))

if os.path.basename(_THIS_DIR).lower() == "logs":
    LOG_DIR = _THIS_DIR
else:
    LOG_DIR = os.path.join(_THIS_DIR, "logs")

os.makedirs(LOG_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────
# 2. File formatter — verbose เต็ม (ไม่เปลี่ยน)
# ─────────────────────────────────────────────────────────────
_FILE_FORMAT  = "[%(asctime)s] [%(levelname)s] [%(filename)s:%(funcName)s] - %(message)s"
_DATE_FORMAT  = "%Y-%m-%d %H:%M:%S"


class THTimeFormatter(logging.Formatter):
    """Formatter ที่แปลง timestamp เป็น ICT (UTC+7) สำหรับ file log"""

    def converter(self, timestamp):
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        return (dt + timedelta(hours=7)).timetuple()


# ─────────────────────────────────────────────────────────────
# 3. Console formatter — สะอาด มีสี
# ─────────────────────────────────────────────────────────────

# ANSI color codes
_RESET  = "\033[0m"
_DIM    = "\033[2m"
_BOLD   = "\033[1m"

_COLORS = {
    "DEBUG":    "\033[90m",   # เทาเข้ม
    "INFO":     "\033[0m",    # ปกติ (ขาว/default terminal)
    "WARNING":  "\033[33m",   # เหลือง
    "ERROR":    "\033[31m",   # แดง
    "CRITICAL": "\033[1;31m", # แดงหนา
}

_EMOJI = {
    "DEBUG":    "·",
    "INFO":     " ",   # ไม่มี emoji — ให้ INFO ดูเบาและอ่านง่ายที่สุด
    "WARNING":  "⚠",
    "ERROR":    "✗",
    "CRITICAL": "✗",
}

# ตรวจว่า terminal รองรับสี หรือผู้ใช้ปิดสีผ่าน env
_USE_COLOR: bool = (
    sys.stderr.isatty()
    and os.environ.get("NO_COLOR", "") == ""
    and os.environ.get("TERM", "") != "dumb"
)


class ColorConsoleFormatter(logging.Formatter):
    """
    Console formatter แบบสะอาด:
      - แสดงเฉพาะ HH:MM:SS (ไม่มีวันที่ ไม่มี module/function)
      - สีต่างกันตาม level (ปิดได้ผ่าน NO_COLOR=1)
      - DEBUG ใช้ dim text แทนสีจัด เพื่อไม่รกสายตา
    """

    def converter(self, timestamp):
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        return (dt + timedelta(hours=7)).timetuple()

    def format(self, record: logging.LogRecord) -> str:
        # เวลาสั้น HH:MM:SS (ICT)
        ct = self.converter(record.created)
        time_str = f"{ct.tm_hour:02d}:{ct.tm_min:02d}:{ct.tm_sec:02d}"

        level = record.levelname
        emoji = _EMOJI.get(level, " ")
        msg   = record.getMessage()

        # แนบ exception info ถ้ามี (เช่น exc_info=True)
        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            msg = f"{msg}\n{record.exc_text}"

        if _USE_COLOR:
            color = _COLORS.get(level, _RESET)
            time_part = f"{_DIM}{time_str}{_RESET}"
            body      = f"{color}{emoji} {msg}{_RESET}"
        else:
            time_part = time_str
            body      = f"{emoji} {msg}"

        return f"{time_part} {body}"


# ─────────────────────────────────────────────────────────────
# 4. setup_logger
# ─────────────────────────────────────────────────────────────

# ระดับ console — ปรับได้ผ่าน env var (default: INFO)
_CONSOLE_LEVEL_NAME = os.environ.get("CONSOLE_LEVEL", "INFO").upper()
_CONSOLE_LEVEL      = getattr(logging, _CONSOLE_LEVEL_NAME, logging.INFO)


def setup_logger(name: str, log_file: str, level: int = logging.INFO) -> logging.Logger:
    """
    สร้าง Logger ที่ออกทั้ง Console และ File

    Console: ColorConsoleFormatter (สั้น สะอาด) — แสดง INFO ขึ้นไป
    File:    THTimeFormatter (verbose) — แสดงทุก level รวม DEBUG
    """
    logger = logging.getLogger(name)
    logger.propagate = False
    logger.setLevel(level)

    log_file_path = os.path.join(LOG_DIR, log_file)

    # ป้องกัน duplicate handlers เมื่อ import ซ้ำ
    already_has_file_handler = any(
        isinstance(h, logging.FileHandler)
        and getattr(h, "baseFilename", None) == log_file_path
        for h in logger.handlers
    )

    if not already_has_file_handler:
        # ── File handler — verbose, rotate 5 MB × 3 ──────────────
        file_fmt = THTimeFormatter(_FILE_FORMAT, _DATE_FORMAT)
        file_handler = RotatingFileHandler(
            log_file_path,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(file_fmt)
        file_handler.setLevel(logging.DEBUG)   # เขียนทุก level ลงไฟล์
        logger.addHandler(file_handler)

        # ── Console handler — สะอาด, กรอง DEBUG ──────────────────
        console_fmt = ColorConsoleFormatter()
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(console_fmt)
        console_handler.setLevel(_CONSOLE_LEVEL)  # default INFO (ซ่อน DEBUG)
        logger.addHandler(console_handler)

    return logger


# ─────────────────────────────────────────────────────────────
# 5. Loggers
# ─────────────────────────────────────────────────────────────
sys_logger = setup_logger("system_logger", "system.log",    level=logging.DEBUG)
llm_logger = setup_logger("llm_logger",    "llm_trace.log", level=logging.DEBUG)


# ─────────────────────────────────────────────────────────────
# 5b. configure_all_loggers — hook root + suppress noisy libs
# ─────────────────────────────────────────────────────────────

# Third-party loggers ที่ verbose เกินจำเป็น → เพิ่มได้เรื่อยๆ
_SUPPRESS_TO_WARNING: list[str] = [
    "yfinance",
    "peewee",
    "urllib3",
    "urllib3.connectionpool",
    "requests",
    "requests.packages.urllib3",
    "httpx",
    "httpcore",
    "asyncio",
    "websocket",
    "websockets",
    "aiohttp",
    "chardet",
    "charset_normalizer",
    "PIL",
]

# Internal loggers ที่ spammy — ให้ขึ้น console เฉพาะ INFO+
# (DEBUG ยังเขียนลงไฟล์ผ่าน root file handler)
_INTERNAL_INFO_ONLY: list[str] = [
    "ToolRegistry",
    "fetch_price",
    "fetch_indicators",
    "fetch_news",
    "NewsFetcher",
    "Orchestrator",
    "GoldTradingOrchestrator",
    "OHLCVFetcher",
    "GoldDataFetcher",
    "InterceptorManager",
]


def configure_all_loggers() -> None:
    """
    ตั้งค่า root logger ให้ใช้ ColorConsoleFormatter และ THTimeFormatter
    เหมือนกับ sys_logger — ครอบคลุมทุก logging.getLogger() ในระบบ
    โดยไม่ต้องแก้แต่ละไฟล์

    เรียก 1 ครั้งเมื่อ import module นี้
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # ป้องกัน duplicate เมื่อ import ซ้ำ
    if any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        return

    # ── Root file handler — เก็บทุก log จากทุก module ──────────
    root_log_path = os.path.join(LOG_DIR, "system.log")
    root_file_fmt = THTimeFormatter(_FILE_FORMAT, _DATE_FORMAT)
    root_file_handler = RotatingFileHandler(
        root_log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    root_file_handler.setFormatter(root_file_fmt)
    root_file_handler.setLevel(logging.DEBUG)
    root.addHandler(root_file_handler)

    # ── Root console handler — สะอาด INFO+ ──────────────────────
    root_console_fmt = ColorConsoleFormatter()
    root_console_handler = logging.StreamHandler(sys.stderr)
    root_console_handler.setFormatter(root_console_fmt)
    root_console_handler.setLevel(_CONSOLE_LEVEL)
    root.addHandler(root_console_handler)

    # ── Suppress third-party spam ─────────────────────────────────
    for lib in _SUPPRESS_TO_WARNING:
        logging.getLogger(lib).setLevel(logging.WARNING)

    # ── Internal verbose loggers — INFO+ บน console ──────────────
    for name in _INTERNAL_INFO_ONLY:
        logging.getLogger(name).setLevel(logging.INFO)


# เรียกทันทีตอน import
configure_all_loggers()


# ─────────────────────────────────────────────────────────────
# 6. Decorator — จับเวลา (Elapsed Time) & Action
# ─────────────────────────────────────────────────────────────
def log_method(logger_instance):
    """
    Decorator สำหรับ wrap function ให้ log START / END / ERROR
    พร้อม elapsed time อัตโนมัติ

    ตัวอย่างการใช้:
        @log_method(sys_logger)
        def my_function(...):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            logger_instance.debug(f"▶ START {func.__name__}")
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start_time
                logger_instance.debug(f"✓ END {func.__name__} ({elapsed:.2f}s)")
                return result
            except Exception as e:
                elapsed = time.time() - start_time
                logger_instance.error(
                    f"{func.__name__} failed: {e} ({elapsed:.2f}s)",
                    exc_info=True,
                )
                raise
        return wrapper
    return decorator