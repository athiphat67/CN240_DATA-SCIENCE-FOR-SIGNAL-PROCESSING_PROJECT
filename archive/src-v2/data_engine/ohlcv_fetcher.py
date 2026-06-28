from pathlib import Path
import os
import time
import pandas as pd
import numpy as np
import requests
import random

# ==============================
# CONFIG
# ==============================

INTERVAL_TO_MINUTES = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}

TD_INTERVAL_MAP = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1day",
}

YF_MAX_DAYS = {
    "1m": 7,
    "5m": 60,
    "15m": 60,
    "30m": 60,
    "1h": 730,
    "4h": 730,
}

INTERVAL_MIN_FETCH_DAYS = {
    "1m": 2,
    "5m": 5,
    "15m": 7,
    "30m": 7,
    "1h": 14,
    "4h": 30,
    "1d": 30,
}

TWELVEDATA_TS_URL = "https://api.twelvedata.com/time_series"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# ==============================
# UTILS
# ==============================


def _ensure_utc_index(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index, utc=True)
        return df
    if df.index.tzinfo is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    
    return df


def _retry_request(session, url, params, retries=3, backoff=2):
    for attempt in range(retries):
        try:
            resp = session.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(backoff**attempt)


def _calculate_fetch_days(cached_df, requested_days, interval="1d", min_candles=50):
    if cached_df.empty or len(cached_df) < min_candles:
        return requested_days

    now = pd.Timestamp.now('UTC')

    required_cutoff = now - pd.Timedelta(days=requested_days)
    oldest_cached   = cached_df.index[0]

    if oldest_cached.date() > required_cutoff.date():
        print(f"[CACHE] Cache starts at {oldest_cached.date()} but need data from {required_cutoff.date()} → full fetch")
        return requested_days

    # cache ครอบคลุมแล้ว → fetch แค่ส่วนที่หายไป (incremental)
    last_time  = cached_df.index[-1]
    delta_days = (now - last_time) / pd.Timedelta(days=1)

    if delta_days >= requested_days:
        return requested_days

    # ← แก้: ใช้ minimum ตาม interval แทน hardcode 2
    min_days = INTERVAL_MIN_FETCH_DAYS.get(interval, 7)
    return max(min_days, int(delta_days) + 1)


def _estimate_candles(interval: str, days: int) -> int:
    minutes = INTERVAL_TO_MINUTES.get(interval)
    if not minutes:
        return 5000  # fallback safe

    return int((1440 / minutes) * days)


def _validate_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    df = df.copy()

    # 1. บังคับให้ทุกอย่างเป็นตัวเลข (ถ้าแปลงไม่ได้ให้เป็น NaN)
    cols = ["open", "high", "low", "close"]
    for col in cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 2. ลบแถวที่มี NaN ในราคาหลักๆ ออกก่อน
    df = df.dropna(subset=cols)

    # 3. ตรวจสอบความถูกต้องของราคา
    # เพิ่ม print เช็กตัวอย่างข้อมูลสักนิด
    if not df.empty:
        print(
            f"[DEBUG] Sample before filter: High={df['high'].iloc[0]}, Low={df['low'].iloc[0]}"
        )

    df = df[
        (df["high"] >= df["low"])
        & (df["high"] > 0)
        & (df["low"] > 0)
        & (df["open"] > 0)
        & (df["close"] > 0)
    ]

    return df


# ==============================
# MAIN FUNCTION
# ==============================
BASE_DIR = Path(__file__).resolve().parent.parent


