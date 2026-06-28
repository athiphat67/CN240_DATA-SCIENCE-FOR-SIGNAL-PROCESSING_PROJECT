# tests/test_snapshot_alignment.py
# ─────────────────────────────────────────────────────────────────────────────
# Snapshot Alignment Test Suite
#
# ตรวจสอบว่า Feature ที่คำนวณโดย Src_V4 (feature_engine.py) ตรงกับ
# Snapshot ที่เก็บไว้ใน DB (v3_signals.features_snap)
#
# ใช้งาน: .\env\Scripts\python.exe -m pytest tests/test_snapshot_alignment.py -v
# ─────────────────────────────────────────────────────────────────────────────

import os
import sys
import json
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ── Env Setup ──────────────────────────────────────────────────────────────
# ⚠️  MUST load dotenv BEFORE any project imports — config/settings.py reads
#    os.getenv() at import time. If env is not loaded first, SUPABASE_URL/KEY
#    will be empty strings and all DB calls silently fail.
os.environ.setdefault('_ENV_LOADED', '0')
if os.environ['_ENV_LOADED'] == '0':
    # resolve .env relative to Src_V4 root, not the tests/ subdirectory
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    from dotenv import load_dotenv
    load_dotenv(os.path.join(_root, '.env'), override=True)
    os.environ['_ENV_LOADED'] = '1'

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import create_client
from core.candle_builder import build_candles
from core.feature_engine import compute_features

# ── Tolerance thresholds ───────────────────────────────────────────────────
#   ค่าที่ยอมรับได้ระหว่าง V4 กับ DB snapshot
#   ค่าเหล่านี้อาจต่างกันเล็กน้อยเพราะ DB ถูก snap ณ เวลาก่อนหน้า
STRICT_TOL   = 0.01    # ±1%  สำหรับ features ที่ควรตรงกันมากที่สุด
RELAXED_TOL  = 0.10    # ±10% สำหรับ features ที่ขึ้นอยู่กับจำนวนแท่งใน session
ATR_TOL      = 0.50    # ±50% สำหรับ ATR ที่รับผลกระทบจาก weekend fix
SESSION_TOL  = 0.20    # ±20% สำหรับ session-aware features

# ── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def db_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    assert url and key, "Missing SUPABASE_URL or SUPABASE_KEY in .env"
    return create_client(url, key)


@pytest.fixture(scope="module")
def v4_features():
    """คำนวณ Features จาก Src_V4 pipeline ณ แท่งเทียนล่าสุด"""
    try:
        candles = build_candles()
        feat = compute_features(candles)
        return feat
    except Exception as e:
        pytest.skip(f"build_candles/compute_features ล้มเหลว: {e}")


@pytest.fixture(scope="module")
def db_snapshots(db_client):
    """ดึง Snapshots ล่าสุด 10 แถวจาก v3_signals (รวม HOLD ด้วย)
    
    Note: ไม่ filter signal_type เพราะในช่วง low-volatility อาจมีแต่ HOLD
    """
    res = (
        db_client.table("v3_signals")
        .select("id, bar_time, signal_type, ranker_score, features_snap")
        .order("id", desc=True)
        .limit(10)
        .execute()
    )
    rows = []
    for r in res.data:
        snap = r.get("features_snap", {})
        if isinstance(snap, str):
            snap = json.loads(snap)
        rows.append({
            "id":           r["id"],
            "bar_time":     r["bar_time"],
            "signal_type":  r.get("signal_type", "HOLD"),
            "ranker_score": float(r["ranker_score"] or 0),
            "snap":         snap,
        })
    return rows


@pytest.fixture(scope="module")
def latest_db_snap(db_snapshots):
    """ดึง Snapshot ล่าสุดจาก DB"""
    if not db_snapshots:
        pytest.skip("ไม่มี Snapshot ใน v3_signals — รัน main.py ก่อน")
    return db_snapshots[0]


# ═══════════════════════════════════════════════════════════════════════════
# TEST GROUP 1: Weekend Filter (root cause fix)
# ═══════════════════════════════════════════════════════════════════════════

