# rationale/generator.py
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from .templates import bullish_drivers, holding_drivers, bearish_drivers

def build_trade_payload(
    signal_type: str, 
    ranker_score: float, 
    shap_values: List[float], 
    feature_names: List[str], 
    current_ask: Optional[float],
    current_bid: Optional[float]
) -> Dict[str, Any]:
    """
    สร้าง Rationale Text เพื่อเลียนแบบ LLM ให้ XGBoost Ranker (v3)
    Scenario B: Fallback to HOLD on logical trading errors, crash on coding errors.
    """
    strength = round(ranker_score * 100, 2)

    # ─── Scenario B Fallback 1: Invalid Signal String ─────────────────────────
    valid_signals = ["BUY", "SELL", "HOLD"]
    if signal_type not in valid_signals:
        signal_type = "HOLD" # Force safe state

    # ─── กำหนด Action, Price และ SHAP Drivers ตาม Signal Type ────────────────
    if signal_type == "BUY":
        action = "BUY"
        exec_price = current_ask
        spread_action = "Aggressively crossing the spread at Ask price"
        drivers = sorted([(f, v) for f, v in zip(feature_names, shap_values) if v > 0], key=lambda x: x[1], reverse=True)
        template_dict = bullish_drivers

    elif signal_type == "SELL":
        action = "SELL"
        exec_price = current_bid
        spread_action = "Hitting the Bid price to exit position"
        drivers = sorted([(f, v) for f, v in zip(feature_names, shap_values) if v < 0], key=lambda x: x[1])
        template_dict = bearish_drivers

    else: # "HOLD" หรือ forced fallback
        action = "HOLD"
        exec_price = None
        spread_action = "Maintaining current position as structural edge remains intact"
        drivers = sorted([(f, v) for f, v in zip(feature_names, shap_values) if v > 0], key=lambda x: x[1], reverse=True)
        template_dict = holding_drivers

    # ─── Scenario B Fallback 2: Empty Drivers (All SHAP = 0) ──────────────────
    if len(drivers) == 0:
        reason_1 = "no clear quantitative driver identified"
        reason_2 = "flat SHAP distribution across all features"
        # Override action to HOLD if it was trying to BUY/SELL but had no proof
        if action != "HOLD":
            action = "HOLD"
            exec_price = None
            spread_action = "defaulting to hold due to lack of clear SHAP conviction"
    else:
        top_1_feat = drivers[0][0]
        top_2_feat = drivers[1][0] if len(drivers) > 1 else None
        
        reason_1 = template_dict.get(top_1_feat, f"key quantitative data from {top_1_feat}")
        reason_2 = template_dict.get(top_2_feat, f"supporting data from {top_2_feat}") if top_2_feat else "no secondary confirmation available"

    # ─── สร้าง Text Rationale สไตล์ดุดัน ─────────────────────────────────────
    rationale_text = (
        f"[{action}] Model Strength: {strength}%. "
        f"Primary catalyst: {reason_1}. "
        f"Secondary confirmation: {reason_2}. "
    )
    
    if action in ["BUY", "SELL"] and exec_price is not None:
        rationale_text += f"Action: {spread_action} ({exec_price:.2f} THB)."
    else:
        rationale_text += f"Action: {spread_action}."

    # ─── สร้าง dict สำหรับ top_shap_features แบบปลอดภัย ────────────────────────
    top_shap_features = {}
    if len(drivers) > 0:
        top_shap_features[drivers[0][0]] = round(drivers[0][1], 4)
    if len(drivers) > 1:
        top_shap_features[drivers[1][0]] = round(drivers[1][1], 4)

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "signal_type": action,
        "execution_price": exec_price,
        "strength_pct": strength,
        "rationale_text": rationale_text,
        "top_shap_features": top_shap_features
    }
    
    return payload