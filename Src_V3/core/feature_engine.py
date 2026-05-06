"""
core/feature_engine.py — Phase 2: M10 Feature Engine

Receives candles_df (2200 bars × 14 cols) from Phase 1
→ computes all 34 features across the full DataFrame (vectorized)
→ returns FeaturesRow TypedDict for the latest bar only

Anti-lookahead mechanisms (prevent future data leakage):
  • _safe_pct_change / _safe_diff : zeroed at session boundaries
  • Expanding accumulators (not rolling) for within-session features
  • SESSION_EXPECTED_BARS constant (not actual session length) for FSP
  • Rolling OLS (2016-bar sliding window, past data only) for F_Syn_Price
  • ATR first bar of session uses H-L only (no prev_close from prior session)
"""

from __future__ import annotations

import logging
import math
from typing import TypedDict

import numpy as np
import pandas as pd
import pytz

from config.settings import (
    ATR_WINDOW,
    CONV_FACTOR,
    CORR_WINDOW,
    OLS_WINDOW,
    SESSION_EXPECTED_BARS,
    SESSION_HOURS,
    SPREAD_NORM_WINDOW,
    TIMEZONE,
    VOL_WINDOW,
)

logger = logging.getLogger("trading")
TZ = pytz.timezone(TIMEZONE)

# ─── TypedDict ────────────────────────────────────────────────────────────────

class FeaturesRow(TypedDict):
    # ── Meta (not fed to model) ────────────────────────────────────────────────
    bar_time         : str
    session          : str      # Morning / Afternoon / Night / Closed

    # ── Synthetic ─────────────────────────────────────────────────────────────
    F_Syn_Price      : float
    F_Thai_Premium   : float

    # ── Macro ─────────────────────────────────────────────────────────────────
    F_Corr_XAU_USD   : float
    F_XAU_Mom_Short  : float
    F_XAU_Mom_Mid    : float
    F_USD_Mom        : float
    F_ATR_48         : float
    F_Regime         : int      # +1 uptrend / -1 downtrend

    # ── Session-Aware ─────────────────────────────────────────────────────────
    F_FSP            : float    # [0, 1] fractional session progress
    F_SA_TWAP_Dev    : float
    F_SA_MDD         : float    # ≤ 0
    F_SA_Vol         : float
    F_SA_Range       : float
    F_SA_Position    : float    # [0, 1]
    F_Historical_Vol_THB : float
    F_Remaining_Vol  : float
    F_SRVR           : float
    F_Price_Vs_Open  : float
    F_Mom_1bar       : float
    F_Mom_3bar       : float
    F_SA_Drawdown_Pct: float    # % ≤ 0
    F_HSH_vs_THBGold_Dev : float

    # ── Time ──────────────────────────────────────────────────────────────────
    F_DayOfWeek      : int      # 0=Mon … 4=Fri
    F_MinuteOfDay    : int      # 0 … 1439

    # ── Technical ─────────────────────────────────────────────────────────────
    F_RSI_14         : float
    F_RSI_6          : float
    F_BB_Pos         : float
    F_XAU_Spread_Norm: float
    F_Hour_Sin       : float
    F_Hour_Cos       : float
    F_Session_Type   : int      # 0=Morning / 1=Afternoon / 2=Night / -1=Closed
    F_HSH_Spread     : float
    F_Spread_Cost_Pct: float
    F_Spread_vs_ATR  : float

    # ── Pass-through (not fed to model) ───────────────────────────────────────
    hsh_close_ask    : float
    hsh_close_bid    : float
    xau_close        : float
    usd_close        : float


# ─── Session Helpers ──────────────────────────────────────────────────────────

_SESSION_TYPE_MAP: dict[str, int] = {
    "Morning": 0, "Afternoon": 1, "Night": 2, "Closed": -1
}


def assign_session(bar_time) -> str:
    """Return session name for a given bar timestamp (public — used by Phase 4/7)."""
    minutes = bar_time.hour * 60 + bar_time.minute
    for name, (start, end) in SESSION_HOURS.items():
        if start <= minutes < end:
            return name
    return "Closed"


