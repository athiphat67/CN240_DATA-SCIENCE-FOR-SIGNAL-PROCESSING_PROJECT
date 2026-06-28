# tests/test_confirm_buy_ui.py
"""
Tests for tools/confirm_trade_ui.py — Confirm BUY flow.
"""
import pytest
from unittest.mock import patch, MagicMock
from tests.conftest import MOCK_PENDING_SIGNAL


class TestConfirmBuySuccess:
    @patch("tools.confirm_trade_ui.notify_buy_confirmed")
    @patch("tools.confirm_trade_ui.send_trade_log")
    @patch("tools.confirm_trade_ui.set_state")
    @patch("tools.confirm_trade_ui.mark_signal_execution", return_value=True)
    @patch("tools.confirm_trade_ui.open_trade_from_signal", return_value=True)
    @patch("tools.confirm_trade_ui.get_signal_by_id", return_value=MOCK_PENDING_SIGNAL)
    @patch("tools.confirm_trade_ui.get_current_state", return_value="EMPTY")
    def test_full_confirm_buy(
        self, mock_state, mock_get_sig, mock_open,
        mock_mark, mock_set, mock_log, mock_notify,
    ):
        from tools.confirm_trade_ui import confirm_buy
        result = confirm_buy("40100", "sig_20260510_100000")

        assert "✅ BUY Confirmed" in result
        mock_open.assert_called_once()
        mock_mark.assert_called_once_with("sig_20260510_100000", "CONFIRMED", 40100.0)
        mock_set.assert_called_once_with("HOLDING")
        mock_notify.assert_called_once()


class TestConfirmBuyValidation:
    @patch("tools.confirm_trade_ui.get_current_state", return_value="EMPTY")
    def test_empty_price_rejected(self, _):
        from tools.confirm_trade_ui import confirm_buy
        assert "❌" in confirm_buy("", "sig_test")

    @patch("tools.confirm_trade_ui.get_current_state", return_value="EMPTY")
    def test_zero_price_rejected(self, _):
        from tools.confirm_trade_ui import confirm_buy
        assert "❌" in confirm_buy("0", "sig_test")

    @patch("tools.confirm_trade_ui.get_current_state", return_value="HOLDING")
    def test_already_holding_rejected(self, _):
        from tools.confirm_trade_ui import confirm_buy
        assert "HOLDING" in confirm_buy("40100", "sig_test")

    @patch("tools.confirm_trade_ui.get_signal_by_id")
    @patch("tools.confirm_trade_ui.get_current_state", return_value="EMPTY")
    def test_sell_signal_rejected(self, _, mock_get):
        mock_get.return_value = {**MOCK_PENDING_SIGNAL, "signal_type": "SELL"}
        from tools.confirm_trade_ui import confirm_buy
        assert "not a BUY" in confirm_buy("40100", "sig_test")

    @patch("tools.confirm_trade_ui.get_signal_by_id")
    @patch("tools.confirm_trade_ui.get_current_state", return_value="EMPTY")
    def test_unpassed_signal_rejected(self, _, mock_get):
        mock_get.return_value = {**MOCK_PENDING_SIGNAL, "passed": False}
        from tools.confirm_trade_ui import confirm_buy
        assert "did not pass" in confirm_buy("40100", "sig_test")

    @patch("tools.confirm_trade_ui.get_signal_by_id")
    @patch("tools.confirm_trade_ui.get_current_state", return_value="EMPTY")
    def test_already_confirmed_rejected(self, _, mock_get):
        mock_get.return_value = {**MOCK_PENDING_SIGNAL, "execution_status": "CONFIRMED"}
        from tools.confirm_trade_ui import confirm_buy
        assert "not pending" in confirm_buy("40100", "sig_test")


class TestConfirmBuyPartialFailure:
    """If trade opens but mark_signal fails, state must still become HOLDING."""

    @patch("tools.confirm_trade_ui.notify_buy_confirmed")
    @patch("tools.confirm_trade_ui.set_state")
    @patch("tools.confirm_trade_ui.mark_signal_execution", return_value=False)  # FAIL
    @patch("tools.confirm_trade_ui.open_trade_from_signal", return_value=True)
    @patch("tools.confirm_trade_ui.get_signal_by_id", return_value=MOCK_PENDING_SIGNAL)
    @patch("tools.confirm_trade_ui.get_current_state", return_value="EMPTY")
    def test_partial_fail_still_holding(
        self, mock_state, mock_get, mock_open, mock_mark,
        mock_set, mock_notify,
    ):
        from tools.confirm_trade_ui import confirm_buy
        result = confirm_buy("40100", "sig_20260510_100000")

        assert "⚠️" in result
        # CRITICAL: State must be HOLDING even if mark fails
        mock_set.assert_called_once_with("HOLDING")


class TestConfirmBuyOpenTradeFail:
    @patch("tools.confirm_trade_ui.set_state")
    @patch("tools.confirm_trade_ui.open_trade_from_signal", return_value=False)  # FAIL
    @patch("tools.confirm_trade_ui.get_signal_by_id", return_value=MOCK_PENDING_SIGNAL)
    @patch("tools.confirm_trade_ui.get_current_state", return_value="EMPTY")
    def test_open_fail_no_state_change(self, _, mock_get, mock_open, mock_set):
        from tools.confirm_trade_ui import confirm_buy
        result = confirm_buy("40100", "sig_20260510_100000")

        assert "❌" in result
        mock_set.assert_not_called()
