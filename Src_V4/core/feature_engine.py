# core/feature_engine.py
# ⚠️  ซิงค์กับ 02_feature_engineering.py (training script) — ห้ามแก้สูตรโดยไม่อัปเดต training ด้วย
import pandas as pd
# pyrefly: ignore [missing-import]
import numpy as np
import logging
from typing import TypedDict
from config.settings import (
    OLS_WINDOW, ATR_WINDOW, CORR_WINDOW, VOL_WINDOW,
    CONV_FACTOR, SESSION_HOURS
)

logger = logging.getLogger("system")

# ── Constants ที่ตรงกับ CONFIG ใน training script ────────────────────────────
# F_Historical_Vol_THB ใช้ weight ratio เท่านั้น (ตรงกับ training)
# ไม่รวม purity factor ต่างจาก CONV_FACTOR ที่ใช้กับ F_Syn_Price
_HIST_VOL_WEIGHT = 15.244 / 31.1035   # ≈ 0.4901

# Expected session lengths ตรงกับ training script (Morning=18, Afternoon=27, Night=48)
# ⚠️  ห้ามเปลี่ยนค่านี้โดยไม่ retrain model — F_FSP, F_Remaining_Vol, F_SRVR ขึ้นอยู่กับค่านี้
_SESSION_EXPECTED = {'Morning': 18, 'Afternoon': 27, 'Night': 48}


class FeaturesRow(TypedDict):
    # ─── Meta ──────────────────────────────────────────────────────────────────
    bar_time        : str
    session         : str
    # ─── Synthetic ─────────────────────────────────────────────────────────────
    F_Syn_Price     : float
    F_Thai_Premium  : float
    # ─── Macro ─────────────────────────────────────────────────────────────────
    F_Corr_XAU_USD  : float
    F_XAU_Mom_Short : float
    F_XAU_Mom_Mid   : float
    F_USD_Mom       : float
    F_ATR_48        : float
    F_Regime        : int
    # ─── Session ───────────────────────────────────────────────────────────────
    F_FSP               : float
    F_SA_TWAP_Dev       : float
    F_SA_MDD            : float
    F_SA_Vol            : float
    F_SA_Range          : float
    F_SA_Position       : float
    F_Historical_Vol_THB: float
    F_Remaining_Vol     : float
    F_SRVR              : float
    F_Price_Vs_Open     : float
    F_Mom_1bar          : float
    F_Mom_3bar          : float
    F_SA_Drawdown_Pct   : float
    F_HSH_vs_THBGold_Dev: float
    # ─── Time ──────────────────────────────────────────────────────────────────
    F_DayOfWeek     : int
    F_MinuteOfDay   : int
    # ─── Technical ─────────────────────────────────────────────────────────────
    F_RSI_14        : float
    F_RSI_6         : float
    F_BB_Pos        : float
    F_XAU_Spread_Norm: float
    F_Hour_Sin      : float
    F_Hour_Cos      : float
    F_Session_Type  : int
    F_HSH_Spread    : float
    F_Spread_Cost_Pct: float
    F_Spread_vs_ATR : float
    # ─── Pass-through (ไม่เข้า model) ──────────────────────────────────────────
    hsh_close_ask   : float
    hsh_close_bid   : float
    xau_close       : float
    usd_close       : float


def _assign_session(dt_idx: pd.DatetimeIndex) -> pd.Series:
    """ระบุ Session ให้แต่ละแท่ง รองรับข้ามเที่ยงคืน (Night: 18:00-01:59)"""
    mins = dt_idx.hour * 60 + dt_idx.minute
    cond = pd.Series("Closed", index=dt_idx)
    for name, (start, end) in SESSION_HOURS.items():
        if start < end:
            cond[(mins >= start) & (mins < end)] = name
        else:
            cond[(mins >= start) | (mins < end)] = name
    return cond


def _safe_pct_change(series: pd.Series, session_series: pd.Series, periods: int = 1) -> pd.Series:
    """คำนวณ % Change โดยรีเซ็ตค่าที่ขอบ Session"""
    ret = series.pct_change(periods)
    crosses_boundary = session_series != session_series.shift(periods)
    ret[crosses_boundary] = 0.0
    return ret


