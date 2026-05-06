"""
tests/test_candle_builder.py — Unit tests สำหรับ Phase 1: M10 Candle Builder

รันด้วย:
    pytest tests/test_candle_builder.py -v
"""

import pytest
import pandas as pd
import numpy as np
import pytz
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from config.settings import OLS_WINDOW, TIMEZONE

TZ = pytz.timezone(TIMEZONE)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _make_second_level_ticks(
    n: int = 500,
    start: str = "2026-05-05 09:00:00",
    ask_base: float = 70_000.0,
    bid_base: float = 69_900.0,
    spread_noise: float = 5.0,
    tz: str = "Asia/Bangkok",
) -> pd.DataFrame:
    """สร้าง mock tick data ระดับวินาที"""
    idx = pd.date_range(start=start, periods=n, freq="30s", tz=tz)
    rng = np.random.default_rng(42)
    noise = rng.uniform(-50, 50, n).cumsum()
    df = pd.DataFrame(
        {
            "timestamp": idx.astype(str),
            "ask": ask_base + noise + spread_noise,
            "bid": ask_base + noise,
        }
    )
    return df


def _make_xau_ticks(n: int = 500, start: str = "2026-05-05 09:00:00") -> pd.DataFrame:
    rng = np.random.default_rng(99)
    idx = pd.date_range(start=start, periods=n, freq="30s", tz="Asia/Bangkok")
    base = 2_300.0
    noise = rng.uniform(-5, 5, n).cumsum()
    df = pd.DataFrame(
        {
            "timestamp": idx.astype(str),
            "open": base + noise,
            "high": base + noise + 2,
            "low": base + noise - 2,
            "close": base + noise + 0.5,
            "spread": rng.uniform(0.1, 0.5, n),
        }
    )
    return df


def _make_usd_ticks(n: int = 500, start: str = "2026-05-05 09:00:00") -> pd.DataFrame:
    idx = pd.date_range(start=start, periods=n, freq="30s", tz="Asia/Bangkok")
    df = pd.DataFrame(
        {
            "timestamp": idx.astype(str),
            "close": [35.5 + i * 0.001 for i in range(n)],
        }
    )
    return df


# ─── Tests: _to_m10_candles ───────────────────────────────────────────────────

class TestToM10Candles:
    def test_output_has_correct_columns(self):
        from core.candle_builder import _to_m10_candles

        df = _make_second_level_ticks(600)
        result = _to_m10_candles(
            df,
            ohlcv_cols={
                "ask": {"open": "hsh_open_ask", "high": "hsh_high_ask",
                        "low": "hsh_low_ask", "close": "hsh_close_ask"},
                "bid": {"open": "hsh_open_bid", "high": "hsh_high_bid",
                        "low": "hsh_low_bid", "close": "hsh_close_bid"},
            },
        )
        expected_cols = [
            "hsh_open_ask", "hsh_high_ask", "hsh_low_ask", "hsh_close_ask",
            "hsh_open_bid", "hsh_high_bid", "hsh_low_bid", "hsh_close_bid",
        ]
        for col in expected_cols:
            assert col in result.columns, f"Missing column: {col}"

    def test_m10_bar_count_correct(self):
        """500 ticks at 30s = 250 min → 25 M10 bars"""
        from core.candle_builder import _to_m10_candles

        df = _make_second_level_ticks(500)
        result = _to_m10_candles(
            df,
            ohlcv_cols={
                "ask": {"open": "open_ask", "high": "high_ask",
                        "low": "low_ask", "close": "close_ask"},
            },
        )
        # 500 ticks × 30s = 15000s = 250 min → 25 M10 bars
        assert len(result) == 25, f"Expected 25 bars, got {len(result)}"

    def test_high_geq_low_always(self):
        """high ต้องไม่น้อยกว่า low"""
        from core.candle_builder import _to_m10_candles

        df = _make_second_level_ticks(600)
        result = _to_m10_candles(
            df,
            ohlcv_cols={
                "ask": {"open": "open_ask", "high": "high_ask",
                        "low": "low_ask", "close": "close_ask"},
            },
        )
        assert (result["high_ask"] >= result["low_ask"]).all()

    def test_index_is_monotonic(self):
        from core.candle_builder import _to_m10_candles

        df = _make_second_level_ticks(300)
        result = _to_m10_candles(
            df,
            ohlcv_cols={"ask": {"open": "o", "high": "h", "low": "l", "close": "c"}},
        )
        assert result.index.is_monotonic_increasing

    def test_index_tz_is_bangkok(self):
        from core.candle_builder import _to_m10_candles

        df = _make_second_level_ticks(300)
        result = _to_m10_candles(
            df,
            ohlcv_cols={"ask": {"open": "o", "high": "h", "low": "l", "close": "c"}},
        )
        assert str(result.index.tz) == TIMEZONE


