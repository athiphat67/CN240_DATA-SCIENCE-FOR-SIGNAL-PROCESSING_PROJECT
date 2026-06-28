# core/model_inference.py
import json
import logging
import xgboost as xgb
import pandas as pd
from config.settings import MODEL_PATH, MODEL_META_PATH
from core.feature_engine import FeaturesRow

logger = logging.getLogger("system")

_model: xgb.XGBRanker | None = None
_meta: dict | None = None
_expected_cols: list[str] = []

def _load_model():
    """โหลดโมเดลครั้งเดียวตอน Startup + ดึง Schema จริงจาก Booster"""
    global _model, _meta, _expected_cols
    if _model is not None:
        return
        
    logger.info(f"[P3] Loading model from {MODEL_PATH}...")
    _model = xgb.XGBRanker()
    _model.load_model(MODEL_PATH)
    
    with open(MODEL_META_PATH, "r", encoding="utf-8") as f:
        _meta = json.load(f)
        
    # 🔑 ดึงชื่อและลำดับ Feature ที่โมเดลรู้จักจริง ๆ จาก Booster
    _expected_cols = _model.get_booster().feature_names
    if not _expected_cols:
        raise ValueError("[P3] Model has no feature_names. Check training process.")
        
    logger.info(f"[P3] ✅ Model loaded: {_meta.get('model_name')} | Expected Features: {len(_expected_cols)}")

def run_inference(features_row: FeaturesRow) -> dict:
    _load_model()
    
    missing = [c for c in _expected_cols if c not in features_row]
    if missing:
        raise ValueError(f"[P3] Missing features for inference: {missing}")
        
    X = pd.DataFrame([features_row])[_expected_cols]
    nan_cols = X.columns[X.isna().any()].tolist()
    if nan_cols:
        raise ValueError(f"[P3] NaN in critical features: {nan_cols}")
        
    try:
        # 🔑 Predict Score
        score = float(_model.predict(X)[0])
        
        # 🔑 Compute SHAP Values (pred_contribs=True คืนค่า shape: 1, n_features+1)
        booster = _model.get_booster()
        dmat = xgb.DMatrix(X, feature_names=_expected_cols)
        contrib = booster.predict(dmat, pred_contribs=True)
        shap_values = contrib[0, :-1].tolist()  # ตัด bias column ท้ายสุดออก
        
    except Exception as e:
        raise RuntimeError(f"[P3] XGBoost prediction/SHAP failed: {e}") from e
        
    return {
        "bar_time"      : features_row["bar_time"],
        "ranker_score"  : score,
        "model_version" : _meta.get("model_name", "unknown"),
        "features_snap" : dict(features_row),
        "shap_values"   : shap_values,          # ← เพิ่ม
        "feature_names" : _expected_cols,       # ← เพิ่ม
    }