"""
backtest/data/merge_hsh.py
══════════════════════════════════════════════════════════════════════
Merge ราคา HSH จริง (Buy/Sell) เข้ากับ Final_Merged_Backtest_Data_M5.csv
รันครั้งเดียวก่อน backtest — ไม่ต้องรันซ้ำ

Input:
  merged_csv  : Final_Merged_Backtest_Data_M5.csv
                (Datetime, open, High, Low, Close, Volume, gold_spot_usd, usd_thb_rate)
  hsh_csv     : HSH965_gold_5min.csv
                (Datetime, Buy, Sell) — timestamp format "2026-02-03 01.55"

Output:
  output_csv  : Final_Merged_HSH_M5.csv
                เพิ่ม 3 columns:
                  hsh_buy      : ราคาที่ HSH รับซื้อ (เราขายได้ราคานี้)
                  hsh_sell     : ราคาที่ HSH ขาย (เราซื้อได้ราคานี้)
                  has_real_hsh : True/False — มีราคาจริงไหม

ข้อมูล HSH ครอบคลุม Feb 3 - Apr 2 เท่านั้น
ช่วง Dec 22 - Feb 2 จะได้ has_real_hsh=False → SimPortfolio fallback ใช้ Close + spread

Usage:
  python backtest/data/merge_hsh.py \
    --merged  backtest/data/Final_Merged_Backtest_Data_M5.csv \
    --hsh     backtest/data/HSH965_gold_5min.csv \
    --output  backtest/data/Final_Merged_HSH_M5.csv
══════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# tolerance: ถ้า timestamp ห่างกันเกิน 10 นาที → ถือว่าไม่มีข้อมูล HSH
TOLERANCE_MINUTES = 10


def _fix_hsh_timestamp(ts_str: str) -> str:
    """
    แปลง "2026-02-03 01.55" → "2026-02-03 01:55"
    HSH CSV ใช้ จุด แทน : ใน time part
    """
    import re
    # จับ pattern HH.MM ท้าย string แล้วแทนด้วย HH:MM
    return re.sub(r"(\d{2})\.(\d{2})$", r"\1:\2", str(ts_str).strip())


def merge_hsh(
    merged_csv: str,
    hsh_csv: str,
    output_csv: str,
    tolerance_minutes: int = TOLERANCE_MINUTES,
) -> pd.DataFrame:
    """
    Merge HSH Buy/Sell เข้า merged_csv ด้วย merge_asof backward
    คืน DataFrame ที่ merge แล้ว
    """
    tol = pd.Timedelta(minutes=tolerance_minutes)

    # ── 1. โหลด Final_Merged ─────────────────────────────────────
    logger.info(f"Loading merged CSV: {merged_csv}")
    main = pd.read_csv(merged_csv, encoding="utf-8-sig")
    main.columns = main.columns.str.strip()

    dt_col = next(
        (c for c in main.columns if c.lower() in ("datetime", "timestamp", "time")),
        None,
    )
    if dt_col is None:
        raise ValueError(f"ไม่พบ datetime column ใน {merged_csv}")

    main["timestamp"] = pd.to_datetime(main[dt_col], errors="coerce")
    main = main.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    logger.info(f"  main: {len(main):,} rows | {main['timestamp'].min()} → {main['timestamp'].max()}")

    # ── 2. โหลด HSH CSV + fix timestamp ──────────────────────────
    logger.info(f"Loading HSH CSV: {hsh_csv}")
    hsh = pd.read_csv(hsh_csv, encoding="utf-8-sig")
    hsh.columns = hsh.columns.str.strip()

    # fix timestamp format จุด→colon
    hsh_dt_col = next(
        (c for c in hsh.columns if c.lower() in ("datetime", "timestamp", "time")),
        None,
    )
    if hsh_dt_col is None:
        raise ValueError(f"ไม่พบ datetime column ใน {hsh_csv}")

    hsh["timestamp"] = hsh[hsh_dt_col].apply(_fix_hsh_timestamp)
    hsh["timestamp"] = pd.to_datetime(hsh["timestamp"], errors="coerce")
    bad = hsh["timestamp"].isna().sum()
    if bad > 0:
        logger.warning(f"  HSH: parse ไม่ได้ {bad} แถว → dropped")
    hsh = hsh.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)

    # normalize column names: Buy/buy → hsh_buy, Sell/sell → hsh_sell
    col_map = {}
    for c in hsh.columns:
        if c.lower() == "buy":
            col_map[c] = "hsh_buy"
        elif c.lower() == "sell":
            col_map[c] = "hsh_sell"
    hsh = hsh.rename(columns=col_map)

    if "hsh_buy" not in hsh.columns or "hsh_sell" not in hsh.columns:
        raise ValueError(
            f"ไม่พบ Buy/Sell columns ใน HSH CSV\n"
            f"  columns ที่พบ: {list(hsh.columns)}"
        )

    hsh["hsh_buy"]  = pd.to_numeric(hsh["hsh_buy"],  errors="coerce")
    hsh["hsh_sell"] = pd.to_numeric(hsh["hsh_sell"], errors="coerce")
    hsh = hsh.dropna(subset=["hsh_buy", "hsh_sell"])

    logger.info(
        f"  HSH: {len(hsh):,} rows | {hsh['timestamp'].min()} → {hsh['timestamp'].max()}\n"
        f"  HSH spread stats: mean={( hsh['hsh_sell'] - hsh['hsh_buy']).mean():.1f} "
        f"median={(hsh['hsh_sell'] - hsh['hsh_buy']).median():.1f} THB"
    )

    # ── 3. merge_asof — backward, tolerance 10 min ───────────────
    logger.info(f"Merging with tolerance={tolerance_minutes}min ...")
    merged = pd.merge_asof(
        main,
        hsh[["timestamp", "hsh_buy", "hsh_sell"]],
        on="timestamp",
        direction="backward",
        tolerance=tol,
    )

    # has_real_hsh = True เฉพาะแถวที่ได้ hsh_buy จริง (ไม่ใช่ NaN)
    merged["has_real_hsh"] = merged["hsh_buy"].notna()

    # แถวที่ไม่มีข้อมูล → ใส่ 0.0 เป็น sentinel (SimPortfolio check has_real_hsh ก่อน)
    merged["hsh_buy"]  = merged["hsh_buy"].fillna(0.0)
    merged["hsh_sell"] = merged["hsh_sell"].fillna(0.0)

    # ── 4. สรุป ───────────────────────────────────────────────────
    real_count = merged["has_real_hsh"].sum()
    total      = len(merged)
    pct        = real_count / total * 100

    logger.info(f"\n{'='*55}")
    logger.info(f"  Merge result: {total:,} rows total")
    logger.info(f"  has_real_hsh=True  : {real_count:,} rows ({pct:.1f}%)")
    logger.info(f"  has_real_hsh=False : {total - real_count:,} rows ({100-pct:.1f}%) ← fallback")
    logger.info(f"{'='*55}")

    # ── 5. บันทึก ─────────────────────────────────────────────────
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(output_csv, index=False, encoding="utf-8-sig")
    logger.info(f"✓ Saved: {output_csv}")

    return merged


def main():
    parser = argparse.ArgumentParser(description="Merge HSH real prices into backtest CSV")
    parser.add_argument(
        "--merged",
        default="services/agent/backtest/data/Final_Merged_Backtest_Data_M5.csv",
        help="Path to Final_Merged_Backtest_Data_M5.csv",
    )
    parser.add_argument(
        "--hsh",
        default="services/agent/backtest/data/HSH965_BuySell_Clean/output/HSH965_gold_5min.csv",
        help="Path to HSH965_gold_5min.csv",
    )
    parser.add_argument(
        "--output",
        default="backtest/data/Final_Merged_HSH_M5.csv",
        help="Output CSV path",
    )
    parser.add_argument(
        "--tolerance",
        type=int,
        default=TOLERANCE_MINUTES,
        help=f"Tolerance in minutes (default={TOLERANCE_MINUTES})",
    )
    args = parser.parse_args()

    try:
        df = merge_hsh(
            merged_csv=args.merged,
            hsh_csv=args.hsh,
            output_csv=args.output,
            tolerance_minutes=args.tolerance,
        )
        print(f"\n✓ Done — {len(df):,} rows saved to {args.output}")
    except Exception as e:
        logger.error(f"✗ Failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()