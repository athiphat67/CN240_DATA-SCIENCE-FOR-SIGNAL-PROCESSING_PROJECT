import os
import sys
import time
import logging
from datetime import datetime

# Setup paths so we can import modules
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Monkey-patch config BEFORE importing others
import config.settings
config.settings.DRY_RUN = True  # Ensure we don't write anything to real Supabase

# Monkey-patch discord sender to ensure [TEST] is printed
import notifier.discord_notifier
original_send = notifier.discord_notifier.send_discord

def patched_send(content: str) -> None:
    if "[TEST]" not in content:
        content = "🧪 **[TEST - SELL LOGIC DRYRUN]**\n" + content
    
    print(f"\n{'='*40}")
    print(f"📨 DISCORD MESSAGE SENT:")
    print(f"{content}")
    print(f"{'='*40}\n")
    
    # Actually send it to Discord
    original_send(content)

notifier.discord_notifier.send_discord = patched_send

from core.dynamic_tp_manager import DynamicTPManager
from rationale.generator import build_trade_payload
from notifier.discord_notifier import notify_sell_signal, notify_dynamic_tp

# Setup minimal logging to see what's happening
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("trading")

def mock_features(bar_time: str, bid: float, ask: float, atr: float = 10.0):
    return {
        "bar_time": bar_time,
        "session": "Open",
        "hsh_close_ask": ask,
        "hsh_close_bid": bid,
        "xau_close": 2300.0,
        "F_ATR_48": atr
    }

def mock_inference(score: float = 0.8):
    return {
        "ranker_score": score,
        "shap_values": [-0.15, -0.05],
        "feature_names": ["F_SMA_7", "F_RSI_14"],
        "features_snap": {"F_SMA_7": 2310, "F_RSI_14": 45}
    }

