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
import pytz
import logging
from datetime import datetime, timedelta
from supabase import create_client, Client
from config.settings import SUPABASE_URL, SUPABASE_KEY, LOOKBACK_BARS, TIMEZONE, SESSION_HOURS

logger = logging.getLogger("system")
TZ = "Asia/Bangkok"
_BKK_TZ = pytz.timezone(TZ)

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
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize(
            TZ, ambiguous="NaT", nonexistent="NaT"
        )
    else:
        df["timestamp"] = df["timestamp"].dt.tz_convert(TZ)
    df.set_index("timestamp", inplace=True)
    df.sort_index(inplace=True)

    for col in price_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
            df.loc[df[col] <= 0.0, col] = np.nan

    return df


# Maximum allowed pct change between consecutive ticks for a given price column.
# Gold can move ~1% in 10 min on news but a single-tick jump > this is almost
# always a bad feed. Picked conservative on the high side to avoid false trips.
_OUTLIER_MAX_PCT_JUMP = 0.015  # 1.5%


def _filter_outlier_ticks(
    df: pd.DataFrame, price_col: str, max_pct_jump: float = _OUTLIER_MAX_PCT_JUMP
) -> pd.DataFrame:
    """Mask ticks whose pct-change from the *last known good* tick exceeds the threshold.

    Protects against bad ticks (typos / glitched feeds) from contaminating the
    `.last()` aggregation during resample and then propagating via ffill.
    Outlier ticks are set to NaN so subsequent ffill restores the prior good
    value rather than the spike.

    Iterative implementation: once a tick is flagged as outlier, the reference
    used for the next pct-change check stays at the previous good value. This
    prevents a sustained bad value (e.g. the same spike repeating for N bars)
    from "anchoring" the reference and slipping back through the filter.
    """
    if df.empty or price_col not in df.columns:
        return df

    values = df[price_col].to_numpy(copy=True)
    n = len(values)
    last_good = np.nan
    outlier_idx: list[int] = []

    for i in range(n):
        v = values[i]
        if np.isnan(v) or v <= 0:
            continue
        if np.isnan(last_good):
            last_good = v
            continue
        pct = abs(v - last_good) / last_good
        if pct > max_pct_jump:
            values[i] = np.nan
            outlier_idx.append(i)
        else:
            last_good = v

    if outlier_idx:
        sample = {
            df.index[idx]: float(df[price_col].iloc[idx]) for idx in outlier_idx[:3]
        }
        logger.warning(
            f"[Outlier] {price_col}: masked {len(outlier_idx)} tick(s) with > "
            f"{max_pct_jump * 100:.1f}% jump from last-good (examples: {sample})"
        )
        df[price_col] = values
    return df




def build_candles() -> pd.DataFrame:
    """
    [FIXED] Phase 1: เลียนแบบ app.py 100%
    - Join ข้อมูลดิบแบบ Outer แล้ว ffill เพื่อเชื่อมเช้าวันจันทร์กับวันศุกร์
    - Resample จาก DataFrame เดียวกันเพื่อให้ High/Low/Close ตรงกัน
    """
    logger.info("[P1] Building M10 candles (Exact Sync with app.py)...")
    # Anchor explicitly to Asia/Bangkok so the fetch window is correct on any
    # host TZ (UTC servers in particular). datetime.now().astimezone() would
    # use the system TZ and silently shift the window by hours.
    now_bkk = datetime.now(_BKK_TZ)

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

    # 2b. Mask outlier ticks (>1.5% intra-tick jump) BEFORE the join+ffill.
    # Without this, a single bad tick (e.g. 72,210 instead of 70,210) gets
    # picked up by resample.last() and then ffill carries it forward for the
    # entire window where no fresh ticks arrive — distorting downstream
    # rolling features and P&L calculations until a real tick lands again.
    hsh_df = _filter_outlier_ticks(hsh_df, "bid_96")
    hsh_df = _filter_outlier_ticks(hsh_df, "ask_96")
    ig_df  = _filter_outlier_ticks(ig_df, "spot_price")
    ig_df  = _filter_outlier_ticks(ig_df, "usd_thb", max_pct_jump=0.005)  # FX much tighter

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
