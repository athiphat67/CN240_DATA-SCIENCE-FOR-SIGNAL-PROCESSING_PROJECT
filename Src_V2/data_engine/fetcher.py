"""
fetcher.py — Gold Trading Agent · Phase 1 (Deterministic)
ดึงข้อมูลราคาทองคำไทย + ข่าวสาร ผ่าน Data APIs พร้อมรองรับ Timeframe ย่อย
"""

# Standard library
import logging
import os
import random
import statistics
from typing import Optional
from data_engine.ohlcv_fetcher import OHLCVFetcher
from data_engine.thailand_timestamp import get_thai_time

# Third-party libraries
import pandas as pd
import requests
import json
from dotenv import load_dotenv

# โหลดตัวแปรจากไฟล์ .env เข้าสู่ระบบ Environment ของ Python
load_dotenv()

# ⚠️  ห้ามใช้ logging.basicConfig() ที่นี่ — จะ override root logger ของ logger_setup.py
# configure_all_loggers() ถูกเรียกอัตโนมัติตอน import logger_setup แล้ว
logger = logging.getLogger(__name__)

# ─── Constants ──────────────────────────────────────────────────────────────────
GOLD_API_URL = "https://api.gold-api.com/price/XAU"
FOREX_API_URL = "https://api.exchangerate-api.com/v4/latest/USD"

TROY_OUNCE_IN_GRAMS = 31.1034768
THAI_GOLD_BAHT_IN_GRAMS = 15.244
THAI_GOLD_PURITY = 0.965

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