def _safe_diff(series: pd.Series, session_series: pd.Series, periods: int = 1) -> pd.Series:
    """คำนวณ Diff โดยรีเซ็ตค่าที่ขอบ Session"""
    d = series.diff(periods)
    crosses_boundary = session_series != session_series.shift(periods)
    d[crosses_boundary] = 0.0
    return d


def _rolling_ols_numpy(x_arr: np.ndarray, y_arr: np.ndarray, window: int):
    """
    Rolling OLS ด้วย numpy sliding_window_view — ตรงกับ compute_rolling_synthetic()
    ใน training script (02_feature_engineering.py) ทุกประการ
    """
    n = len(x_arr)
    slopes     = np.full(n, np.nan)
    intercepts = np.full(n, np.nan)

    if n < window:
        return slopes, intercepts

    win_x  = np.lib.stride_tricks.sliding_window_view(x_arr, window)
    win_y  = np.lib.stride_tricks.sliding_window_view(y_arr, window)

    sum_x  = win_x.sum(axis=1)
    sum_y  = win_y.sum(axis=1)
    sum_xx = (win_x * win_x).sum(axis=1)
    sum_xy = (win_x * win_y).sum(axis=1)

    denom  = window * sum_xx - sum_x ** 2
    safe   = denom != 0

    b = np.where(safe, (window * sum_xy - sum_x * sum_y) / np.where(safe, denom, 1), np.nan)
    a = np.where(safe, (sum_y - b * sum_x) / window, np.nan)

    slopes[window - 1:]     = b
    intercepts[window - 1:] = a
    return slopes, intercepts