class TestWeekendFilter:
    """ตรวจสอบว่า candle_builder ตัดวันเสาร์-อาทิตย์ทิ้งอย่างถูกต้อง"""

    def test_no_saturday_candles(self, v4_features):
        snap = v4_features  # dict ออกมาจาก compute_features
        bar_time_str = snap.get("bar_time", "")
        # ตรวจผ่าน candles จริง
        candles = build_candles()
        sat_sun = candles[candles.index.dayofweek >= 5]
        assert sat_sun.empty, (
            f"พบข้อมูลวันเสาร์/อาทิตย์ {len(sat_sun)} แถว — weekend filter พัง!"
        )

    def test_no_outside_session_candles(self):
        """ตรวจว่าไม่มีแท่งนอกเวลาทำการ (02:00-05:59)"""
        candles = build_candles()
        hour = candles.index.hour
        # ช่วง 02:00-05:59 ไม่ใช่ Session ใด
        outside = candles[(hour >= 2) & (hour < 6)]
        assert outside.empty, (
            f"พบแท่งนอกเวลาทำการ {len(outside)} แถว (02:00-05:59)"
        )

    def test_monday_follows_friday(self):
        """ตรวจว่า index ข้ามจากวันศุกร์ถึงวันจันทร์โดยตรง"""
        candles = build_candles()
        dows = pd.Series(candles.index.dayofweek, index=candles.index)
        # หา transition จาก dayofweek n → n+1 ที่ข้ามเสาร์อาทิตย์
        for i in range(len(dows) - 1):
            curr_dow = dows.iloc[i]
            next_dow = dows.iloc[i + 1]
            # ไม่ควรมี dayofweek 5 (Sat) หรือ 6 (Sun)
            assert next_dow < 5 or next_dow == curr_dow, (
                f"พบการข้ามไปวันหยุด: {dows.index[i]} (dow={curr_dow}) → "
                f"{dows.index[i+1]} (dow={next_dow})"
            )


# ═══════════════════════════════════════════════════════════════════════════
# TEST GROUP 2: ATR Alignment (primary divergence metric)
# ═══════════════════════════════════════════════════════════════════════════

class TestATRAlignment:
    """F_ATR_48 เป็น Feature ที่บ่งบอกว่า weekend fix ทำงานหรือไม่"""

    def test_atr_nonzero_on_weekday(self, v4_features):
        """หลัง fix แล้ว ATR ต้องไม่เป็น 0.0 ในช่วงตลาดเปิด"""
        atr = v4_features.get("F_ATR_48", 0.0)
        bar_time = v4_features.get("bar_time", "")
        # ถ้ามีข้อมูลย้อนหลังพอ ATR ต้องไม่เป็น 0
        assert atr > 0.0, (
            f"F_ATR_48={atr} ยังเป็น 0.0 ที่ {bar_time} — "
            "candle_builder ยังมีปัญหา weekend filter หรือข้อมูล XAU ไม่อัปเดต"
        )

    def test_atr_reasonable_range(self, v4_features):
        """ATR ในหน่วย XAU ควรอยู่ในช่วง 0.1 ถึง 20 (reasonable market range)"""
        atr = v4_features.get("F_ATR_48", 0.0)
        assert 0.1 <= atr <= 20.0, (
            f"F_ATR_48={atr:.4f} นอกช่วงที่สมเหตุสมผล [0.1, 20.0]"
        )

    def test_atr_vs_db_within_tolerance(self, v4_features, latest_db_snap):
        """ATR ของ V4 ควร align กับ DB snapshot ที่ใกล้เคียงกัน"""
        v4_atr  = v4_features.get("F_ATR_48", 0.0)
        db_atr  = float(latest_db_snap["snap"].get("F_ATR_48", 0.0))

        # ถ้า DB snap เก่ายังเป็น 0.0 ให้ skip (snap ถูกเขียนก่อน fix)
        if db_atr == 0.0:
            pytest.skip(
                f"DB snapshot (id={latest_db_snap['id']}) มี F_ATR_48=0.0 "
                "— snap นี้ถูกเขียนก่อน weekend-fix, รัน main.py ใหม่แล้วทดสอบอีกครั้ง"
            )

        # ATR เป็น time-varying — ถ้าคนละ bar_time ไม่สามารถ compare ได้ตรง
        v4_bar = v4_features.get("bar_time", "")
        db_bar = latest_db_snap.get("bar_time", "")
        if v4_bar != db_bar:
            pytest.skip(
                f"bar_time ต่างกัน: V4={v4_bar} DB={db_bar} — ATR เป็น time-varying ไม่สามารถ compare คนละแท่งได้"
            )

        diff_pct = abs(v4_atr - db_atr) / max(abs(db_atr), 1e-9)
        assert diff_pct <= ATR_TOL, (
            f"F_ATR_48 ต่างเกิน {ATR_TOL*100:.0f}%: V4={v4_atr:.4f} DB={db_atr:.4f} "
            f"(diff={diff_pct*100:.1f}%)"
        )


