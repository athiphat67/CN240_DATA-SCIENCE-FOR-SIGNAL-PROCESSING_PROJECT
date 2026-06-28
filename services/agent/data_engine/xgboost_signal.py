import os
import io
import joblib
import requests
import numpy as np
from dotenv import load_dotenv

from data_engine.extract_features import get_xgboost_feature

load_dotenv()

# ─────────────────────────────────────────────────────────────
# Signal Config  (ปรับได้ตาม model_using.md § 3.1 / § 4)
# ─────────────────────────────────────────────────────────────
BASE_THRESHOLD = 0.70   # เกณฑ์หลักกลาง Session
MIN_THRESHOLD  = 0.55   # เกณฑ์ต่ำสุดที่ยอมรับ (ท้าย Session)
CONFLICT_GAP   = 0.15   # ระยะห่างขั้นต่ำระหว่าง prob_buy และ prob_sell

# ─────────────────────────────────────────────────────────────
# Model Cache — โหลดครั้งเดียว ใช้ซ้ำตลอด process
# ─────────────────────────────────────────────────────────────
_model_cache: dict = {}   # {"buy": <model>, "sell": <model>}


def _load_model_from_hf(model_key: str, hf_url: str, hf_token: str):
    """
    โหลด .pkl model จาก HuggingFace file URL แล้ว cache ไว้ใน memory
    ถ้าโหลดแล้วจะไม่ดาวน์โหลดซ้ำจนกว่า process จะ restart
    """
    if model_key in _model_cache:
        return _model_cache[model_key]

    print(f"📥 [XGBoost] Downloading {model_key} model from HuggingFace...")

    headers = {"Authorization": f"Bearer {hf_token}"}
    response = requests.get(hf_url, headers=headers, timeout=30)
    response.raise_for_status()

    model = joblib.load(io.BytesIO(response.content))
    _model_cache[model_key] = model

    print(f"✅ [XGBoost] {model_key} model loaded ({len(response.content) / 1024:.1f} KB)")
    return model


# ─────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────

def _compute_dynamic_threshold(session_progress: float, trades_done: int) -> float:
    """
    คำนวณ Dynamic Threshold ตาม model_using.md § 2.3

    trades_done == 0  (ยังไม่ได้เทรดใน Session นี้)
      - progress < 0.5   → base + 0.10  (เข้มงวดมาก ต้นรอบ)
      - progress 0.5–0.9 → ค่อยๆ ลด base → min  (เปิดรับมากขึ้น)
      - progress > 0.9   → MIN_THRESHOLD  (ยืดหยุ่น ท้ายรอบ)

    trades_done > 0   (เทรดไปแล้ว)
      → base + 0.15  (เข้มงวดขึ้นอีก ป้องกัน Overtrading)
    """
    if trades_done > 0:
        return BASE_THRESHOLD + 0.15

    if session_progress < 0.5:
        return BASE_THRESHOLD + 0.10

    if session_progress <= 0.9:
        # Linear interpolation: base → min ในช่วง 0.5 – 0.9
        t = (session_progress - 0.5) / 0.4
        return round(BASE_THRESHOLD + (MIN_THRESHOLD - BASE_THRESHOLD) * t, 4)

    return MIN_THRESHOLD


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

