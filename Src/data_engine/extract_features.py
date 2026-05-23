import json
import os
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Union


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
    is_asian = 1 if 7 <= hour < 15 else 0
    is_london = 1 if 15 <= hour < 23 else 0
    is_ny = 1 if (20 <= hour <= 23) or (0 <= hour < 4) else 0

    # ==========================================
    # 2. MARKET & TECHNICAL FEATURES
    # ==========================================
    market = data["market_data"]
    tech = data["technical_indicators"]

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
    """สกัดเฉพาะ Time Features สำหรับ XGBoost Model (26 Features Set)"""
    dt = pd.to_datetime(timestamp_str)
    hour = dt.hour
    minute = dt.minute
    
    # ── Cyclical Encoding ──────────────────────────────────────────────────────
    hour_sin = round(np.sin(2 * np.pi * hour / 24), 6)
    hour_cos = round(np.cos(2 * np.pi * hour / 24), 6)
    minute_sin = round(np.sin(2 * np.pi * minute / 60), 6)
    minute_cos = round(np.cos(2 * np.pi * minute / 60), 6)
    
    # ── Session Progress (0.0 - 1.0) ──────────────────────────────────────────
    total_minutes = hour * 60 + minute
    session_length = 8 * 60  # ทุก Session = 8 ชม. = 480 นาที
    
    if 7 <= hour < 15:
        minutes_from_start = total_minutes - (7 * 60)
        session_progress = round(minutes_from_start / session_length, 4)
    elif 15 <= hour < 23:
        minutes_from_start = total_minutes - (15 * 60)
        session_progress = round(minutes_from_start / session_length, 4)
    elif (20 <= hour <= 23) or (0 <= hour < 4):
        if total_minutes >= 20 * 60:
            minutes_from_start = total_minutes - (20 * 60)
        else:
            minutes_from_start = (4 * 60) + total_minutes
        session_progress = round(minutes_from_start / session_length, 4)
    else:
        session_progress = 0.0
        
    session_progress = max(0.0, min(1.0, session_progress))
    
    return {
        "hour_sin": hour_sin,
        "hour_cos": hour_cos,
        "minute_sin": minute_sin,
        "minute_cos": minute_cos,
        "session_progress": session_progress,
        "day_of_week": dt.dayofweek,
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
    ออกแบบให้ส่งออกเฉพาะ 26 Features ที่มีประสิทธิภาพสูงสุด

    Parameters
    ----------
    data : dict | str
        - dict  → payload จาก orchestrator.run() โดยตรง
        - str   → path ของ latest.json
    as_dataframe : bool
        - False → คืน dict
        - True  → คืน pd.DataFrame 1 แถว

    Returns
    -------
    dict หรือ pd.DataFrame ที่มี 26 features (ทั้งหมดเป็นตัวเลข พร้อม predict ได้ทันที)
    """
    # ── โหลดข้อมูล ─────────────────────────────────────────────────────────────
    if isinstance(data, str):
        if not os.path.exists(data):
            raise FileNotFoundError(f"❌ ไม่พบไฟล์ {data}")
        with open(data, "r", encoding="utf-8") as f:
            data = json.load(f)

    market = data["market_data"]
    tech   = data["technical_indicators"]

    # ── แยกข้อมูลย่อย ─────────────────────────────────────────────────────────
    spot_data   = market.get("spot_price_usd", {})
    # รองรับทั้ง key "ohlc" หรือ "xauusd_ohlc" ถ้ามีใน JSON
    ohlc_data   = market.get("ohlc", {}) or market.get("xauusd_ohlc", {})
    forex_data  = market.get("forex", {})
    price_trend = market.get("price_trend", {})
    
    trend_data  = tech.get("trend", {})
    rsi_data    = tech.get("rsi", {})
    macd_data   = tech.get("macd", {})
    atr_data    = tech.get("atr", {})
    bb_data     = tech.get("bollinger", {})

    # ── [1] OHLC DATA ───────────────────────────────────────────────────────────
    # ถ้าไม่มี OHLC จริง จะใช้ close จาก spot_price แทนทั้งหมด เพื่อป้องกัน Error
    close_px = float(ohlc_data.get("close", spot_data.get("price_usd_per_oz", 0) or 0))
    open_px  = float(ohlc_data.get("open", close_px) or close_px)
    high_px  = float(ohlc_data.get("high", close_px) or close_px)
    low_px   = float(ohlc_data.get("low", close_px) or close_px)

    # ── [2] RETURNS & DELTAS ────────────────────────────────────────────────────
    xauusd_ret1 = float(price_trend.get("change_pct", 0) or 0)
    xauusd_ret3 = float(price_trend.get("3p_change_pct", 0) or 0)
    usdthb_ret1 = float(forex_data.get("usd_thb_change_pct", 0) or 0)
    
    xau_macd_delta1 = float(macd_data.get("delta1", 0) or 0)
    xau_rsi_delta1  = float(rsi_data.get("delta1", 0) or 0)

    # ── [3] DISTANCE FROM EMAs ──────────────────────────────────────────────────
    ema_21 = float(trend_data.get("ema_21", trend_data.get("ema_20", 0)) or 0) # ถ้าไม่มี 21 ใช้ 20 แทน
    ema_50 = float(trend_data.get("ema_50", 0) or 0)

    xauusd_dist_ema21 = round((close_px - ema_21) / close_px * 100, 4) if (close_px > 0 and ema_21 > 0) else 0.0
    xauusd_dist_ema50 = round((close_px - ema_50) / close_px * 100, 4) if (close_px > 0 and ema_50 > 0) else 0.0
    usdthb_dist_ema21 = float(forex_data.get("usd_thb_dist_ema21", 0) or 0)

    # ── [4] INDICATORS ──────────────────────────────────────────────────────────
    _trend_map = {"uptrend": 1, "sideways": 0, "downtrend": -1}
    trend_regime    = _trend_map.get(trend_data.get("trend", "sideways"), 0)
    xauusd_rsi14    = float(rsi_data.get("value", 50) or 50)
    xauusd_macd_hist = float(macd_data.get("histogram", 0) or 0)
    xauusd_bb_width = float(bb_data.get("bandwidth", 0) or 0)
    
    # ATR Normalized (เป็น % ของราคา) ถ้าไม่มี key ให้คำนวณจาก ATR / Close
    atr_val = float(atr_data.get("value", 0) or 0)
    xauusd_atr_norm = float(atr_data.get("normalized", round(atr_val / close_px * 100, 4) if close_px > 0 else 0.0) or 0)
    
    atr_rank50 = float(atr_data.get("rank50", 0.5) or 0.5)

    # ── [5] CANDLESTICK PATTERNS ────────────────────────────────────────────────
    # คำนวณจาก OHLC ถ้ามี (กรณีไม่มี OHLC จะได้ 0.0)
    range_size = high_px - low_px
    if range_size > 0:
        # wick_bias: ตั้งแต่ +1 (Close=High, ซื้อขาด) ถึง -1 (Close=Low, ขายขาด)
        wick_bias = round((close_px - low_px - (high_px - close_px)) / range_size, 4)
        # body_strength: ขนาดตัวเทียบกับความกว้าง (1 = Marubozu)
        body_strength = round(abs(close_px - open_px) / range_size, 4)
    else:
        wick_bias = 0.0
        body_strength = 0.0

    # ── [6] TIME FEATURES ───────────────────────────────────────────────────────
    time_feats = _extract_time_features(data["meta"]["generated_at"])

    # ── [ASSEMBLE FINAL 26 FEATURES] ───────────────────────────────────────────
    feats = {
        "xauusd_open":        open_px,
        "xauusd_high":        high_px,
        "xauusd_low":         low_px,
        "xauusd_close":       close_px,
        "xauusd_ret1":        xauusd_ret1,
        "xauusd_ret3":        xauusd_ret3,
        "usdthb_ret1":        usdthb_ret1,
        "xau_macd_delta1":    xau_macd_delta1,
        "xauusd_dist_ema21":  xauusd_dist_ema21,
        "xauusd_dist_ema50":  xauusd_dist_ema50,
        "usdthb_dist_ema21":  usdthb_dist_ema21,
        "trend_regime":       trend_regime,
        "xauusd_rsi14":       xauusd_rsi14,
        "xau_rsi_delta1":     xau_rsi_delta1,
        "xauusd_macd_hist":   xauusd_macd_hist,
        "xauusd_atr_norm":    xauusd_atr_norm,
        "xauusd_bb_width":    xauusd_bb_width,
        "atr_rank50":         atr_rank50,
        "wick_bias":          wick_bias,
        "body_strength":      body_strength,
        "hour_sin":           time_feats["hour_sin"],
        "hour_cos":           time_feats["hour_cos"],
        "minute_sin":         time_feats["minute_sin"],
        "minute_cos":         time_feats["minute_cos"],
        "session_progress":   time_feats["session_progress"],
        "day_of_week":        time_feats["day_of_week"],
    }

    # ── Sanity check: แทน NaN/Inf ด้วย 0 ────────────────────────────────────────
    feats = {
        k: (0.0 if (v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v)))) else v)
        for k, v in feats.items()
    }

    if as_dataframe:
        return pd.DataFrame([feats])
    return feats


if __name__ == "__main__":
    # หาตำแหน่งไฟล์ extract_features.py (ใน Src/data_engine)
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # ชี้เป้าไปที่ output/latest.json และ Data/features_master.csv นอกสุด
    json_path = os.path.join(current_dir, "..", "agent_core", "data", "latest.json")
    csv_path = os.path.join(current_dir, "..", "..", "Data", "features_master.csv")

    build_feature_dataset(json_file_path=json_path, csv_file_path=csv_path)