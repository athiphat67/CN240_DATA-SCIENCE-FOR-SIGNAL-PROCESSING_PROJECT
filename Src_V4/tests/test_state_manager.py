# tests/test_state_manager.py
"""
Tests for core/state_manager.py — the single state writer for the system.
"""
import pytest
from unittest.mock import MagicMock, patch


class TestSetStateRetry:
    """P1-1: set_state must have 3-retry + raise."""

    def test_set_state_success_first_try(self):
        mock_client = MagicMock()
        with patch("core.state_manager.DRY_RUN", False), \
             patch("core.state_manager._get_client", return_value=mock_client):
            from core.state_manager import set_state
            set_state("HOLDING")
        mock_client.table.assert_called()

    def test_set_state_retries_on_failure(self):
        mock_client = MagicMock()
        execute = mock_client.table.return_value.update.return_value.eq.return_value.execute
        execute.side_effect = [Exception("fail1"), Exception("fail2"), None]

        with patch("core.state_manager.DRY_RUN", False), \
             patch("core.state_manager._get_client", return_value=mock_client), \
             patch("core.state_manager.time.sleep"):
            from core.state_manager import set_state
            set_state("EMPTY")

        assert execute.call_count == 3

    def test_set_state_raises_after_3_failures(self):
        mock_client = MagicMock()
        execute = mock_client.table.return_value.update.return_value.eq.return_value.execute
        execute.side_effect = Exception("permanent failure")

        with patch("core.state_manager.DRY_RUN", False), \
             patch("core.state_manager._get_client", return_value=mock_client), \
             patch("core.state_manager.time.sleep"):
            from core.state_manager import set_state
            with pytest.raises(Exception, match="permanent failure"):
                set_state("EMPTY")

        assert execute.call_count == 3


class TestSetStateValidation:
    def test_invalid_state_raises_value_error(self):
        from core.state_manager import set_state
        with pytest.raises(ValueError, match="Invalid state"):
            set_state("INVALID")

    def test_dry_run_updates_memory(self):
        import core.state_manager as sm
        # Ensure DRY_RUN is True in module scope
        with patch.object(sm, "DRY_RUN", True):
            sm._dry_run_state = "EMPTY"
            sm.set_state("HOLDING")
            assert sm.get_current_state() == "HOLDING"
            sm.set_state("EMPTY")
            assert sm.get_current_state() == "EMPTY"


class TestNoUpdateStateImport:
    """Verify orchestrator does NOT import update_state (source-level check)."""

    def test_orchestrator_source_no_update_state_import(self):
        import os
        orch_path = os.path.join(
            os.path.dirname(__file__), "..", "scheduler", "orchestrator.py"
        )
        with open(orch_path, "r") as f:
            source = f.read()
        import_lines = [
            line.strip() for line in source.splitlines()
            if "update_state" in line
            and not line.strip().startswith("#")
            and "import" in line
        ]
        assert len(import_lines) == 0, \
            f"update_state still imported: {import_lines}"

    def test_orchestrator_source_no_update_state_calls(self):
        import os
        orch_path = os.path.join(
            os.path.dirname(__file__), "..", "scheduler", "orchestrator.py"
        )
        with open(orch_path, "r") as f:
            source = f.read()
        call_lines = [
            line.strip() for line in source.splitlines()
            if "update_state(" in line
            and not line.strip().startswith("#")
        ]
        assert len(call_lines) == 0, \
            f"update_state() still called: {call_lines}"