def compute_features(candles_df: pd.DataFrame) -> FeaturesRow:
    """
    คำนวณ 34 Features จาก M10 Candles
    ซิงค์กับ 02_feature_engineering.py (training script) ทุกสูตร

    Input columns ที่ต้องการ:
        hsh_close_ask, hsh_close_bid,
        xau_close, xau_high, xau_low,
        usd_close
    """
    df = candles_df.copy()

    if len(df) < OLS_WINDOW + 10:
        raise ValueError("[P2] ข้อมูลไม่พอสำหรับ OLS Cold Start")

    # ── Session & Boundary ID ─────────────────────────────────────────────────
    df["session"]    = _assign_session(df.index)
    df["session_id"] = (df["session"] != df["session"].shift(1)).cumsum()

    # ── Group 1: Synthetic & Premium ─────────────────────────────────────────
    # CONV_FACTOR รวม purity (ตรงกับ training: conv_factor ใน compute_rolling_synthetic)
    x_arr = (df["xau_close"] * CONV_FACTOR * df["usd_close"]).values
    y_arr = df["hsh_close_ask"].values

    slopes, intercepts = _rolling_ols_numpy(x_arr, y_arr, OLS_WINDOW)
    df["F_Syn_Price"]    = slopes * x_arr + intercepts
    df["F_Thai_Premium"] = df["hsh_close_ask"] - df["F_Syn_Price"]

    # ── Group 2: Macro ────────────────────────────────────────────────────────
    xau_ret = _safe_pct_change(df["xau_close"], df["session_id"], 1)
    usd_ret = _safe_pct_change(df["usd_close"], df["session_id"], 1)

    df["F_Corr_XAU_USD"]  = xau_ret.rolling(CORR_WINDOW).corr(usd_ret)
    df["F_XAU_Mom_Short"] = _safe_pct_change(df["xau_close"], df["session_id"], 3)
    df["F_XAU_Mom_Mid"]   = _safe_pct_change(df["xau_close"], df["session_id"], 12)
    df["F_USD_Mom"]       = _safe_pct_change(df["usd_close"], df["session_id"], 6)

    # ATR(48) with Session Boundary Fix
    prev_close = df["xau_close"].shift(1)
    h_l  = df["xau_high"] - df["xau_low"]
    h_pc = (df["xau_high"] - prev_close).abs()
    l_pc = (df["xau_low"]  - prev_close).abs()

    crosses_boundary = df["session_id"] != df["session_id"].shift(1)
    h_pc[crosses_boundary] = h_l[crosses_boundary]
    l_pc[crosses_boundary] = h_l[crosses_boundary]

    tr = pd.concat([h_l, h_pc, l_pc], axis=1).max(axis=1)
    df["F_ATR_48"] = tr.rolling(ATR_WINDOW).mean()

    # Regime — EMA default adjust=True ตรงกับ training (ไม่ใส่ adjust=False)
    ema_fast = df["xau_close"].ewm(span=20).mean()
    ema_slow = df["xau_close"].ewm(span=50).mean()
    df["F_Regime"] = np.sign(ema_fast - ema_slow).astype(int)

    # ── Group 3: Session-Aware ────────────────────────────────────────────────
    df["Expected_Session_Length"] = df["session"].map(_SESSION_EXPECTED).fillna(18)

    bar_in_session = df.groupby("session_id").cumcount()
    df["F_FSP"] = (bar_in_session / (df["Expected_Session_Length"] - 1).clip(lower=1)).clip(upper=1.0)

    grp    = df.groupby("session_id")
    prices = df["hsh_close_ask"]

    exp_mean = grp["hsh_close_ask"].expanding().mean().droplevel(0)
    exp_max  = grp["hsh_close_ask"].expanding().max().droplevel(0)
    exp_min  = grp["hsh_close_ask"].expanding().min().droplevel(0)
    exp_std  = grp["hsh_close_ask"].expanding().std().fillna(0).droplevel(0)

    df["F_SA_TWAP_Dev"] = prices - exp_mean
    df["F_SA_MDD"]      = prices - exp_max
    df["F_SA_Vol"]      = exp_std
    df["F_SA_Range"]    = exp_max - exp_min
    df["F_SA_Position"] = (prices - exp_min) / (df["F_SA_Range"].clip(lower=1.0))

    # F_Historical_Vol_THB — ใช้ _HIST_VOL_WEIGHT (weight ratio เท่านั้น, ไม่รวม purity)
    # ตรงกับ training: hist_vol_xau * (WEIGHT_TH_BAHT / WEIGHT_TROY_OUNCE) * USD_Close
    hist_vol_xau = _safe_pct_change(df["xau_close"], df["session_id"], 1).rolling(VOL_WINDOW).std() * df["xau_close"]
    df["F_Historical_Vol_THB"] = hist_vol_xau * _HIST_VOL_WEIGHT * df["usd_close"]
    df["F_Remaining_Vol"]      = df["F_Historical_Vol_THB"] * (1.0 - df["F_FSP"])
    df["F_SRVR"]               = df["F_Remaining_Vol"] / df["F_ATR_48"].replace(0, 1e-9)

    df["F_Price_Vs_Open"] = grp["hsh_close_ask"].transform(
        lambda x: (x - x.iloc[0]) / (x.iloc[0] + 1e-9)
    )

    df["F_Mom_1bar"] = _safe_pct_change(df["hsh_close_ask"], df["session_id"], 1)
    df["F_Mom_3bar"] = _safe_pct_change(df["hsh_close_ask"], df["session_id"], 3)

    # F_SA_Drawdown_Pct — ใช้ transform ครั้งเดียว ตรงกับ training
    df["F_SA_Drawdown_Pct"] = grp["hsh_close_ask"].transform(
        lambda x: (x - x.expanding().max()) / (x.expanding().max() + 1e-9)
    )

    thb_gold_ret = _safe_pct_change(df["xau_close"] * df["usd_close"], df["session_id"], 1)
    hsh_ret      = _safe_pct_change(df["hsh_close_ask"], df["session_id"], 1)
    df["F_HSH_vs_THBGold_Dev"] = (hsh_ret - thb_gold_ret).rolling(6).mean()

    df["F_DayOfWeek"]   = df.index.dayofweek
    df["F_MinuteOfDay"] = df.index.hour * 60 + df.index.minute

    # ── Group 4: Technical ────────────────────────────────────────────────────
    def _calc_rsi(series, session_series, period):
        delta = _safe_diff(series, session_series, 1)
        gain  = delta.where(delta > 0, 0.0).rolling(period).mean()
        loss  = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi.fillna(50)

    df["F_RSI_14"] = _calc_rsi(df["hsh_close_ask"], df["session_id"], 14)
    df["F_RSI_6"]  = _calc_rsi(df["hsh_close_ask"], df["session_id"], 6)

    bb_mid = df["hsh_close_ask"].rolling(20).mean()
    bb_std = df["hsh_close_ask"].rolling(20).std()
    df["F_BB_Pos"] = (df["hsh_close_ask"] - bb_mid) / (2 * bb_std.replace(0, 1e-9))

    # F_XAU_Spread_Norm — ใช้ XAU High-Low เป็น XAU_Spread ตรงกับ training
    # training: df['XAU_Spread'] / df['XAU_Spread'].rolling(VOL_WINDOW).mean().replace(0, 1e-9)
    xau_spread = (df["xau_high"] - df["xau_low"]).replace(0, np.nan).ffill().fillna(0.5)
    df["F_XAU_Spread_Norm"] = xau_spread / xau_spread.rolling(VOL_WINDOW, min_periods=1).mean().replace(0, 1e-9)

    hour_dec = df.index.hour + df.index.minute / 60
    df["F_Hour_Sin"] = np.sin(2 * np.pi * hour_dec / 24)
    df["F_Hour_Cos"] = np.cos(2 * np.pi * hour_dec / 24)
    df["F_Session_Type"] = df["session"].map({"Morning": 0, "Afternoon": 1, "Night": 2}).fillna(-1).astype(int)

    # HSH Spread = ask - bid (เทียบเท่า HSH_Spread_Sim ใน training)
    hsh_spread = df["hsh_close_ask"] - df["hsh_close_bid"]
    df["F_HSH_Spread"]      = hsh_spread
    df["F_Spread_Cost_Pct"] = hsh_spread / df["hsh_close_ask"]
    df["F_Spread_vs_ATR"]   = hsh_spread / df["F_ATR_48"].replace(0, 1e-9)

    # ── Final Cleanup & Return Latest Row ────────────────────────────────────
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df.dropna(subset=["F_Syn_Price"], inplace=True)
    if df.empty:
        raise RuntimeError("[P2] OLS Cold Start ยังไม่ครบ window")

    latest = df.iloc[-1]

    return FeaturesRow(
        bar_time=latest.name.isoformat(),
        session=latest["session"],
        F_Syn_Price=latest["F_Syn_Price"],
        F_Thai_Premium=latest["F_Thai_Premium"],
        F_Corr_XAU_USD=latest["F_Corr_XAU_USD"],
        F_XAU_Mom_Short=latest["F_XAU_Mom_Short"],
        F_XAU_Mom_Mid=latest["F_XAU_Mom_Mid"],
        F_USD_Mom=latest["F_USD_Mom"],
        F_ATR_48=latest["F_ATR_48"],
        F_Regime=int(latest["F_Regime"]),
        F_FSP=latest["F_FSP"],
        F_SA_TWAP_Dev=latest["F_SA_TWAP_Dev"],
        F_SA_MDD=latest["F_SA_MDD"],
        F_SA_Vol=latest["F_SA_Vol"],
        F_SA_Range=latest["F_SA_Range"],
        F_SA_Position=latest["F_SA_Position"],
        F_Historical_Vol_THB=latest["F_Historical_Vol_THB"],
        F_Remaining_Vol=latest["F_Remaining_Vol"],
        F_SRVR=latest["F_SRVR"],
        F_Price_Vs_Open=latest["F_Price_Vs_Open"],
        F_Mom_1bar=latest["F_Mom_1bar"],
        F_Mom_3bar=latest["F_Mom_3bar"],
        F_SA_Drawdown_Pct=latest["F_SA_Drawdown_Pct"],
        F_HSH_vs_THBGold_Dev=latest["F_HSH_vs_THBGold_Dev"],
        F_DayOfWeek=int(latest["F_DayOfWeek"]),
        F_MinuteOfDay=int(latest["F_MinuteOfDay"]),
        F_RSI_14=latest["F_RSI_14"],
        F_RSI_6=latest["F_RSI_6"],
        F_BB_Pos=latest["F_BB_Pos"],
        F_XAU_Spread_Norm=latest["F_XAU_Spread_Norm"],
        F_Hour_Sin=latest["F_Hour_Sin"],
        F_Hour_Cos=latest["F_Hour_Cos"],
        F_Session_Type=int(latest["F_Session_Type"]),
        F_HSH_Spread=latest["F_HSH_Spread"],
        F_Spread_Cost_Pct=latest["F_Spread_Cost_Pct"],
        F_Spread_vs_ATR=latest["F_Spread_vs_ATR"],
        hsh_close_ask=latest["hsh_close_ask"],
        hsh_close_bid=latest["hsh_close_bid"],
        xau_close=latest["xau_close"],
        usd_close=latest["usd_close"]
    )