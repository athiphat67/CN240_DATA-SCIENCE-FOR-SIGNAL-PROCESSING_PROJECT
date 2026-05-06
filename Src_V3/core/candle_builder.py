"""
core/candle_builder.py — Phase 1: M10 Candle Builder

ดึงราคา HSH (bid/ask), XAU/USD, USD/THB จาก Supabase
→ aggregate เป็น M10 OHLCV rolling buffer
→ ส่ง candles_df (2200 bars × 15 cols) ไปยัง Feature Engine

Input tables (Supabase):
  • hsh_prices     — timestamp, bid, ask          (tick data)
  • xau_prices     — timestamp, open, high, low, close, spread  (already OHLCV per tick)
  • usd_thb_prices — timestamp, close             (tick data)

Output:
  candles_df : pd.DataFrame (DatetimeIndex Asia/Bangkok, freq=10min)
    Columns  : hsh_open_ask, hsh_high_ask, hsh_low_ask, hsh_close_ask,
               hsh_open_bid, hsh_high_bid, hsh_low_bid, hsh_close_bid,
               xau_open, xau_high, xau_low, xau_close, xau_spread, usd_close
"""

from __future__ import annotations

import logging
import time

import pandas as pd
import pytz

from config.settings import (
    LOOKBACK_BARS,
    OLS_WINDOW,
    SUPABASE_KEY,
    SUPABASE_URL,
    TIMEFRAME_MIN,
    TIMEZONE,
)

logger = logging.getLogger("system")
TZ = pytz.timezone(TIMEZONE)

# ─── Supabase client (lazy init, shared across calls) ─────────────────────────
_supabase = None


def _get_supabase():
    """Lazy init — import supabase ช้า เพื่อให้ unit test ไม่ต้องการ package"""
    global _supabase
    if _supabase is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise RuntimeError(
                "SUPABASE_URL / SUPABASE_KEY ไม่ถูกตั้งค่า — ตรวจสอบ .env"
            )
        try:
            from supabase import create_client as _create_client
        except ImportError as exc:
            raise RuntimeError(
                "supabase-py ไม่ได้ติดตั้ง — รัน: pip install supabase==2.4.0"
            ) from exc
        _supabase = _create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _fetch_with_retry(
    table: str,
    columns: str,
    lookback_minutes: int,
    max_retries: int = 3,
) -> list[dict]:
    """
    Fetch rows from Supabase with exponential backoff.
    ดึงข้อมูลย้อนหลัง `lookback_minutes` นาที
    """
    sb = _get_supabase()
    cutoff = (
        pd.Timestamp.now(tz="UTC")
        - pd.Timedelta(minutes=lookback_minutes)
    ).isoformat()

    for attempt in range(max_retries):
        try:
            resp = (
                sb.table(table)
                .select(columns)
                .gte("timestamp", cutoff)
                .order("timestamp", desc=False)
                .execute()
            )
            return resp.data or []
        except Exception as exc:
            if attempt == max_retries - 1:
                logger.error(
                    f"[candle_builder] ดึงข้อมูล {table} ล้มเหลวหลัง {max_retries} ครั้ง: {exc}"
                )
                raise
            wait = 2 ** attempt
            logger.warning(
                f"[candle_builder] {table} fetch attempt {attempt+1} failed ({exc}), retry in {wait}s"
            )
            time.sleep(wait)