# ─── Tests: _validate ─────────────────────────────────────────────────────────

class TestValidate:
    def _make_valid_candles(self, n: int = OLS_WINDOW + 100) -> pd.DataFrame:
        """สร้าง candles_df ที่ผ่าน validation ทุกข้อ"""
        idx = pd.date_range(
            "2026-01-01 09:00", periods=n, freq="10min", tz=TIMEZONE
        )
        return pd.DataFrame(
            {
                "hsh_open_ask":  70_100.0,
                "hsh_high_ask":  70_200.0,
                "hsh_low_ask":   70_000.0,
                "hsh_close_ask": 70_100.0,
                "hsh_open_bid":  70_000.0,
                "hsh_high_bid":  70_100.0,
                "hsh_low_bid":   69_900.0,
                "hsh_close_bid": 70_000.0,
                "xau_open":      2_300.0,
                "xau_high":      2_305.0,
                "xau_low":       2_295.0,
                "xau_close":     2_302.0,
                "xau_spread":    0.3,
                "usd_close":     35.5,
            },
            index=idx,
        )

    def test_valid_candles_pass(self):
        from core.candle_builder import _validate

        df = self._make_valid_candles()
        _validate(df)  # ไม่ raise

    def test_too_few_bars_raises(self):
        from core.candle_builder import _validate

        df = self._make_valid_candles(n=OLS_WINDOW)  # ขาด 50 bars
        with pytest.raises(ValueError, match="ข้อมูลไม่พอสำหรับ OLS"):
            _validate(df)

    def test_nan_close_ask_raises(self):
        from core.candle_builder import _validate

        df = self._make_valid_candles()
        df.loc[df.index[100], "hsh_close_ask"] = float("nan")
        with pytest.raises(ValueError, match="hsh_close_ask มี NaN"):
            _validate(df)

    def test_ask_leq_bid_raises(self):
        from core.candle_builder import _validate

        df = self._make_valid_candles()
        # ทำให้ ask < bid ที่ bar index 50
        df.loc[df.index[50], "hsh_close_ask"] = 69_990.0  # < bid 70_000
        with pytest.raises(ValueError, match="hsh_close_ask ≤ hsh_close_bid"):
            _validate(df)

    def test_non_monotonic_index_raises(self):
        from core.candle_builder import _validate

        df = self._make_valid_candles()
        # สลับ 2 rows เพื่อทำให้ไม่ monotonic
        idx_list = list(df.index)
        idx_list[100], idx_list[101] = idx_list[101], idx_list[100]
        df.index = idx_list
        with pytest.raises(ValueError, match="monotonic"):
            _validate(df)


# ─── Tests: fetch_latest_bid ─────────────────────────────────────────────────

class TestFetchLatestBid:
    def test_returns_float(self):
        from core.candle_builder import fetch_latest_bid

        mock_resp = MagicMock()
        mock_resp.data = [{"bid": "70000.50"}]
        mock_sb = MagicMock()
        mock_sb.table().select().order().limit().execute.return_value = mock_resp

        with patch("core.candle_builder._get_supabase", return_value=mock_sb):
            result = fetch_latest_bid()

        assert isinstance(result, float)
        assert result == 70000.50

    def test_raises_on_empty_response(self):
        from core.candle_builder import fetch_latest_bid

        mock_resp = MagicMock()
        mock_resp.data = []
        mock_sb = MagicMock()
        mock_sb.table().select().order().limit().execute.return_value = mock_resp

        with patch("core.candle_builder._get_supabase", return_value=mock_sb):
            with pytest.raises((ValueError, Exception)):
                fetch_latest_bid()