#!/usr/bin/env python3
"""
Standalone test runner for DynamicTPManager
Run: python tests/test_dynamic_tp_manager.py
"""
import sys
import os
import logging

# Allow running from project root or tests/ directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.dynamic_tp_manager import DynamicTPManager

# Silence TPManager logs during testing for cleaner console output
logging.getLogger("trading").setLevel(logging.CRITICAL)

# ─── Test Harness ──────────────────────────────────────────────────────────────
tests_passed = 0
tests_failed = 0

def run_test(test_func):
    global tests_passed, tests_failed
    try:
        test_func()
        print(f"✅ PASS: {test_func.__name__}")
        tests_passed += 1
    except AssertionError as e:
        print(f"❌ FAIL: {test_func.__name__}\n   → {e}")
        tests_failed += 1
    except Exception as e:
        print(f"💥 ERROR: {test_func.__name__}\n   → {type(e).__name__}: {e}")
        tests_failed += 1

# ─── Test Cases ───────────────────────────────────────────────────────────────
def test_initial_state():
    tp = DynamicTPManager()
    assert not tp.is_active, "Should start inactive"
    assert tp.entry_ask is None
    assert tp.highest_bid == 0.0
    assert not tp._breakeven_locked

def test_activation_sets_state():
    tp = DynamicTPManager()
    tp.activate(entry_ask=30000.0, entry_score=0.75, initial_bid=30000.0)
    assert tp.is_active
    assert tp.entry_ask == 30000.0
    assert tp.entry_score == 0.75
    assert tp.highest_bid == 30000.0

def test_reset_clears_state():
    tp = DynamicTPManager()
    tp.activate(30000.0, 0.75, 30000.0)
    tp.reset()
    assert not tp.is_active
    assert tp.entry_ask is None
    assert tp.highest_bid == 0.0
    assert not tp._breakeven_locked

def test_tp_updated_on_price_increase():
    """Price moves up enough that raw_trail stays above be_floor"""
    tp = DynamicTPManager(atr_multiplier=1.5, breakeven_atr_mult=1.0, score_drop_threshold=0.15)
    tp.activate(30000.0, 0.75, 30000.0)
    # Lock breakeven first to bypass BREAKEVEN_LOCK event on subsequent updates
    tp.update(current_bid=30100.0, atr_48=100.0, current_score=0.75)
    
    # be_floor = 30000 + max(2.0, 100) = 30100
    trigger, price, trail = tp.update(current_bid=30300.0, atr_48=100.0, current_score=0.74)
    assert trigger == "TP_UPDATED", f"Expected TP_UPDATED, got {trigger}"
    assert price is not None
    # raw_trail = 30300 - 150 = 30150 | active = max(30150, 30100) = 30150
    assert trail == 30150.0, f"Trail should be 30150, got {trail}"

def test_breakeven_lock_fires_once():
    tp = DynamicTPManager(atr_multiplier=1.5, breakeven_atr_mult=1.0, score_drop_threshold=0.15)
    tp.activate(30000.0, 0.75, 30000.0)
    # Profit reaches exactly 1.0x ATR -> 30100
    trigger, price, trail = tp.update(current_bid=30100.0, atr_48=100.0, current_score=0.75)
    assert trigger == "BREAKEVEN_LOCK", f"Expected BREAKEVEN_LOCK, got {trigger}"
    assert tp._breakeven_locked is True
    assert trail == 30100.0

    # Subsequent update should NOT fire BREAKEVEN_LOCK again
    trigger2, _, trail2 = tp.update(current_bid=30150.0, atr_48=100.0, current_score=0.74)
    assert trigger2 != "BREAKEVEN_LOCK", f"Lock fired twice! Got {trigger2}"
    assert tp._breakeven_locked is True

def test_trail_hit_when_price_drops():
    tp = DynamicTPManager(atr_multiplier=1.5, breakeven_atr_mult=1.0, score_drop_threshold=0.15)
    tp.activate(30000.0, 0.75, 30000.0)
    # Move price up to lock breakeven
    tp.update(current_bid=30200.0, atr_48=100.0, current_score=0.74)
    # highest_bid = 30200, raw_trail = 30050, be_floor = 30100 → active_trail = 30100
    trigger, price, trail = tp.update(current_bid=30090.0, atr_48=100.0, current_score=0.70)
    assert trigger == "TRAIL_HIT", f"Expected TRAIL_HIT, got {trigger}"
    assert trail == 30100.0
    assert price == 30100.0

