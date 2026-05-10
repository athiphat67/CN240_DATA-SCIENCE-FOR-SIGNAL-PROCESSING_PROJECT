# rationale/generator.py
import math
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from .templates import bullish_drivers, holding_drivers, bearish_drivers, cautious_drivers


def _sigmoid_strength(ranker_score: float) -> float:
    """
    แปลง raw LambdaMART score (unbounded) → เปอร์เซ็นต์ใน (0, 100)
    ใช้ sigmoid เพื่อไม่ให้แสดง "Model Strength: 196%" หรือ "-214%"

    ค่า reference:
        score =  0.0  → 50.0%  (neutral)
        score =  1.0  → 73.1%  (confident bullish)
        score = -1.0  → 26.9%  (confident bearish)
        score =  3.0  → 95.3%  (very high confidence)
    """
    return round(1 / (1 + math.exp(-ranker_score)) * 100, 2)


def build_trade_payload(
    signal_type: str,
    ranker_score: float,
    shap_values: List[float],
    feature_names: List[str],
    current_ask: Optional[float],
    current_bid: Optional[float],
    state_before: Optional[str] = None,   # "HOLDING" | "EMPTY" | None
) -> Dict[str, Any]:
    """
    สร้าง Rationale Text เพื่อเลียนแบบ LLM ให้ XGBoost Ranker (v3.1)
    Scenario B: Fallback to HOLD on logical trading errors, crash on coding errors.

    Args:
        signal_type   : "BUY" | "SELL" | "HOLD"
        ranker_score  : raw LambdaMART score — ไม่ bounded, ใช้ sigmoid ก่อนแสดงผล
        shap_values   : SHAP vector (same length as feature_names)
        feature_names : FEATURE_COLS จาก lambdamart_v11_meta.json
        current_ask   : hsh_close_ask (ใช้สำหรับ BUY)
        current_bid   : hsh_close_bid (ใช้สำหรับ SELL)
        state_before  : position state ก่อน signal นี้ — ใช้สำหรับ HOLD spread_action
    """

    # ─── Step 1: Normalize strength (sigmoid, bounded 0–100) ──────────────────
    strength = _sigmoid_strength(ranker_score)

    # ─── Step 2: Scenario B Fallback 1 — Invalid Signal String ───────────────
    valid_signals = ["BUY", "SELL", "HOLD"]
    if signal_type not in valid_signals:
        signal_type = "HOLD"  # Force safe state

    # ─── Step 3: Route by signal type + SHAP direction ────────────────────────
    if signal_type == "BUY":
        action = "BUY"
        exec_price = current_ask
        spread_action = "Aggressively crossing the spread at Ask price"
        # positive SHAP = features pushing score UP = bullish evidence
        drivers = sorted(
            [(f, v) for f, v in zip(feature_names, shap_values) if v > 0],
            key=lambda x: x[1],
            reverse=True,
        )
        template_dict = bullish_drivers

    elif signal_type == "SELL":
        action = "SELL"
        exec_price = current_bid
        spread_action = "Hitting the Bid price to exit position"
        # negative SHAP = features pulling score DOWN = bearish evidence
        drivers = sorted(
            [(f, v) for f, v in zip(feature_names, shap_values) if v < 0],
            key=lambda x: x[1],
        )
        template_dict = bearish_drivers

    else:  # "HOLD" (genuine or forced fallback)
        action = "HOLD"
        exec_price = None

        # ── Fix #1 (Critical): SHAP direction depends on ranker_score sign ──
        #
        # score < 0 → bearish signal blocked by gate OR no bullish conviction
        #   → narrative should explain WHY we didn't enter
        #   → use NEGATIVE SHAP features (the blockers) + cautious_drivers tone
        #
        # score > 0 → bullish signal passed score gate but blocked elsewhere
        #   (e.g. session gate, spread gate)
        #   → narrative should explain what remains valid while we wait
        #   → use POSITIVE SHAP features + holding_drivers tone (original logic)

        if ranker_score < 0:
            drivers = sorted(
                [(f, v) for f, v in zip(feature_names, shap_values) if v < 0],
                key=lambda x: x[1],  # most negative first
            )
            template_dict = cautious_drivers
        else:
            drivers = sorted(
                [(f, v) for f, v in zip(feature_names, shap_values) if v > 0],
                key=lambda x: x[1],
                reverse=True,
            )
            template_dict = holding_drivers

        # ── Fix #2 (Moderate): spread_action contextualised by state_before ──
        #
        # "Maintaining current position" is wrong when state_before = EMPTY.
        # Pass state_before from the orchestrator to get the right wording.
        _state = (state_before or "").upper()
        if _state == "HOLDING":  # ✅ I-3: was "LONG" which never matched
            spread_action = "Maintaining current long position as structural edge remains intact"
        elif _state == "EMPTY":
            spread_action = "No entry taken — model confidence is below the required threshold"
        else:
            # state_before not provided or unexpected value → generic safe fallback
            spread_action = "Maintaining current position as structural edge remains intact"

    # ─── Step 4: Scenario B Fallback 2 — Empty Drivers (All SHAP = 0) ────────
    if len(drivers) == 0:
        reason_1 = "no clear quantitative driver identified"
        reason_2 = "flat SHAP distribution across all features"
        if action != "HOLD":
            action = "HOLD"
            exec_price = None
            spread_action = "defaulting to hold due to lack of clear SHAP conviction"
    else:
        top_1_feat = drivers[0][0]
        top_2_feat = drivers[1][0] if len(drivers) > 1 else None

        reason_1 = template_dict.get(top_1_feat, f"key quantitative data from {top_1_feat}")
        reason_2 = (
            template_dict.get(top_2_feat, f"supporting data from {top_2_feat}")
            if top_2_feat
            else "no secondary confirmation available"
        )

    # ─── Step 5: Assemble rationale text ──────────────────────────────────────
    rationale_text = (
        f"[{action}] Model Strength: {strength}%. "
        f"Primary catalyst: {reason_1}. "
        f"Secondary confirmation: {reason_2}. "
    )

    if action in ["BUY", "SELL"] and exec_price is not None:
        rationale_text += f"Action: {spread_action} ({exec_price:.2f} THB)."
    else:
        rationale_text += f"Action: {spread_action}."

    # ─── Step 6: top_shap_features (reflect actual drivers used) ──────────────
    top_shap_features: Dict[str, float] = {}
    if len(drivers) > 0:
        top_shap_features[drivers[0][0]] = round(drivers[0][1], 4)
    if len(drivers) > 1:
        top_shap_features[drivers[1][0]] = round(drivers[1][1], 4)

    # ─── Step 7: Build payload ─────────────────────────────────────────────────
    payload = {
        "timestamp":          datetime.now(timezone.utc).isoformat(),
        "signal_type":        action,        # final (may differ from input if fallback triggered)
        "execution_price":    exec_price,    # Ask for BUY, Bid for SELL, None for HOLD
        "strength_pct":       strength,      # sigmoid-normalised, always in (0, 100)
        "rationale_text":     rationale_text,
        "top_shap_features":  top_shap_features,  # reflects direction-correct SHAP
    }

    return payload