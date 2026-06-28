# core/signal_recorder.py
import json
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Any, Dict, Optional
import pytz

TZ = pytz.timezone("Asia/Bangkok")

def _serialize_obj(obj: Any) -> Any:
    """แปลง Numpy/Pandas types ให้เป็น Native Python สำหรับ JSONB"""
    if isinstance(obj, (np.integer,)): return int(obj)
    if isinstance(obj, (np.floating,)): return float(obj)
    if isinstance(obj, np.ndarray): return obj.tolist()
    if isinstance(obj, pd.Timestamp): return obj.isoformat()
    if isinstance(obj, datetime): return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

def build_signal_record(gate_result: dict, rationale_payload: Optional[dict] = None) -> dict:
    """
    Phase 5: สร้าง record สำหรับ INSERT ลง signals table
    รองรับ BUY / SELL / HOLD + แนบ Rationale จาก SHAP Generator
    """
    # 1. แปลง features_snap ให้ปลอดภัยต่อ JSONB
    raw_snap = gate_result.get("features_snap", {})
    safe_snap = json.loads(json.dumps(raw_snap, default=_serialize_obj))
    
    # 2. ดึงข้อมูล Rationale อย่างปลอดภัย (Fallback ถ้า payload เป็น None)
    rationale_text = None
    top_shap_features = {}
    if rationale_payload:
        rationale_text = rationale_payload.get("rationale_text")
        raw_shap = rationale_payload.get("top_shap_features", {})
        top_shap_features = json.loads(json.dumps(raw_shap, default=_serialize_obj))
        
    # 3. ประกอบ Record ตรง Schema signals table
    return {
        "id"              : gate_result["signal_id"],
        "bar_time"        : gate_result["bar_time"],
        "session"         : gate_result["session"],
        "signal_type"     : gate_result["signal_type"],   # "BUY" | "SELL" | "HOLD"
        "ranker_score"    : float(gate_result["ranker_score"]),
        "state_before"    : gate_result["state_before"],
        "hsh_ask_price"   : float(gate_result["hsh_ask"]) if gate_result.get("hsh_ask") else None,
        "hsh_bid_price"   : float(gate_result["hsh_bid"]) if gate_result.get("hsh_bid") else None,
        "xau_price"       : float(gate_result["xau_close"]) if gate_result.get("xau_close") else None,
        "atr_at_signal"   : float(gate_result["atr_48"]) if gate_result.get("atr_48") else None,
        "passed"          : bool(gate_result["passed"]),
        "reject_reason"   : gate_result.get("reject_reason"),
        "dry_run"         : bool(gate_result["dry_run"]),
        "features_snap"   : safe_snap,
        "rationale_text"  : rationale_text,
        "top_shap_features": top_shap_features,
        "created_at"      : datetime.now(TZ).isoformat(),
    }