"""
api/health.py — Health Check Endpoints

ตรวจสอบสถานะของระบบหลักจากระบบภายนอก:
- Database connection
- HF API availability  
- External service connectivity

ไม่รบกวนการทำงานหลัก เพียงแค่ monitoring
"""

from typing import Optional
import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ต้องนำเข้าในบริบท API (e.g. FastAPI app)
# from fastapi import APIRouter, HTTPException
# router = APIRouter(prefix="/api", tags=["health"])


class HealthCheckService:
    """
    Lightweight health check — ตรวจสอบความพร้อมของระบบ
    ไม่มี side effects ไม่มีการเปลี่ยนแปลงสถานะ
    """
    
    def __init__(self):
        self.last_check_time: Optional[datetime] = None
        self.last_db_status: Optional[bool] = None
        self.last_api_status: Optional[bool] = None
    
    async def check_database(self, db) -> dict:
        """ตรวจสอบการเชื่อมต่อ PostgreSQL โดยไม่ทำให้พัง"""
        try:
            # ใช้ time.sleep ที่มีอยู่ + simple query
            import time
            start = time.time()
            
            # ลองเข้าถึง connection pool (ไม่ execute ประมาณ query ใด)
            conn = None
            try:
                conn = db.pool.getconn()
                elapsed = time.time() - start
                self.last_db_status = True
                return {
                    "status": "healthy",
                    "response_time_ms": round(elapsed * 1000, 2),
                }
            finally:
                if conn:
                    db.pool.putconn(conn)
        except Exception as e:
            logger.warning(f"Database health check failed: {e}")
            self.last_db_status = False
            return {
                "status": "unhealthy",
                "error": str(e)[:100],
            }
    
    async def check_hf_api(self, hf_token: Optional[str] = None) -> dict:
        """ตรวจสอบ HF Inference API (HuggingFace)"""
        try:
            import httpx
            import os
            
            token = hf_token or os.getenv("HF_TOKEN")
            if not token:
                return {
                    "status": "skipped",
                    "reason": "HF_TOKEN not configured",
                }
            
            # ลองติดต่อ HF API ด้วย simple request
            async with httpx.AsyncClient(timeout=5.0) as client:
                headers = {"Authorization": f"Bearer {token}"}
                # ใช้ HF inference API status endpoint
                resp = await client.get(
                    "https://huggingface.co/api/",
                    headers=headers,
                )
                
                self.last_api_status = resp.status_code < 400
                return {
                    "status": "healthy" if resp.status_code < 400 else "degraded",
                    "status_code": resp.status_code,
                }
        except asyncio.TimeoutError:
            logger.warning("HF API health check timeout")
            self.last_api_status = False
            return {
                "status": "timeout",
                "error": "HF API did not respond within 5 seconds",
            }
        except Exception as e:
            logger.warning(f"HF API health check failed: {e}")
            self.last_api_status = False
            return {
                "status": "unhealthy",
                "error": str(e)[:100],
            }
    
    async def check_rss_connectivity(self) -> dict:
        """ตรวจสอบความสามารถในการเชื่อมต่อ RSS feed"""
        try:
            import httpx
            
            # ตัวอย่าง: ตรวจสอบ BBC News RSS
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://feeds.bbci.co.uk/news/rss.xml",
                    follow_redirects=True,
                )
                return {
                    "status": "healthy" if resp.status_code == 200 else "degraded",
                    "status_code": resp.status_code,
                }
        except asyncio.TimeoutError:
            return {"status": "timeout", "error": "RSS feed timeout"}
        except Exception as e:
            logger.warning(f"RSS connectivity check failed: {e}")
            return {"status": "unhealthy", "error": str(e)[:100]}


# ─ FastAPI Integration ─────────────────────────────────────────────────────
# เพิ่มไปในไฟล์ api/main.py ของคุณ:
#
# from api.health import HealthCheckService
# health_service = HealthCheckService()
#
# @app.get("/api/health")
# async def health_check(db: RunDatabase = Depends(get_db)):
#     """GET /api/health - ตรวจสอบสถานะระบบ"""
#     checks = await asyncio.gather(
#         health_service.check_database(db),
#         health_service.check_hf_api(),
#         health_service.check_rss_connectivity(),
#     )
#     
#     all_healthy = all(
#         c.get("status") in ["healthy", "skipped"] 
#         for c in checks
#     )
#     
#     return {
#         "timestamp": datetime.now().isoformat(),
#         "overall_status": "healthy" if all_healthy else "degraded",
#         "database": checks[0],
#         "hf_api": checks[1],
#         "rss_feeds": checks[2],
#     }
