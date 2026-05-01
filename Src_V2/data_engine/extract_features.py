import json
import logging
import os
import time as _time
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Union

logger = logging.getLogger(__name__)


def build_feature_dataset(json_file_path, csv_file_path):
    """
    อ่านไฟล์ JSON ล่าสุด สกัดเฉพาะ Feature ที่จำเป็นสำหรับ ML
    พร้อมเพิ่ม Time Features และ Trading Sessions
    แล้วนำไปต่อท้าย (Append) ในตาราง CSV
    """
    if not os.path.exists(json_file_path):
        print(f"❌ ไม่พบไฟล์ {json_file_path}")
        print(
            "💡 คำแนะนำ: รัน python orchestrator.py หรือ conJSON.py เพื่อสร้าง latest.json ก่อน"
        )
        return

    with open(json_file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # ==========================================
    # 1. TIME FEATURES & TRADING SESSIONS
    # ==========================================
    timestamp_str = data["meta"]["generated_at"]
    dt = pd.to_datetime(timestamp_str)

    hour = dt.hour
    day_of_week = dt.dayofweek  # 0=วันจันทร์, 6=วันอาทิตย์

    # รอบเวลาตลาดทองคำ (เวลาไทย UTC+7)
    # Asian Session (โตเกียว): 07:00 - 15:00
    # London Session (ยุโรป): 15:00 - 23:00
    # New York Session (อเมริกา): 20:00 - 04:00 (ทับซ้อนกับลอนดอนช่วง 20:00-23:00 ซึ่งราคามักจะสวิงแรงสุด)
    is_asian = 1 if 7 <= hour < 15 else 0
    is_london = 1 if 15 <= hour < 23 else 0
    is_ny = 1 if (20 <= hour <= 23) or (0 <= hour < 4) else 0

    # ==========================================
    # 2. MARKET & TECHNICAL FEATURES
    # ==========================================
    market = data["market_data"]
    tech = data["technical_indicators"]

    # Categorical Encoding (แปลงข้อความเป็นตัวเลขให้ ML)
    trend_map = {"uptrend": 1, "downtrend": -1, "sideways": 0}

    features = {
        # --- Time ---
        "datetime": timestamp_str,
        "hour": hour,
        "day_of_week": day_of_week,
        "is_asian_session": is_asian,
        "is_london_session": is_london,
        "is_ny_session": is_ny,
        # --- Price Data ---
        "spot_price": market["spot_price_usd"]["price_usd_per_oz"],
        "usd_thb": market["forex"]["usd_thb"],
        "thai_gold_sell": market["thai_gold_thb"]["sell_price_thb"],
        # --- Indicators ---
        "rsi": tech["rsi"]["value"],
        "macd_hist": tech["macd"]["histogram"],
        "bollinger_pct_b": tech["bollinger"]["pct_b"],
        "bollinger_bw": tech["bollinger"]["bandwidth"],
        "atr": tech["atr"]["value"],
        "trend_encoded": trend_map.get(tech["trend"]["trend"], 0),
        "ema_20": tech["trend"]["ema_20"],
        "sma_200": tech["trend"]["sma_200"],
    }

    # ==========================================
    # 3. SENTIMENT FEATURES (NLP)
    # ==========================================
    news_cats = data["news"]["by_category"]
    target_categories = [
        "thai_gold_market",
        "gold_price",
        "geopolitics",
        "dollar_index",
        "fed_policy",
    ]

    for cat in target_categories:
        cat_data = news_cats.get(cat, {})
        articles = cat_data.get("articles", [])

        if articles:
            # หาค่าเฉลี่ย Sentiment ของแต่ละหมวด (-1.0 ถึง 1.0)
            avg_sent = sum(a.get("sentiment_score", 0.0) for a in articles) / len(
                articles
            )
        else:
            avg_sent = 0.0

        features[f"sentiment_{cat}"] = round(avg_sent, 4)

    # ==========================================
    # 4. EXPORT TO CSV
    # ==========================================
    df_new = pd.DataFrame([features])

    os.makedirs(os.path.dirname(csv_file_path), exist_ok=True)
    file_exists = os.path.isfile(csv_file_path)

    # บันทึกแบบ Append (ต่อท้ายเรื่อยๆ)
    df_new.to_csv(
        csv_file_path, mode="a", header=not file_exists, index=False, encoding="utf-8"
    )

    print(f"✅ สกัด Features ลง {os.path.basename(csv_file_path)} สำเร็จ!")
    print(
        f"   📊 Spot: {features['spot_price']} | RSI: {features['rsi']} | NY Session: {bool(features['is_ny_session'])}"
    )



# ==========================================
# SHARED HELPERS (ใช้ร่วมกันทั้ง 2 functions)
# ==========================================

def _extract_time_features(timestamp_str: str) -> dict:
    """สกัด Time & Session Features จาก timestamp string"""
    dt = pd.to_datetime(timestamp_str)
    hour = dt.hour
    return {
        "hour":              hour,
        "day_of_week":       dt.dayofweek,  # 0=จันทร์, 6=อาทิตย์
        "is_asian_session":  int(7  <= hour < 15),
        "is_london_session": int(15 <= hour < 23),
        "is_ny_session":     int((20 <= hour <= 23) or (0 <= hour < 4)),
    }


def _extract_sentiment_features(news_by_category: dict) -> dict:
    """สกัด Sentiment เฉลี่ยแยกตาม Category ที่มีผลต่อทองคำโดยตรง"""
    target_categories = [
        "thai_gold_market",
        "gold_price",
        "geopolitics",
        "dollar_index",
        "fed_policy",
    ]
    feats = {}
    for cat in target_categories:
        cat_data = news_by_category.get(cat, {})
        # รองรับทั้ง format เก่า (list) และ format ใหม่ (dict with 'articles' key)
        articles = cat_data if isinstance(cat_data, list) else cat_data.get("articles", [])
        if articles:
            avg = sum(a.get("sentiment_score", 0.0) for a in articles) / len(articles)
        else:
            avg = 0.0
        feats[f"sentiment_{cat}"] = round(avg, 4)
    return feats


def get_xgboost_feature(
    data: Union[dict, str],
    as_dataframe: bool = False,
) -> Union[dict, pd.DataFrame]:
    """
    สกัด Feature Set ที่ครบสมบูรณ์สำหรับ XGBoost Buy/Sell Models
    (ออกแบบให้ตรงกับ hyperparams ใน finetune_dual_results.json)

    Parameters
    ----------
    data : dict | str
        - dict  → payload จาก orchestrator.run() โดยตรง (เร็วกว่า ไม่ต้อง I/O)
        - str   → path ของ latest.json (อ่านไฟล์ให้อัตโนมัติ)
    as_dataframe : bool
        - False → คืน dict  (ใช้กับ model.predict(pd.DataFrame([feat])))
        - True  → คืน pd.DataFrame 1 แถว (ใช้กับ pipeline ที่ต้องการ DataFrame)

    Returns
    -------
    dict หรือ pd.DataFrame ที่มี features เฉพาะตัวเลข พร้อม predict ได้ทันที

    Feature Groups
    --------------
    [1] Time (5)         : hour, day_of_week, session flags x3
    [2] Price (6)        : spot, usd_thb, thai sell/buy/spread/mid
    [3] Momentum (3)     : 1-candle, 5-candle %chg, 10-candle range %
    [4] RSI (2)          : value + signal encoded
    [5] MACD (4)         : line, signal_line, histogram, crossover encoded
    [6] Bollinger (5)    : pct_b, bandwidth, signal encoded, upper/lower distance %
    [7] ATR (2)          : value, volatility_level encoded
    [8] Trend/EMA (5)    : ema_20, ema_50, ema_200, ema_spread %, trend encoded
    [9] Sentiment (5)    : avg score per news category
    ─────────────────────────────────────────────────────────
    Total: 37 features (ทั้งหมดเป็นตัวเลข ไม่มี string / NaN)

    Notes
    -----
    - `sma_200` ใน build_feature_dataset เดิมนั้น key ผิด → indicators.py ใช้ `ema_200`
      ฟังก์ชันนี้แก้ไขเป็น ema_200 ที่ถูกต้องแล้ว
    - sell_model มี scale_pos_weight=2.67 (imbalanced มากกว่า buy_model=1.43)
      ดังนั้น threshold ที่เหมาะสมของ sell อาจต้องปรับสูงกว่า 0.5
    """
    # ── โหลดข้อมูล ─────────────────────────────────────────────────────────────
    if isinstance(data, str):
        if not os.path.exists(data):
            raise FileNotFoundError(f"❌ ไม่พบไฟล์ {data}")
        with open(data, "r", encoding="utf-8") as f:
            data = json.load(f)

    market = data["market_data"]
    tech   = data["technical_indicators"]

    # ─── Encoding Maps ──────────────────────────────────────────────────────────
    _trend_map = {"uptrend": 1, "sideways": 0, "downtrend": -1}

    # bullish_cross=2 (Action) > bullish_zone=1 (State) เพื่อให้ XGBoost แยกน้ำหนักได้
    _macd_cross_map = {
        "bullish_cross": 2,
        "bullish_zone":  1,
        "neutral":       0,
        "bearish_zone": -1,
        "bearish_cross": -2,
    }
    _rsi_signal_map   = {"overbought": 1,  "neutral": 0, "oversold": -1}
    _bb_signal_map    = {"above_upper": 1, "inside": 0,  "below_lower": -1}
    _atr_vol_map      = {"high": 2, "normal": 1, "low": 0}

    # ── [1] TIME FEATURES ───────────────────────────────────────────────────────
    feats = _extract_time_features(data["meta"]["generated_at"])

    # ── [2] PRICE FEATURES ──────────────────────────────────────────────────────
    spot_data  = market.get("spot_price_usd", {})
    forex_data = market.get("forex", {})
    thai_data  = market.get("thai_gold_thb", {})

    sell_thb = float(thai_data.get("sell_price_thb", 0) or 0)
    buy_thb  = float(thai_data.get("buy_price_thb",  0) or 0)
    mid_thb  = float(thai_data.get("mid_price_thb",  0) or (sell_thb + buy_thb) / 2 if sell_thb + buy_thb > 0 else 0)

    feats.update({
        "spot_price":       float(spot_data.get("price_usd_per_oz", 0) or 0),
        "usd_thb":          float(forex_data.get("usd_thb", 0) or 0),
        "thai_gold_sell":   sell_thb,
        "thai_gold_buy":    buy_thb,
        "thai_gold_spread": round(sell_thb - buy_thb, 2),
        "thai_gold_mid":    round(mid_thb, 2),
    })

    # ── [3] PRICE MOMENTUM (จาก price_trend ของ Orchestrator) ──────────────────
    price_trend = market.get("price_trend", {})
    r_high = float(price_trend.get("10p_range_high", 0) or 0)
    r_low  = float(price_trend.get("10p_range_low",  0) or 0)
    range_pct = round((r_high - r_low) / r_low * 100, 4) if r_low > 0 else 0.0

    feats.update({
        "price_change_pct":    float(price_trend.get("change_pct",    0) or 0),
        "price_5p_change_pct": float(price_trend.get("5p_change_pct", 0) or 0),
        "price_10p_range_pct": range_pct,
    })

    # ── [4] RSI ─────────────────────────────────────────────────────────────────
    rsi_data = tech.get("rsi", {})
    feats.update({
        "rsi":               float(rsi_data.get("value",  50) or 50),
        "rsi_signal_encoded": _rsi_signal_map.get(rsi_data.get("signal", "neutral"), 0),
    })

    # ── [5] MACD ────────────────────────────────────────────────────────────────
    macd_data = tech.get("macd", {})
    feats.update({
        "macd_line":              float(macd_data.get("macd_line",   0) or 0),
        "macd_signal_line":       float(macd_data.get("signal_line", 0) or 0),
        "macd_hist":              float(macd_data.get("histogram",   0) or 0),
        "macd_crossover_encoded": _macd_cross_map.get(
            macd_data.get("crossover", macd_data.get("signal", "neutral")), 0
        ),
    })

    # ── [6] BOLLINGER BANDS ─────────────────────────────────────────────────────
    bb_data   = tech.get("bollinger", {})
    spot_px   = feats["spot_price"]
    bb_upper  = float(bb_data.get("upper",  0) or 0)
    bb_lower  = float(bb_data.get("lower",  0) or 0)

    # ระยะห่างจาก Band บน/ล่าง (% ของราคา) → บอกว่าราคาใกล้ขอบแค่ไหน
    dist_upper = round((bb_upper - spot_px) / spot_px * 100, 4) if spot_px > 0 and bb_upper > 0 else 0.0
    dist_lower = round((spot_px - bb_lower) / spot_px * 100, 4) if spot_px > 0 and bb_lower > 0 else 0.0

    feats.update({
        "bb_pct_b":            float(bb_data.get("pct_b",     0.5) or 0.5),
        "bb_bandwidth":        float(bb_data.get("bandwidth", 0)   or 0),
        "bb_signal_encoded":   _bb_signal_map.get(bb_data.get("signal", "inside"), 0),
        "bb_dist_upper_pct":   dist_upper,
        "bb_dist_lower_pct":   dist_lower,
    })

    # ── [7] ATR ─────────────────────────────────────────────────────────────────
    atr_data = tech.get("atr", {})
    feats.update({
        "atr":                    float(atr_data.get("value", 0) or 0),
        "atr_volatility_encoded": _atr_vol_map.get(atr_data.get("volatility_level", "normal"), 1),
    })

    # ── [8] TREND / EMA ─────────────────────────────────────────────────────────
    trend_data = tech.get("trend", {})
    ema_20  = float(trend_data.get("ema_20",  0) or 0)
    ema_50  = float(trend_data.get("ema_50",  0) or 0)
    # หมายเหตุ: key ที่ถูกต้องคือ ema_200 (ไม่ใช่ sma_200 ที่ build_feature_dataset ใช้ผิด)
    ema_200 = float(trend_data.get("ema_200", 0) or 0)

    # % spread ระหว่าง EMA20 กับ EMA50 → วัดความแรงของ Trend
    ema_spread_pct = round((ema_20 - ema_50) / ema_50 * 100, 4) if ema_50 > 0 else 0.0

    feats.update({
        "ema_20":           ema_20,
        "ema_50":           ema_50,
        "ema_200":          ema_200,
        "ema_20_50_spread_pct": ema_spread_pct,
        "trend_encoded":    _trend_map.get(trend_data.get("trend", "sideways"), 0),
    })

    # ── [9] SENTIMENT ───────────────────────────────────────────────────────────
    news_by_cat = data.get("news", {}).get("by_category", {})
    feats.update(_extract_sentiment_features(news_by_cat))

    # ── Sanity check: แทน NaN/Inf ด้วย 0 ────────────────────────────────────────
    feats = {
        k: (0.0 if (v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v)))) else v)
        for k, v in feats.items()
    }

    if as_dataframe:
        return pd.DataFrame([feats])
    return feats


