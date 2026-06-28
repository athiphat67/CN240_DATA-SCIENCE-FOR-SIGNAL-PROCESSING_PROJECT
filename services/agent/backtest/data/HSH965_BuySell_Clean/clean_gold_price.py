"""
HSH Gold Price Data Cleaner
============================
รวมไฟล์ GetHistoryGoldPriceList* และ HSH965* ทั้งหมด
ทำความสะอาด → deduplicate → resample 1min / 5min → export CSV

วิธีใช้:
  1. วางไฟล์นี้ไว้ใน folder เดียวกับ GetHistoryGoldPriceList, GetHistoryGoldPriceList-1 ... -49
     และ HSH965_31Mar, HSH965_01Apr, HSH965_02Apr
  2. รัน:  python clean_gold_price.py
  3. จะได้:  gold_1min.csv  และ  gold_5min.csv
"""

import json
import os
import re
from datetime import datetime, timedelta, timezone
import pandas as pd

# ── Config ──────────────────────────────────────────────────────────────────
FOLDER = "services/agent/backtest/data/HSH965_BuySell_Clean/raw_data"            # เปลี่ยนถ้าไฟล์อยู่ที่อื่น เช่น  r"C:\Downloads\gold"
TZ_OFFSET = 7           # UTC+7 (เวลาไทย)
OUTPUT_1MIN = "services/agent/backtest/data/HSH965_BuySell_Clean/output_hsh/HSH965_gold_1min.csv"
OUTPUT_5MIN = "services/agent/backtest/data/HSH965_BuySell_Clean/output_hsh/HSH965_gold_5min.csv"
DATETIME_FORMAT = "%Y-%m-%d %H.%M"    # 2026-03-30 23.59

# ── Helpers ──────────────────────────────────────────────────────────────────
TH_TZ = timezone(timedelta(hours=TZ_OFFSET))

def parse_market_date(raw: str):
    """
    รับ string ISO8601 เช่น '2026-03-30T23:59:31.587'
    คืน datetime aware (Asia/Bangkok UTC+7)
    ถ้า parse ไม่ได้ คืน None
    """
    if not raw or not isinstance(raw, str):
        return None
    # ตัด fractional seconds ให้เหลือแค่ 6 หลัก (microseconds)
    raw_clean = re.sub(r'(\.\d{6})\d+', r'\1', raw.strip())
    # รองรับทั้งมี/ไม่มี timezone suffix
    fmts = [
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    ]
    dt = None
    for fmt in fmts:
        try:
            dt = datetime.strptime(raw_clean, fmt)
            break
        except ValueError:
            continue
    if dt is None:
        return None
    # ถ้า naive → ถือว่าเป็นเวลาไทยอยู่แล้ว
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TH_TZ)
    return dt


def validate_datetime(dt) -> tuple[bool, str]:
    """ตรวจสอบความสมเหตุสมผลของเวลา"""
    if dt is None:
        return False, "parse ไม่ได้"
    # ช่วงเวลาที่สมเหตุสมผล: 2020-01-01 ถึง วันพรุ่งนี้
    lo = datetime(2020, 1, 1, tzinfo=TH_TZ)
    hi = datetime.now(tz=TH_TZ) + timedelta(days=1)
    if dt < lo:
        return False, f"เก่าเกินไป ({dt.date()})"
    if dt > hi:
        return False, f"อนาคตเกินไป ({dt.date()})"
    return True, "ok"


