# core/signal_gate.py
import logging
from config.settings import (
    SIGNAL_THRESHOLD, DRY_RUN,
    STATE_EMPTY, STATE_HOLDING,
    GATE_SRVR_MIN, GATE_SPREAD_NORM_MAX, GATE_REGIME_REQUIRED,
)
from core.state_manager import get_current_state
from core.feature_engine import FeaturesRow

logger = logging.getLogger("trading")

def evaluate_signal_gate(inference_result: dict, features_row: FeaturesRow) -> dict:
    """
    Phase 4: ตรวจสอบ State + Gate Conditions → ตัดสินใจ BUY / SELL / No Signal
    """
    score = inference_result["ranker_score"]
    session = features_row["session"]
    F_SRVR = features_row["F_SRVR"]
    F_Regime = features_row["F_Regime"]
    
    # 🔁 ใช้ F_XAU_Noise_Ratio แทน F_XAU_Spread_Norm ตามการอัปเดต Phase 2
    F_Noise_Ratio = features_row.get("F_XAU_Noise_Ratio", features_row.get("F_XAU_Spread_Norm", 0.0))
    
    current_state = get_current_state()
    
    # ─── Shared Gates ─────────────────────────────────────────────────────────
    base_gates = {
        "market_open": session != "Closed",
        "noise_gate": F_Noise_Ratio < GATE_SPREAD_NORM_MAX, # เดิมคือ spread_gate
    }
    
    signal_type = None
    passed = False
    reject_reason = None
    gates_detail = {}
    
    # ─── BUY Logic (state = EMPTY) ────────────────────────────────────────────
    if current_state == STATE_EMPTY:
        buy_gates = {
            **base_gates,
            "score_gate"   : score >= SIGNAL_THRESHOLD,
            "srvr_gate"    : F_SRVR >= GATE_SRVR_MIN,
            "regime_gate"  : F_Regime == GATE_REGIME_REQUIRED,
        }
        gates_detail = buy_gates
        passed = all(buy_gates.values())
        signal_type   = "BUY" if passed else "HOLD"  # 🔁 เปลี่ยน None → HOLD
        reject_reason = None if passed else next(k for k, v in buy_gates.items() if not v)

    # ─── SELL Logic (state = HOLDING) ─────────────────────────────────────────
    elif current_state == STATE_HOLDING:
        sell_gates = {
            **base_gates,
            "score_below_threshold" : score < SIGNAL_THRESHOLD,
        }
        gates_detail = sell_gates
        passed = all(sell_gates.values())
        signal_type   = "SELL" if passed else "HOLD" # 🔁 เปลี่ยน None → HOLD
        reject_reason = None if passed else next(k for k, v in sell_gates.items() if not v)
            
    else:
        raise RuntimeError(f"[Gate] Unknown state: {current_state}")
        
    # ─── Signal ID Generation ─────────────────────────────────────────────────
    # Format: sig_YYYYMMDD_HHMMSS
    bt = features_row["bar_time"][:19].replace("-", "").replace(":", "").replace("T", "_")
    signal_id = f"sig_{bt}"
    
    return {
        "signal_id": signal_id,
        "bar_time": features_row["bar_time"],
        "session": session,
        "signal_type": signal_type,
        "ranker_score": score,
        "state_before": current_state,
        "gates_detail": gates_detail,
        "passed": passed,
        "reject_reason": reject_reason,
        "dry_run": DRY_RUN,
        "features_snap": inference_result["features_snap"],
        "hsh_ask": features_row["hsh_close_ask"],
        "hsh_bid": features_row["hsh_close_bid"],
        "xau_close": features_row["xau_close"],
        "atr_48": features_row["F_ATR_48"],
    }