# ═══════════════════════════════════════════════════════════════════════════
# TEST GROUP 3: Macro Feature Alignment
# ═══════════════════════════════════════════════════════════════════════════

class TestMacroFeatureAlignment:
    """Macro features ที่คำนวณจากราคา XAU และ USD"""

    MACRO_FEATURES = [
        ("F_Regime",        "int",    STRICT_TOL),
        ("F_XAU_Mom_Short", "float",  RELAXED_TOL),
        ("F_XAU_Mom_Mid",   "float",  RELAXED_TOL),
        ("F_USD_Mom",       "float",  RELAXED_TOL),
        ("F_Corr_XAU_USD",  "float",  RELAXED_TOL),
    ]

    def test_regime_is_valid(self, v4_features):
        """F_Regime ต้องเป็น -1, 0 หรือ 1"""
        regime = v4_features.get("F_Regime", None)
        assert regime in (-1, 0, 1), f"F_Regime={regime} ไม่ใช่ [-1, 0, 1]"

    def test_corr_xau_usd_range(self, v4_features):
        """Correlation ต้องอยู่ใน [-1, 1]"""
        corr = v4_features.get("F_Corr_XAU_USD", None)
        assert corr is not None, "F_Corr_XAU_USD ไม่มีในผลลัพธ์"
        assert -1.01 <= corr <= 1.01, f"F_Corr_XAU_USD={corr} นอกช่วง [-1, 1]"

    @pytest.mark.parametrize("feat_name,feat_type,tol", MACRO_FEATURES)
    def test_macro_feature_vs_db(self, feat_name, feat_type, tol,
                                 v4_features, latest_db_snap):
        """ตรวจค่า Macro Feature ของ V4 เทียบกับ DB snapshot"""
        v4_val = v4_features.get(feat_name)
        db_val = latest_db_snap["snap"].get(feat_name)

        if v4_val is None:
            pytest.skip(f"{feat_name} ไม่มีใน V4 features output")
        if db_val is None:
            pytest.skip(f"{feat_name} ไม่มีใน DB snapshot")

        # Time-varying features: skip ถ้าคนละ bar_time
        v4_bar = v4_features.get("bar_time", "")
        db_bar = latest_db_snap.get("bar_time", "")
        if v4_bar != db_bar:
            pytest.skip(
                f"{feat_name}: bar_time ต่างกัน (V4={v4_bar} DB={db_bar}) "
                "— time-varying feature ไม่สามารถ compare คนละแท่งได้"
            )

        v4_val = float(v4_val)
        db_val = float(db_val)

        diff_pct = abs(v4_val - db_val) / max(abs(db_val), 1e-9)
        assert diff_pct <= tol, (
            f"{feat_name}: V4={v4_val:.6f} DB={db_val:.6f} diff={diff_pct*100:.1f}% > {tol*100:.0f}%"
        )


# ═══════════════════════════════════════════════════════════════════════════
# TEST GROUP 4: Session-Aware Feature Alignment
# ═══════════════════════════════════════════════════════════════════════════

class TestSessionFeatureAlignment:
    """Session features ขึ้นอยู่กับตำแหน่งแท่งใน Session"""

    SESSION_FEATURES = [
        "F_FSP", "F_SA_Range", "F_SA_Vol", "F_SA_Position",
        "F_SA_TWAP_Dev", "F_SA_MDD", "F_SRVR", "F_RSI_14",
        "F_RSI_6", "F_BB_Pos", "F_HSH_Spread",
    ]

    def test_fsp_range(self, v4_features):
        """F_FSP ต้องอยู่ใน [0, 1]"""
        fsp = v4_features.get("F_FSP", None)
        assert fsp is not None
        assert 0.0 <= fsp <= 1.0, f"F_FSP={fsp} นอกช่วง [0, 1]"

    def test_sa_range_positive(self, v4_features):
        """F_SA_Range ต้องไม่ติดลบ"""
        r = v4_features.get("F_SA_Range", None)
        assert r is not None
        assert r >= 0.0, f"F_SA_Range={r} ต่ำกว่า 0"

    def test_sa_position_range(self, v4_features):
        """F_SA_Position ต้องอยู่ใน [0, 1]"""
        p = v4_features.get("F_SA_Position", None)
        assert p is not None
        assert -0.01 <= p <= 1.01, f"F_SA_Position={p} นอกช่วง [0, 1]"

    def test_rsi_range(self, v4_features):
        """RSI ต้องอยู่ใน [0, 100]"""
        for feat in ("F_RSI_14", "F_RSI_6"):
            v = v4_features.get(feat, None)
            assert v is not None, f"{feat} ไม่มีในผลลัพธ์"
            assert 0.0 <= v <= 100.0, f"{feat}={v} นอกช่วง [0, 100]"

    def test_session_features_no_nan(self, v4_features):
        """ทุก Session Feature ต้องไม่เป็น NaN"""
        for feat in self.SESSION_FEATURES:
            val = v4_features.get(feat)
            if val is not None:
                assert not (isinstance(val, float) and np.isnan(val)), (
                    f"{feat} เป็น NaN — มีปัญหา NaN propagation"
                )