def load_file(path: str) -> list[dict]:
    """โหลด JSON ไฟล์ คืน list of records"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    try:
        return data["Response"]["GoldPriceList"]
    except (KeyError, TypeError):
        print(f"  ⚠️  ไม่พบ Response.GoldPriceList ใน {os.path.basename(path)}")
        return []


# ── Scan files ───────────────────────────────────────────────────────────────
pattern_hist = re.compile(r'^GetHistoryGoldPriceList(-\d+)?$', re.IGNORECASE)
pattern_hsh  = re.compile(r'^HSH965_', re.IGNORECASE)

files_found = []
for name in os.listdir(FOLDER):
    if pattern_hist.match(name) or pattern_hsh.match(name):
        files_found.append(os.path.join(FOLDER, name))

if not files_found:
    print("❌ ไม่พบไฟล์ใดเลย กรุณาตรวจสอบ FOLDER path")
    exit(1)

print(f"✅ พบไฟล์ทั้งหมด {len(files_found)} ไฟล์")

# ── Load & parse ─────────────────────────────────────────────────────────────
rows = []
bad_count = 0

for path in sorted(files_found):
    name = os.path.basename(path)
    records = load_file(path)
    file_bad = 0
    for r in records:
        dt = parse_market_date(r.get("MarketDate") or r.get("MarketDateStr"))
        ok, reason = validate_datetime(dt)
        if not ok:
            file_bad += 1
            bad_count += 1
            continue
        buy  = r.get("HSHBuy")
        sell = r.get("HSHSell")
        if buy is None or sell is None:
            file_bad += 1
            bad_count += 1
            continue
        rows.append({
            "GoldPriceId": r.get("GoldPriceId"),
            "dt": dt,
            "Buy": float(buy),
            "Sell": float(sell),
        })
    status = f"({file_bad} records มีปัญหา)" if file_bad else ""
    print(f"  📄 {name:<40} {len(records):>6} records {status}")

print(f"\n📊 รวมทั้งหมด: {len(rows) + bad_count} records | ใช้ได้: {len(rows)} | ข้ามไป: {bad_count}")

# ── DataFrame & Deduplicate ───────────────────────────────────────────────────
df = pd.DataFrame(rows)
before = len(df)
df = df.drop_duplicates(subset="GoldPriceId", keep="first")
after = len(df)
print(f"🔁 Deduplicate: ลบ {before - after} รายการซ้ำ → เหลือ {after} records")

df = df.sort_values("dt").reset_index(drop=True)

# ── Check missing days ────────────────────────────────────────────────────────
all_dates = pd.to_datetime(df["dt"]).dt.date.unique()
all_dates_sorted = sorted(all_dates)
date_min, date_max = all_dates_sorted[0], all_dates_sorted[-1]

expected_days = pd.date_range(date_min, date_max, freq="D").date
missing_days = sorted(set(expected_days) - set(all_dates_sorted))

print(f"\n📅 ช่วงวันที่: {date_min} ถึง {date_max}")
print(f"   มีข้อมูล {len(all_dates_sorted)} วัน | คาดว่าควรมี {len(expected_days)} วัน")
if missing_days:
    print(f"   ⚠️  วันที่ขาดหาย ({len(missing_days)} วัน):")
    for d in missing_days:
        print(f"        - {d}")
else:
    print("   ✅ ไม่มีวันขาดหาย")

# ── Resample helper ───────────────────────────────────────────────────────────
def resample_and_export(df: pd.DataFrame, freq: str, outfile: str):
    """
    Resample ตาม freq ('1min' หรือ '5min')
    ใช้ราคาปิด (last) ของแต่ละช่วง
    Export CSV พร้อม format datetime
    """
    ts = df.set_index("dt")[["Buy", "Sell"]]
    ts.index = pd.DatetimeIndex(ts.index)

    resampled = ts.resample(freq, label="left", closed="left").last().dropna()

    out = resampled.reset_index()
    out.columns = ["Datetime", "Buy", "Sell"]
    out["Buy"]  = out["Buy"].astype(int)
    out["Sell"] = out["Sell"].astype(int)
    out["Datetime"] = out["Datetime"].dt.strftime(DATETIME_FORMAT)

    out.to_csv(outfile, index=False, encoding="utf-8-sig")
    print(f"  💾 {outfile}  →  {len(out):,} rows")
    return out

print(f"\n⏱️  กำลัง resample...")
resample_and_export(df, "1min",  OUTPUT_1MIN)
resample_and_export(df, "5min",  OUTPUT_5MIN)

print("\n✅ เสร็จสิ้น!")