def _build_session_meta(index: pd.DatetimeIndex) -> tuple[pd.Series, pd.Series]:
    """
    Build session labels and unique session IDs for the entire index.

    Returns
    -------
    session_name : pd.Series[str]  — "Morning" / "Afternoon" / "Night" / "Closed"
    session_id   : pd.Series[int]  — increments every time session name changes
                                      (each continuous block gets its own ID)
    """
    session_name = pd.Series(
        [assign_session(ts) for ts in index],
        index=index,
        dtype=object,
    )
    session_id = (session_name != session_name.shift()).cumsum().astype(int)
    return session_name, session_id


# ─── Anti-Lookahead Helpers ───────────────────────────────────────────────────

def _safe_pct_change(
    series: pd.Series, periods: int, session_id: pd.Series
) -> pd.Series:
    """
    Percentage change zeroed at session boundaries.
    For periods > 1, zeroes out if ANY bar in the lookback crossed a session boundary
    (i.e. session_id at current bar ≠ session_id `periods` bars ago).
    """
    result = series.pct_change(periods)
    crossed = session_id != session_id.shift(periods)
    result[crossed] = 0.0
    return result.fillna(0.0)


def _safe_diff(
    series: pd.Series, periods: int, session_id: pd.Series
) -> pd.Series:
    """Absolute diff zeroed at session boundaries (used for RSI gain/loss)."""
    result = series.diff(periods)
    crossed = session_id != session_id.shift(periods)
    result[crossed] = 0.0
    return result.fillna(0.0)


# ─── Core Calculation Helpers ─────────────────────────────────────────────────

def _rolling_ols_predict(y: pd.Series, x: pd.Series, window: int) -> pd.Series:
    """
    Vectorized rolling OLS: returns fitted value = slope × x + intercept
    for each bar, using only the past `window` observations.

    Anti-lookahead: rolling window is left-aligned (past data only).
    Cold start: first (window-1) bars return NaN — these are trimmed by
    candle_builder ensuring LOOKBACK_BARS >> OLS_WINDOW.
    """
    df_ols = pd.DataFrame({
        "y":  y,
        "x":  x,
        "x2": x * x,
        "xy": x * y,
    })
    roll = df_ols.rolling(window=window, min_periods=window)

    n      = window
    sum_x  = roll["x"].sum()
    sum_y  = roll["y"].sum()
    sum_x2 = roll["x2"].sum()
    sum_xy = roll["xy"].sum()

    denom     = (n * sum_x2 - sum_x ** 2).replace(0, np.nan)
    slope     = (n * sum_xy - sum_x * sum_y) / denom
    intercept = (sum_y - slope * sum_x) / n

    return slope * x + intercept


def _atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    window: int,
    session_id: pd.Series,
) -> pd.Series:
    """
    Average True Range with session-boundary correction:
      - Normal bars : TR = max(H-L, |H-PrevClose|, |L-PrevClose|)
      - Session-start bars : TR = H-L  (no valid prev_close from prior session)
    """
    prev_close = close.shift(1)
    boundary   = session_id != session_id.shift(1)

    hl  = high - low
    hpc = (high - prev_close).abs()
    lpc = (low  - prev_close).abs()

    tr = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
    tr[boundary] = hl[boundary]  # overwrite boundary bars

    return tr.rolling(window, min_periods=window).mean()


def _rsi(
    series: pd.Series, period: int, session_id: pd.Series
) -> pd.Series:
    """
    RSI using Wilder's smoothing (EWM alpha = 1/period).
    Gains/losses computed via _safe_diff → zeroed at session boundaries.
    Cold-start bars filled with 50.0 (neutral).
    """
    delta    = _safe_diff(series, 1, session_id)
    gain     = delta.clip(lower=0.0)
    loss     = (-delta).clip(lower=0.0)

    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    rs  = avg_gain / avg_loss.replace(0.0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + rs)
    return rsi.fillna(50.0)


# ─── Main Public Function ─────────────────────────────────────────────────────

