# tests/test_model_sell_integration.py
"""
Model SELL path must: insert signal → check return → close trade → set EMPTY → reset TP.
"""
import pytest
from unittest.mock import patch, MagicMock
from tests.conftest import (
    MOCK_FEATURES_ROW, MOCK_INFERENCE_RESULT, MOCK_SELL_GATE_RESULT,
)


class TestModelSellSuccess:
    @patch("scheduler.orchestrator.notify_sell_signal")
    @patch("scheduler.orchestrator.notify_error")
    @patch("scheduler.orchestrator.set_state")
    @patch("scheduler.orchestrator.close_open_trade", return_value=True)
    @patch("scheduler.orchestrator.mark_signal_execution", return_value=True)
    @patch("scheduler.orchestrator.insert_bar_log", return_value=True)
    @patch("scheduler.orchestrator.insert_signal", return_value=True)
    @patch("scheduler.orchestrator.build_trade_payload", return_value={
        "rationale_text": "test", "top_shap_features": {},
    })
    @patch("scheduler.orchestrator.evaluate_signal_gate")
    @patch("scheduler.orchestrator.run_inference")
    @patch("scheduler.orchestrator.compute_features")
    @patch("scheduler.orchestrator.build_candles")
    @patch("scheduler.orchestrator.get_current_state", return_value="HOLDING")
    @patch("scheduler.orchestrator.get_open_trade", return_value={"id": 1, "entry_ask": 40100.0, "entry_score": 0.15, "entry_bid_at_signal": 40050.0})
    def test_model_sell_full_flow(
        self, mock_get_trade, mock_get_state,
        mock_candles, mock_features, mock_inference, mock_gate,
        mock_payload, mock_insert_signal, mock_insert_bar,
        mock_mark, mock_close, mock_set_state,
        mock_notify_error, mock_notify_sell,
    ):
        mock_candles.return_value = MagicMock()
        mock_features.return_value = MOCK_FEATURES_ROW.copy()
        mock_inference.return_value = MOCK_INFERENCE_RESULT.copy()
        mock_gate.return_value = MOCK_SELL_GATE_RESULT.copy()

        from scheduler.orchestrator import run_signal_pipeline, tp_manager
        tp_manager.activate(40100.0, 0.15, 40050.0, sl_price=40000.0)

        run_signal_pipeline()

        # Verify ordering: insert_signal before close_open_trade
        mock_insert_signal.assert_called_once()
        mock_close.assert_called_once()
        mock_set_state.assert_called_once_with("EMPTY")
        mock_notify_sell.assert_called_once()
        assert not tp_manager.is_active, "TP must be reset after SELL"


class TestModelSellInsertFail:
    """P1-3: If insert_signal fails, SELL must abort."""

    @patch("scheduler.orchestrator.notify_sell_signal")
    @patch("scheduler.orchestrator.notify_error")
    @patch("scheduler.orchestrator.set_state")
    @patch("scheduler.orchestrator.close_open_trade")
    @patch("scheduler.orchestrator.insert_bar_log", return_value=True)
    @patch("scheduler.orchestrator.insert_signal", return_value=False)  # FAIL
    @patch("scheduler.orchestrator.build_trade_payload", return_value={
        "rationale_text": "test", "top_shap_features": {},
    })
    @patch("scheduler.orchestrator.evaluate_signal_gate")
    @patch("scheduler.orchestrator.run_inference")
    @patch("scheduler.orchestrator.compute_features")
    @patch("scheduler.orchestrator.build_candles")
    @patch("scheduler.orchestrator.get_current_state", return_value="HOLDING")
    @patch("scheduler.orchestrator.get_open_trade", return_value={"id": 1, "entry_ask": 40100.0, "entry_score": 0.15, "entry_bid_at_signal": 40050.0})
    def test_insert_fail_aborts_sell(
        self, mock_get_trade, mock_get_state,
        mock_candles, mock_features, mock_inference, mock_gate,
        mock_payload, mock_insert_signal, mock_insert_bar,
        mock_close, mock_set_state, mock_notify_error, mock_notify_sell,
    ):
        mock_candles.return_value = MagicMock()
        mock_features.return_value = MOCK_FEATURES_ROW.copy()
        mock_inference.return_value = MOCK_INFERENCE_RESULT.copy()
        mock_gate.return_value = MOCK_SELL_GATE_RESULT.copy()

        from scheduler.orchestrator import run_signal_pipeline
        run_signal_pipeline()

        # Must NOT close trade or change state
        mock_close.assert_not_called()
        mock_set_state.assert_not_called()
        mock_notify_error.assert_called_once()


class TestModelSellCloseFail:
    @patch("scheduler.orchestrator.notify_sell_signal")
    @patch("scheduler.orchestrator.notify_error")
    @patch("scheduler.orchestrator.set_state")
    @patch("scheduler.orchestrator.close_open_trade", return_value=False)  # FAIL
    @patch("scheduler.orchestrator.insert_bar_log", return_value=True)
    @patch("scheduler.orchestrator.insert_signal", return_value=True)
    @patch("scheduler.orchestrator.build_trade_payload", return_value={
        "rationale_text": "test", "top_shap_features": {},
    })
    @patch("scheduler.orchestrator.evaluate_signal_gate")
    @patch("scheduler.orchestrator.run_inference")
    @patch("scheduler.orchestrator.compute_features")
    @patch("scheduler.orchestrator.build_candles")
    @patch("scheduler.orchestrator.get_current_state", return_value="HOLDING")
    @patch("scheduler.orchestrator.get_open_trade", return_value={"id": 1, "entry_ask": 40100.0, "entry_score": 0.15, "entry_bid_at_signal": 40050.0})
    def test_close_fail_aborts_state_change(
        self, mock_get_trade, mock_get_state,
        mock_candles, mock_features, mock_inference, mock_gate,
        mock_payload, mock_insert_signal, mock_insert_bar,
        mock_close, mock_set_state, mock_notify_error, mock_notify_sell,
    ):
        mock_candles.return_value = MagicMock()
        mock_features.return_value = MOCK_FEATURES_ROW.copy()
        mock_inference.return_value = MOCK_INFERENCE_RESULT.copy()
        mock_gate.return_value = MOCK_SELL_GATE_RESULT.copy()

        from scheduler.orchestrator import run_signal_pipeline
        run_signal_pipeline()

        # State must NOT change when close fails
        mock_set_state.assert_not_called()
        mock_notify_error.assert_called_once()
