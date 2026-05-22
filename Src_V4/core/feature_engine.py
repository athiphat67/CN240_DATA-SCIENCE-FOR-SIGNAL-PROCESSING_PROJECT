# core/feature_engine.py
# ⚠️  ซิงค์กับ app.py (source of truth) — ห้ามแก้สูตรโดยไม่อัปเดต training ด้วย
#
# CHANGELOG (fixed vs เวอร์ชันก่อน):
#
#   [FIX-1] _HIST_VOL_WEIGHT: กลับไปใช้ (15.244/31.1035) ไม่รวม purity
#           เดิม: _HIST_VOL_WEIGHT = CONV_FACTOR  ≈ 0.4744  ← รวม purity ← ผิด
#           ใหม่: _HIST_VOL_WEIGHT = 15.244 / 31.1035  ≈ 0.4901 ← ตรงกับ app.py
#           app.py บรรทัด 164:
#             df['F_Historical_Vol_THB'] = hist_vol_xau * (15.244/31.1035) * df['USD_Close']
#           หมายเหตุ: F_Syn_Price ยังคงใช้ CONV_FACTOR (รวม purity) ถูกต้องอยู่
#
#   [FIX-2] Session ID format: ใช้ "YYYY-MM-DD_Session" (คงไว้จาก version ก่อน ✓)
#
#   [FIX-3] RSI: ใช้ .diff() ปกติ (คงไว้จาก version ก่อน ✓)
#
#   [FIX-4] F_Mom_1bar / F_Mom_3bar: เปลี่ยนจาก _safe_pct_change() เป็น .pct_change() ปกติ
#           app.py บรรทัด 171-172:
#             df['F_Mom_3bar'] = df['HSH_Sell_Sim'].pct_change(3).fillna(0)
#             df['F_Mom_1bar'] = df['HSH_Sell_Sim'].pct_change(1).fillna(0)
#           ไม่มี session boundary reset ใน app.py สำหรับ features เหล่านี้
#
#   [FIX-5] F_ATR_48: ลบ session boundary fix ออก ตรงกับ app.py
#           app.py บรรทัด 123-128 ไม่มี boundary reset บน h_pc/l_pc
#           feature_engine เดิมมี crosses_boundary correction ← ไม่ตรง training
#
#   [FIX-6] compute_features(): รับ full candles (ไม่ถูก filter session มาแล้ว)
#           compute features บน full dataset → filter session → extract bar ล่าสุด
#           แก้ปัญหา rolling window ไม่มี warm-up data ช่วงต้น session
#           (Root Cause 1 ตาม diagram)
#
# ─────────────────────────────────────────────────────────────────────────────

import pandas as pd
import numpy as np
import logging
from typing import TypedDict
from config.settings import (
    OLS_WINDOW,
    ATR_WINDOW,
    CORR_WINDOW,
    VOL_WINDOW,
    CONV_FACTOR,
    SESSION_HOURS,
    SESSION_EXPECTED_BARS,
    SPREAD_NORM_WINDOW,
)

logger = logging.getLogger("system")

# ── Constants ─────────────────────────────────────────────────────────────────

# [FIX-1] ใช้ 15.244/31.1035 ตรงกับ app.py บรรทัด 164 (ไม่รวม purity)
# app.py: hist_vol_xau * (15.244/31.1035) * df['USD_Close']
# Note: F_Syn_Price ยังคงใช้ CONV_FACTOR=(15.244/31.1035)*(0.965/0.995) ≈ 0.4744
_HIST_VOL_WEIGHT = 15.244 / 31.1035  # ≈ 0.4901  (ไม่รวม purity — ตรงกับ app.py)

# Expected session lengths (ตรงกับ app.py + SESSION_EXPECTED_BARS ใน config)
_SESSION_EXPECTED = SESSION_EXPECTED_BARS  # Morning=36, Afternoon=36, Night=48


# ─────────────────────────────────────────────────────────────────────────────
# TypedDict
# ─────────────────────────────────────────────────────────────────────────────