# ============================================================
# v2.1 — 26-feature extractor for Dual-Model XGBoost
# ============================================================
#
# คืน dict ที่มี keys ตรงกับไฟล์ models/feature_columns.json (length=26)
# ใช้ในระบบ inference หลักของ Src_V2 main.py (XGBoostPredictor dual model)
#
# IMPORTANT: ห้ามแก้ get_xgboost_feature() เดิม (37 features) เพราะมีโค้ดอื่นใช้

# Schema canonical สำหรับ 26 features (ใช้ตรวจซ้ำว่า keys ครบ)
_V2_FEATURE_COLUMNS = [
    "xauusd_open", "xauusd_high", "xauusd_low", "xauusd_close",
    "xauusd_ret1", "xauusd_ret3", "usdthb_ret1",
    "xau_macd_delta1", "xauusd_dist_ema21", "xauusd_dist_ema50",
    "usdthb_dist_ema21", "trend_regime",
    "xauusd_rsi14", "xau_rsi_delta1", "xauusd_macd_hist",
    "xauusd_atr_norm", "xauusd_bb_width", "atr_rank50",
    "wick_bias", "body_strength",
    "hour_sin", "hour_cos", "minute_sin", "minute_cos",
    "session_progress", "day_of_week",
]

_V2_TREND_MAP = {"uptrend": 1.0, "sideways": 0.0, "downtrend": -1.0}
_EPS = 1e-9


