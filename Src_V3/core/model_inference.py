"""
core/model_inference.py — Phase 3: Model Inference

โหลด LambdaMART v11 (XGBoost Ranker, native .json format) ครั้งเดียวตอน startup
→ validate features → score แถวปัจจุบัน → ส่ง inference_result ไป Phase 4

Design decisions:
  • XGBoost native .json (ไม่ใช้ pickle) — portable ข้าม Python version,
    ไม่มีความเสี่ยง arbitrary code execution
  • FEATURE_COLS โหลดจาก metadata เป็น single source of truth
    (Phase 3 ไม่ hardcode feature list เด็ดขาด)
  • Model โหลดระดับ module → import ครั้งเดียว, ไม่โหลดซ้ำทุก bar
  • Startup validation ตรวจ feature count + model n_trees
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

from config.settings import MODEL_META_PATH, MODEL_PATH, SIGNAL_THRESHOLD

logger = logging.getLogger("trading")

# ─── Module-level singleton (loaded once at startup) ──────────────────────────

def _load_model_and_meta() -> tuple[xgb.XGBRanker, dict, list[str]]:
    """
    โหลด model + metadata ตอน import.
    Raises RuntimeError ถ้าไฟล์ไม่มีหรือ feature count ไม่ตรง
    """
    # ── 1. Load metadata ────────────────────────────────────────────────────
    meta_path = Path(MODEL_META_PATH)
    if not meta_path.exists():
        raise RuntimeError(
            f"[model_inference] Model metadata ไม่พบ: {MODEL_META_PATH}\n"
            "  ตรวจสอบว่า models/lambdamart_v11_meta.json อยู่ในโปรเจกต์"
        )

    with meta_path.open() as f:
        meta: dict = json.load(f)

    feature_cols: list[str] = meta["feature_cols"]

    if len(feature_cols) == 0:
        raise RuntimeError(
            "[model_inference] feature_cols ใน metadata ว่าง — metadata เสียหาย"
        )

    # ── 2. Load model ───────────────────────────────────────────────────────
    model_path = Path(MODEL_PATH)
    if not model_path.exists():
        raise RuntimeError(
            f"[model_inference] Model file ไม่พบ: {MODEL_PATH}\n"
            "  ใส่ไฟล์ lambdamart_v11.json ไว้ใน models/ แล้วลองใหม่"
        )

    model = xgb.XGBRanker()
    model.load_model(str(model_path))

    # ── 3. Startup validation ───────────────────────────────────────────────
    # ตรวจ n_trees ตรงกับ metadata
    expected_trees = meta.get("n_trees")
    if expected_trees is not None:
        actual_trees = model.get_booster().num_boosted_rounds()
        if actual_trees != expected_trees:
            raise RuntimeError(
                f"[model_inference] Model tree count mismatch: "
                f"metadata says {expected_trees}, model has {actual_trees}\n"
                "  ตรวจสอบว่าโหลด model file ถูกเวอร์ชั่น"
            )

    logger.info(
        f"[model_inference] ✅ Loaded {meta['model_name']} "
        f"({expected_trees} trees, {len(feature_cols)} features, "
        f"trained {meta.get('trained_at', 'unknown')})"
    )
    return model, meta, feature_cols


try:
    _model, _meta, FEATURE_COLS = _load_model_and_meta()
    MODEL_VERSION = _meta["model_name"]
except Exception as _load_exc:
    # Re-raise with context — startup in main.py will catch and sys.exit(1)
    raise RuntimeError(f"[model_inference] Startup load failed: {_load_exc}") from _load_exc


# ─── Public Inference Function ────────────────────────────────────────────────

def run_inference(features_row: dict) -> dict:
    """
    Score แถวล่าสุดด้วย LambdaMART v11.

    Parameters
    ----------
    features_row : FeaturesRow (TypedDict หรือ plain dict)
        ผลลัพธ์จาก compute_features() — ต้องมีครบทุก key ใน FEATURE_COLS

    Returns
    -------
    dict with keys:
        bar_time      : str   — ISO8601 timestamp ของ bar นี้
        ranker_score  : float — raw score จาก XGBRanker.predict()
        model_version : str   — "lambdamart_v11"
        above_threshold: bool — ranker_score >= SIGNAL_THRESHOLD
        features_snap : dict  — snapshot ของ features_row ทั้งหมด

    Raises
    ------
    ValueError — missing features หรือ NaN ใน feature vector
    """
    # ── 1. Check missing features ────────────────────────────────────────────
    missing = [c for c in FEATURE_COLS if c not in features_row]
    if missing:
        raise ValueError(
            f"[model_inference] Missing features (ต้องมีใน FeaturesRow): {missing}"
        )

    # ── 2. Build DataFrame ───────────────────────────────────────────────────
    X = pd.DataFrame([features_row])[FEATURE_COLS]

    # ── 3. Check NaN in feature vector ───────────────────────────────────────
    nan_cols = X.columns[X.isna().any()].tolist()
    if nan_cols:
        raise ValueError(
            f"[model_inference] NaN ใน feature vector: {nan_cols} "
            f"— bar {features_row.get('bar_time')}"
        )

    # ── 4. Check dtype — XGBoost ต้องการ numeric ────────────────────────────
    non_numeric = [
        col for col in X.columns
        if not pd.api.types.is_numeric_dtype(X[col])
    ]
    if non_numeric:
        raise ValueError(
            f"[model_inference] Non-numeric columns: {non_numeric}"
        )

    # ── 5. Run inference ─────────────────────────────────────────────────────
    # XGBRanker.predict() ต้องการ qid (group) ตอน train แต่ตอน predict ไม่ต้องการ
    score = float(_model.predict(X)[0])

    above_threshold = score >= SIGNAL_THRESHOLD

    logger.info(
        f"[model_inference] bar={features_row.get('bar_time')} | "
        f"score={score:.4f} | "
        f"threshold={SIGNAL_THRESHOLD} | "
        f"{'✅ ABOVE' if above_threshold else '❌ below'}"
    )

    return {
        "bar_time"       : features_row.get("bar_time", ""),
        "ranker_score"   : score,
        "model_version"  : MODEL_VERSION,
        "above_threshold": above_threshold,
        "features_snap"  : dict(features_row),
    }