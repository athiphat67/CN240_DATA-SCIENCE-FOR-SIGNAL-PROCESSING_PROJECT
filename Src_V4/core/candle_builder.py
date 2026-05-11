# core/candle_builder.py
#
# CHANGELOG vs เวอร์ชันก่อน:
#
#   [FIX-CB-1] ลบ _filter_sessions() ออกจาก build_candles()
#              เดิม: filter session ก่อนส่งให้ feature_engine → rolling windows (ATR_48,
#              Vol_144, Corr_18) ไม่มี warm-up data ช่วงต้น session
#              แก้ไข: ส่ง full candles (ครอบคลุม 24/7) ให้ feature_engine
#              ให้ feature_engine compute บน full dataset แล้ว extract bar ล่าสุดเอง
#
#   [NOTE] คง closed='right', label='right' ไว้ตามเดิม — ถูกต้องแล้ว
#          pipeline รัน 07:30 → bar label 07:30 = tick 07:20:01–07:30:00 (ปิดสมบูรณ์พอดี)
#          ราคาที่ต่างกับ app.py (Root cause 2 ใน diagram) มาจาก ffill strategy
#          ไม่ใช่ resample timing — ไม่ต้องแก้
#
import os
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
from supabase import create_client, Client
from config.settings import SUPABASE_URL, SUPABASE_KEY, LOOKBACK_BARS, TIMEZONE, SESSION_HOURS

logger = logging.getLogger("system")
TZ = "Asia/Bangkok"

_client: Client | None = None

def _get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client

def _fetch_table_chunked(table: str, start_dt: str, end_dt: str, chunk_size: int = 5000) -> pd.DataFrame:
    """ดึงข้อมูลแบบ Pagination เพื่อเลี่ยง Supabase PostgREST Limit (default 1000)"""
    all_rows = []
    offset = 0
    client = _get_client()

    while True:
        try:
            res = (
                client.table(table)
                .select("*")
                .gte("timestamp", start_dt)
                .lte("timestamp", end_dt)
                .order("timestamp", desc=False)
                .range(offset, offset + chunk_size - 1)
                .execute()
            )
            if not res.data:
                break
            all_rows.extend(res.data)
            if len(res.data) < chunk_size:
                break
            offset += chunk_size
        except Exception as e:
            logger.error(f"DB fetch error on {table} at offset {offset}: {e}")
            break

    return pd.DataFrame(all_rows)

def _clean_and_localize(df: pd.DataFrame, price_cols: list) -> pd.DataFrame:
    """จัดการ Timezone และแปลง 0.0 / null เป็น NaN"""
    if df.empty:
        return df

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["timestamp"] = df["timestamp"].dt.tz_localize(
        TZ, ambiguous="NaT", nonexistent="NaT"
    )
    df.set_index("timestamp", inplace=True)
    df.sort_index(inplace=True)

    for col in price_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            df.loc[df[col] <= 0.0, col] = np.nan

    return df


def build_candles() -> pd.DataFrame:
    """
    [FIXED] Phase 1: เลียนแบบ app.py 100%
    - Join ข้อมูลดิบแบบ Outer แล้ว ffill เพื่อเชื่อมเช้าวันจันทร์กับวันศุกร์
    - Resample จาก DataFrame เดียวกันเพื่อให้ High/Low/Close ตรงกัน
    """
    logger.info("[P1] Building M10 candles (Exact Sync with app.py)...")
    now_bkk = datetime.now().astimezone()

    LOOKBACK_DAYS = 35
    start_dt = (now_bkk - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
    end_dt = now_bkk.strftime("%Y-%m-%dT%H:%M:%S")

    # 1. Fetch Raw Data
    hsh_raw = _fetch_table_chunked("gold_prices_hsh", start_dt, end_dt)
    ig_raw  = _fetch_table_chunked("gold_prices_ig", start_dt, end_dt)

    if hsh_raw.empty or ig_raw.empty:
        raise RuntimeError("[P1] ไม่พบข้อมูลดิบ")

    # 2. Clean & Localize
    hsh_df = _clean_and_localize(hsh_raw, ["bid_96", "ask_96"])
    ig_df  = _clean_and_localize(ig_raw, ["spot_price", "usd_thb"])

    # 3. [CRITICAL] Join Raw Ticks & Forward Fill (เลียนแบบ app.py บรรทัด 182-184)
    # วิธีนี้จะทำให้เช้าวันจันทร์มีราคา HSH จากวันศุกร์มาใช้ต่อได้
    raw_combined = hsh_df[["bid_96", "ask_96"]].join(
        ig_df[["spot_price", "usd_thb"]], how="outer"
    ).ffill().bfill()

    # 4. Resample M10 (ใช้ Default: closed='left', label='left' ตาม app.py)
    # คำนวณ High/Low ของ IG จากค่า spot_price ในช่วงเวลานั้น
    candles = raw_combined.resample("10min", closed="right", label="right").agg({
        "ask_96": "last",
        "bid_96": "last",
        "spot_price": ["last", "max", "min"],
        "usd_thb": "last"
    })
    
    # Flatten columns
    candles.columns = [
        "hsh_close_ask", "hsh_close_bid", 
        "xau_close", "xau_high", "xau_low", 
        "usd_close"
    ]

    # 5. Dropna (เลียนแบบ app.py บรรทัด 188 - ลบแท่งที่ไม่มีการเคลื่อนไหวจริงออก เช่น เสาร์-อาทิตย์)
    # แต่จะเก็บแท่งเช้าวันจันทร์ไว้ได้เพราะเรา ffill ข้อมูลดิบมาแล้ว
    candles.dropna(subset=["hsh_close_ask", "xau_close"], inplace=True)

    # 6. เพิ่ม XAU_Spread (เลียนแบบ app.py บรรทัด 191)
    candles["xau_spread"] = candles["xau_high"] - candles["xau_low"]
    candles["xau_spread"] = candles["xau_spread"].replace(0, np.nan).ffill().fillna(0.5)

    logger.info(f"[P1] ✅ Candles Synced: {len(candles)} bars | Latest: {candles.index[-1]}")
    return candles