def _safe_float(v, default: float = 0.0) -> float:
    """แปลงเป็น float พร้อม guard NaN/Inf/None → default"""
    if v is None:
        return float(default)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return float(default)
    if np.isnan(f) or np.isinf(f):
        return float(default)
    return f


def _session_progress(hour: int, minute: int) -> float:
    """0..1 ตามตำแหน่งภายใน Asian/London/NY session (เวลาไทย UTC+7)"""
    minutes_of_day = hour * 60 + minute
    # Asian 07:00-15:00
    if 7 * 60 <= minutes_of_day < 15 * 60:
        return (minutes_of_day - 7 * 60) / (8 * 60)
    # London 15:00-23:00
    if 15 * 60 <= minutes_of_day < 23 * 60:
        return (minutes_of_day - 15 * 60) / (8 * 60)
    # NY (overlap) 20:00-04:00 — handle wrap
    if 20 * 60 <= minutes_of_day < 24 * 60:
        return (minutes_of_day - 20 * 60) / (8 * 60)
    if 0 <= minutes_of_day < 4 * 60:
        return (minutes_of_day + 4 * 60) / (8 * 60)
    return 0.0


# ============================================================
# OHLCV-based computation helpers (ใช้เฉพาะใน get_xgboost_feature_v2)
# คำนวณ indicator จาก _raw_ohlcv โดยตรงเพื่อให้ได้ค่า delta ที่ถูกต้อง
# แทนที่การพึ่งพา prev_value / prev_histogram ใน payload ซึ่งมักไม่มี
# ============================================================

