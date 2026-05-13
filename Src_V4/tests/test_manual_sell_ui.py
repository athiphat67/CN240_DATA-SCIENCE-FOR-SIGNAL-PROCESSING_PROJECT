# tests/test_manual_sell_ui.py
"""
Manual SELL via UI must create audit signal record before closing trade.
"""
import pytest
from unittest.mock import patch, MagicMock


class TestManualSellSuccess:
    @patch("tools.confirm_trade_ui.notify_sell_confirmed")
    @patch("tools.confirm_trade_ui.send_trade_log")
    @patch("tools.confirm_trade_ui.set_state")
    @patch("tools.confirm_trade_ui.close_open_trade", return_value=True)
    @patch("tools.confirm_trade_ui.insert_signal", return_value=True)
    @patch("tools.confirm_trade_ui.get_current_state", return_value="HOLDING")
    def test_full_manual_sell(
        self, mock_state, mock_insert, mock_close,
        mock_set, mock_log, mock_notify,
    ):
        from tools.confirm_trade_ui import confirm_sell
        result = confirm_sell("40050")

        assert "✅ SELL Confirmed" in result

        # Signal record created first
        mock_insert.assert_called_once()
        inserted = mock_insert.call_args[0][0]
        assert inserted["signal_type"] == "SELL"
        assert inserted["execution_status"] == "CONFIRMED"
        assert inserted["id"].startswith("manual_sell_")

        # Close trade with FK-safe exit_signal_id
        mock_close.assert_called_once()
        close_kwargs = mock_close.call_args[1]
        assert close_kwargs["exit_signal_id"] == inserted["id"]
        assert close_kwargs["reason"] == "MANUAL_SELL_CONFIRMED"

        mock_set.assert_called_once_with("EMPTY")


class TestManualSellValidation:
    @patch("tools.confirm_trade_ui.get_current_state", return_value="HOLDING")
    def test_empty_price_rejected(self, _):
        from tools.confirm_trade_ui import confirm_sell
        assert "❌" in confirm_sell("")

    @patch("tools.confirm_trade_ui.get_current_state", return_value="EMPTY")
    def test_already_empty(self, _):
        from tools.confirm_trade_ui import confirm_sell
        assert "EMPTY" in confirm_sell("40050")


class TestManualSellInsertFail:
    @patch("tools.confirm_trade_ui.set_state")
    @patch("tools.confirm_trade_ui.close_open_trade")
    @patch("tools.confirm_trade_ui.insert_signal", return_value=False)
    @patch("tools.confirm_trade_ui.get_current_state", return_value="HOLDING")
    def test_insert_fail_no_close(self, _, mock_insert, mock_close, mock_set):
        from tools.confirm_trade_ui import confirm_sell
        result = confirm_sell("40050")

        assert "❌" in result
        mock_close.assert_not_called()
        mock_set.assert_not_called()


class TestManualSellCloseFail:
    @patch("tools.confirm_trade_ui.set_state")
    @patch("tools.confirm_trade_ui.close_open_trade", return_value=False)
    @patch("tools.confirm_trade_ui.insert_signal", return_value=True)
    @patch("tools.confirm_trade_ui.get_current_state", return_value="HOLDING")
    def test_close_fail_no_state_change(self, _, mock_insert, mock_close, mock_set):
        from tools.confirm_trade_ui import confirm_sell
        result = confirm_sell("40050")

        assert "❌" in result
        mock_set.assert_not_called()