def test_score_fade_on_confidence_drop():
    """Score drops significantly while price stays safely above trail"""
    tp = DynamicTPManager(atr_multiplier=1.5, breakeven_atr_mult=1.0, score_drop_threshold=0.15)
    tp.activate(30000.0, 0.80, 30000.0)
    # Lock breakeven
    tp.update(current_bid=30200.0, atr_48=100.0, current_score=0.80)
    
    # Trigger score fade
    trigger, _, trail = tp.update(current_bid=30200.0, atr_48=100.0, current_score=0.64)
    assert trigger == "SCORE_FADE", f"Expected SCORE_FADE, got {trigger}"
    assert trail == 30100.0  # Trail unchanged, score triggered warning

def test_inactive_returns_none():
    tp = DynamicTPManager()
    trigger, price, trail = tp.update(30000.0, 100.0, 0.75)
    assert trigger == "NONE", f"Expected NONE, got {trigger}"
    assert price is None
    assert trail == 0.0

def test_invalid_atr_returns_none():
    tp = DynamicTPManager()
    tp.activate(30000.0, 0.75, 30000.0)
    t1, p1, _ = tp.update(30000.0, atr_48=None, current_score=0.75)
    assert t1 == "NONE"
    t2, p2, _ = tp.update(30000.0, atr_48=-10.0, current_score=0.75)
    assert t2 == "NONE"

def test_trigger_priority_trail_vs_score():
    """Confirms TRAIL_HIT > SCORE_FADE in evaluation order"""
    tp = DynamicTPManager(atr_multiplier=1.5, breakeven_atr_mult=1.0, score_drop_threshold=0.15)
    tp.activate(30000.0, 0.80, 30000.0)
    tp.update(current_bid=30200.0, atr_48=100.0, current_score=0.80)
    # Price drops below trail (30050), score also fades significantly (0.80 -> 0.60)
    trigger, _, _ = tp.update(current_bid=30000.0, atr_48=100.0, current_score=0.60)
    assert trigger == "TRAIL_HIT", f"Expected TRAIL_HIT (higher priority), got {trigger}"

def test_sl_hit():
    """Test that SL is hit when price drops below sl_price"""
    tp = DynamicTPManager(atr_multiplier=1.5, breakeven_atr_mult=1.0, score_drop_threshold=0.15)
    tp.activate(30000.0, 0.75, 30000.0, sl_price=29900.0)
    trigger, price, trail = tp.update(current_bid=29800.0, atr_48=100.0, current_score=0.75)
    assert trigger == "SL_HIT", f"Expected SL_HIT, got {trigger}"
    assert price == 29900.0

# ─── SL Recovery Scenarios ───────────────────────────────────────────────────

def test_sl_recovery_score_bounced():
    """Bar after SL: score bounces back above entry_score - 0.10 → cancel pending SELL."""
    tp = DynamicTPManager(recovery_score_margin=0.10)
    tp.activate(30000.0, entry_score=0.50, initial_bid=30000.0, sl_price=29900.0)
    tp.update(current_bid=29850.0, atr_48=100.0, current_score=0.30)  # SL_HIT bar

    # Next bar: score recovers to 0.43 (>= 0.50 - 0.10 = 0.40)
    assert tp.should_cancel_pending_sell(0.43) is True,  "score=0.43 should cancel"
    assert tp.should_cancel_pending_sell(0.40) is True,  "score=0.40 (boundary) should cancel"
    assert tp.should_cancel_pending_sell(0.39) is False, "score=0.39 should NOT cancel"

def test_sl_recovery_score_still_low():
    """Bar after SL: score stays below threshold → do not cancel, keep pending."""
    tp = DynamicTPManager(recovery_score_margin=0.10)
    tp.activate(30000.0, entry_score=0.50, initial_bid=30000.0, sl_price=29900.0)
    tp.update(current_bid=29850.0, atr_48=100.0, current_score=0.20)  # SL_HIT bar

    # Next bar: score is 0.25 — still well below 0.40 threshold
    assert tp.should_cancel_pending_sell(0.25) is False, "score=0.25 should NOT cancel"

# ─── Main Runner ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 55)
    print("🧪 Running DynamicTPManager Tests")
    print("=" * 55)

    test_list = [
        test_initial_state,
        test_activation_sets_state,
        test_reset_clears_state,
        test_tp_updated_on_price_increase,
        test_breakeven_lock_fires_once,
        test_trail_hit_when_price_drops,
        test_score_fade_on_confidence_drop,
        test_inactive_returns_none,
        test_invalid_atr_returns_none,
        test_trigger_priority_trail_vs_score,
        test_sl_hit,
        # SL recovery
        test_sl_recovery_score_bounced,
        test_sl_recovery_score_still_low,
    ]

    for test in test_list:
        run_test(test)

    print("\n" + "=" * 55)
    print(f"📊 RESULTS: {tests_passed} Passed | {tests_failed} Failed")
    print("=" * 55)
    sys.exit(0 if tests_failed == 0 else 1)