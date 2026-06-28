import os
import time
import logging

# 1. Enforce DRY_RUN dynamically so it doesn't touch the real DB
os.environ["DRY_RUN"] = "true"

import config.settings
config.settings.DRY_RUN = True

from core.candle_builder import build_candles
from core.feature_engine import compute_features
from core.model_inference import run_inference
from core.signal_gate import evaluate_signal_gate
from core.state_manager import set_state, get_current_state, STATE_EMPTY, STATE_HOLDING
from rationale.generator import build_trade_payload
from notifier.discord_notifier import notify_buy_signal, notify_sell_signal, notify_heartbeat
from logger_setup import setup_logging

setup_logging()
logger = logging.getLogger("system")

def run_test():
    print("="*60)
    print("PIPELINE FLOW TEST (OPTION A)")
    print("="*60)
    print("\n1. Fetching Live Market Data & Running Real Model...")
    
    try:
        candles_df = build_candles()
        features_row = compute_features(candles_df)
    except Exception as e:
        print(f"[ERROR] Failed to fetch data: {e}")
        return
    
    # Bypass market closed logic just for the test
    if features_row["session"] == "Closed":
        print("[WARNING] Market is currently closed. Overriding session to 'Morning' for testing purposes.")
        features_row["session"] = "Morning"

    # Ensure auxiliary gates pass by mocking some features, so only the model score controls the signal
    features_row["F_SRVR"] = max(features_row.get("F_SRVR", 0), config.settings.GATE_SRVR_MIN + 0.1)
    features_row["F_Regime"] = config.settings.GATE_REGIME_REQUIRED
    features_row["F_XAU_Noise_Ratio"] = min(features_row.get("F_XAU_Noise_Ratio", 0), config.settings.GATE_SPREAD_NORM_MAX - 0.1)

    inference_result = run_inference(features_row)
    real_score = inference_result["ranker_score"]
    
    print(f"\n[REAL RESULT] Live Model Score: {real_score:.4f}")
    
    time.sleep(2)

    # ---------------------------------------------------------
    print("\n" + "-"*40)
    print("TEST 1: FORCING A 'BUY' SIGNAL")
    print("-"*40)
    
    set_state(STATE_EMPTY)  # Ensure we start empty
    print(f"Current State: {get_current_state()}")
    
    buy_inference = inference_result.copy()
    buy_inference["ranker_score"] = 3.5  # Very high score to force BUY
    
    gate_result_buy = evaluate_signal_gate(buy_inference, features_row)
    if gate_result_buy["passed"] and gate_result_buy["signal_type"] == "BUY":
        rationale_payload = build_trade_payload(
            signal_type="BUY",
            ranker_score=buy_inference["ranker_score"],
            shap_values=buy_inference.get("shap_values", []),
            feature_names=buy_inference.get("feature_names", []),
            current_ask=gate_result_buy["hsh_ask"],
            current_bid=gate_result_buy["hsh_bid"],
            state_before=gate_result_buy["state_before"]
        )
        set_state(STATE_HOLDING) # Move to holding
        notify_buy_signal(gate_result_buy, rationale_payload)
        print("[OK] BUY SIGNAL processed and sent to Discord!")
    else:
        print(f"[FAIL] BUY SIGNAL failed. Reason: {gate_result_buy.get('reject_reason')}")
    
    time.sleep(3)

    # ---------------------------------------------------------
    print("\n" + "-"*40)
    print("TEST 2: FORCING A 'HOLD' SIGNAL")
    print("-"*40)
    
    print(f"Current State: {get_current_state()}")
    # State is now HOLDING. A score > threshold should result in HOLD (rejecting sell)
    hold_inference = inference_result.copy()
    hold_inference["ranker_score"] = 1.0  # Still > SIGNAL_THRESHOLD (0.07)
    
    gate_result_hold = evaluate_signal_gate(hold_inference, features_row)
    if not gate_result_hold["passed"] and gate_result_hold["signal_type"] == "HOLD":
        print("[OK] HOLD SIGNAL evaluated correctly.")
        print("   (Normally, HOLD doesn't send a trade notification. Sending Heartbeat instead...)")
        notify_heartbeat(get_current_state(), features_row["bar_time"], hold_inference["ranker_score"])
    else:
        print("[FAIL] HOLD SIGNAL failed to evaluate correctly.")

    time.sleep(3)

    # ---------------------------------------------------------
    print("\n" + "-"*40)
    print("TEST 3: FORCING A 'SELL' SIGNAL")
    print("-"*40)
    
    print(f"Current State: {get_current_state()}")
    # State is still HOLDING. A score < threshold should result in SELL
    sell_inference = inference_result.copy()
    sell_inference["ranker_score"] = -2.5  # Very low score to force SELL
    
    gate_result_sell = evaluate_signal_gate(sell_inference, features_row)
    if gate_result_sell["passed"] and gate_result_sell["signal_type"] == "SELL":
        rationale_payload = build_trade_payload(
            signal_type="SELL",
            ranker_score=sell_inference["ranker_score"],
            shap_values=sell_inference.get("shap_values", []),
            feature_names=sell_inference.get("feature_names", []),
            current_ask=gate_result_sell["hsh_ask"],
            current_bid=gate_result_sell["hsh_bid"],
            state_before=gate_result_sell["state_before"]
        )
        set_state(STATE_EMPTY) # Reset to empty
        notify_sell_signal(gate_result_sell, rationale_payload)
        print("[OK] SELL SIGNAL processed and sent to Discord!")
    else:
        print(f"[FAIL] SELL SIGNAL failed. Reason: {gate_result_sell.get('reject_reason')}")

    print("\n" + "="*60)
    print("TEST COMPLETE")
    print("Please check your Discord channel to verify the 3 notifications.")
    print("="*60)

if __name__ == "__main__":
    run_test()