class FeaturesRow(TypedDict):
    # ─── Meta ──────────────────────────────────────────────────────────────────
    bar_time: str
    session: str
    # ─── Synthetic ─────────────────────────────────────────────────────────────
    F_Syn_Price: float
    F_Thai_Premium: float
    # ─── Macro ─────────────────────────────────────────────────────────────────
    F_Corr_XAU_USD: float
    F_XAU_Mom_Short: float
    F_XAU_Mom_Mid: float
    F_USD_Mom: float
    F_ATR_48: float
    F_Regime: int
    # ─── Session ───────────────────────────────────────────────────────────────
    F_FSP: float
    F_SA_TWAP_Dev: float
    F_SA_MDD: float
    F_SA_Vol: float
    F_SA_Range: float
    F_SA_Position: float
    F_Historical_Vol_THB: float
    F_Remaining_Vol: float
    F_SRVR: float
    F_Price_Vs_Open: float
    F_Mom_1bar: float
    F_Mom_3bar: float
    F_SA_Drawdown_Pct: float
    F_HSH_vs_THBGold_Dev: float
    # ─── Time ──────────────────────────────────────────────────────────────────
    F_DayOfWeek: int
    F_MinuteOfDay: int
    # ─── Technical ─────────────────────────────────────────────────────────────
    F_RSI_14: float
    F_RSI_6: float
    F_BB_Pos: float
    F_XAU_Spread_Norm: float
    F_Hour_Sin: float
    F_Hour_Cos: float
    F_Session_Type: int
    F_HSH_Spread: float
    F_Spread_Cost_Pct: float
    F_Spread_vs_ATR: float
    # ─── Pass-through (ไม่เข้า model) ──────────────────────────────────────────
    hsh_close_ask: float
    hsh_close_bid: float
    xau_close: float
    usd_close: float


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _assign_session(dt_idx: pd.DatetimeIndex) -> pd.Series:
    """ระบุ Session name ให้แต่ละแท่ง รองรับข้ามเที่ยงคืน (Night: 18:00-01:59)"""
    mins = dt_idx.hour * 60 + dt_idx.minute
    result = pd.Series("Closed", index=dt_idx)
    for name, (start, end) in SESSION_HOURS.items():
        if start < end:
            result[(mins >= start) & (mins < end)] = name
        else:
            result[(mins >= start) | (mins < end)] = name
    return result


def _assign_session_id(
    dt_idx: pd.DatetimeIndex, session_series: pd.Series
) -> pd.Series:
    """
    [FIX-2] สร้าง session_id แบบ "YYYY-MM-DD_Morning" ให้ตรงกับ app.py

    app.py:
        def assign_session(dt):
            if 6 <= h < 12:    return f"{dt.date()}_Morning"
            elif 12 <= h < 18: return f"{dt.date()}_Afternoon"
            else:
                base = dt.date() if h >= 18 else (dt - Timedelta(days=1)).date()
                return f"{base}_Night"
    """
    h = dt_idx.hour

    # base date: Night ช่วง 00:00-01:59 ต้องใช้วันก่อนหน้า
    before_midnight = (h >= 0) & (h < 2)  # 00:00–01:59
    base_dates = np.where(
        before_midnight,
        pd.DatetimeIndex(dt_idx) - pd.Timedelta(days=1),
        pd.DatetimeIndex(dt_idx),
    )
    base_date_str = pd.Series(
        [
            str(d.date()) if hasattr(d, "date") else str(pd.Timestamp(d).date())
            for d in base_dates
        ],
        index=dt_idx,
    )

    return base_date_str + "_" + session_series


def _safe_pct_change(
    series: pd.Series, session_id: pd.Series, periods: int = 1
) -> pd.Series:
    """คำนวณ % Change โดยรีเซ็ตค่าที่ขอบ Session (ใช้เฉพาะ features ที่ต้องการ boundary reset)"""
    ret = series.pct_change(periods)
    crosses = session_id != session_id.shift(periods)
    ret[crosses] = 0.0
    return ret