def get_xgboost_signal(raw_data: dict, trades_done_in_session: int = 0) -> str:
    """
    Dual-Model XGBoost Signal สำหรับทองคำไทย

    ขั้นตอน (ตาม model_using.md § 2)
    ──────────────────────────────────
    1. สกัด 26 Features จาก raw_data
    2. โหลด BUY Model (.pkl) จาก HF → cache ไว้ใน memory
    3. โหลด SELL Model (.pkl) จาก HF → cache ไว้ใน memory
    4. เรียก predict_proba() → prob_buy, prob_sell
    5. ตรวจ Conflict Gap
    6. คำนวณ Dynamic Threshold ตาม session_progress และ trades_done_in_session
    7. ออกสัญญาณ BUY / SELL / HOLD

    .env ที่ต้องมี
    ───────────────
    HF_TOKEN              = hf_...
    HF_XGBOOST_BUY_URL    = https://huggingface.co/.../model_buy.pkl?download=true
    HF_XGBOOST_SELL_URL   = https://huggingface.co/.../model_sell.pkl?download=true
    """
    # ── 1. ตรวจสอบ Config ─────────────────────────────────────────────────────
    hf_token        = os.getenv("HF_TOKEN")
    hf_buy_url      = os.getenv("HF_XGBOOST_BUY_URL")
    hf_sell_url     = os.getenv("HF_XGBOOST_SELL_URL")

    if not hf_token or not hf_buy_url or not hf_sell_url:
        print("⚠️ [XGBoost] ข้ามการทำงาน: ไม่พบ HF_TOKEN / HF_XGBOOST_BUY_URL / HF_XGBOOST_SELL_URL ใน .env")
        return "HOLD"

    # ── 2. สกัด Features ──────────────────────────────────────────────────────
    features = get_xgboost_feature(raw_data, as_dataframe=True)  # คืน DataFrame 1 แถว
    session_progress = float(features["session_progress"].iloc[0])

    # ── 3. โหลด / ดึงจาก Cache ────────────────────────────────────────────────
    try:
        buy_model  = _load_model_from_hf("buy",  hf_buy_url,  hf_token)
        sell_model = _load_model_from_hf("sell", hf_sell_url, hf_token)
    except requests.exceptions.HTTPError as e:
        print(f"❌ [XGBoost] ดาวน์โหลดโมเดลไม่สำเร็จ: {e}")
        print("💡 ตรวจสอบว่า HF_XGBOOST_BUY_URL / HF_XGBOOST_SELL_URL ถูกต้อง และ HF_TOKEN มีสิทธิ์เข้าถึง")
        return "HOLD"
    except Exception as e:
        print(f"❌ [XGBoost] โหลดโมเดลล้มเหลว: {e}")
        return "HOLD"

    # ── 4. Predict Probabilities ───────────────────────────────────────────────
    try:
        # predict_proba คืน [[prob_class0, prob_class1]]
        # Class=1 คือ "มีสัญญาณ" ดึงเฉพาะ column index 1
        prob_buy  = float(buy_model.predict_proba(features)[0][1])
        prob_sell = float(sell_model.predict_proba(features)[0][1])
    except Exception as e:
        print(f"❌ [XGBoost] predict_proba ล้มเหลว: {e}")
        return "HOLD"

    print(f"🌲 [XGBoost] prob_buy={prob_buy:.4f}  prob_sell={prob_sell:.4f}  "
          f"session_progress={session_progress:.2f}  trades_done={trades_done_in_session}")

    # ── 5. Conflict Gap Check ─────────────────────────────────────────────────
    if abs(prob_buy - prob_sell) < CONFLICT_GAP:
        print(f"🟡 [XGBoost] HOLD — Conflict Gap ไม่เพียงพอ "
              f"(|{prob_buy:.4f} - {prob_sell:.4f}| < {CONFLICT_GAP})")
        return "HOLD"

    # ── 6. Dynamic Threshold ──────────────────────────────────────────────────
    current_threshold = _compute_dynamic_threshold(session_progress, trades_done_in_session)
    print(f"🎯 [XGBoost] Dynamic Threshold = {current_threshold:.4f}")

    # ── 7. Signal Engine ──────────────────────────────────────────────────────
    if prob_buy >= current_threshold and prob_buy > prob_sell:
        print(f"🟢 [XGBoost] BUY  (prob_buy={prob_buy:.4f} >= {current_threshold:.4f})")
        return "BUY"

    if prob_sell >= current_threshold and prob_sell > prob_buy:
        print(f"🔴 [XGBoost] SELL (prob_sell={prob_sell:.4f} >= {current_threshold:.4f})")
        return "SELL"

    print(f"🟡 [XGBoost] HOLD — prob ไม่ผ่าน threshold ({current_threshold:.4f})")
    return "HOLD"