"""
tools/fetch_price.py — Tool: ดึงข้อมูลราคาทอง
ครอบคลุม: spot price (USD), thai gold (THB), OHLCV, recent candles
"""

import logging
import pandas as pd
from typing import Optional

from data_engine.fetcher import GoldDataFetcher
from data_engine.thailand_timestamp import convert_index_to_thai_tz
from data_engine.tools.interceptor_manager import start_interceptor_background

logger = logging.getLogger(__name__)

TOOL_NAME = "fetch_price"
TOOL_DESCRIPTION = (
    "ดึงข้อมูลราคาทองแบบ real-time: spot price (USD), "
    "ราคาทองไทย (THB), แท่งเทียน OHLCV ย้อนหลัง และ 5 แท่งล่าสุด"
)

# เปิด WebSocket ทันทีที่ import tool นี้ (รันแค่ครั้งเดียวต่อโปรเซส)
start_interceptor_background()

_fetcher = GoldDataFetcher()


def fetch_price(
    history_days: int = 90,
    interval: str = "5m",
) -> dict:
    """
    ดึงข้อมูลราคาทองทั้งหมด

    Args:
        history_days: จำนวนวันย้อนหลังสำหรับ OHLCV (default 90)
        interval: Timeframe เช่น "1m", "5m", "15m", "1h", "1d" (default "5m")

    Returns:
        dict: spot_price_usd, thai_gold_thb, recent_price_action,
              ohlcv_df (ส่งต่อให้ fetch_indicators), data_sources, error
    """
    logger.info(f"[fetch_price] Fetching price data (interval={interval}, history={history_days}d)...")

    try:
        raw = _fetcher.fetch_all(history_days=history_days, interval=interval)
    except Exception as e:
        logger.error(f"[fetch_price] fetch_all failed: {e}")
        return {"error": str(e)}

    spot_data  = raw.get("spot_price", {})
    thai_gold  = raw.get("thai_gold", {})
    ohlcv_df: Optional[pd.DataFrame] = raw.get("ohlcv_df")

    # ── Recent price action (5 แท่งล่าสุด) ──────────────────────────────────
    recent_price_action = []
    if ohlcv_df is not None and not ohlcv_df.empty:
        recent_candles = ohlcv_df.tail(5).copy()
        if len(recent_candles) < 5:
            logger.warning(f"⚠️ [fetch_price] Only {len(recent_candles)} recent candles (expected 5)")
        recent_candles.index = convert_index_to_thai_tz(recent_candles.index)
        for idx, row in recent_candles.iterrows():
            recent_price_action.append({
                "datetime": idx.isoformat(),
                "open":     float(row["open"]),
                "high":     float(row["high"]),
                "low":      float(row["low"]),
                "close":    float(row["close"]),
                "volume":   int(row["volume"]) if pd.notna(row["volume"]) else 0,
            })
    else:
        logger.warning("[fetch_price] No OHLCV data available")

    logger.info(f"[fetch_price] ✅ Done — {len(recent_price_action)} recent candles")

    return {
        "spot_price_usd":      spot_data,
        "thai_gold_thb":       thai_gold,
        "forex":               raw.get("forex", {}),
        "recent_price_action": recent_price_action,
        "ohlcv_df":            ohlcv_df,
        "data_sources": {
            "price":     spot_data.get("source"),
            "thai_gold": thai_gold.get("source"),
            "forex":     raw.get("forex", {}).get("source"),
        },
        "error": None,
    }
