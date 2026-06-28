import logging
import os
import time
from functools import wraps
from datetime import datetime, timezone, timedelta
from logging.handlers import RotatingFileHandler

# ─────────────────────────────────────────────────────────────
# 1. กำหนดโฟลเดอร์เก็บ Log
#
# FIX: ถ้าไฟล์นี้อยู่ใน logs/ subfolder ให้ใช้ parent directory
#      เพื่อป้องกัน logs/logs/ ซ้อนกัน
# ─────────────────────────────────────────────────────────────
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT_DIR = os.path.dirname(_THIS_DIR)

if os.path.basename(_THIS_DIR).lower() == "logs":
    # ถ้าอยู่ใน logs อยู่แล้ว ก็สั่งให้สร้าง logs ข้างในตัวมันเองอีกที
    LOG_DIR = os.path.join(_THIS_DIR, "logs")
else:
    # ถ้าไม่อยู่ใน logs ให้สร้าง logs/logs (สองชั้น)
    LOG_DIR = os.path.join(_THIS_DIR, "logs", "logs")

os.makedirs(LOG_DIR, exist_ok=True)
# ─────────────────────────────────────────────────────────────
# 2. Custom Formatter — TH Time (UTC+7)
# ─────────────────────────────────────────────────────────────
class THTimeFormatter(logging.Formatter):
    def converter(self, timestamp):
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        return (dt + timedelta(hours=7)).timetuple()

# รูปแบบ Log: [Timestamp] [Level] [Module:Function] - Message
LOG_FORMAT  = "[%(asctime)s] [%(levelname)s] [%(filename)s:%(funcName)s] - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# ─────────────────────────────────────────────────────────────
# 3. setup_logger
# ─────────────────────────────────────────────────────────────
def setup_logger(name: str, log_file: str, level=logging.INFO) -> logging.Logger:
    """
    สร้าง Logger ที่ออกทั้ง Console และ File

    FIX: ใช้ getLogger(name) แทน hardcode "client"
         → sys_logger และ llm_logger แยกเป็นคนละ instance จริงๆ
         → llm_trace.log มีข้อมูลแยกต่างหากจาก system.log

    FIX: ใช้ RotatingFileHandler (max 5 MB × 3 backup files)
         แทน FileHandler ธรรมดา เพื่อป้องกัน disk เต็มบน production
    """
    logger = logging.getLogger(name)   # FIX: ใช้ name จริง ไม่ hardcode "client"
    logger.propagate = False
    logger.setLevel(level)

    # FIX: ตรวจว่ายังไม่มี FileHandler สำหรับ log_file นี้
    #      (ป้องกัน duplicate handlers ถ้า module ถูก import หลายครั้ง)
    log_file_path = os.path.join(LOG_DIR, log_file)
    already_has_file_handler = any(
        isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == log_file_path
        for h in logger.handlers
    )

    if not already_has_file_handler:
        formatter = THTimeFormatter(LOG_FORMAT, DATE_FORMAT)

        # FIX: RotatingFileHandler — หมุน file อัตโนมัติเมื่อ > 5 MB, เก็บ 3 backup
        file_handler = RotatingFileHandler(
            log_file_path,
            maxBytes=5 * 1024 * 1024,   # 5 MB
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # Console Handler (เพิ่มครั้งเดียวพร้อม FileHandler)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger

# ─────────────────────────────────────────────────────────────
# 4. สร้าง Loggers
# ─────────────────────────────────────────────────────────────
sys_logger = setup_logger("system_logger", "system.log",    level=logging.DEBUG)
llm_logger = setup_logger("llm_logger",    "llm_trace.log", level=logging.DEBUG)

# ─────────────────────────────────────────────────────────────
# 5. Decorator — จับเวลา (Elapsed Time) & Action
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
            logger_instance.debug(f"▶️ START Action: {func.__name__}")
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start_time
                logger_instance.info(
                    f"✅ END Action: {func.__name__} | Elapsed: {elapsed:.2f}s"
                )
                return result
            except Exception as e:
                elapsed = time.time() - start_time
                logger_instance.error(
                    f"❌ ERROR in {func.__name__}: {e} | Elapsed: {elapsed:.2f}s",
                    exc_info=True,
                )
                raise
        return wrapper
    return decorator