class OHLCVFetcher:
    def __init__(self, session=None):
        self.session = session or requests.Session()

    def fetch_historical_ohlcv(
        self,
        days: int = 90,
        interval: str = "1d",
        twelvedata_symbol: str = "XAU/USD",
        yf_symbol: str = "GC=F",
        max_td_output_size: int = 5000,
        use_cache: bool = True,
        cache_dir: str = str(BASE_DIR / "cache"),
    ) -> pd.DataFrame:

        cache_file = (
            Path(cache_dir)
            / f"ohlcv_{twelvedata_symbol.replace('/', '_')}_{interval}.csv"
        )
        cached_df = pd.DataFrame()

        # ==============================
        # 1. LOAD CACHE
        # ==============================
        if use_cache:
            Path(cache_dir).mkdir(parents=True, exist_ok=True)

            if cache_file.exists():
                try:
                    cached_df = pd.read_csv(cache_file, index_col="datetime")
                    cached_df.index = pd.to_datetime(cached_df.index, utc=True, errors="coerce")  # ← coerce แทน crash
                    cached_df = cached_df[cached_df.index.notna()]  # ← ตัดแถวที่ parse ไม่ได้ทิ้ง

                    if cached_df.empty:
                        print("[CACHE] All rows invalid after date parse — discarding cache")
                        cached_df = pd.DataFrame()
                    
                    required = ["open", "high", "low", "close"]
                    if not all(c in cached_df.columns for c in required):
                        print("[CACHE] Invalid columns — discarding cache")
                        cached_df = pd.DataFrame() 
                    else:
                        cached_df = _ensure_utc_index(cached_df)
                        print(f"[CACHE] Loaded {len(cached_df)} rows")
                except Exception as e:
                    print(f"[CACHE] Read failed: {e}")
                    # 🚀 เพิ่มบรรทัดนี้: ถ้าอ่านไฟล์แคชพัง ให้ล้างข้อมูลเป็น DataFrame ว่างทันที!
                    cached_df = pd.DataFrame()

        # ==============================
        # 2. CALCULATE FETCH RANGE
        # ==============================
        fetch_days = _calculate_fetch_days(cached_df, days, interval=interval)

        # ==============================
        # 3. FETCH FROM YFINANCE (PRIMARY)
        # ==============================
        df_api = pd.DataFrame()
        print("[YF] Fetching from Yahoo Finance as primary source (for Volume)...")

        try:
            import yfinance as yf

            max_days = YF_MAX_DAYS.get(interval, days)
            safe_days = min(fetch_days, max_days)

            ticker = yf.Ticker(yf_symbol)
            df_api = ticker.history(period=f"{safe_days}d", interval=interval)

            # retry ถ้า empty และยังมีวันให้ขยาย
            if df_api.empty and safe_days < fetch_days:
                print(f"[YF] Retry with full period: {fetch_days}d (was {safe_days}d)")
                safe_days = min(fetch_days, max_days)
                df_api = ticker.history(period=f"{safe_days}d", interval=interval)

            # ← column processing ต้องอยู่ตรงนี้เสมอ ไม่ว่าจะ retry หรือไม่
            if not df_api.empty:
                df_api.columns = [c.lower() for c in df_api.columns]
                df_api = df_api[["open", "high", "low", "close", "volume"]]
                df_api.index.name = "datetime"
                print(f"[YF] Fetched {len(df_api)} rows")
            else:
                print("[DEBUG] YF returned EMPTY dataframe")

        except Exception as e:
            print(f"[YF] Failed: {e}")

        # ==============================
        # 4. FALLBACK: TWELVEDATA
        # ==============================
        api_key = os.getenv("TWELVEDATA_API_KEY")

        if df_api.empty and api_key:
            print("[TD] Fallback activated - Fetching from TwelveData...")
            try:
                td_interval = TD_INTERVAL_MAP.get(interval, "1day")

                estimated = _estimate_candles(interval, fetch_days)
                output_size = min(estimated, max_td_output_size)

                params = {
                    "symbol": twelvedata_symbol,
                    "interval": td_interval,
                    "outputsize": output_size,
                    "apikey": api_key,
                    "timezone": "UTC",
                }

                data = _retry_request(self.session, TWELVEDATA_TS_URL, params)

                if "values" in data:
                    df_api = pd.DataFrame(data["values"])
                    df_api["datetime"] = pd.to_datetime(df_api["datetime"])
                    df_api.set_index("datetime", inplace=True)
                    df_api = df_api.astype(float)

                    if "volume" not in df_api.columns:
                        df_api["volume"] = np.nan

                    df_api = df_api[["open", "high", "low", "close", "volume"]]

                    print(f"[TD] Fetched {len(df_api)} rows")
                    print(f"[DEBUG] TD Raw Data: {len(df_api)} rows found")
                else:
                    print(
                        f"[DEBUG] TD API Message: {data.get('message', 'No values key in response')}"
                    )

            except Exception as e:
                print(f"[TD] Failed: {e}")

        # ==============================
        # 5. MERGE + CLEAN
        # ==============================
        if not df_api.empty:
            df_api = _ensure_utc_index(df_api)
            before_val = len(df_api)
            df_api = _validate_ohlcv(df_api)
            after_val = len(df_api)
            if before_val != after_val:
                print(f"[DEBUG] Validation removed {before_val - after_val} invalid rows")

            # ← merge ของเก่า + ใหม่ (ต้องทำเสมอ ไม่ใช่แค่ fallback)
            if not cached_df.empty:
                df = pd.concat([cached_df, df_api])
                df = df[~df.index.duplicated(keep="last")]
            else:
                df = df_api

            df = df.sort_index()
            cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
            df = df[df.index >= cutoff]

            if use_cache:
                df.to_csv(cache_file)
                print(f"[CACHE] Updated ({len(df)} rows)")

            return df

        # ==============================
        # 6. FINAL FALLBACK
        # ==============================
        if not cached_df.empty:
            print("[FALLBACK] Using cached data")
            cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
            return cached_df[cached_df.index >= cutoff]

        return pd.DataFrame()
