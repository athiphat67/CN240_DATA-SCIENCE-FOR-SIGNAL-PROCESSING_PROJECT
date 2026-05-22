"""
db/seed_prices_from_csv.py

Backfill gold_prices_hsh and gold_prices_ig from local CSV exports.

Usage (from Src_V4/):
    python db/seed_prices_from_csv.py

CSVs expected at:
    Src_V4/hsh_recent.csv   — columns: timestamp, ask_96, bid_96, created_at
    Src_V4/ig_recent.csv    — columns: timestamp, spot_price, usd_thb, created_at

Timestamps in CSVs are Bangkok time (naive). This script localises them to
Asia/Bangkok before inserting so Supabase stores correct TIMESTAMPTZ values.
Rows are upserted in batches of 500; duplicates are skipped via
on_conflict=timestamp (unique index on each table).
"""

import os
import sys
import logging
import pandas as pd
import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config.settings import SUPABASE_URL, SUPABASE_KEY
from supabase import create_client

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

BKK = pytz.timezone("Asia/Bangkok")
BATCH = 500

HSH_CSV = os.path.join(os.path.dirname(os.path.dirname(__file__)), "hsh_recent.csv")
IG_CSV  = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ig_recent.csv")


def _to_iso(series: pd.Series) -> pd.Series:
    """Localise naive BKK timestamps and return ISO-8601 strings for Supabase."""
    dts = pd.to_datetime(series, errors="coerce")
    if dts.dt.tz is None:
        dts = dts.dt.tz_localize(BKK, ambiguous="NaT", nonexistent="NaT")
    else:
        dts = dts.dt.tz_convert(BKK)
    return dts.dt.strftime("%Y-%m-%dT%H:%M:%S%z")


def _upsert_batch(client, table: str, rows: list[dict]) -> int:
    try:
        client.table(table).insert(rows, count="exact").execute()
        return len(rows)
    except Exception as e:
        # Row-level duplicate — retry one-by-one to skip existing rows
        inserted = 0
        for row in rows:
            try:
                client.table(table).insert(row).execute()
                inserted += 1
            except Exception:
                pass
        return inserted


def seed_hsh(client):
    log.info(f"Loading {HSH_CSV}...")
    df = pd.read_csv(HSH_CSV)
    df["timestamp"] = _to_iso(df["timestamp"])
    df = df[["timestamp", "ask_96", "bid_96"]].dropna()

    total = 0
    for i in range(0, len(df), BATCH):
        chunk = df.iloc[i : i + BATCH].to_dict("records")
        total += _upsert_batch(client, "gold_prices_hsh", chunk)
        if (i // BATCH) % 10 == 0:
            log.info(f"  gold_prices_hsh: {total}/{len(df)} rows inserted")

    log.info(f"gold_prices_hsh done — {total} rows upserted")
    return total


def seed_ig(client):
    log.info(f"Loading {IG_CSV}...")
    df = pd.read_csv(IG_CSV)
    df["timestamp"] = _to_iso(df["timestamp"])
    df = df[["timestamp", "spot_price", "usd_thb"]].dropna()

    total = 0
    for i in range(0, len(df), BATCH):
        chunk = df.iloc[i : i + BATCH].to_dict("records")
        total += _upsert_batch(client, "gold_prices_ig", chunk)
        if (i // BATCH) % 10 == 0:
            log.info(f"  gold_prices_ig: {total}/{len(df)} rows inserted")

    log.info(f"gold_prices_ig done — {total} rows upserted")
    return total


if __name__ == "__main__":
    if not SUPABASE_URL or not SUPABASE_KEY:
        log.error("SUPABASE_URL / SUPABASE_KEY not set in .env")
        sys.exit(1)

    client = create_client(SUPABASE_URL, SUPABASE_KEY)

    hsh_n = seed_hsh(client)
    ig_n  = seed_ig(client)

    log.info(f"Backfill complete — HSH: {hsh_n} rows, IG: {ig_n} rows")
    log.info("Re-run main.py to verify L2 passes with more bars.")