def _ohlcv_ema(series: pd.Series, span: int) -> pd.Series:
    """EMA แบบ Wilder-compatible (adjust=False) — ใช้ span ตรงๆ"""
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def _ohlcv_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    """
    RSI แบบ Wilder Smoothing (EWM com=period-1) — ตรงกับ TradingView / ta-lib
    คืน Series ขนาดเท่ากับ closes (NaN ช่วงแรกก่อนมีข้อมูลพอ)
    """
    delta = closes.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(com=period - 1, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def _ohlcv_macd_hist(closes: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    """
    MACD Histogram = (EMA_fast - EMA_slow) - EMA_signal
    ตรงกับ standard MACD ที่ใช้ทั่วไป
    """
    ema_fast = closes.ewm(span=fast, adjust=False, min_periods=fast).mean()
    ema_slow = closes.ewm(span=slow, adjust=False, min_periods=slow).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    return macd_line - signal_line


def _ohlcv_true_range(ohlcv: pd.DataFrame) -> pd.Series:
    """
    True Range = max(H-L, |H-prevC|, |L-prevC|)
    แม่นกว่า H-L อย่างเดียวโดยเฉพาะช่วง gap
    """
    high  = ohlcv["high"].astype(float)
    low   = ohlcv["low"].astype(float)
    close = ohlcv["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr


# ============================================================
# USDTHB Series Fetcher — พร้อม in-memory cache 5 นาที
#
# ทำไมต้องมีตัวนี้:
#   orchestrator ส่ง USDTHB มาเป็น snapshot เดียว (32.47)
#   แต่ feature usdthb_ret1 และ usdthb_dist_ema21 ต้องการ time series
#   จึงดึง USDTHB=X จาก yfinance โดยตรง + cache 5 นาทีเพื่อไม่ hit API ทุกรอบ
# ============================================================

_usdthb_series_cache: dict = {
    "series": None,     # pd.Series | None
    "fetched_at": 0.0,  # monotonic timestamp
}
_USDTHB_SERIES_TTL: int = 300  # วินาที (5 นาที)


def _fetch_usdthb_series(interval: str = "5m", min_candles: int = 25) -> pd.Series:
    """
    ดึง USDTHB close series จาก yfinance (ticker: USDTHB=X)
    - Cache TTL 5 นาที → ไม่ hit API ทุกรอบ 15 นาที
    - ต้องการ >=25 candles (EMA21 + buffer) ถ้าน้อยกว่าคืน empty Series
    - ถ้า yfinance ไม่ได้ติดตั้ง หรือ network ขาด → คืน empty Series (ไม่ crash)

    Returns
    -------
    pd.Series[float]  close prices เรียงตาม time (index=DatetimeIndex)
                      ว่างถ้าดึงไม่ได้ → features กลับไปเป็น 0.0
    """
    global _usdthb_series_cache

    now = _time.monotonic()
    cached = _usdthb_series_cache
    if (
        cached["series"] is not None
        and len(cached["series"]) >= min_candles
        and (now - cached["fetched_at"]) < _USDTHB_SERIES_TTL
    ):
        return cached["series"]

    try:
        import yfinance as yf

        df = yf.download(
            "USDTHB=X",
            period="5d",        # 5 วัน → มีข้อมูล forex เพียงพอแน่นอน (forex 5m)
            interval=interval,
            auto_adjust=True,
            progress=False,
        )
        if df.empty:
            logger.warning("[USDTHB] yfinance returned empty DataFrame for USDTHB=X")
            return pd.Series(dtype=float)

        # yfinance อาจส่ง MultiIndex columns มาถ้า version ใหม่
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close_col = next((c for c in df.columns if c.lower() == "close"), None)
        if close_col is None:
            logger.warning("[USDTHB] 'Close' column not found in USDTHB=X data")
            return pd.Series(dtype=float)

        closes = df[close_col].astype(float).dropna()
        if len(closes) < min_candles:
            logger.warning(
                "[USDTHB] not enough candles: got %d, need %d", len(closes), min_candles
            )
            return pd.Series(dtype=float)

        # อัปเดต cache
        _usdthb_series_cache["series"] = closes
        _usdthb_series_cache["fetched_at"] = now
        logger.info("[USDTHB] fetched %d candles (5m) from yfinance", len(closes))
        return closes

    except ImportError:
        logger.warning("[USDTHB] yfinance not installed → usdthb features = 0.0")
        return pd.Series(dtype=float)
    except Exception as exc:
        logger.warning("[USDTHB] fetch failed: %s → usdthb features = 0.0", exc)
        return pd.Series(dtype=float)


def get_xgboost_feature_v2(market_state: dict) -> dict:
    """
    สกัด **26 features** ตาม schema models/feature_columns.json
    สำหรับใช้กับ Dual-Model XGBoost (model_buy.pkl + model_sell.pkl)

    Parameters
    ----------
    market_state : dict
        payload จาก GoldTradingOrchestrator.run() — ต้องมี:
        - "_raw_ohlcv" : pandas.DataFrame index Asia/Bangkok (open/high/low/close)
        - "market_data" : forex / thai_gold_thb / spot_price_usd
        - "technical_indicators" : rsi / macd / bollinger / atr / trend
        - "meta.generated_at" : ISO timestamp

    Returns
    -------
    dict[str, float] : ขนาด 26, key ตรงกับ _V2_FEATURE_COLUMNS เป๊ะ
    """
    md = market_state.get("market_data", {}) or {}
    ti = market_state.get("technical_indicators", {}) or {}
    ohlcv = market_state.get("_raw_ohlcv")

    # ── 1. Candle OHLC + returns + OHLCV-derived indicators ──────
    o = h = l = c = 0.0
    ret1 = ret3 = 0.0
    atr_rank50  = 0.5   # default neutral rank
    rsi_delta1  = 0.0   # computed from OHLCV RSI series
    macd_delta1 = 0.0   # computed from OHLCV MACD series
    dist_ema21  = 0.0   # computed from OHLCV EMA21 (ไม่ใช้ ema_20 ของ payload ที่ชื่อผิด)

    _has_ohlcv = isinstance(ohlcv, pd.DataFrame) and not ohlcv.empty

    if _has_ohlcv:
        last = ohlcv.iloc[-1]
        o = _safe_float(last.get("open"))
        h = _safe_float(last.get("high"))
        l = _safe_float(last.get("low"))
        c = _safe_float(last.get("close"))

        closes = (
            ohlcv["close"].astype(float).dropna()
            if "close" in ohlcv.columns
            else pd.Series(dtype=float)
        )

        # ── returns ────────────────────────────────────────────
        if len(closes) >= 2 and closes.iloc[-2] != 0:
            ret1 = float(closes.iloc[-1] / closes.iloc[-2] - 1.0)
        if len(closes) >= 4 and closes.iloc[-4] != 0:
            ret3 = float(closes.iloc[-1] / closes.iloc[-4] - 1.0)

        # ── RSI delta: rsi[-1] - rsi[-2] (OHLCV-computed) ─────
        # แก้ปัญหา: payload ไม่มี prev_value → rsi_delta1 เคยเป็น 0 ตลอด
        if len(closes) >= 30:  # ต้องการ >= period+warmup
            try:
                rsi_series = _ohlcv_rsi(closes, period=14).dropna()
                if len(rsi_series) >= 2:
                    rsi_delta1 = float(rsi_series.iloc[-1] - rsi_series.iloc[-2])
            except Exception:
                rsi_delta1 = 0.0

        # ── MACD histogram delta: hist[-1] - hist[-2] (OHLCV-computed) ─
        # แก้ปัญหา: payload ไม่มี prev_histogram → macd_delta1 เคยเป็น 0 ตลอด
        if len(closes) >= 60:  # ต้องการ >= slow+signal+warmup
            try:
                macd_hist_series = _ohlcv_macd_hist(closes).dropna()
                if len(macd_hist_series) >= 2:
                    macd_delta1 = float(
                        macd_hist_series.iloc[-1] - macd_hist_series.iloc[-2]
                    )
            except Exception:
                macd_delta1 = 0.0

        # ── EMA21 distance (OHLCV-computed, ไม่ใช้ ema_20 ของ payload) ─
        # แก้ปัญหา: payload ให้แค่ ema_20 แต่ feature ชื่อ dist_ema21
        if len(closes) >= 21:
            try:
                ema21_series = _ohlcv_ema(closes, span=21).dropna()
                if len(ema21_series) >= 1:
                    ema21_val = float(ema21_series.iloc[-1])
                    dist_ema21 = (c - ema21_val) / ema21_val if ema21_val > 0 else 0.0
            except Exception:
                dist_ema21 = 0.0

        # ── ATR rank50 (True Range แท้จริง ไม่ใช่ H-L approximation) ─
        # แก้ปัญหา: เดิมใช้ H-L เท่านั้น → underestimate ช่วง gap
        _ohlcv_cols = {"high", "low", "close"}
        if len(ohlcv) >= 5 and _ohlcv_cols.issubset(ohlcv.columns):
            try:
                tr = _ohlcv_true_range(ohlcv)
                window_tr = tr.tail(50).dropna()
                if len(window_tr) >= 5:
                    atr_rank50 = _safe_float(window_tr.rank(pct=True).iloc[-1], 0.5)
            except Exception:
                atr_rank50 = 0.5

    # ── 2. Forex / USDTHB ───────────────────────────────────────
    # ดึง USDTHB time series จาก yfinance (cache 5 นาที)
    # เพื่อคำนวณ usdthb_ret1 และ usdthb_dist_ema21 แทนค่า 0.0 เดิม
    usdthb_ret1       = 0.0
    usdthb_dist_ema21 = 0.0

    _usdthb_closes = _fetch_usdthb_series(interval="5m", min_candles=25)

    if len(_usdthb_closes) >= 2:
        _uthb_cur  = _safe_float(_usdthb_closes.iloc[-1])
        _uthb_prev = _safe_float(_usdthb_closes.iloc[-2])
        if _uthb_prev > 0:
            usdthb_ret1 = (_uthb_cur / _uthb_prev) - 1.0  # 1-candle % return

        # EMA21 distance: ต้องการ >=21 candles (แต่ series มีอยู่แล้ว >=25)
        if len(_usdthb_closes) >= 21:
            try:
                _ema21_thb_series = _ohlcv_ema(_usdthb_closes, span=21).dropna()
                if len(_ema21_thb_series) >= 1:
                    _ema21_thb_val = float(_ema21_thb_series.iloc[-1])
                    if _ema21_thb_val > 0:
                        usdthb_dist_ema21 = (_uthb_cur - _ema21_thb_val) / _ema21_thb_val
            except Exception:
                usdthb_dist_ema21 = 0.0

    # ── 3. RSI (current value จาก payload — แม่นกว่า OHLCV ถ้า orchestrator คำนวณครบ)
    rsi_data = ti.get("rsi") or {}
    rsi = _safe_float(rsi_data.get("value"), 50.0)
    # rsi_delta1 คำนวณจาก OHLCV แล้วด้านบน — ไม่ทับตรงนี้

    # ── 4. MACD ─────────────────────────────────────────────────
    macd_data = ti.get("macd") or {}
    macd_hist = _safe_float(macd_data.get("histogram"))
    # macd_delta1 คำนวณจาก OHLCV แล้วด้านบน — ไม่ทับตรงนี้

    # ── 5. Bollinger ────────────────────────────────────────────
    bb_data = ti.get("bollinger") or {}
    bb_width = _safe_float(bb_data.get("bandwidth"))

    # ── 6. ATR (normalized vs price) ───────────────────────────
    atr_data = ti.get("atr") or {}
    atr_value = _safe_float(atr_data.get("value"))
    atr_norm = (atr_value / c) if c > 0 else 0.0

    # ── 7. Trend / EMA ──────────────────────────────────────────
    trend_data = ti.get("trend") or {}
    # dist_ema21 คำนวณจาก OHLCV EMA21 แล้วด้านบน — ไม่ทับตรงนี้
    ema_50 = _safe_float(trend_data.get("ema_50"))
    dist_ema50 = (c - ema_50) / ema_50 if ema_50 > 0 else 0.0
    trend_regime = _V2_TREND_MAP.get(str(trend_data.get("trend", "sideways")).lower(), 0.0)

    # ── 8. Candle metrics: wick_bias + body_strength ───────────
    rng = h - l
    if rng > _EPS:
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l
        wick_bias = (upper_wick - lower_wick) / rng
        body_strength = abs(c - o) / rng
    else:
        wick_bias = 0.0
        body_strength = 0.0

    # ── 9. Time encodings ───────────────────────────────────────
    ts_str = (market_state.get("meta") or {}).get("generated_at") \
        or market_state.get("timestamp")
    try:
        dt = pd.to_datetime(ts_str)
    except Exception:
        dt = pd.Timestamp.now(tz="Asia/Bangkok")
    hour = int(dt.hour)
    minute = int(dt.minute)
    dow = int(dt.dayofweek)

    hour_rad = 2.0 * np.pi * (hour / 24.0)
    minute_rad = 2.0 * np.pi * (minute / 60.0)
    

    feats = {
        # Candle
        "xauusd_open":        _safe_float(o),
        "xauusd_high":        _safe_float(h),
        "xauusd_low":         _safe_float(l),
        "xauusd_close":       _safe_float(c),
        "xauusd_ret1":        _safe_float(ret1),
        "xauusd_ret3":        _safe_float(ret3),
        "usdthb_ret1":        _safe_float(usdthb_ret1),
        # MACD / EMA distances / trend
        "xau_macd_delta1":    _safe_float(macd_delta1),
        "xauusd_dist_ema21":  _safe_float(dist_ema21),
        "xauusd_dist_ema50":  _safe_float(dist_ema50),
        "usdthb_dist_ema21":  _safe_float(usdthb_dist_ema21),
        "trend_regime":       _safe_float(trend_regime),
        # Oscillators
        "xauusd_rsi14":       _safe_float(rsi),
        "xau_rsi_delta1":     _safe_float(rsi_delta1),
        "xauusd_macd_hist":   _safe_float(macd_hist),
        # Volatility
        "xauusd_atr_norm":    _safe_float(atr_norm),
        "xauusd_bb_width":    _safe_float(bb_width),
        "atr_rank50":         _safe_float(atr_rank50, 0.5),
        # Candle shape
        "wick_bias":          _safe_float(wick_bias),
        "body_strength":      _safe_float(body_strength),
        # Cyclic time
        "hour_sin":           float(np.sin(hour_rad)),
        "hour_cos":           float(np.cos(hour_rad)),
        "minute_sin":         float(np.sin(minute_rad)),
        "minute_cos":         float(np.cos(minute_rad)),
        "session_progress":   _safe_float(_session_progress(hour, minute)),
        "day_of_week":        float(dow),
    }
    
    print("**********************************************************************")
    print(feats)
    print("**********************************************************************")

    # Sanity: ต้องครบ 26 keys ตรงตาม schema
    missing = [k for k in _V2_FEATURE_COLUMNS if k not in feats]
    if missing:
        raise RuntimeError(f"get_xgboost_feature_v2: missing keys {missing}")

    # คืนเฉพาะ 26 keys ตามลำดับ schema
    return {k: feats[k] for k in _V2_FEATURE_COLUMNS}


if __name__ == "__main__":
    # หาตำแหน่งไฟล์ extract_features.py (ใน Src/data_engine)
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # ชี้เป้าไปที่ output/latest.json และ Data/features_master.csv นอกสุด
    json_path = os.path.join(current_dir, "..", "agent_core", "data", "latest.json")
    csv_path = os.path.join(current_dir, "..", "..", "Data", "features_master.csv")

    build_feature_dataset(json_file_path=json_path, csv_file_path=csv_path)