class GoldDataFetcher:
    def __init__(self, news_api_key: Optional[str] = None):
        self.news_api_key = news_api_key
        self.session = requests.Session()
        self.ohlcv_fetcher = OHLCVFetcher(session=self.session)

    def fetch_gold_spot_usd(self) -> dict:
        """
        ดึงราคา Spot Gold (XAU/USD) แบบ Waterfall
        ให้ความสำคัญกับ Real-time Source เป็นอันดับแรก ไม่ใช้ Median ป้องกันการโดนข้อมูล Delay โหวตออก
        """
        # ── 1. TwelveData (Primary: Real-time XAU/USD) ──
        try:
            api_key = os.getenv("TWELVEDATA_API_KEY")
            if api_key:
                url = f"https://api.twelvedata.com/price?symbol=XAU/USD&apikey={api_key}"
                resp = self.session.get(url, timeout=5)
                if resp.status_code == 200:
                    price = float(resp.json().get("price", 0))
                    if price > 0:
                        logger.info(f"✅ ใช้เรท Spot Gold จาก TwelveData (Real-time): {price}")
                        return {
                            "source": "twelvedata",
                            "price_usd_per_oz": price,
                            "timestamp": get_thai_time().isoformat(),
                            "confidence": 0.9,
                        }
        except Exception as e:
            logger.warning(f"twelvedata spot failed: {e}")

        # ── 2. Yahoo Finance (Secondary: ใช้ fast_info แทนการดึง History) ──
        try:
            import yfinance as yf
            ticker = yf.Ticker("GC=F")
            # ใช้ fast_info จะได้ราคา Tick ล่าสุดไวกว่าและไม่อิงกราฟที่ปิดแท่ง
            price = ticker.fast_info.get('lastPrice', 0)
            if price > 0:
                logger.info(f"⚠️ ใช้เรท Spot Gold จาก YFinance fast_info: {price}")
                return {
                    "source": "yfinance_fast_info",
                    "price_usd_per_oz": price,
                    "timestamp": get_thai_time().isoformat(),
                    "confidence": 0.7,
                }
        except Exception as e:
            logger.warning(f"yfinance spot failed: {e}")

        # ── 3. Gold-API (Fallback สุดท้าย) ──
        try:
            self.session.headers.update({"User-Agent": random.choice(USER_AGENTS)})
            resp = self.session.get(GOLD_API_URL, timeout=5)
            if resp.status_code == 200:
                price = float(resp.json().get("price", 0))
                if price > 0:
                    logger.warning(f"⚠️ ใช้เรท Spot Gold จาก Gold-API: {price}")
                    return {
                        "source": "gold-api",
                        "price_usd_per_oz": price,
                        "timestamp": get_thai_time().isoformat(),
                        "confidence": 0.5,
                    }
        except Exception as e:
            logger.warning(f"gold-api spot failed: {e}")

        logger.error("🚨 ดึงราคา Spot Gold ไม่ได้จากทุก Source!")
        return {}

    def compute_confidence(self, prices: dict) -> float:
        if len(prices) == 0: return 0.0
        if len(prices) == 1: return 0.6
        values = list(prices.values())
        median_val = statistics.median(values)
        if median_val == 0: return 0.0
        max_diff = max(abs(p - median_val) / median_val for p in values)
        penalty = max_diff * 10
        confidence = max(0.0, 1.0 - penalty)
        return round(confidence, 3)

    def fetch_usd_thb_rate(self) -> dict:
        """
        ดึงเรทเงิน USD/THB แบบ 4-Layer Fallback (Local -> Global)
        ให้ความสำคัญกับ Interceptor เป็นอันดับแรก เพื่อให้ข้อมูลชุดเดียวกัน (Consistency)
        """
        # ── Layer 1: Interceptor (Primary - ข้อมูลชุดเดียวกับราคาทองไทย) ──
        logger.info("กำลังดึงเรท USD/THB จาก Interceptor เป็นอันดับแรก...")
        live_data = self.fetch_latest_from_interceptor()
        if live_data and live_data.get("usd_thb_live", 0) > 0:
            logger.info(f"✅ ใช้เรท USD/THB จาก Interceptor: {live_data['usd_thb_live']:.4f}")
            return {
                "source": "interceptor_live",
                "usd_thb": live_data["usd_thb_live"],
                "timestamp": live_data.get("timestamp", get_thai_time().isoformat()),
            }
        
        logger.warning("❌ Layer 1 (Interceptor) ไม่มีค่า USD/THB หรือเป็น 0, กำลังลอง Layer 2...")

        # ── Layer 2: Yahoo Finance (Secondary - Global, Real-time 24/5) ──
        try:
            import yfinance as yf
            df = yf.Ticker("USDTHB=X").history(period="1d", interval="1m")
            if not df.empty:
                thb_rate = float(df["Close"].iloc[-1])
                logger.info(f"✅ ใช้เรท USD/THB จาก YFinance: {thb_rate:.4f}")
                return {
                    "source": "yfinance",
                    "usd_thb": thb_rate,
                    "timestamp": get_thai_time().isoformat(),
                }
        except Exception as e:
            logger.warning(f"YFinance USD/THB failed: {e}")

        # ── Layer 3: TwelveData (Tertiary - Global) ──
        try:
            api_key = os.getenv("TWELVEDATA_API_KEY")
            if api_key:
                url = f"https://api.twelvedata.com/price?symbol=USD/THB&apikey={api_key}"
                resp = self.session.get(url, timeout=5)
                if resp.status_code == 200:
                    thb_rate = float(resp.json().get("price", 0))
                    if thb_rate > 0:
                        logger.info(f"✅ ใช้เรท USD/THB จาก TwelveData: {thb_rate:.4f}")
                        return {
                            "source": "twelvedata",
                            "usd_thb": thb_rate,
                            "timestamp": get_thai_time().isoformat(),
                        }
        except Exception as e:
            logger.warning(f"TwelveData USD/THB failed: {e}")

        # ── Layer 4: Exchangerate-API (Last Resort - อัปเดตวันละครั้ง) ──
        logger.warning("⚠️ ใช้ Fallback สุดท้าย (exchangerate-api)")
        self.session.headers.update({"User-Agent": random.choice(USER_AGENTS)})
        try:
            resp = self.session.get(FOREX_API_URL, timeout=10)
            resp.raise_for_status()
            rates = resp.json().get("rates", {})
            thb = float(rates.get("THB", 0))
            return {
                "source": "exchangerate-api.com",
                "usd_thb": thb,
                "timestamp": get_thai_time().isoformat(),
            }
        except Exception as e:
            logger.error(f"fetch_usd_thb_rate completely failed: {e}")
            return {"usd_thb": 34.0, "source": "hardcoded_fallback"}
        
    def fetch_latest_from_interceptor(self) -> dict:
        """
        ดึงข้อมูล Real-time (รวมถึง USD/THB) จากไฟล์ JSON ที่ Background Thread ของเรา
        (gold_interceptor_lite.py) อัปเดตไว้ตลอดเวลา
        """
        json_path = "latest_gold_price.json"
        
        if not os.path.exists(json_path):
            logger.warning(f"File {json_path} not found. (Waiting for interceptor to run...)")
            return {}

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                latest = json.load(f)
            
            # ถ้ามีข้อมูล ให้คืนค่าออกมาให้หมด
            if latest and "usd_thb_live" in latest:
                return {
                    "source": latest.get("source", "interceptor_live"),
                    "sell_price_thb": float(latest.get('sell_price_thb', 0)), 
                    "buy_price_thb": float(latest.get('buy_price_thb', 0)),
                    "gold_spot_usd": float(latest.get('gold_spot_usd', 0)),
                    "usd_thb_live": float(latest.get('usd_thb_live', 0)),
                    "timestamp": latest.get('timestamp', get_thai_time().isoformat())
                }
            return {}
            
        except Exception as e:
            logger.error(f"Error reading live gold data from JSON: {e}") 
            return {}

    def calc_thai_gold_price(
        self,
        price_usd_per_oz: float,
        usd_thb: float,
    ) -> dict:
        """
        อ่านข้อมูลราคาทองไทยจากไฟล์ JSON ที่สร้างโดย gold_interceptor_lite.py
        หากไม่มีข้อมูล จะทำการสลับไปใช้สมการคำนวณ (Fallback) อัตโนมัติ โดยใช้ usd_thb เป็นตัวแปรภายใน
        """
        json_path = "latest_gold_price.json"
        
        try:
            if os.path.exists(json_path):
                with open(json_path, "r", encoding="utf-8") as f:
                    result_data = json.load(f)
                
                if "sell_price_thb" in result_data and "buy_price_thb" in result_data:
                    logger.info(f"Thai Gold (from JSON) — Sell: ฿{result_data['sell_price_thb']:,.0f} | Buy: ฿{result_data['buy_price_thb']:,.0f}")
                    return result_data
        except Exception as e:
            logger.error(f"❌ ระบบอ่านไฟล์ JSON ขัดข้อง: {e}")

        logger.warning("ไม่สามารถดึงข้อมูลจากไฟล์ได้ — สลับไปใช้โหมดคำนวณ (Fallback)")

        # ─── Fallback: คำนวณแบบเดิม (หากไฟล์พังหรือไม่อัปเดต) ───

        if price_usd_per_oz == 0 or usd_thb == 0:
            return {}

        price_thb_per_oz = price_usd_per_oz * usd_thb
        price_thb_per_gram = price_thb_per_oz / TROY_OUNCE_IN_GRAMS
        price_thb_per_baht = (
            price_thb_per_gram * THAI_GOLD_BAHT_IN_GRAMS * THAI_GOLD_PURITY
        )
        
        sell_price = round((price_thb_per_baht + 50) / 50) * 50
        buy_price = round((price_thb_per_baht - 50) / 50) * 50

        logger.info(
            f"Thai Gold (Fallback-Dataset Logic) — Sell: ฿{sell_price:,.0f} | Buy: ฿{buy_price:,.0f} (Spread=฿{sell_price - buy_price:,.0f})"
        )
        return {
            "source": "calculated_fallback",
            "price_thb_per_baht_weight": round(price_thb_per_baht, 2),
            "sell_price_thb": sell_price,
            "buy_price_thb": buy_price,
            "spread_thb": sell_price - buy_price,
        }

    # ─── Main Fetch All ────────────────────────────────────────────────────────
    def fetch_all(self, include_news=True, history_days=90, interval="1d") -> dict:
        spot = self.fetch_gold_spot_usd()
        internal_usd = self.fetch_usd_thb_rate()
        thai = self.calc_thai_gold_price(
            price_usd_per_oz=spot.get("price_usd_per_oz", 0),
            usd_thb=internal_usd.get("usd_thb", 0),
        )

        try:
            ohlcv = self.ohlcv_fetcher.fetch_historical_ohlcv(
                days=history_days, interval=interval
            )
            
            # 🚀 DATA STITCHING: นำราคา Real-time ไปแพตช์ใส่กราฟ OHLCV ที่ Delay
            live_price = spot.get("price_usd_per_oz")
            if live_price and not ohlcv.empty:
                        
                # ดึง Index ของแถวสุดท้ายออกมาเก็บไว้ก่อน
                last_idx = ohlcv.index[-1]
                
                # แก้ไขราคา Close ของแท่งล่าสุดให้เป็น Real-time โดยใช้ .loc
                ohlcv.loc[last_idx, 'close'] = live_price
                        
                # ขยายหางกราฟ (High/Low) ให้คลุมราคาปัจจุบัน (ถ้ามันทะลุกรอบ)
                current_high = ohlcv.loc[last_idx, 'high']
                current_low = ohlcv.loc[last_idx, 'low']
                
                live_price_f = float(live_price)
                        
                ohlcv.loc[last_idx, 'high'] = max(current_high, live_price_f)
                ohlcv.loc[last_idx, 'low'] = min(current_low, live_price_f)
                        
                logger.info(f"✨ Stitched Real-time Spot (${live_price}) into the latest OHLCV candle.")

        except Exception as e:
            logger.error(f"[fetch_all] OHLCV fetch error (non-fatal): {e}")
            ohlcv = pd.DataFrame()  # ← คืน empty แทน crash

        return {
            "spot_price": spot,
            "thai_gold":  thai,
            "forex": {
                "usd_thb": internal_usd.get("usd_thb", 0.0),
                "source":  internal_usd.get("source", "unknown"),
            },
            "ohlcv_df":   ohlcv,
            "fetched_at": get_thai_time().isoformat(),
        }