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


if __name__ == "__main__":
    # หาตำแหน่งไฟล์ extract_features.py (ใน Src/data_engine)
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # ชี้เป้าไปที่ output/latest.json และ Data/features_master.csv นอกสุด
    json_path = os.path.join(current_dir, "..", "agent_core", "data", "latest.json")
    csv_path = os.path.join(current_dir, "..", "..", "Data", "features_master.csv")

    build_feature_dataset(json_file_path=json_path, csv_file_path=csv_path)