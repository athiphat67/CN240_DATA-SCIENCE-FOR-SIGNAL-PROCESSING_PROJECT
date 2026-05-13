# tests/test_orchestrator_buy_pending.py
"""
BUY signal must NOT set HOLDING or activate TP.
It must only insert signal as PENDING_CONFIRM.
"""
import pytest
from unittest.mock import patch, MagicMock, ANY
from tests.conftest import (
    MOCK_FEATURES_ROW, MOCK_INFERENCE_RESULT, MOCK_BUY_GATE_RESULT,
)


class TestBuySignalPendingConfirm:
    """When gate produces BUY, orchestrator must NOT change state."""

    @patch("scheduler.orchestrator.notify_buy_signal")
    @patch("scheduler.orchestrator.insert_bar_log", return_value=True)
    @patch("scheduler.orchestrator.insert_signal", return_value=True)
    @patch("scheduler.orchestrator.build_trade_payload", return_value={
        "rationale_text": "test", "top_shap_features": {},
    })
    @patch("scheduler.orchestrator.evaluate_signal_gate")
    @patch("scheduler.orchestrator.run_inference")
    @patch("scheduler.orchestrator.compute_features")
    @patch("scheduler.orchestrator.build_candles")
    @patch("scheduler.orchestrator.get_current_state", return_value="EMPTY")
    @patch("scheduler.orchestrator.set_state")
    @patch("scheduler.orchestrator.get_open_trade", return_value=None)
    def test_buy_signal_stays_empty(
        self, mock_get_trade, mock_set_state, mock_get_state,
        mock_candles, mock_features, mock_inference, mock_gate,
        mock_payload, mock_insert_signal, mock_insert_bar, mock_notify_buy,
    ):
        mock_candles.return_value = MagicMock()
        mock_features.return_value = MOCK_FEATURES_ROW.copy()
        mock_inference.return_value = MOCK_INFERENCE_RESULT.copy()
        mock_gate.return_value = MOCK_BUY_GATE_RESULT.copy()

        from scheduler.orchestrator import run_signal_pipeline
        run_signal_pipeline()

        # Signal inserted with PENDING_CONFIRM
        mock_insert_signal.assert_called_once()
        inserted = mock_insert_signal.call_args[0][0]
        assert inserted["execution_status"] == "PENDING_CONFIRM"

        # State MUST NOT change
        mock_set_state.assert_not_called()

        # Notify buy signal (WAITING CONFIRM)
        mock_notify_buy.assert_called_once()

    @patch("scheduler.orchestrator.notify_buy_signal")
    @patch("scheduler.orchestrator.insert_bar_log", return_value=True)
    @patch("scheduler.orchestrator.insert_signal", return_value=True)
    @patch("scheduler.orchestrator.build_trade_payload", return_value={
        "rationale_text": "test", "top_shap_features": {},
    })
    @patch("scheduler.orchestrator.evaluate_signal_gate")
    @patch("scheduler.orchestrator.run_inference")
    @patch("scheduler.orchestrator.compute_features")
    @patch("scheduler.orchestrator.build_candles")
    @patch("scheduler.orchestrator.get_current_state", return_value="EMPTY")
    @patch("scheduler.orchestrator.close_open_trade")
    @patch("scheduler.orchestrator.get_open_trade", return_value=None)
    def test_buy_signal_no_trade_opened(
        self, mock_get_trade, mock_close, mock_get_state,
        mock_candles, mock_features, mock_inference, mock_gate,
        mock_payload, mock_insert_signal, mock_insert_bar, mock_notify_buy,
    ):
        mock_candles.return_value = MagicMock()
        mock_features.return_value = MOCK_FEATURES_ROW.copy()
        mock_inference.return_value = MOCK_INFERENCE_RESULT.copy()
        mock_gate.return_value = MOCK_BUY_GATE_RESULT.copy()

        from scheduler.orchestrator import run_signal_pipeline
        run_signal_pipeline()

        # No trade should be opened by the orchestrator on BUY signal
        mock_close.assert_not_called()

    @patch("scheduler.orchestrator.notify_buy_signal")
    @patch("scheduler.orchestrator.insert_bar_log", return_value=True)
    @patch("scheduler.orchestrator.insert_signal", return_value=True)
    @patch("scheduler.orchestrator.build_trade_payload", return_value={
        "rationale_text": "test", "top_shap_features": {},
    })
    @patch("scheduler.orchestrator.evaluate_signal_gate")
    @patch("scheduler.orchestrator.run_inference")
    @patch("scheduler.orchestrator.compute_features")
    @patch("scheduler.orchestrator.build_candles")
    @patch("scheduler.orchestrator.get_current_state", return_value="EMPTY")
    @patch("scheduler.orchestrator.get_open_trade", return_value=None)
    def test_buy_signal_tp_not_activated(
        self, mock_get_trade, mock_get_state,
        mock_candles, mock_features, mock_inference, mock_gate,
        mock_payload, mock_insert_signal, mock_insert_bar, mock_notify_buy,
    ):
        mock_candles.return_value = MagicMock()
        mock_features.return_value = MOCK_FEATURES_ROW.copy()
        mock_inference.return_value = MOCK_INFERENCE_RESULT.copy()
        mock_gate.return_value = MOCK_BUY_GATE_RESULT.copy()

        from scheduler.orchestrator import run_signal_pipeline, tp_manager
        tp_manager.reset()  # Ensure clean state

        run_signal_pipeline()

        assert not tp_manager.is_active, "TP manager must NOT activate on BUY signal"
