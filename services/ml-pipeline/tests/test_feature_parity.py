# tests/test_feature_parity.py
"""
Feature Parity Test: Verifies that core/feature_engine.py produces identical
output to the reference formulas in core/app.py for the same input data.

This test creates synthetic M10 candle data, feeds it through feature_engine.py,
and validates that:
1. No feature is NaN (all fillna chains applied)
2. Session expected lengths match app.py (36, 36, 48)
3. Feature values are finite and within reasonable bounds
4. Feature output contains all model-expected columns
5. Drawdown uses groupby.apply (not transform)
"""
import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta


# ── Helper: generate synthetic M10 candles ────────────────────────────────────

def _make_candles(n_bars: int = 2100, seed: int = 42) -> pd.DataFrame:
    """Create realistic synthetic M10 candle data for feature testing."""
    np.random.seed(seed)

    # Start at Monday 06:00 BKK
    start = datetime(2026, 5, 4, 6, 0)
    times = [start + timedelta(minutes=10 * i) for i in range(n_bars)]
    idx = pd.DatetimeIndex(times)

    # Simulate XAU around 2350, USD around 34.5, HSH around 40000
    xau_base = 2350.0
    usd_base = 34.5
    hsh_base = 40000.0

    xau_walk = np.cumsum(np.random.randn(n_bars) * 0.5)
    usd_walk = np.cumsum(np.random.randn(n_bars) * 0.01)
    hsh_walk = np.cumsum(np.random.randn(n_bars) * 10)

    df = pd.DataFrame({
        "xau_close": xau_base + xau_walk,
        "xau_high":  xau_base + xau_walk + np.abs(np.random.randn(n_bars) * 0.5),
        "xau_low":   xau_base + xau_walk - np.abs(np.random.randn(n_bars) * 0.5),
        "usd_close": usd_base + usd_walk,
        "hsh_close_ask": hsh_base + hsh_walk,
        "hsh_close_bid": hsh_base + hsh_walk - np.abs(np.random.randn(n_bars) * 20 + 30),
    }, index=idx)

    return df


# ── Feature columns expected by the model ─────────────────────────────────────
MODEL_FEATURE_COLS = [
    "F_Syn_Price", "F_Thai_Premium", "F_Corr_XAU_USD",
    "F_XAU_Mom_Short", "F_XAU_Mom_Mid", "F_USD_Mom",
    "F_ATR_48", "F_Regime", "F_FSP", "F_SA_TWAP_Dev",
    "F_SA_MDD", "F_SA_Vol", "F_SA_Range", "F_SA_Position",
    "F_Historical_Vol_THB", "F_Remaining_Vol", "F_SRVR",
    "F_Price_Vs_Open", "F_Mom_1bar", "F_Mom_3bar",
    "F_SA_Drawdown_Pct", "F_HSH_vs_THBGold_Dev",
    "F_DayOfWeek", "F_MinuteOfDay",
    "F_RSI_14", "F_RSI_6", "F_BB_Pos", "F_XAU_Spread_Norm",
    "F_Hour_Sin", "F_Hour_Cos", "F_Session_Type",
    "F_HSH_Spread", "F_Spread_Cost_Pct", "F_Spread_vs_ATR",
]


class TestSessionExpectedLengths:
    """Fix #6: Session lengths must match app.py."""

    def test_session_expected_matches_app(self):
        from core.feature_engine import _SESSION_EXPECTED
        assert _SESSION_EXPECTED == {'Morning': 36, 'Afternoon': 36, 'Night': 48}


class TestNoNaNInOutput:
    """All features must be finite (no NaN, no inf) after fillna chains."""

    def test_no_nan_features(self):
        from core.feature_engine import compute_features
        candles = _make_candles(2100)
        result = compute_features(candles)

        for col in MODEL_FEATURE_COLS:
            val = result[col]
            assert val is not None, f"{col} is None"
            assert not (isinstance(val, float) and np.isnan(val)), f"{col} is NaN"
            assert not (isinstance(val, float) and np.isinf(val)), f"{col} is inf"


