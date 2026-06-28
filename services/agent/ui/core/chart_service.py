"""
core/chart_service.py — Real-time Gold Price Service
Gold Trading Agent v3.2

ดึงราคาทองจาก goldapi.io (GOLDAPI_KEY ใน .env)
+ เก็บ provider metadata สำหรับแสดงตาราง
"""

import os
import time
import requests
from datetime import datetime, timezone, timedelta
from collections import deque
from dotenv import load_dotenv

load_dotenv()

GOLDAPI_KEY  = os.environ.get("GOLDAPI_KEY", "")
GOLDAPI_BASE = "https://www.goldapi.io/api"
MAX_HISTORY  = 300   # เก็บสูงสุด 300 จุด


class ChartService:
    def __init__(self):
        self.api_key         = GOLDAPI_KEY
        self.price_history   = deque(maxlen=MAX_HISTORY)
        self._last_fetch_ts  = 0.0
        self._min_interval   = 15       # วินาที — ป้องกัน call ถี่เกิน
        self._last_result    = None

    # ── Public ───────────────────────────────────────────────────────

    def fetch_price(self, currency: str = "THB") -> dict:
        """
        GET /XAU/{currency}  →  goldapi.io

        Returns dict:
          status, price (per oz), price_gram_24k,
          open_price, high_price, low_price, prev_close,
          change, change_pct, currency, timestamp, fetched_at
        """
        now = time.time()
        if now - self._last_fetch_ts < self._min_interval and self._last_result:
            return self._last_result

        if not self.api_key:
            return {
                "status": "error",
                "error":  "GOLDAPI_KEY ยังไม่ได้ตั้งค่าใน .env",
                "hint":   "เพิ่ม GOLDAPI_KEY=<your_key> ใน .env แล้ว restart",
            }

        url     = f"{GOLDAPI_BASE}/XAU/{currency}"
        headers = {"x-access-token": self.api_key, "Content-Type": "application/json"}

        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            d = resp.json()

            price      = float(d.get("price")            or 0)
            open_p     = float(d.get("open_price")       or 0)
            high_p     = float(d.get("high_price")       or 0)
            low_p      = float(d.get("low_price")        or 0)
            prev_close = float(d.get("prev_close_price") or 0)
            change     = float(d.get("ch")               or 0)
            change_pct = float(d.get("chp")              or 0)
            price_gram = round(price / 31.1035, 2)

            # Bangkok = UTC+7
            bkk = datetime.now(timezone(timedelta(hours=7)))
            result = {
                "status":        "success",
                "price":         round(price, 2),
                "price_gram_24k": price_gram,
                "open_price":    round(open_p, 2),
                "high_price":    round(high_p, 2),
                "low_price":     round(low_p, 2),
                "prev_close":    round(prev_close, 2),
                "change":        round(change, 2),
                "change_pct":    round(change_pct, 4),
                "currency":      currency,
                "timestamp":     bkk.strftime("%d/%m/%Y %H:%M:%S"),
                "fetched_at":    bkk.strftime("%H:%M:%S"),
            }

            self.price_history.append({
                "time":  bkk.strftime("%H:%M"),
                "price": price,
                "ts":    now,
            })
            self._last_fetch_ts = now
            self._last_result   = result
            return result

        except requests.HTTPError as e:
            code = e.response.status_code if e.response else "?"
            return {
                "status": "error",
                "error":  f"HTTP {code} — ตรวจสอบ API key และ quota ที่ goldapi.io",
            }
        except requests.Timeout:
            return {"status": "error", "error": "Request timeout (>10s)"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def get_history(self) -> list:
        return list(self.price_history)

    def clear_history(self):
        self.price_history.clear()
        self._last_result   = None
        self._last_fetch_ts = 0.0

    # ── Provider Metadata ────────────────────────────────────────────

    @staticmethod
    def get_providers_info() -> list:
        """
        คืน list ของ provider พร้อม API key status
        ใช้ render ตาราง Provider ในหน้า Live Chart
        """
        return [
            {
                "name":       "Gemini 2.5 Flash",
                "model_id":   "gemini-2.5-flash-preview-04-17",
                "tier":       "Free",
                "rate_limit": "15 req/min",
                "api_key_set": bool(os.environ.get("GEMINI_API_KEY")),
            },
            {
                "name":       "LLaMA 3.3 70B (Groq)",
                "model_id":   "llama-3.3-70b-versatile",
                "tier":       "Free",
                "rate_limit": "30 req/min",
                "api_key_set": bool(os.environ.get("GROQ_API_KEY")),
            },
            {
                "name":       "Mock (Testing)",
                "model_id":   "mock-v1",
                "tier":       "Free",
                "rate_limit": "unlimited",
                "api_key_set": True,
            },
        ]


# Singleton
chart_service = ChartService()