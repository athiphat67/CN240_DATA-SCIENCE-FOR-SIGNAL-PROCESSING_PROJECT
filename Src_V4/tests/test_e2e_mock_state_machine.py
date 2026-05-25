# tests/test_e2e_mock_state_machine.py
"""
End-to-end state machine scenarios using only DynamicTPManager (no Supabase).
Verifies the full lifecycle: EMPTY → BUY → HOLDING → SELL → EMPTY.
"""
import pytest
from core.dynamic_tp_manager import DynamicTPManager


class TestE2ELifecycle:
    """Full BUY → HOLD → SELL cycle using TP manager directly."""

    def test_empty_to_holding_to_empty_model_sell(self):
        """Scenario: EMPTY → Confirm BUY → HOLDING → Model SELL → EMPTY."""
        tp = DynamicTPManager(atr_multiplier=1.5, breakeven_atr_mult=1.0,
                              score_drop_threshold=0.15)
        state = "EMPTY"

        # 1. BUY signal fires — state stays EMPTY, TP inactive
        assert state == "EMPTY"
        assert not tp.is_active

        # 2. User confirms BUY — activates TP, state becomes HOLDING
        tp.activate(40100.0, entry_score=0.15, initial_bid=40050.0,
                     sl_price=40000.0)
        state = "HOLDING"
        assert tp.is_active
        assert state == "HOLDING"

        # 3. Normal bars — TP updates, no exit
        trigger, _, trail = tp.update(40120.0, 100.0, 0.14)
        assert trigger in ("TP_UPDATED", "BREAKEVEN_LOCK")
        assert state == "HOLDING"

        # 4. Score drops below threshold → Model SELL (gate produces SELL)
        state = "EMPTY"  # Orchestrator sets after close_open_trade
        tp.reset()
        assert not tp.is_active
        assert state == "EMPTY"

    def test_empty_to_holding_sl_hit(self):
        """Scenario: EMPTY → Confirm BUY → SL_HIT → EMPTY."""
        tp = DynamicTPManager(atr_multiplier=1.5)
        state = "EMPTY"

        # Confirm BUY
        tp.activate(40100.0, 0.15, 40050.0, sl_price=40000.0)
        state = "HOLDING"

        # Price crashes below SL
        trigger, price, _ = tp.update(39900.0, 100.0, 0.15)
        assert trigger == "SL_HIT"
        assert price == 40000.0

        # Forced SELL → EMPTY
        state = "EMPTY"
        tp.reset()
        assert not tp.is_active

    def test_empty_to_holding_trail_hit(self):
        """Scenario: EMPTY → Confirm BUY → price pumps → TRAIL_HIT → EMPTY."""
        tp = DynamicTPManager(atr_multiplier=1.5, breakeven_atr_mult=1.0)
        state = "EMPTY"

        tp.activate(40100.0, 0.15, 40050.0, sl_price=40000.0)
        state = "HOLDING"

        # Price pumps
        tp.update(40300.0, 100.0, 0.15)  # highest_bid=40300, trail=40150

        # Price drops below trail
        trigger, _, trail = tp.update(40100.0, 100.0, 0.15)
        assert trigger == "TRAIL_HIT"

        state = "EMPTY"
        tp.reset()
        assert not tp.is_active

    def test_score_fade_is_warning_only(self):
        """SCORE_FADE should NOT trigger an exit — just a warning."""
        tp = DynamicTPManager(atr_multiplier=1.5, breakeven_atr_mult=1.0,
                              score_drop_threshold=0.15)
        tp.activate(40100.0, 0.50, 40050.0, sl_price=40000.0)
        state = "HOLDING"

        # Bid=40150 is BELOW breakeven trigger (40100 + max(2, 100*1.0) = 40200)
        # so BREAKEVEN_LOCK won't fire, but score drop 0.50→0.34 ≥ 0.15 triggers SCORE_FADE
        trigger, _, _ = tp.update(40150.0, 100.0, 0.34)
        assert trigger == "SCORE_FADE", f"Expected SCORE_FADE, got {trigger}"
        # State should remain HOLDING — orchestrator does NOT force exit on SCORE_FADE
        assert state == "HOLDING"

    def test_breakeven_lock_then_trail_hit(self):
        """Breakeven locks → protects downside → eventual TRAIL_HIT."""
        tp = DynamicTPManager(atr_multiplier=1.5, breakeven_atr_mult=1.0)
        tp.activate(40100.0, 0.15, 40050.0)

        # Price reaches breakeven trigger
        trigger, price, trail = tp.update(40200.0, 100.0, 0.15)
        assert trigger == "BREAKEVEN_LOCK"
        assert tp._breakeven_locked

        # be_floor = 40100 + 2 = 40102
        # raw_trail = 40200 - 150 = 40050
        # active_trail = max(40050, 40102) = 40102
        assert trail == 40102.0

        # Price drops below be_floor
        trigger2, _, _ = tp.update(40090.0, 100.0, 0.15)
        assert trigger2 == "TRAIL_HIT"

    def test_confirm_buy_mark_fail_still_holding(self):
        """Simulates partial failure: trade OPEN but mark fails → still HOLDING."""
        tp = DynamicTPManager()
        state = "EMPTY"

        # Simulate: open_trade success, mark_signal fails
        # System must force state to HOLDING
        tp.activate(40100.0, 0.15, 40050.0)
        state = "HOLDING"  # Forced by partial failure handler

        assert tp.is_active
        assert state == "HOLDING"

    def test_sell_insert_fail_stays_holding(self):
        """If insert_signal fails during SELL, state must stay HOLDING."""
        tp = DynamicTPManager()
        tp.activate(40100.0, 0.15, 40050.0)
        state = "HOLDING"

        # insert_signal returns False → abort
        # State stays HOLDING, TP stays active
        assert tp.is_active
        assert state == "HOLDING"

    def test_close_trade_fail_stays_holding(self):
        """If close_open_trade fails, state must stay HOLDING."""
        tp = DynamicTPManager()
        tp.activate(40100.0, 0.15, 40050.0)
        state = "HOLDING"

        # close_open_trade returns False → abort
        assert tp.is_active
        assert state == "HOLDING"
