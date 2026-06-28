import pandas as pd
import pickle
import json

# 1. โหลดโมเดล (สมมติว่าใช้ model_buy.pkl)
with open("model_buy.pkl", "rb") as f:
    model_buy = pickle.load(f)

# 2. โหลดลิสต์รายชื่อคอลัมน์จากไฟล์ JSON
with open("feature_columns.json", "r") as f:
    feature_columns = json.load(f)

# 3. สมมติว่าคุณดึงข้อมูลตลาดล่าสุดมาแล้ว และคำนวณค่าต่างๆ เสร็จหมดแล้ว
# (ข้อมูลสมมติ ณ เวลาปัจจุบัน)
latest_market_data = {
    "xauusd_open": 2300.50,
    "xauusd_high": 2305.00,
    "xauusd_low": 2298.00,
    "xauusd_close": 2302.10,
    "xauusd_ret1": 0.0015,
    "xauusd_ret3": -0.0005,
    "usdthb_ret1": 0.0002,
    "xau_macd_delta1": 0.5,
    "xauusd_dist_ema21": 2.5,
    "xauusd_dist_ema50": 5.0,
    "usdthb_dist_ema21": 0.01,
    "trend_regime": 1,
    "xauusd_rsi14": 58.5,
    "xau_rsi_delta1": 2.1,
    "xauusd_macd_hist": 1.2,
    "xauusd_atr_norm": 0.002,
    "xauusd_bb_width": 0.005,
    "atr_rank50": 0.8,
    "wick_bias": 0.1,
    "body_strength": 0.6,
    "hour_sin": 0.866,
    "hour_cos": 0.5,
    "minute_sin": 0.0,
    "minute_cos": 1.0,
    "session_progress": 0.4,
    "day_of_week": 2
}

# 4. แปลงข้อมูลล่าสุดให้เป็น Pandas DataFrame
df_new = pd.DataFrame([latest_market_data])

# 5. ⚠️ จุดสำคัญ: บังคับเรียงลำดับคอลัมน์ให้ตรงกับตอนเทรนโมเดลเป๊ะๆ
df_ready = df_new[feature_columns]

# 6. โยนเข้าโมเดลเพื่อทำนาย (Predict)
# แทนที่จะใช้ .predict() ธรรมดา
# prediction = model_buy.predict(df_ready)

# ให้ใช้ .predict_proba() เพื่อดึงค่า Entry Prob Buy ออกมา (จะตรงกับในตาราง Google Sheets ของคุณ)
probabilities = model_buy.predict_proba(df_ready)

# โครงสร้างผลลัพธ์จะเป็น [Prob_ฝั่ง0, Prob_ฝั่ง1]
# เราดึงเฉพาะดัชนี [0][1] ซึ่งคือ Entry Prob Buy
prob_buy = probabilities[0][1] 

print(f"ความน่าจะเป็นในการ Buy: {prob_buy:.3f}")

# นำไปสร้างเงื่อนไขเข้าเทรดที่คมขึ้น (อ้างอิงจาก Backtest ของคุณที่ 0.8+ แล้วกำไร MFE สูงมาก)
if prob_buy >= 0.85:
    print("🔥 สัญญาณ BUY คุณภาพสูง! ยิงออเดอร์เลย!")
else:
    print("⏳ สัญญาณยังไม่ชัดเจน รอก่อน (No Trade)")