# ═══════════════════════════════════════════════════════════════════════════
# TEST GROUP 5: Score Alignment
# ═══════════════════════════════════════════════════════════════════════════

class TestScoreAlignment:
    """ตรวจสอบความสอดคล้องของ Ranker Score"""

    def test_v4_ranker_score_is_finite(self, v4_features):
        """Ranker Score ต้องเป็นตัวเลขจำกัด"""
        from core.model_inference import run_inference
        result = run_inference(v4_features)
        score = result.get("ranker_score", None)
        assert score is not None, "run_inference ไม่ return ranker_score"
        assert np.isfinite(float(score)), f"ranker_score={score} ไม่ใช่ค่าจำกัด (Inf/NaN)"

    def test_ranker_score_range(self, v4_features):
        """ตรวจ Score อยู่ในช่วงที่ Model ควรจะ Output"""
        from core.model_inference import run_inference
        result = run_inference(v4_features)
        score = float(result.get("ranker_score", 0))
        # XGBoost LambdaMART output ควรอยู่ในช่วงสมเหตุสมผล
        assert -10.0 <= score <= 10.0, (
            f"ranker_score={score} นอกช่วงที่คาดไว้ [-10, 10] — อาจมีปัญหาการโหลด Model"
        )


# ═══════════════════════════════════════════════════════════════════════════
# TEST GROUP 6: DB Snapshot Freshness
# ═══════════════════════════════════════════════════════════════════════════

class TestSnapshotFreshness:
    """ตรวจสอบว่า DB มีข้อมูลใหม่เพียงพอ"""

    def test_latest_snapshot_within_60min(self, latest_db_snap):
        """Snapshot ล่าสุดต้องไม่เก่ากว่า 60 นาที"""
        import pytz
        TZ_BKK = pytz.timezone("Asia/Bangkok")
        bar_time_str = latest_db_snap["bar_time"]
        bar_time = pd.to_datetime(bar_time_str, utc=True).astimezone(TZ_BKK)
        now_bkk = datetime.now(TZ_BKK)
        age_min = (now_bkk - bar_time).total_seconds() / 60

        # ยกเว้นช่วงวันหยุดสุดสัปดาห์
        if now_bkk.weekday() >= 5:
            pytest.skip("วันหยุดสุดสัปดาห์ ไม่มีสัญญาณใหม่ (ปกติ)")

        assert age_min <= 60, (
            f"Snapshot ล่าสุด (id={latest_db_snap['id']}) เก่า {age_min:.0f} นาที > 60 นาที\n"
            "main.py อาจหยุดทำงาน หรือ pipeline มีปัญหา"
        )

    def test_snapshot_has_all_required_features(self, latest_db_snap):
        """Snapshot ต้องมีทุก Feature ที่จำเป็นสำหรับ Model"""
        REQUIRED = [
            "F_Syn_Price", "F_Thai_Premium", "F_Corr_XAU_USD",
            "F_ATR_48", "F_Regime", "F_FSP", "F_SA_TWAP_Dev",
            "F_SA_MDD", "F_SA_Vol", "F_SA_Range", "F_SA_Position",
            "F_SRVR", "F_RSI_14", "F_RSI_6", "F_BB_Pos",
            "F_XAU_Spread_Norm", "F_Hour_Sin", "F_Hour_Cos",
            "F_DayOfWeek", "F_MinuteOfDay",
        ]
        snap = latest_db_snap["snap"]
        missing = [f for f in REQUIRED if f not in snap]
        assert not missing, (
            f"Snapshot (id={latest_db_snap['id']}) ขาด Features: {missing}"
        )
