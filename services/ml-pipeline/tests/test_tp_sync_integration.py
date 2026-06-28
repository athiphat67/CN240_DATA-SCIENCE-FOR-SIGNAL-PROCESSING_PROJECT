# tests/test_tp_sync_integration.py
"""
Tests for sync_tp_state_from_db — the bridge between
Rich's Manual Confirm (DB active_trade) and Jom's TP manager (in-memory).
"""
import pytest
from unittest.mock import patch, MagicMock
from tests.conftest import MOCK_OPEN_TRADE, MOCK_FEATURES_ROW


class TestSyncResetWhenEmpty:
    """State EMPTY → tp_manager must be inactive."""

    @patch("scheduler.orchestrator.get_open_trade", return_value=None)
    @patch("scheduler.orchestrator.get_current_state", return_value="EMPTY")
    def test_reset_if_active_but_empty(self, mock_state, mock_trade):
        from scheduler.orchestrator import sync_tp_state_from_db, tp_manager
        tp_manager.activate(40100.0, 0.15, 40050.0)
        assert tp_manager.is_active

        sync_tp_state_from_db()

        assert not tp_manager.is_active, "TP must reset when DB state is EMPTY"

    @patch("scheduler.orchestrator.get_open_trade", return_value=None)
    @patch("scheduler.orchestrator.get_current_state", return_value="EMPTY")
    def test_noop_if_already_inactive(self, mock_state, mock_trade):
        from scheduler.orchestrator import sync_tp_state_from_db, tp_manager
        tp_manager.reset()

        sync_tp_state_from_db()

        assert not tp_manager.is_active


class TestSyncActivateFromDB:
    """State HOLDING + inactive tp_manager → recover from active_trade."""

    @patch("scheduler.orchestrator.get_open_trade", return_value=MOCK_OPEN_TRADE)
    @patch("scheduler.orchestrator.get_current_state", return_value="HOLDING")
    def test_activate_from_active_trade(self, mock_state, mock_trade):
        from scheduler.orchestrator import sync_tp_state_from_db, tp_manager
        tp_manager.reset()
        features = MOCK_FEATURES_ROW.copy()

        sync_tp_state_from_db(features)

        assert tp_manager.is_active
        assert tp_manager.entry_ask == 40100.0
        assert tp_manager.entry_score == 0.15
        assert tp_manager.highest_bid == 40050.0

    @patch("scheduler.orchestrator.get_open_trade", return_value=MOCK_OPEN_TRADE)
    @patch("scheduler.orchestrator.get_current_state", return_value="HOLDING")
    def test_sl_price_calculated_from_atr(self, mock_state, mock_trade):
        from scheduler.orchestrator import sync_tp_state_from_db, tp_manager
        tp_manager.reset()
        features = MOCK_FEATURES_ROW.copy()
        features["F_ATR_48"] = 100.0

        sync_tp_state_from_db(features)

        # sl_price = entry_ask - (ATR * TP_SL_ATR_MULT) = 40100 - 100*1.0 = 40000
        assert tp_manager.sl_price == 40000.0


class TestSyncHoldingNoTrade:
    """State HOLDING but no OPEN trade → warn, don't crash."""

    @patch("scheduler.orchestrator.get_open_trade", return_value=None)
    @patch("scheduler.orchestrator.get_current_state", return_value="HOLDING")
    def test_no_trade_warns(self, mock_state, mock_trade):
        from scheduler.orchestrator import sync_tp_state_from_db, tp_manager
        tp_manager.reset()

        # Should not raise, just log warning
        sync_tp_state_from_db()

        assert not tp_manager.is_active


class TestSyncSkipsIfAlreadyActive:
    @patch("scheduler.orchestrator.get_open_trade")
    @patch("scheduler.orchestrator.get_current_state", return_value="HOLDING")
    def test_no_double_activate(self, mock_state, mock_trade):
        from scheduler.orchestrator import sync_tp_state_from_db, tp_manager
        tp_manager.activate(40100.0, 0.15, 40050.0, sl_price=40000.0)

        sync_tp_state_from_db()

        # get_open_trade should NOT be called — TP already active
        mock_trade.assert_not_called()