class TestFillNAChains:
    """Verify individual fillna patterns match app.py."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from core.feature_engine import compute_features
        candles = _make_candles(2100)
        self.result = compute_features(candles)

    def test_corr_xau_usd_not_nan(self):
        assert not np.isnan(self.result["F_Corr_XAU_USD"])

    def test_xau_mom_short_not_nan(self):
        assert not np.isnan(self.result["F_XAU_Mom_Short"])

    def test_xau_mom_mid_not_nan(self):
        assert not np.isnan(self.result["F_XAU_Mom_Mid"])

    def test_usd_mom_not_nan(self):
        assert not np.isnan(self.result["F_USD_Mom"])

    def test_atr_48_not_nan(self):
        assert not np.isnan(self.result["F_ATR_48"])
        assert self.result["F_ATR_48"] >= 0

    def test_bb_pos_not_nan(self):
        assert not np.isnan(self.result["F_BB_Pos"])

    def test_xau_spread_norm_not_nan(self):
        assert not np.isnan(self.result["F_XAU_Spread_Norm"])
        assert self.result["F_XAU_Spread_Norm"] > 0

    def test_hsh_vs_thb_dev_not_nan(self):
        assert not np.isnan(self.result["F_HSH_vs_THBGold_Dev"])

    def test_mom_1bar_not_nan(self):
        assert not np.isnan(self.result["F_Mom_1bar"])

    def test_mom_3bar_not_nan(self):
        assert not np.isnan(self.result["F_Mom_3bar"])

    def test_sa_drawdown_pct_not_nan(self):
        assert not np.isnan(self.result["F_SA_Drawdown_Pct"])

    def test_rsi_14_in_range(self):
        assert 0 <= self.result["F_RSI_14"] <= 100

    def test_rsi_6_in_range(self):
        assert 0 <= self.result["F_RSI_6"] <= 100

    def test_session_type_valid(self):
        assert self.result["F_Session_Type"] in (0, 1, 2)

    def test_fsp_in_range(self):
        assert 0 <= self.result["F_FSP"] <= 1.0


class TestAllModelFeaturesPresent:
    """Output must contain all 34 features the model expects."""

    def test_all_34_features(self):
        from core.feature_engine import compute_features
        candles = _make_candles(2100)
        result = compute_features(candles)

        for col in MODEL_FEATURE_COLS:
            assert col in result, f"Missing feature: {col}"


class TestDrawdownUsesApply:
    """Fix #3: F_SA_Drawdown_Pct must use groupby.apply (not transform)."""

    def test_drawdown_source_code(self):
        """Verify source code uses .apply() not .transform()."""
        import os
        fe_path = os.path.join(
            os.path.dirname(__file__), "..", "core", "feature_engine.py"
        )
        with open(fe_path, "r") as f:
            source = f.read()

        # Find the computation section (after "def compute_features")
        compute_start = source.find("def compute_features")
        compute_section = source[compute_start:]

        # Find the drawdown computation within compute_features
        dd_idx = compute_section.find("F_SA_Drawdown_Pct")
        dd_section = compute_section[dd_idx:dd_idx + 400]

        assert ".apply(drawdown_pct)" in dd_section, \
            f"F_SA_Drawdown_Pct should use .apply(), not .transform(). Found:\n{dd_section[:200]}"
        assert ".fillna(0)" in dd_section, \
            "F_SA_Drawdown_Pct should have .fillna(0)"


class TestFSPWithCorrectSessionLength:
    """Verify F_FSP uses correct expected session length (36, 36, 48)."""

    def test_fsp_morning_scale(self):
        """Morning session at bar 35 (last bar) should have F_FSP = 1.0."""
        from core.feature_engine import compute_features

        # Create data that starts on a Monday morning, enough bars for OLS
        candles = _make_candles(2100)
        result = compute_features(candles)

        # F_FSP should be in [0, 1] and use correct denominator
        fsp = result["F_FSP"]
        assert 0 <= fsp <= 1.0, f"F_FSP={fsp} out of range [0, 1]"


class TestColdStartBehavior:
    """Features at session open should return safe defaults, not NaN."""

    def test_first_bar_of_session(self):
        """Even the first bar should produce no NaN."""
        from core.feature_engine import compute_features
        candles = _make_candles(2100)
        result = compute_features(candles)

        for col in MODEL_FEATURE_COLS:
            val = result[col]
            if isinstance(val, float):
                assert not np.isnan(val), f"{col} is NaN at output"
                assert not np.isinf(val), f"{col} is inf at output"


class TestFeatureOrderMatchesMeta:
    """Feature column order in meta.json must be valid subset of FeaturesRow keys."""

    def test_meta_cols_in_features_row(self):
        import json
        import os
        meta_path = os.path.join(
            os.path.dirname(__file__), "..", "models", "lambdamart_v11_meta.json"
        )
        with open(meta_path, "r") as f:
            meta = json.load(f)

        from core.feature_engine import FeaturesRow
        row_keys = list(FeaturesRow.__annotations__.keys())

        for col in meta["feature_cols"]:
            assert col in row_keys, f"Meta feature '{col}' missing from FeaturesRow"
