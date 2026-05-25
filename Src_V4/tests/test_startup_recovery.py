# tests/test_startup_recovery.py
"""
Tests for main.py startup recovery logic.
Recover_tp_state restores in-memory TP manager from DB on startup.
"""
import pytest
from unittest.mock import patch, MagicMock
from tests.conftest import MOCK_OPEN_TRADE


class TestRecoverTPState:
    def test_dry_run_skips_recovery(self):
        """DRY_RUN=True → recover_tp_state does nothing."""
        with patch("main.DRY_RUN", True):
            from main import recover_tp_state, tp_manager
            tp_manager.reset()
            recover_tp_state()
            assert not tp_manager.is_active

    def test_empty_state_skips_recovery(self):
        with patch("main.DRY_RUN", False), \
             patch("main.get_current_state", return_value="EMPTY"):
            from main import recover_tp_state, tp_manager
            tp_manager.reset()
            recover_tp_state()
            assert not tp_manager.is_active

    def test_already_active_skips_db(self):
        with patch("main.DRY_RUN", False), \
             patch("main.get_current_state", return_value="HOLDING"):
            from main import recover_tp_state, tp_manager
            tp_manager.activate(40100.0, 0.15, 40050.0)
            recover_tp_state()
            assert tp_manager.is_active

    def test_holding_inactive_recovers_from_db(self):
        with patch("main.DRY_RUN", False), \
             patch("main.get_current_state", return_value="HOLDING"), \
             patch("db.supabase_writer.get_open_trade", return_value=MOCK_OPEN_TRADE):
            from main import recover_tp_state, tp_manager
            tp_manager.reset()
            recover_tp_state()
            assert tp_manager.is_active
            assert tp_manager.entry_ask == 40100.0

    def test_holding_no_trade_warns(self):
        with patch("main.DRY_RUN", False), \
             patch("main.get_current_state", return_value="HOLDING"), \
             patch("db.supabase_writer.get_open_trade", return_value=None):
            from main import recover_tp_state, tp_manager
            tp_manager.reset()
            recover_tp_state()
            assert not tp_manager.is_active
