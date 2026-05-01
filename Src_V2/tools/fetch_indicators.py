"""
tools/fetch_indicators.py — Tool: คำนวณ Technical Indicators
ดึงข้อมูล OHLCV ผ่าน OHLCVFetcher แล้วคำนวณ indicators พร้อม data_quality
"""

import logging
import pandas as pd

from data_engine.indicators import TechnicalIndicators
from data_engine.thailand_timestamp import get_thai_time
from data_engine.ohlcv_fetcher import OHLCVFetcher

logger = logging.getLogger(__name__)

TOOL_NAME = "fetch_indicators"
TOOL_DESCRIPTION = (
    "ดึงข้อมูล OHLCV แล้วคำนวณ Technical Indicators: RSI, MACD, Bollinger Bands, EMA, ATR "
    "พร้อม data_quality report และคำแนะนำสำหรับ LLM"
)


def fetch_indicators(
    interval: str = "5m",
    days: int = 90,
    twelvedata_symbol: str = "XAU/USD",
    yf_symbol: str = "GC=F",
    use_cache: bool = True,
    ohlcv_df: pd.DataFrame = None,
) -> dict:
    """
    ดึงข้อมูล OHLCV (ถ้าไม่ได้ส่ง DataFrame มา) แล้วคำนวณ Technical Indicators

    Args:
        interval        : Timeframe เช่น '1m', '5m', '15m', '1h', '1d'
        days            : จำนวนวันย้อนหลังที่ต้องการดึงข้อมูล
        twelvedata_symbol: Symbol สำหรับ TwelveData API (fallback)
        yf_symbol       : Symbol สำหรับ Yahoo Finance (primary)
        use_cache       : เปิด/ปิดการใช้ cache
        ohlcv_df        : (Optional) ส่ง DataFrame เข้ามาโดยตรง จะข้ามการดึงข้อมูล

    Returns:
        dict: {
            "indicators"  : dict  — ผลลัพธ์ indicators ทั้งหมด,
            "data_quality": dict  — quality_score / warnings / llm_instruction,
            "error"       : str | None
        }
    """
    data_quality = {
        "quality_score":   "good",
        "is_weekend":      get_thai_time().weekday() >= 5,
        "llm_instruction": "Use standard technical analysis.",
        "warnings":        [],
    }

    # ──────────────────────────────────────────
    # 1. ดึง OHLCV (ถ้ายังไม่มี DataFrame)
    # ──────────────────────────────────────────
    if ohlcv_df is None or ohlcv_df.empty:
        logger.info(
            f"[fetch_indicators] Fetching OHLCV via OHLCVFetcher "
            f"(symbol={twelvedata_symbol}, interval={interval}, days={days})..."
        )
        try:
            fetcher = OHLCVFetcher()
            ohlcv_df = fetcher.fetch_historical_ohlcv(
                days=days,
                interval=interval,
                twelvedata_symbol=twelvedata_symbol,
                yf_symbol=yf_symbol,
                use_cache=use_cache,
            )
        except Exception as e:
            logger.error(f"[fetch_indicators] OHLCV fetch failed: {e}")
            data_quality["quality_score"] = "degraded"
            data_quality["warnings"].append(f"OHLCV fetch error: {e}")
            return {"indicators": {}, "data_quality": data_quality, "error": str(e)}

    # ──────────────────────────────────────────
    # 2. ตรวจสอบว่ามีข้อมูลหรือไม่
    # ──────────────────────────────────────────
    if ohlcv_df is None or ohlcv_df.empty:
        logger.warning("[fetch_indicators] No OHLCV data — skipping indicators")
        data_quality["quality_score"] = "degraded"
        data_quality["warnings"].append("No OHLCV data available.")
        return {"indicators": {}, "data_quality": data_quality, "error": "No OHLCV data"}

    logger.info(
        f"[fetch_indicators] Computing indicators on {len(ohlcv_df)} candles "
        f"(interval={interval})..."
    )

    # ──────────────────────────────────────────
    # 3. คำนวณ Indicators
    # ──────────────────────────────────────────
    try:
        calc = TechnicalIndicators(ohlcv_df)
        indicators_dict = calc.to_dict(interval=interval)

        if "data_quality" in indicators_dict:
            dq = indicators_dict.pop("data_quality")
            data_quality["warnings"].extend(dq.get("warnings", []))
            data_quality["quality_score"] = dq.get("quality_score", "good")

        if data_quality["is_weekend"]:
            data_quality["warnings"].append(
                "Market is closed (Weekend) — Price data might be stale."
            )
            data_quality["llm_instruction"] = (
                "Market is closed. Weigh news sentiment higher than short-term indicators."
            )

        logger.info(f"[fetch_indicators] ✅ Done — quality={data_quality['quality_score']}")
        return {"indicators": indicators_dict, "data_quality": data_quality, "error": None}

    except Exception as e:
        logger.error(f"[fetch_indicators] Calculation failed: {e}")
        data_quality["quality_score"] = "degraded"
        data_quality["warnings"].append(f"Indicator calc error: {e}")
        return {"indicators": {}, "data_quality": data_quality, "error": str(e)}