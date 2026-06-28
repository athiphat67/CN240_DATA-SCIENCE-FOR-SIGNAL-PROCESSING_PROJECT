"""
tools/interceptor_manager.py — จัดการ Background Thread สำหรับ WebSocket (gold_interceptor_lite)
"""

import threading
import time
import logging

from data_engine.gold_interceptor_lite import start_interceptor

logger = logging.getLogger(__name__)

_interceptor_thread_started = False
_interceptor_lock = threading.Lock()


def _run_interceptor_forever():
    """ฟังก์ชันทำงานเบื้องหลัง: ดึงราคาทองค้างไว้ตลอดเวลา พร้อม auto-reconnect"""
    logger.info("🚀 [Background Thread] เริ่มรันท่อ WebSocket (gold_interceptor_lite)...")
    while True:
        try:
            start_interceptor()
        except Exception as e:
            logger.error(f"❌ [Background Thread] WebSocket หลุดหรือมีปัญหา: {e}")
        logger.info("🔄 [Background Thread] จะพยายามเชื่อมต่อใหม่ใน 5 วินาที...")
        time.sleep(5)


def start_interceptor_background():
    """
    เปิด Background Thread สำหรับ WebSocket — รันแค่ครั้งเดียวต่อ 1 โปรเซส
    ปลอดภัยสำหรับการเรียกซ้ำหลายครั้ง (idempotent)
    """
    global _interceptor_thread_started
    with _interceptor_lock:
        if not _interceptor_thread_started:
            t = threading.Thread(target=_run_interceptor_forever, daemon=True)
            t.start()
            _interceptor_thread_started = True
            logger.info("✅ [InterceptorManager] Background thread เริ่มต้นแล้ว")
        else:
            logger.debug("[InterceptorManager] Background thread รันอยู่แล้ว ข้ามไป")