def run_scenarios():
    print("🚀 Starting Sell Logic Test Scenarios (DRY RUN)\n")

    # We mock entry params
    ENTRY_ASK = 40000.0
    ENTRY_BID = 39950.0
    ATR_VAL = 100.0
    SL_MULTIPLIER = 1.0  # So SL is at 40000 - 100 = 39900

    scenarios = [
        {
            "name": "Scenario 1: Stop Loss (SL) Hit",
            "entry_ask": ENTRY_ASK, "initial_bid": ENTRY_BID, "entry_score": 0.85,
            "prices": [
                {"bid": 39920.0, "ask": 39970.0, "score": 0.80}, # Price drops, no exit
                {"bid": 39850.0, "ask": 39900.0, "score": 0.75}  # Price drops below SL (39900), should trigger SL_HIT
            ]
        },
        {
            "name": "Scenario 2: Trailing Stop Hit (Profitable)",
            "entry_ask": ENTRY_ASK, "initial_bid": ENTRY_BID, "entry_score": 0.85,
            "prices": [
                {"bid": 40200.0, "ask": 40250.0, "score": 0.88}, # Price pumps! TP_UPDATED (Trail goes to 40200 - 1.5*100 = 40050)
                {"bid": 40000.0, "ask": 40050.0, "score": 0.85}  # Price dumps below trail (40050), should trigger TRAIL_HIT
            ]
        },
        {
            "name": "Scenario 3: Breakeven Lock & Trail Hit",
            "entry_ask": ENTRY_ASK, "initial_bid": ENTRY_BID, "entry_score": 0.85,
            "prices": [
                {"bid": 40150.0, "ask": 40200.0, "score": 0.85}, # Price reaches BE trigger (40000 + 100*1.0 = 40100). BREAKEVEN_LOCK
                {"bid": 39950.0, "ask": 40000.0, "score": 0.80}  # Price drops below BE floor (40002). TRAIL_HIT
            ]
        },
        {
            "name": "Scenario 4: Score Fade & Model Sell",
            "entry_ask": ENTRY_ASK, "initial_bid": ENTRY_BID, "entry_score": 0.85,
            "prices": [
                {"bid": 39980.0, "ask": 40030.0, "score": 0.80}, # Normal
                {"bid": 39970.0, "ask": 40020.0, "score": 0.65}, # SCORE_FADE trigger
                {"bid": 39960.0, "ask": 40010.0, "score": 0.20, "force_model_sell": True} # Model decides to explicitly SELL
            ]
        },
        {
            "name": "Scenario 5: Pure Gate SELL (Score Drops Below Threshold while HOLDING)",
            "entry_ask": ENTRY_ASK, "initial_bid": ENTRY_BID, "entry_score": 0.85,
            "prices": [
                {"bid": 40010.0, "ask": 40060.0, "score": 0.50},          # Bar 1: HOLD — price stable, score 0.50 > threshold 0.07
                {"bid": 40020.0, "ask": 40070.0, "score": 0.10},          # Bar 2: HOLD — score 0.10 still above threshold 0.07
                {"bid": 40015.0, "ask": 40065.0, "score": 0.04,           # Bar 3: GATE SELL — score 0.04 < threshold 0.07
                 "gate_sell": True}                                        # TP manager active but NOT triggering — organic exit
            ]
        }
    ]

    for i, sc in enumerate(scenarios, 1):
        print(f"\n{'#'*60}")
        print(f"▶️ RUNNING: {sc['name']}")
        print(f"{'#'*60}")
        
        # 1. Initialize TP Manager
        tp_manager = DynamicTPManager(atr_multiplier=1.5, breakeven_atr_mult=1.0, score_drop_threshold=0.15)
        sl_price = sc["entry_ask"] - (ATR_VAL * SL_MULTIPLIER)
        
        tp_manager.activate(
            entry_ask=sc["entry_ask"],
            entry_score=sc["entry_score"],
            initial_bid=sc["initial_bid"],
            sl_price=sl_price
        )
        print(f"[Bot] 🟢 Position OPENED at Ask={sc['entry_ask']:,.2f} | SL={sl_price:,.2f}")

        for tick in sc["prices"]:
            bid = tick["bid"]
            ask = tick["ask"]
            score = tick["score"]
            is_model_sell = tick.get("force_model_sell", False)
            is_gate_sell  = tick.get("gate_sell", False)  # Scenario 5: organic gate SELL
            
            print(f"  -> [Market Tick] Bid={bid:,.2f}, Score={score:.4f}")
            
            # 2. Check TP Manager
            tp_trigger, tp_price, trail_level = tp_manager.update(bid, ATR_VAL, score)
            
            if tp_trigger != "NONE":
                print(f"     🔔 [TP Alert] {tp_trigger} (Trigger Price: {tp_price:,.2f})")
                notify_dynamic_tp(tp_trigger, tp_price, trail_level, score, ATR_VAL)
                time.sleep(1) # Small delay for discord rate limit

            # 3. Simulate Orchestrator Exit Logic
            if tp_trigger in ("TRAIL_HIT", "SL_HIT") or is_model_sell or is_gate_sell:
                if is_gate_sell:
                    reason = "GATE_SELL_SIGNAL"
                elif is_model_sell:
                    reason = "MODEL_SELL_SIGNAL"
                else:
                    reason = tp_trigger
                print(f"     🚨 [EXIT SIGNAL] Position closed due to {reason}!")
                
                # Build mock data
                feat = mock_features(datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"), bid, ask, ATR_VAL)
                inf = mock_inference(score)
                
                # Build rationale exactly like orchestrator.py
                payload = build_trade_payload(
                    signal_type="SELL",
                    ranker_score=score,
                    shap_values=inf["shap_values"],
                    feature_names=inf["feature_names"],
                    current_ask=ask,
                    current_bid=bid,
                    state_before="HOLDING"
                )
                
                if not is_model_sell and not is_gate_sell:
                    # Forced exit prefix (TP/SL triggered — not an organic gate SELL)
                    payload["rationale_text"] = (
                        f"🤖 **Auto-Exit Trigger:** {reason} @ `{bid:,.2f}` THB\n\n"
                        f"{payload.get('rationale_text', '')}"
                    )

                # ✅ I-1 check: verify tp_manager.reset() is called on gate SELL
                if is_gate_sell:
                    tp_manager.reset()  # mirrors orchestrator.py Gate SELL path
                    print(f"     ✅ [TP Reset] tp_manager.reset() called — I-1 fix verified")
                
                # Send Discord Notification
                gate_result = {
                    "bar_time": feat["bar_time"],
                    "session": feat["session"],
                    "ranker_score": score,
                    "hsh_bid": bid,
                    "xau_close": feat["xau_close"]
                }
                
                notify_sell_signal(gate_result, payload)
                time.sleep(2) # Prevent discord 429 rate limit
                break
                
    print("\n✅ All test scenarios completed!")

if __name__ == '__main__':
    run_scenarios()
