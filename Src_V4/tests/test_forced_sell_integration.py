# tests/test_forced_sell_integration.py
"""
Forced SELL (SL_HIT / TRAIL_HIT) must:
1. Only fire when state=HOLDING and tp_manager.is_active
2. Insert forced signal FIRST
3. Close trade
4. Mark AUTO_EXITED
5. set_state(EMPTY)
6. tp_manager.reset()
7. Return immediately (no duplicate normal signal)
"""
import pytest
from unittest.mock import patch, MagicMock, ANY
from tests.conftest import MOCK_FEATURES_ROW, MOCK_INFERENCE_RESULT


def _make_holding_mocks(mock_candles, mock_features, mock_inference, mock_gate):
    """Configure mocks for a HOLDING state bar."""
    mock_candles.return_value = MagicMock()
    features = MOCK_FEATURES_ROW.copy()
    mock_features.return_value = features
    inf = MOCK_INFERENCE_RESULT.copy()
    mock_inference.return_value = inf
    # Gate produces HOLD (not SELL) — forced exit comes from TP manager
    gate = {
        "signal_id": "sig_20260510_100000",
        "bar_time": features["bar_time"],
        "session": features["session"],
        "signal_type": "HOLD",
        "ranker_score": inf["ranker_score"],
        "state_before": "HOLDING",
        "gates_detail": {},
        "passed": False,
        "reject_reason": "score_gate",
        "dry_run": True,
        "features_snap": features,
        "hsh_ask": features["hsh_close_ask"],
        "hsh_bid": features["hsh_close_bid"],
        "xau_close": features["xau_close"],
        "atr_48": features["F_ATR_48"],
    }
    mock_gate.return_value = gate
    return features, inf


class TestForcedSellSLHit:
    @patch("scheduler.orchestrator.notify_sell_signal")
    @patch("scheduler.orchestrator.notify_dynamic_tp")
    @patch("scheduler.orchestrator.notify_error")
    @patch("scheduler.orchestrator.set_state")
    @patch("scheduler.orchestrator.mark_signal_execution", return_value=True)
    @patch("scheduler.orchestrator.close_open_trade", return_value=True)
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
    @patch("scheduler.orchestrator.get_open_trade", return_value={
        "id": 1, "entry_ask": 40100.0, "entry_score": 0.15,
        "entry_bid_at_signal": 40050.0,
    })
    def test_sl_hit_full_flow(
        self, mock_get_trade, mock_get_state,
        mock_candles, mock_features, mock_inference, mock_gate,
        mock_payload, mock_insert_signal, mock_insert_bar,
        mock_close, mock_mark, mock_set_state,
        mock_notify_error, mock_notify_tp, mock_notify_sell,
    ):
        features, inf = _make_holding_mocks(
            mock_candles, mock_features, mock_inference, mock_gate
        )
        # Set bid below SL to trigger SL_HIT
        features["hsh_close_bid"] = 39950.0

        from scheduler.orchestrator import run_signal_pipeline, tp_manager
        tp_manager.activate(40100.0, 0.15, 40050.0, sl_price=40000.0)

        run_signal_pipeline()

        # 1. Insert forced SELL signal first
        mock_insert_signal.assert_called_once()
        inserted = mock_insert_signal.call_args[0][0]
        assert inserted["signal_type"] == "SELL"
        assert inserted["state_before"] == "HOLDING"
        assert "FORCED_BY_SL_HIT" in (inserted.get("reject_reason") or "")
        assert inserted["execution_status"] == "PENDING_AUTO_EXIT"
        assert inserted["id"].startswith("tp_")

        # 2. Close trade with FK-safe exit_signal_id
        mock_close.assert_called_once()
        close_kwargs = mock_close.call_args[1]
        assert close_kwargs["exit_signal_id"] == inserted["id"]
        assert close_kwargs["reason"] == "SL_HIT"

        # 3. Mark AUTO_EXITED
        mock_mark.assert_called_once()

        # 4. State → EMPTY
        mock_set_state.assert_called_once_with("EMPTY")

        # 5. TP manager reset
        assert not tp_manager.is_active

        # 6. Bar log with state_at_bar=HOLDING
        mock_insert_bar.assert_called_once()
        bar_log = mock_insert_bar.call_args[0][0]
        assert bar_log["state_at_bar"] == "HOLDING"


class TestForcedSellInsertFail:
    @patch("scheduler.orchestrator.notify_sell_signal")
    @patch("scheduler.orchestrator.notify_dynamic_tp")
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
    @patch("scheduler.orchestrator.get_open_trade", return_value={
        "id": 1, "entry_ask": 40100.0, "entry_score": 0.15,
        "entry_bid_at_signal": 40050.0,
    })
    def test_insert_fail_aborts(
        self, mock_get_trade, mock_get_state,
        mock_candles, mock_features, mock_inference, mock_gate,
        mock_payload, mock_insert_signal, mock_insert_bar,
        mock_close, mock_set_state,
        mock_notify_error, mock_notify_tp, mock_notify_sell,
    ):
        features, inf = _make_holding_mocks(
            mock_candles, mock_features, mock_inference, mock_gate
        )
        features["hsh_close_bid"] = 39950.0

        from scheduler.orchestrator import run_signal_pipeline, tp_manager
        tp_manager.activate(40100.0, 0.15, 40050.0, sl_price=40000.0)

        run_signal_pipeline()

        mock_close.assert_not_called()
        mock_set_state.assert_not_called()
        mock_notify_error.assert_called_once()


class TestForcedSellIgnoredWhenEmpty:
    """SL_HIT/TRAIL_HIT must be ignored if state != HOLDING."""

    @patch("scheduler.orchestrator.notify_sell_signal")
    @patch("scheduler.orchestrator.notify_dynamic_tp")
    @patch("scheduler.orchestrator.set_state")
    @patch("scheduler.orchestrator.close_open_trade")
    @patch("scheduler.orchestrator.insert_bar_log", return_value=True)
    @patch("scheduler.orchestrator.insert_signal")
    @patch("scheduler.orchestrator.build_trade_payload", return_value={
        "rationale_text": "test", "top_shap_features": {},
    })
    @patch("scheduler.orchestrator.evaluate_signal_gate")
    @patch("scheduler.orchestrator.run_inference")
    @patch("scheduler.orchestrator.compute_features")
    @patch("scheduler.orchestrator.build_candles")
    @patch("scheduler.orchestrator.get_current_state", return_value="EMPTY")
    @patch("scheduler.orchestrator.get_open_trade", return_value=None)
    def test_sl_hit_ignored_when_empty(
        self, mock_get_trade, mock_get_state,
        mock_candles, mock_features, mock_inference, mock_gate,
        mock_payload, mock_insert_signal, mock_insert_bar,
        mock_close, mock_set_state, mock_notify_tp, mock_notify_sell,
    ):
        """TP manager not active when state EMPTY → SL_HIT cannot fire."""
        features, inf = _make_holding_mocks(
            mock_candles, mock_features, mock_inference, mock_gate
        )

        from scheduler.orchestrator import run_signal_pipeline, tp_manager
        tp_manager.reset()  # Ensure inactive

        run_signal_pipeline()

        # No forced signal should be inserted
        # insert_signal may be called for the normal HOLD signal but
        # close_open_trade and set_state(EMPTY) must NOT be called
        mock_close.assert_not_called()
        mock_set_state.assert_not_called()