def _rolling_ols_numpy(x_arr: np.ndarray, y_arr: np.ndarray, window: int):
    """
    Rolling OLS ด้วย numpy sliding_window_view
    ตรงกับ compute_rolling_synthetic() ใน app.py ทุกประการ
    """
    n = len(x_arr)
    slopes = np.full(n, np.nan)
    intercepts = np.full(n, np.nan)

    if n < window:
        return slopes, intercepts

    win_x = np.lib.stride_tricks.sliding_window_view(x_arr, window)
    win_y = np.lib.stride_tricks.sliding_window_view(y_arr, window)

    sum_x = win_x.sum(axis=1)
    sum_y = win_y.sum(axis=1)
    sum_xx = (win_x * win_x).sum(axis=1)
    sum_xy = (win_x * win_y).sum(axis=1)

    denom = window * sum_xx - sum_x**2
    safe = denom != 0

    b = np.where(
        safe, (window * sum_xy - sum_x * sum_y) / np.where(safe, denom, 1), np.nan
    )
    a = np.where(safe, (sum_y - b * sum_x) / window, np.nan)

    slopes[window - 1 :] = b
    intercepts[window - 1 :] = a
    return slopes, intercepts


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────


def compute_features(candles_df: pd.DataFrame) -> FeaturesRow:
    """
    [FIXED] คำนวณ 34 Features โดยเลียนแบบ Logic ของ app.py 100%
    - ใช้ groupby().apply() สำหรับ Session Features เพื่อความแม่นยำของ expanding()
    - ลบ Manual Boundary Reset ใน ATR ออกเพื่อให้ตรงกับ Training
    """
    df = candles_df.copy()

    _MIN_BARS = 20
    if len(df) < _MIN_BARS:
        raise ValueError(f"[P2] ข้อมูลไม่พอสำหรับ OLS Cold Start (need ≥{_MIN_BARS}, got {len(df)})")

    # Use a smaller OLS window during cold start (new DB / fresh migration).
    # Full OLS_WINDOW resumes automatically once enough bars accumulate.
    _actual_ols = min(OLS_WINDOW, max(_MIN_BARS, len(df) - 10))
    if _actual_ols < OLS_WINDOW:
        logger.warning(
            f"[P2] Cold start: OLS_WINDOW={_actual_ols} (target={OLS_WINDOW}, bars={len(df)})"
        )

    # 1. Session IDs
    df["session"] = _assign_session(df.index)
    df["session_id"] = _assign_session_id(df.index, df["session"])

    # 2. Synthetic & Premium (CONV_FACTOR จาก settings.py)
    x_arr = (df["xau_close"] * CONV_FACTOR * df["usd_close"]).values
    y_arr = df["hsh_close_ask"].values
    slopes, intercepts = _rolling_ols_numpy(x_arr, y_arr, _actual_ols)
    df["F_Syn_Price"] = slopes * x_arr + intercepts
    df["F_Thai_Premium"] = df["hsh_close_ask"] - df["F_Syn_Price"]
    df["F_Syn_Price"] = df["F_Syn_Price"].ffill().fillna(0)
    df["F_Thai_Premium"] = df["F_Thai_Premium"].ffill().fillna(0)

    # 3. Macro Features (No boundary reset ตาม app.py)
    xau_ret = df["xau_close"].pct_change()
    usd_ret = df["usd_close"].pct_change()
    df["F_Corr_XAU_USD"] = xau_ret.rolling(CORR_WINDOW).corr(usd_ret).ffill().fillna(0)
    df["F_XAU_Mom_Short"] = df["xau_close"].pct_change(3).fillna(0)
    df["F_XAU_Mom_Mid"] = df["xau_close"].pct_change(12).fillna(0)
    df["F_USD_Mom"] = df["usd_close"].pct_change(6).fillna(0)

    # ATR 48 (ไม่มี boundary reset บน h_pc/l_pc ตาม app.py บรรทัดที่ 123)
    prev_close = df["xau_close"].shift(1)
    tr = pd.concat(
        [
            df["xau_high"] - df["xau_low"],
            (df["xau_high"] - prev_close).abs(),
            (df["xau_low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["F_ATR_48"] = tr.rolling(ATR_WINDOW).mean().ffill().fillna(0)

    # Regime
    df["F_Regime"] = np.sign(
        df["xau_close"].ewm(span=20).mean() - df["xau_close"].ewm(span=50).mean()
    ).astype(int)

    # 4. Session-Aware Features (ปรับมาใช้ apply() เพื่อแก้ปัญหา expanding() bleed)
    df["Expected_Session_Length"] = df["session"].map(_SESSION_EXPECTED).fillna(36)

    def calc_session_group(group):
        prices = group["hsh_close_ask"]
        exp_len = group["Expected_Session_Length"].iloc[0]

        # Bar in session & FSP
        bar_idx = np.arange(len(group))
        group["F_FSP"] = (bar_idx / max(exp_len - 1, 1)).clip(0, 1.0)

        # Expanding Metrics
        group["F_SA_TWAP_Dev"] = prices - prices.expanding().mean()
        group["F_SA_MDD"] = prices - prices.expanding().max()
        group["F_SA_Vol"] = prices.expanding().std().fillna(0)

        s_max = prices.expanding().max()
        s_min = prices.expanding().min()
        group["F_SA_Range"] = s_max - s_min
        group["F_SA_Position"] = (prices - s_min) / (
            group["F_SA_Range"].replace(0, 1e-9)
        )

        # Drawdown Pct (Sync with BUG-6 fix)
        group["F_SA_Drawdown_Pct"] = (prices - s_max) / (s_max + 1e-9)

        # Price vs Open
        group["F_Price_Vs_Open"] = (prices - prices.iloc[0]) / (prices.iloc[0] + 1e-9)
        return group

    df = df.groupby("session_id", group_keys=False).apply(calc_session_group)

    # Volatility Metrics
    hist_vol_xau = (
        df["xau_close"].pct_change().rolling(VOL_WINDOW).std() * df["xau_close"]
    )
    df["F_Historical_Vol_THB"] = (hist_vol_xau * _HIST_VOL_WEIGHT * df["usd_close"]).ffill().fillna(0)
    df["F_Remaining_Vol"] = (df["F_Historical_Vol_THB"] * (1.0 - df["F_FSP"])).ffill().fillna(0)
    df["F_SRVR"] = (df["F_Remaining_Vol"] / df["F_ATR_48"].replace(0, 1e-9)).ffill().fillna(0)

    # Momentum (No boundary reset)
    df["F_Mom_1bar"] = df["hsh_close_ask"].pct_change(1).fillna(0)
    df["F_Mom_3bar"] = df["hsh_close_ask"].pct_change(3).fillna(0)

    # Dev vs Global
    thb_gold_ret = (df["xau_close"] * df["usd_close"]).pct_change()
    hsh_ret = df["hsh_close_ask"].pct_change()
    df["F_HSH_vs_THBGold_Dev"] = (hsh_ret - thb_gold_ret).rolling(6).mean().fillna(0)

    # 5. Technical & Time
    def _calc_rsi(series, period):
        delta = series.diff()
        gain = delta.where(delta > 0, 0.0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
        return (100 - (100 / (1 + gain / loss.replace(0, np.nan)))).ffill().fillna(50)

    df["F_RSI_14"] = _calc_rsi(df["hsh_close_ask"], 14)
    df["F_RSI_6"] = _calc_rsi(df["hsh_close_ask"], 6)

    bb_mid = df["hsh_close_ask"].rolling(20).mean()
    bb_std = df["hsh_close_ask"].rolling(20).std()
    df["F_BB_Pos"] = (
        (df["hsh_close_ask"] - bb_mid) / (2 * bb_std.replace(0, 1e-9))
    ).fillna(0)

    xau_spread = (df["xau_high"] - df["xau_low"]).replace(0, np.nan).ffill().fillna(0.5)
    df["F_XAU_Spread_Norm"] = (
        (
            xau_spread
            / xau_spread.rolling(SPREAD_NORM_WINDOW, min_periods=1)
            .mean()
            .replace(0, 1e-9)
        )
        .ffill()
        .fillna(1)
    )

    hour_dec = df.index.hour + df.index.minute / 60
    df["F_Hour_Sin"] = np.sin(2 * np.pi * hour_dec / 24)
    df["F_Hour_Cos"] = np.cos(2 * np.pi * hour_dec / 24)
    df["F_Session_Type"] = (
        df["session"]
        .map({"Morning": 0, "Afternoon": 1, "Night": 2})
        .fillna(0)
        .astype(int)
    )

    # Diagnostic Spreads
    hsh_spread = df["hsh_close_ask"] - df["hsh_close_bid"]
    df["F_HSH_Spread"] = hsh_spread
    df["F_Spread_Cost_Pct"] = hsh_spread / df["hsh_close_ask"]
    df["F_Spread_vs_ATR"] = hsh_spread / df["F_ATR_48"].replace(0, 1e-9)

    # 6. Final Filter
    latest = df[df["session"] != "Closed"].iloc[-1]

    # [FIXED] ให้ Pandas จัดการ Timezone ISO Format โดยตรง (เลียนแบบ app.py)
    # ไม่ต้องจับลบ 7 ชั่วโมงและไม่ต้องต่อ string "+00:00" เอง
    bar_ts = latest.name
    bar_time_iso = bar_ts.isoformat()

    return FeaturesRow(
        bar_time=bar_time_iso,
        session=str(latest["session"]),
        F_Syn_Price=float(latest["F_Syn_Price"]),
        F_Thai_Premium=float(latest["F_Thai_Premium"]),
        F_Corr_XAU_USD=float(latest["F_Corr_XAU_USD"]),
        F_XAU_Mom_Short=float(latest["F_XAU_Mom_Short"]),
        F_XAU_Mom_Mid=float(latest["F_XAU_Mom_Mid"]),
        F_USD_Mom=float(latest["F_USD_Mom"]),
        F_ATR_48=float(latest["F_ATR_48"]),
        F_Regime=int(latest["F_Regime"]),
        F_FSP=float(latest["F_FSP"]),
        F_SA_TWAP_Dev=float(latest["F_SA_TWAP_Dev"]),
        F_SA_MDD=float(latest["F_SA_MDD"]),
        F_SA_Vol=float(latest["F_SA_Vol"]),
        F_SA_Range=float(latest["F_SA_Range"]),
        F_SA_Position=float(latest["F_SA_Position"]),
        F_Historical_Vol_THB=float(latest["F_Historical_Vol_THB"]),
        F_Remaining_Vol=float(latest["F_Remaining_Vol"]),
        F_SRVR=float(latest["F_SRVR"]),
        F_Price_Vs_Open=float(latest["F_Price_Vs_Open"]),
        F_Mom_1bar=float(latest["F_Mom_1bar"]),
        F_Mom_3bar=float(latest["F_Mom_3bar"]),
        F_SA_Drawdown_Pct=float(latest["F_SA_Drawdown_Pct"]),
        F_HSH_vs_THBGold_Dev=float(latest["F_HSH_vs_THBGold_Dev"]),
        F_DayOfWeek=int(latest.name.dayofweek),
        F_MinuteOfDay=int(latest.name.hour * 60 + latest.name.minute),
        F_RSI_14=float(latest["F_RSI_14"]),
        F_RSI_6=float(latest["F_RSI_6"]),
        F_BB_Pos=float(latest["F_BB_Pos"]),
        F_XAU_Spread_Norm=float(latest["F_XAU_Spread_Norm"]),
        F_Hour_Sin=float(latest["F_Hour_Sin"]),
        F_Hour_Cos=float(latest["F_Hour_Cos"]),
        F_Session_Type=int(latest["F_Session_Type"]),
        F_HSH_Spread=float(latest["F_HSH_Spread"]),
        F_Spread_Cost_Pct=float(latest["F_Spread_Cost_Pct"]),
        F_Spread_vs_ATR=float(latest["F_Spread_vs_ATR"]),
        hsh_close_ask=float(latest["hsh_close_ask"]),
        hsh_close_bid=float(latest["hsh_close_bid"]),
        xau_close=float(latest["xau_close"]),
        usd_close=float(latest["usd_close"]),
    )
