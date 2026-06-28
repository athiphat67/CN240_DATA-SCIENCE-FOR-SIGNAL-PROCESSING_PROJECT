# tests/conftest.py
"""
Shared fixtures for the HSH Gold ML Trader test suite.

Unit tests: heavy deps (apscheduler, gradio, httpx, xgboost) are mocked.
Integration tests (test_snapshot_alignment.py): real supabase + real .env.
"""
import os
import sys
import types
import pytest
from unittest.mock import MagicMock
from datetime import timezone, timedelta

# ── Ensure project root is importable ─────────────────────────────────────────
_SRC_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _SRC_ROOT)

# ── Load REAL .env FIRST so SUPABASE_URL/KEY are available for integration tests
# ── (unit tests can override these with setdefault after) ────────────────────
from dotenv import load_dotenv as _load_dotenv
_load_dotenv(os.path.join(_SRC_ROOT, ".env"), override=False)

# ── Pre-set fallback env vars for unit tests that don't need real DB ─────────
os.environ.setdefault("DRY_RUN", "true")
os.environ.setdefault("SUPABASE_URL", "https://test.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "test-key")

# ── Real Bangkok timezone for pytz stub ───────────────────────────────────────
BKK_TZ = timezone(timedelta(hours=7))


# ── Gradio context-manager compatible mock ────────────────────────────────────
class _GrContextMock(MagicMock):
    """MagicMock that supports `with` statements, truthiness checks, and
    returns instances with all attributes (like .click(), .change(), etc.)."""
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def __bool__(self):
        return True
    def __call__(self, *args, **kwargs):
        instance = _GrContextMock()
        return instance


# ── Stub out heavy third-party modules (unit tests only) ─────────────────────
# NOTE: supabase and dotenv are NOT stubbed here — integration tests need the real packages.
_STUB_MODULES = [
    "apscheduler", "apscheduler.schedulers", "apscheduler.schedulers.blocking",
    "apscheduler.triggers", "apscheduler.triggers.cron",
    "gradio",
    # NOTE: httpx is NOT stubbed — supabase imports httpx.Timeout at package level
    # NOTE: supabase is NOT stubbed — integration tests need real DB access
    "xgboost",
]

# Only stub pandas/numpy if they're not actually installed
try:
    import pandas  # noqa: F401
except ImportError:
    _STUB_MODULES.extend(["pandas"])
try:
    import numpy  # noqa: F401
except ImportError:
    _STUB_MODULES.extend(["numpy", "numpy.lib", "numpy.lib.stride_tricks"])

for mod_name in _STUB_MODULES:
    if mod_name not in sys.modules:
        stub = types.ModuleType(mod_name)
        if mod_name == "apscheduler.schedulers.blocking":
            stub.BlockingScheduler = MagicMock
        elif mod_name == "apscheduler.triggers.cron":
            stub.CronTrigger = MagicMock
        elif mod_name == "supabase":
            stub.create_client = MagicMock(return_value=MagicMock())
            stub.Client = MagicMock
        elif mod_name == "gradio":
            # Gradio widgets are used as context managers, callables,
            # and have .click()/.change() methods.
            # We use a real MagicMock() module with all attrs auto-created.
            # The key is that __enter__/__exit__ and __bool__ work correctly.
            for attr_name in ["Blocks", "Row", "Column", "Textbox", "Button",
                              "Radio", "Accordion", "Markdown", "Dropdown",
                              "Slider", "Number"]:
                mock_widget = MagicMock()
                mock_widget.return_value.__enter__ = MagicMock(return_value=mock_widget.return_value)
                mock_widget.return_value.__exit__ = MagicMock(return_value=False)
                setattr(stub, attr_name, mock_widget)
            stub.themes = MagicMock()
            stub.themes.Soft = MagicMock(return_value=MagicMock())
        elif mod_name == "xgboost":
            stub.XGBRanker = MagicMock
            stub.DMatrix = MagicMock
        elif mod_name == "pandas":
            stub.DataFrame = MagicMock
            stub.Timestamp = MagicMock
            stub.to_datetime = MagicMock
            stub.read_csv = MagicMock
        elif mod_name == "numpy":
            stub.integer = int
            stub.floating = float
            stub.ndarray = list
            stub.nan = float("nan")
            stub.inf = float("inf")
        sys.modules[mod_name] = stub

# Stub pytz with REAL timezone so datetime.now(TZ) works
if "pytz" not in sys.modules:
    try:
        import pytz  # noqa: F401
    except ImportError:
        _pytz = types.ModuleType("pytz")
        _pytz.timezone = lambda name: BKK_TZ
        sys.modules["pytz"] = _pytz
else:
    # pytz exists but let's make sure it returns a real tzinfo
    pass


# ── Reusable mock data ────────────────────────────────────────────────────────

MOCK_FEATURES_ROW = {
    "bar_time": "2026-05-10T10:00:00+07:00",
    "session": "Morning",
    "hsh_close_ask": 40100.0,
    "hsh_close_bid": 40050.0,
    "xau_close": 2350.0,
    "usd_close": 34.5,
    "F_ATR_48": 100.0,
    "F_SRVR": 0.5,
    "F_Regime": 1,
    "F_XAU_Spread_Norm": 1.0,
    "F_Syn_Price": 40000.0,
    "F_Thai_Premium": 100.0,
    "F_Corr_XAU_USD": 0.3,
    "F_XAU_Mom_Short": 0.002,
    "F_XAU_Mom_Mid": 0.005,
    "F_USD_Mom": -0.001,
    "F_FSP": 0.5,
    "F_SA_TWAP_Dev": 10.0,
    "F_SA_MDD": -5.0,
    "F_SA_Vol": 20.0,
    "F_SA_Range": 50.0,
    "F_SA_Position": 0.6,
    "F_Historical_Vol_THB": 200.0,
    "F_Remaining_Vol": 100.0,
    "F_Price_Vs_Open": 0.001,
    "F_Mom_1bar": 0.0005,
    "F_Mom_3bar": 0.001,
    "F_SA_Drawdown_Pct": -0.001,
    "F_HSH_vs_THBGold_Dev": 0.0001,
    "F_DayOfWeek": 1,
    "F_MinuteOfDay": 600,
    "F_RSI_14": 55.0,
    "F_RSI_6": 58.0,
    "F_BB_Pos": 0.3,
    "F_Hour_Sin": 0.5,
    "F_Hour_Cos": 0.866,
    "F_Session_Type": 0,
    "F_HSH_Spread": 50.0,
    "F_Spread_Cost_Pct": 0.00125,
    "F_Spread_vs_ATR": 0.5,
}

MOCK_INFERENCE_RESULT = {
    "bar_time": "2026-05-10T10:00:00+07:00",
    "ranker_score": 0.15,
    "model_version": "lambdamart_v11",
    "features_snap": MOCK_FEATURES_ROW.copy(),
    "shap_values": [0.05, -0.02, 0.01],
    "feature_names": ["F_Thai_Premium", "F_RSI_14", "F_ATR_48"],
}

MOCK_BUY_GATE_RESULT = {
    "signal_id": "sig_20260510_100000",
    "bar_time": "2026-05-10T10:00:00+07:00",
    "session": "Morning",
    "signal_type": "BUY",
    "ranker_score": 0.15,
    "state_before": "EMPTY",
    "gates_detail": {},
    "passed": True,
    "reject_reason": None,
    "dry_run": True,
    "features_snap": MOCK_FEATURES_ROW.copy(),
    "hsh_ask": 40100.0,
    "hsh_bid": 40050.0,
    "xau_close": 2350.0,
    "atr_48": 100.0,
}

MOCK_SELL_GATE_RESULT = {
    **MOCK_BUY_GATE_RESULT,
    "signal_type": "SELL",
    "state_before": "HOLDING",
}

MOCK_PENDING_SIGNAL = {
    "id": "sig_20260510_100000",
    "bar_time": "2026-05-10T10:00:00+07:00",
    "session": "Morning",
    "signal_type": "BUY",
    "ranker_score": 0.15,
    "state_before": "EMPTY",
    "passed": True,
    "execution_status": "PENDING_CONFIRM",
    "hsh_ask_price": 40100.0,
    "hsh_bid_price": 40050.0,
}

MOCK_OPEN_TRADE = {
    "id": 1,
    "status": "OPEN",
    "entry_signal_id": "sig_20260510_100000",
    "entry_ask": 40100.0,
    "entry_bid_at_signal": 40050.0,
    "entry_score": 0.15,
    "created_at": "2026-05-10T10:05:00+07:00",
}


@pytest.fixture
def tp_manager():
    """Fresh DynamicTPManager for each test."""
    from core.dynamic_tp_manager import DynamicTPManager
    return DynamicTPManager(
        atr_multiplier=1.5,
        breakeven_atr_mult=1.0,
        score_drop_threshold=0.15,
    )


@pytest.fixture
def active_tp_manager(tp_manager):
    """TP manager pre-activated as if Confirm BUY happened."""
    tp_manager.activate(
        entry_ask=40100.0,
        entry_score=0.15,
        initial_bid=40050.0,
        sl_price=40000.0,
    )
    return tp_manager
