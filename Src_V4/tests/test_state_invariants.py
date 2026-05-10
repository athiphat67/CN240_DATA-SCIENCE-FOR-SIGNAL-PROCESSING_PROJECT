# tests/test_state_invariants.py
"""
State machine invariant checks.
These verify that no combination of operations can leave
the system in an inconsistent state.
"""
import pytest
from core.dynamic_tp_manager import DynamicTPManager


class TestStateInvariants:
    """Logical invariants that must hold true at all times."""

    def test_empty_state_tp_inactive(self):
        """INVARIANT: state=EMPTY → tp_manager must be inactive."""
        tp = DynamicTPManager()
        tp.reset()
        assert not tp.is_active

    def test_tp_reset_clears_all(self):
        """INVARIANT: tp_manager.reset() clears ALL state."""
        tp = DynamicTPManager()
        tp.activate(40100.0, 0.15, 40050.0, sl_price=40000.0)
        tp.reset()
        assert not tp.is_active
        assert tp.entry_ask is None
        assert tp.entry_score is None
        assert tp.sl_price is None
        assert tp.highest_bid == 0.0
        assert not tp._breakeven_locked

    def test_activate_requires_valid_entry(self):
        """INVARIANT: activate() sets is_active=True."""
        tp = DynamicTPManager()
        tp.activate(40100.0, 0.15, 40050.0)
        assert tp.is_active
        assert tp.entry_ask == 40100.0

    def test_inactive_tp_returns_none(self):
        """INVARIANT: inactive TP → update() returns NONE."""
        tp = DynamicTPManager()
        trigger, price, trail = tp.update(40050.0, 100.0, 0.15)
        assert trigger == "NONE"
        assert price is None

    def test_sl_priority_over_trail(self):
        """INVARIANT: SL_HIT fires before updating highest_bid."""
        tp = DynamicTPManager(atr_multiplier=1.5)
        tp.activate(40100.0, 0.15, 40050.0, sl_price=40000.0)
        trigger, _, _ = tp.update(39900.0, 100.0, 0.15)
        assert trigger == "SL_HIT"
        # highest_bid should NOT be updated to 39900
        assert tp.highest_bid == 40050.0

    def test_breakeven_fires_once(self):
        """INVARIANT: BREAKEVEN_LOCK fires exactly once."""
        tp = DynamicTPManager(atr_multiplier=1.5, breakeven_atr_mult=1.0)
        tp.activate(40100.0, 0.15, 40050.0)
        # First time reaching BE trigger
        t1, _, _ = tp.update(40200.0, 100.0, 0.15)
        assert t1 == "BREAKEVEN_LOCK"
        # Second time
        t2, _, _ = tp.update(40250.0, 100.0, 0.15)
        assert t2 != "BREAKEVEN_LOCK"


class TestSchemaContract:
    """Verify supabase_schema.sql contains required elements."""

    def _read_schema(self):
        with open("db/supabase_schema.sql", "r") as f:
            return f.read()

    def test_active_trades_table_exists(self):
        sql = self._read_schema()
        assert "v3_active_trades" in sql

    def test_signals_has_execution_status(self):
        sql = self._read_schema()
        assert "execution_status" in sql

    def test_signals_has_confirmed_fields(self):
        sql = self._read_schema()
        for col in ["confirmed_at", "confirmed_price", "confirm_note"]:
            assert col in sql, f"Missing column: {col}"

    def test_signals_has_rationale_fields(self):
        sql = self._read_schema()
        for col in ["rationale_text", "top_shap_features"]:
            assert col in sql, f"Missing column: {col}"

    def test_active_trades_has_fk_fields(self):
        sql = self._read_schema()
        for col in ["entry_signal_id", "exit_signal_id", "entry_ask",
                     "exit_bid", "pnl_thb", "status"]:
            assert col in sql, f"Missing column: {col}"

    def test_unique_open_trade_constraint(self):
        sql = self._read_schema()
        assert "uniq_one_open_trade" in sql

    def test_notify_pgrst(self):
        sql = self._read_schema()
        assert "NOTIFY pgrst" in sql

    def test_exit_signal_index(self):
        sql = self._read_schema()
        assert "idx_active_trades_exit_signal" in sql
