# core/candle_builder.py
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
    
    # 1. Timezone: DB เก็บเป็น naive UTC → localize UTC → convert BKK
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df["timestamp"] = df["timestamp"].dt.tz_localize(
        TZ, ambiguous="NaT", nonexistent="NaT"
    )
    df.set_index("timestamp", inplace=True)
    df.sort_index(inplace=True)
    
    # 2. Price Format: แปลง string/0.0 เป็น float64 + แทนที่ 0.0 ด้วย NaN
    for col in price_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            df.loc[df[col] <= 0.0, col] = np.nan
            
    return df

def _filter_sessions(df: pd.DataFrame) -> pd.DataFrame:
    """ตัดแท่งนอกเวลาทำการทิ้ง รองรับ Session ข้ามเที่ยงคืน"""
    if df.empty:
        return df
    
    mask = pd.Series(False, index=df.index)
    time_in_mins = df.index.hour * 60 + df.index.minute
    
    for _, (start_min, end_min) in SESSION_HOURS.items():
        if start_min < end_min:
            # Session ปกติ (ไม่ข้ามวัน)
            mask |= (time_in_mins >= start_min) & (time_in_mins < end_min)
        else:
            # Session ข้ามเที่ยงคืน (Night: 18:00-01:59)
            mask |= (time_in_mins >= start_min) | (time_in_mins < end_min)
            
    # ตัดเสาร์-อาทิตย์ (5=Sat, 6=Sun) อย่างเด็ดขาด (ตรงกับ Training Data)
    weekend_mask = (df.index.dayofweek < 5)
    final_mask = mask & weekend_mask
            
    return df[final_mask].copy()

def build_candles() -> pd.DataFrame:
    """
    Phase 1: ดึงข้อมูล → Clean → Resample M10 → Filter Session → Validate
    """
    logger.info("[P1] Building M10 candles...")
    now_bkk = datetime.now().astimezone()
    
    # 🔍 แก้ไข: ตลาดเปิด ~14 ชม./วัน (5 วัน/สัปดาห์) → ได้ ~120 แท่ง/วัน
    # OLS ต้องการ 2016 แท่ง → ต้องดึงย้อนหลัง ~35 วันปฏิทิน เพื่อชดเชยช่วงตลาดปิด/วันหยุด
    LOOKBACK_DAYS = 35
    start_dt = (now_bkk - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%S")
    end_dt = now_bkk.strftime("%Y-%m-%dT%H:%M:%S")
    
    # 1. Fetch Raw Data
    hsh_raw = _fetch_table_chunked("gold_prices_hsh", start_dt, end_dt)
    ig_raw  = _fetch_table_chunked("gold_prices_ig", start_dt, end_dt)
    
    if hsh_raw.empty or ig_raw.empty:
        raise RuntimeError("[P1] ไม่พบข้อมูลดิบใน Supabase (ตรวจสอบช่วงวันหรือ Table Name)")
        
    # 2. Clean & Localize
    hsh_df = _clean_and_localize(hsh_raw, ["bid_96", "ask_96"])
    ig_df  = _clean_and_localize(ig_raw, ["spot_price", "usd_thb"])
    
    # 3. Resample to M10 (ใช้ '10min' แทน '10T' เพื่อเลี่ยง FutureWarning)
    hsh_m10 = hsh_df.resample("10min", closed="right", label="right").agg({
        "bid_96": ["first", "max", "min", "last"],
        "ask_96": ["first", "max", "min", "last"]
    })
    hsh_m10.columns = [f"{col[0]}_{col[1]}" for col in hsh_m10.columns]
    hsh_m10.rename(columns={
        "ask_96_first": "hsh_open_ask", "ask_96_max": "hsh_high_ask",
        "ask_96_min": "hsh_low_ask", "ask_96_last": "hsh_close_ask",
        "bid_96_first": "hsh_open_bid", "bid_96_max": "hsh_high_bid",
        "bid_96_min": "hsh_low_bid", "bid_96_last": "hsh_close_bid"
    }, inplace=True)
    
    ig_m10 = ig_df.resample("10min", closed="right", label="right").agg({
        "spot_price": ["first", "max", "min", "last"],
        "usd_thb": ["last"]
    })
    ig_m10.columns = [f"{col[0]}_{col[1]}" for col in ig_m10.columns]
    ig_m10.rename(columns={
        "spot_price_first": "xau_open", "spot_price_max": "xau_high",
        "spot_price_min": "xau_low", "spot_price_last": "xau_close",
        "usd_thb_last": "usd_close"
    }, inplace=True)
    
    # 4. Join & Forward Fill minor gaps
    candles = hsh_m10.join(ig_m10, how="outer").sort_index()
    # หมายเหตุ: limit=1 deprecated ใน pandas 2.2+ → ใช้ ffill() ธรรมดาแทน
    candles = candles.ffill()
    candles.dropna(subset=["hsh_close_ask", "xau_close", "usd_close"], inplace=True)
    
    # 5. Filter Sessions
    candles = _filter_sessions(candles)
    
    # 6. Validation
    assert len(candles) >= 50, f"[P1] ข้อมูลน้อยเกินไป: {len(candles)} แท่ง"
    assert candles.index.is_monotonic_increasing, "[P1] Index ไม่เรียงเวลา"
    assert (candles["hsh_close_ask"] > candles["hsh_close_bid"]).all(), "[P1] พบ Ask ≤ Bid"
    
    logger.info(f"[P1] ✅ Candles ready: {len(candles)} bars | Range: {candles.index[0]} → {candles.index[-1]}")
    return candles