def _prepare_index(df: pd.DataFrame, ts_col: str = "timestamp") -> pd.DataFrame:
    """Parse timestamp → DatetimeIndex in TZ, sort, numeric cast."""
    df = df.copy()
    df[ts_col] = pd.to_datetime(df[ts_col], utc=True)
    df = df.set_index(ts_col).sort_index()
    df.index = df.index.tz_convert(TZ)
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _tick_to_m10_ohlc(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """
    Aggregate a single tick-data column (bid or ask) → M10 OHLC DataFrame.
    Correct for tick/quote data where each row is a single price observation.

    bar_time 09:00 covers ticks [09:00, 09:10) — pandas default closed='left'.
    """
    s = df[col]
    resampled = s.resample(f"{TIMEFRAME_MIN}min").agg(
        open="first",
        high="max",
        low="min",
        close="last",
    )
    prefix = col  # e.g. "ask" → "ask_open", "ask_high", ...
    resampled.columns = [f"{prefix}_{c}" for c in resampled.columns]
    return resampled


def _xau_ohlcv_to_m10(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate XAU OHLCV source data → M10 candles.

    xau_prices already has open/high/low/close per row (per tick/second).
    Correct aggregation:
      xau_open  = first  'open'  in 10-min bar   (first opening quote)
      xau_high  = max    'high'  in 10-min bar   (highest intra-bar high)
      xau_low   = min    'low'   in 10-min bar   (lowest intra-bar low)
      xau_close = last   'close' in 10-min bar   (last closing quote)

    NOTE: using _to_m10_candles for XAU would be WRONG — that function
    computes OHLC *of* each source column (i.e. OHLC of open ticks),
    giving xau_open = last 'open' tick, not the first. This is the bug fix.
    """
    freq = f"{TIMEFRAME_MIN}min"
    return pd.DataFrame({
        "xau_open":  df["open"].resample(freq).first(),
        "xau_high":  df["high"].resample(freq).max(),
        "xau_low":   df["low"].resample(freq).min(),
        "xau_close": df["close"].resample(freq).last(),
    })


def _resample_single(
    df: pd.DataFrame,
    src_col: str,
    agg: str = "last",
) -> pd.Series:
    """Resample a single column (e.g. spread, usd_close) → M10 Series."""
    return df[src_col].resample(f"{TIMEFRAME_MIN}min").agg(agg)


# ─── Main Public Function ─────────────────────────────────────────────────────

def build_m10_candles() -> pd.DataFrame:
    """
    ดึงข้อมูลจาก Supabase 3 ตาราง → aggregate → validate → return candles_df

    Returns
    -------
    pd.DataFrame
        Index  : DatetimeIndex (Asia/Bangkok, freq=10min)
        Shape  : (LOOKBACK_BARS,) × 14 columns
        Columns: hsh_open_ask, hsh_high_ask, hsh_low_ask, hsh_close_ask,
                 hsh_open_bid, hsh_high_bid, hsh_low_bid, hsh_close_bid,
                 xau_open, xau_high, xau_low, xau_close,
                 xau_spread, usd_close

    Raises
    ------
    ValueError  — validation ล้มเหลว (ข้อมูลไม่พอ / NaN / ask ≤ bid)
    RuntimeError — Supabase connection fail
    """
    # ─── ความยาว lookback ที่ต้องการ (×2 buffer สำหรับ non-market gaps) ──────
    lookback_minutes = LOOKBACK_BARS * TIMEFRAME_MIN * 2

    logger.info(
        f"[candle_builder] Fetching {LOOKBACK_BARS} M10 bars "
        f"(lookback window: {lookback_minutes // 60:.0f}h)"
    )

    # ─── 1. Fetch & aggregate HSH tick data ──────────────────────────────────
    hsh_raw = _fetch_with_retry("hsh_prices", "timestamp,bid,ask", lookback_minutes)
    if not hsh_raw:
        raise ValueError("[candle_builder] hsh_prices ไม่มีข้อมูลในช่วงที่กำหนด")

    hsh_df = _prepare_index(pd.DataFrame(hsh_raw))

    ask_ohlc = _tick_to_m10_ohlc(hsh_df, "ask").rename(columns={
        "ask_open": "hsh_open_ask", "ask_high": "hsh_high_ask",
        "ask_low":  "hsh_low_ask",  "ask_close": "hsh_close_ask",
    })
    bid_ohlc = _tick_to_m10_ohlc(hsh_df, "bid").rename(columns={
        "bid_open": "hsh_open_bid", "bid_high": "hsh_high_bid",
        "bid_low":  "hsh_low_bid",  "bid_close": "hsh_close_bid",
    })
    hsh_candles = pd.concat([ask_ohlc, bid_ohlc], axis=1)
    logger.debug(
        f"[candle_builder] HSH raw rows: {len(hsh_df):,} → {len(hsh_candles)} M10 bars"
    )

    # ─── 2. Fetch & aggregate XAU OHLCV source data ──────────────────────────
    xau_raw = _fetch_with_retry(
        "xau_prices", "timestamp,open,high,low,close,spread", lookback_minutes
    )
    if not xau_raw:
        raise ValueError("[candle_builder] xau_prices ไม่มีข้อมูลในช่วงที่กำหนด")

    xau_df = _prepare_index(pd.DataFrame(xau_raw))
    xau_candles = _xau_ohlcv_to_m10(xau_df)      # correct OHLCV aggregation

    xau_spread_s = _resample_single(xau_df, "spread", agg="mean")
    xau_spread_s.name = "xau_spread"
    logger.debug(
        f"[candle_builder] XAU raw rows: {len(xau_df):,} → {len(xau_candles)} M10 bars"
    )

    # ─── 3. Fetch & aggregate USD/THB ────────────────────────────────────────
    usd_raw = _fetch_with_retry("usd_thb_prices", "timestamp,close", lookback_minutes)
    if not usd_raw:
        raise ValueError("[candle_builder] usd_thb_prices ไม่มีข้อมูลในช่วงที่กำหนด")

    usd_df = _prepare_index(pd.DataFrame(usd_raw))
    usd_close_s = _resample_single(usd_df, "close", agg="last")
    usd_close_s.name = "usd_close"
    logger.debug(f"[candle_builder] USD/THB raw rows: {len(usd_df):,}")

    # ─── 4. Merge all sources ─────────────────────────────────────────────────
    candles_df = (
        hsh_candles
        .join(xau_candles,   how="outer")
        .join(xau_spread_s,  how="outer")
        .join(usd_close_s,   how="outer")
    )

    # Forward-fill USD/THB and XAU spread (data may lag slightly)
    candles_df["usd_close"]  = candles_df["usd_close"].ffill()
    candles_df["xau_spread"] = candles_df["xau_spread"].ffill()

    # ─── 5. Trim → keep LOOKBACK_BARS most-recent bars ───────────────────────
    candles_df = candles_df.tail(LOOKBACK_BARS).copy()
    candles_df.index.name = "bar_time"

    # ─── 6. Validate ─────────────────────────────────────────────────────────
    _validate(candles_df)

    logger.info(
        f"[candle_builder] ✅ candles_df ready: {len(candles_df)} bars, "
        f"latest bar: {candles_df.index[-1]}"
    )
    return candles_df


# ─── Validation ───────────────────────────────────────────────────────────────

def _validate(candles_df: pd.DataFrame) -> None:
    """
    ตรวจสอบ candles_df ก่อนส่งไป Feature Engine
    Raises ValueError ถ้าข้อมูลไม่ผ่านเงื่อนไข
    """
    min_required = OLS_WINDOW + 50  # cold-start buffer

    if len(candles_df) < min_required:
        raise ValueError(
            f"[candle_builder] ข้อมูลไม่พอสำหรับ OLS: "
            f"มี {len(candles_df)} bars, ต้องการ ≥ {min_required}"
        )

    if not candles_df.index.is_monotonic_increasing:
        raise ValueError(
            "[candle_builder] Candles ต้องเรียงตามเวลา (monotonic increasing)"
        )

    if candles_df["hsh_close_ask"].isna().any():
        n_nan = candles_df["hsh_close_ask"].isna().sum()
        raise ValueError(
            f"[candle_builder] hsh_close_ask มี NaN {n_nan} แท่ง — ตรวจสอบข้อมูล HSH"
        )

    # Ask > Bid — ตรวจเฉพาะแท่งที่ทั้งคู่มีค่า (market hours)
    both_valid = (
        candles_df["hsh_close_ask"].notna() & candles_df["hsh_close_bid"].notna()
    )
    if not (
        candles_df.loc[both_valid, "hsh_close_ask"]
        > candles_df.loc[both_valid, "hsh_close_bid"]
    ).all():
        raise ValueError(
            "[candle_builder] พบ hsh_close_ask ≤ hsh_close_bid — ข้อมูลผิดปกติ"
        )

    logger.debug(
        f"[candle_builder] Validation passed: {len(candles_df)} bars | "
        f"NaN hsh_ask={candles_df['hsh_close_ask'].isna().sum()} | "
        f"NaN xau_close={candles_df['xau_close'].isna().sum()} | "
        f"NaN usd_close={candles_df['usd_close'].isna().sum()}"
    )


# ─── Utility: fetch latest bid only (for Position Monitor) ───────────────────

def fetch_latest_bid() -> float:
    """
    ดึง bid ล่าสุดจาก hsh_prices สำหรับ Position Monitor (Phase 7)
    ไม่ต้องสร้าง candle — ต้องการแค่ราคา mark-to-market ปัจจุบัน
    """
    sb = _get_supabase()
    try:
        resp = (
            sb.table("hsh_prices")
            .select("bid")
            .order("timestamp", desc=True)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        if not rows:
            raise ValueError("[candle_builder] ไม่มีข้อมูล bid ล่าสุด")
        return float(rows[0]["bid"])
    except Exception as exc:
        logger.error(f"[candle_builder] fetch_latest_bid failed: {exc}")
        raise