def compute_features(candles_df: pd.DataFrame) -> FeaturesRow:
    """
    Compute all 34 model features + pass-through fields from candles_df.

    Parameters
    ----------
    candles_df : pd.DataFrame
        Output of build_m10_candles() — 2200 bars, DatetimeIndex (Asia/Bangkok)

    Returns
    -------
    FeaturesRow
        All features for the latest (most recent) bar.

    Raises
    ------
    ValueError — NaN found in critical features for the latest bar
    """
    df = candles_df.copy()

    # ── 0. Session labels ─────────────────────────────────────────────────────
    session_name, session_id = _build_session_meta(df.index)
    df["_session"]    = session_name
    df["_session_id"] = session_id

    price    = df["hsh_close_ask"]
    # Theoretical THB price: XAU(USD/oz) × conv_factor × USD/THB → THB/บาทไทย
    x_theory = df["xau_close"] * CONV_FACTOR * df["usd_close"]

    # ── 1. F_Syn_Price — Rolling OLS (2016 bars, past-only) ──────────────────
    # Fits  hsh_close_ask ~ β₀ + β₁ × x_theory  on a sliding 2016-bar window
    df["F_Syn_Price"]    = _rolling_ols_predict(price, x_theory, OLS_WINDOW)
    df["F_Thai_Premium"] = price - df["F_Syn_Price"]

    # ── 2. F_Corr_XAU_USD — Rolling correlation XAU vs USD returns ───────────
    xau_ret = _safe_pct_change(df["xau_close"], 1, session_id)
    usd_ret = _safe_pct_change(df["usd_close"], 1, session_id)

    df["F_Corr_XAU_USD"] = (
        xau_ret
        .rolling(CORR_WINDOW, min_periods=CORR_WINDOW)
        .corr(usd_ret)
        .fillna(0.0)
    )

    # ── 3. Momentum features ──────────────────────────────────────────────────
    df["F_XAU_Mom_Short"] = _safe_pct_change(df["xau_close"], 3,  session_id)
    df["F_XAU_Mom_Mid"]   = _safe_pct_change(df["xau_close"], 12, session_id)
    df["F_USD_Mom"]       = _safe_pct_change(df["usd_close"], 6,  session_id)

    # ── 4. F_ATR_48 — 8-hour ATR of HSH ask prices ───────────────────────────
    df["F_ATR_48"] = _atr(
        df["hsh_high_ask"],
        df["hsh_low_ask"],
        df["hsh_close_ask"],
        ATR_WINDOW,
        session_id,
    )

    # ── 5. F_Regime — EMA20 vs EMA50 crossover ───────────────────────────────
    ema20 = price.ewm(span=20, adjust=False).mean()
    ema50 = price.ewm(span=50, adjust=False).mean()
    df["F_Regime"] = np.sign(ema20 - ema50).astype(int)
    # Replace 0 (flat) with -1 (treat as downtrend / no signal)
    df["F_Regime"] = df["F_Regime"].replace(0, -1)

    # ── 6. Session-Aware Features (expanding within each session block) ───────
    grp = df.groupby("_session_id", group_keys=False)

    # Bar index within session (0-based)
    df["_bar_in_session"] = grp.cumcount()

    # Session open price = first hsh_close_ask of each session block
    df["_session_open"] = grp["hsh_close_ask"].transform("first")

    # Expanding within-session statistics (anti-lookahead: no future bars used)
    df["_sa_mean"] = grp["hsh_close_ask"].transform(lambda x: x.expanding().mean())
    df["_sa_max"]  = grp["hsh_close_ask"].transform(lambda x: x.expanding().max())
    df["_sa_min"]  = grp["hsh_close_ask"].transform(lambda x: x.expanding().min())
    df["_sa_std"]  = grp["hsh_close_ask"].transform(lambda x: x.expanding().std())

    # F_FSP: uses SESSION_EXPECTED_BARS constant, NOT actual session length
    # (actual length is only known at session end → lookahead if used)
    expected_bars = df["_session"].map(SESSION_EXPECTED_BARS)
    df["F_FSP"] = (
        df["_bar_in_session"] / (expected_bars - 1)
    ).clip(0.0, 1.0).fillna(0.0)
    # Closed-session bars have no SESSION_EXPECTED_BARS → FSP = 0
    df.loc[df["_session"] == "Closed", "F_FSP"] = 0.0

    df["F_SA_TWAP_Dev"]  = price - df["_sa_mean"]
    df["F_SA_MDD"]       = price - df["_sa_max"]        # ≤ 0

    df["F_SA_Vol"]       = df["_sa_std"].fillna(0.0)

    sa_range = (df["_sa_max"] - df["_sa_min"]).fillna(0.0)
    df["F_SA_Range"] = sa_range
    df["F_SA_Position"] = (
        (price - df["_sa_min"]) / sa_range.replace(0.0, np.nan)
    ).clip(0.0, 1.0).fillna(0.5)  # 0.5 = mid when range is 0 (first bar)

    df["F_Price_Vs_Open"] = (
        (price - df["_session_open"]) / df["_session_open"].replace(0.0, np.nan)
    ).fillna(0.0)

    df["F_SA_Drawdown_Pct"] = (
        (price - df["_sa_max"]) / df["_sa_max"].replace(0.0, np.nan)
    ).fillna(0.0)

    # ── 7. Historical & Remaining Volatility ──────────────────────────────────
    # Convert XAU return std → THB/บาทไทย units (same as P&L currency)
    xau_ret_std = xau_ret.rolling(VOL_WINDOW, min_periods=VOL_WINDOW).std()
    df["F_Historical_Vol_THB"] = (
        xau_ret_std * df["xau_close"] * CONV_FACTOR * df["usd_close"]
    ).fillna(0.0)

    df["F_Remaining_Vol"] = df["F_Historical_Vol_THB"] * (1.0 - df["F_FSP"])

    df["F_SRVR"] = (
        df["F_Remaining_Vol"] / df["F_ATR_48"].replace(0.0, np.nan)
    ).fillna(0.0)

    # ── 8. HSH vs THB-Gold Deviation (6-bar rolling mean of return spread) ────
    thb_gold_ret = _safe_pct_change(df["xau_close"] * df["usd_close"], 1, session_id)
    hsh_ret      = _safe_pct_change(price, 1, session_id)
    df["F_HSH_vs_THBGold_Dev"] = (
        (hsh_ret - thb_gold_ret).rolling(6, min_periods=1).mean()
    )

    # ── 9. HSH Short Momentum (safe, within-session) ──────────────────────────
    df["F_Mom_1bar"] = _safe_pct_change(price, 1, session_id)
    df["F_Mom_3bar"] = _safe_pct_change(price, 3, session_id)

    # ── 10. Time Features ─────────────────────────────────────────────────────
    df["F_DayOfWeek"]   = df.index.dayofweek.astype(int)        # 0=Mon … 4=Fri
    df["F_MinuteOfDay"] = (df.index.hour * 60 + df.index.minute).astype(int)

    hour_frac        = df.index.hour + df.index.minute / 60.0
    df["F_Hour_Sin"] = np.sin(2.0 * np.pi * hour_frac / 24.0)
    df["F_Hour_Cos"] = np.cos(2.0 * np.pi * hour_frac / 24.0)

    df["F_Session_Type"] = (
        df["_session"].map(_SESSION_TYPE_MAP).fillna(-1).astype(int)
    )

    # ── 11. Technical: RSI ────────────────────────────────────────────────────
    df["F_RSI_14"] = _rsi(price, 14, session_id)
    df["F_RSI_6"]  = _rsi(price, 6,  session_id)

    # ── 12. Bollinger Band Position (20-bar, global rolling) ─────────────────
    bb_mid = price.rolling(20, min_periods=20).mean()
    bb_std = price.rolling(20, min_periods=20).std()
    df["F_BB_Pos"] = (
        (price - bb_mid) / (2.0 * bb_std.replace(0.0, np.nan))
    ).fillna(0.0)

    # ── 13. XAU Spread Normalised (144-bar rolling) ───────────────────────────
    xau_spread_mean = (
        df["xau_spread"]
        .rolling(SPREAD_NORM_WINDOW, min_periods=SPREAD_NORM_WINDOW)
        .mean()
    )
    df["F_XAU_Spread_Norm"] = (
        df["xau_spread"] / xau_spread_mean.replace(0.0, np.nan)
    ).fillna(1.0)  # default = 1.0 (normal) during cold start

    # ── 14. HSH Spread Features ───────────────────────────────────────────────
    df["F_HSH_Spread"]      = df["hsh_close_ask"] - df["hsh_close_bid"]
    df["F_Spread_Cost_Pct"] = (
        df["F_HSH_Spread"] / df["hsh_close_ask"].replace(0.0, np.nan)
    ).fillna(0.0)
    df["F_Spread_vs_ATR"] = (
        df["F_HSH_Spread"] / df["F_ATR_48"].replace(0.0, np.nan)
    ).fillna(0.0)

    # ── 15. Extract latest bar and build FeaturesRow ──────────────────────────
    latest = df.iloc[-1]

    features: FeaturesRow = {
        # Meta
        "bar_time" : latest.name.isoformat(),
        "session"  : str(latest["_session"]),
        # Synthetic
        "F_Syn_Price"    : float(latest["F_Syn_Price"]),
        "F_Thai_Premium" : float(latest["F_Thai_Premium"]),
        # Macro
        "F_Corr_XAU_USD"  : float(latest["F_Corr_XAU_USD"]),
        "F_XAU_Mom_Short"  : float(latest["F_XAU_Mom_Short"]),
        "F_XAU_Mom_Mid"    : float(latest["F_XAU_Mom_Mid"]),
        "F_USD_Mom"        : float(latest["F_USD_Mom"]),
        "F_ATR_48"         : float(latest["F_ATR_48"]),
        "F_Regime"         : int(latest["F_Regime"]),
        # Session
        "F_FSP"             : float(latest["F_FSP"]),
        "F_SA_TWAP_Dev"     : float(latest["F_SA_TWAP_Dev"]),
        "F_SA_MDD"          : float(latest["F_SA_MDD"]),
        "F_SA_Vol"          : float(latest["F_SA_Vol"]),
        "F_SA_Range"        : float(latest["F_SA_Range"]),
        "F_SA_Position"     : float(latest["F_SA_Position"]),
        "F_Historical_Vol_THB": float(latest["F_Historical_Vol_THB"]),
        "F_Remaining_Vol"   : float(latest["F_Remaining_Vol"]),
        "F_SRVR"            : float(latest["F_SRVR"]),
        "F_Price_Vs_Open"   : float(latest["F_Price_Vs_Open"]),
        "F_Mom_1bar"        : float(latest["F_Mom_1bar"]),
        "F_Mom_3bar"        : float(latest["F_Mom_3bar"]),
        "F_SA_Drawdown_Pct" : float(latest["F_SA_Drawdown_Pct"]),
        "F_HSH_vs_THBGold_Dev": float(latest["F_HSH_vs_THBGold_Dev"]),
        # Time
        "F_DayOfWeek"   : int(latest["F_DayOfWeek"]),
        "F_MinuteOfDay" : int(latest["F_MinuteOfDay"]),
        # Technical
        "F_RSI_14"        : float(latest["F_RSI_14"]),
        "F_RSI_6"         : float(latest["F_RSI_6"]),
        "F_BB_Pos"        : float(latest["F_BB_Pos"]),
        "F_XAU_Spread_Norm": float(latest["F_XAU_Spread_Norm"]),
        "F_Hour_Sin"      : float(latest["F_Hour_Sin"]),
        "F_Hour_Cos"      : float(latest["F_Hour_Cos"]),
        "F_Session_Type"  : int(latest["F_Session_Type"]),
        "F_HSH_Spread"    : float(latest["F_HSH_Spread"]),
        "F_Spread_Cost_Pct": float(latest["F_Spread_Cost_Pct"]),
        "F_Spread_vs_ATR" : float(latest["F_Spread_vs_ATR"]),
        # Pass-through
        "hsh_close_ask" : float(latest["hsh_close_ask"]),
        "hsh_close_bid" : float(latest["hsh_close_bid"]),
        "xau_close"     : float(latest["xau_close"]),
        "usd_close"     : float(latest["usd_close"]),
    }

    _validate_features(features)

    logger.info(
        f"[feature_engine] ✅ bar={features['bar_time']} | "
        f"session={features['session']} | "
        f"ATR={features['F_ATR_48']:.2f} | "
        f"RSI14={features['F_RSI_14']:.1f} | "
        f"SRVR={features['F_SRVR']:.3f}"
    )
    return features


# ─── Validation ───────────────────────────────────────────────────────────────

_CRITICAL_FEATURES = [
    "F_Syn_Price", "F_Thai_Premium",
    "F_ATR_48", "F_RSI_14", "F_RSI_6", "F_BB_Pos",
    "F_SRVR", "F_FSP",
    "hsh_close_ask", "hsh_close_bid",
]


def _validate_features(features: FeaturesRow) -> None:
    """Raise ValueError if any critical feature is NaN or missing."""
    nan_cols = [
        k for k in _CRITICAL_FEATURES
        if features.get(k) is None or (
            isinstance(features[k], float) and math.isnan(features[k])
        )
    ]
    if nan_cols:
        raise ValueError(
            f"[feature_engine] NaN in critical features: {nan_cols} "
            f"— bar {features.get('bar_time')}"
        )