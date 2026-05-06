# HSH ML Trading System — Complete Architecture & Reference Guide

**ฮั่วเซ่งเฮง Gold · XGBoost Ranker Signal · Fractional Buy/Sell Simulation · Supabase + Discord**

> **Stack:** Python 3.11 · PostgreSQL (Supabase) · APScheduler · Discord Webhook
> **Model:** LambdaMART v11 (XGBoost Ranker · 420 trees) · Timeframe M10
> **Signal:** BUY only (Long-only simulation) · Fractional Gold (THB-based)

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Directory Structure](#directory-structure)
3. [Phase 0 — Infrastructure & Config](#phase-0)
4. [Phase 1 — M10 Candle Builder](#phase-1)
5. [Phase 2 — Feature Engine (M10)](#phase-2)
6. [Phase 3 — Model Inference](#phase-3)
7. [Phase 4 — Signal Gate](#phase-4)
8. [Phase 5 — Order Simulator](#phase-5)
9. [Phase 6 — TP/SL Calculator](#phase-6)
10. [Phase 7 — Position Monitor](#phase-7)
11. [Phase 8 — Supabase Schema & Writer](#phase-8)
12. [Phase 9 — Discord Notifier](#phase-9)
13. [Phase 10 — Scheduler Orchestrator](#phase-10)
14. [Feature Engineering Deep Dive (M10)](#feature-engineering)
15. [Logging Strategy](#logging)
16. [Deployment Guide](#deployment)
17. [Data Flow Summary](#data-flow)
18. [Error Handling & Failsafes](#errors)
19. [Testing & Paper Trading](#testing)
20. [Build Order](#build-order)

---

<a name="quick-start"></a>
## Quick Start

```bash
# 1. Clone repo
git clone <repo-url> hsh_ml_trader
cd hsh_ml_trader

# 2. Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Setup environment variables
cp .env.example .env
# แก้ไข .env ด้วย credentials จริง

# 5. ตรวจสอบ Supabase schema
psql $DATABASE_URL < db/supabase_schema.sql

# 6. รัน paper trading (dry run) ก่อน
DRY_RUN=true python main.py

# 7. รัน live (เมื่อ test ผ่านแล้ว)
python main.py
```

### Prerequisites

| Requirement | Version | หมายเหตุ |
|-------------|---------|----------|
| Python | 3.11+ | ทดสอบบน 3.11.x |
| Supabase project | — | ต้องมี service role key |
| Discord webhook | — | สร้างผ่าน Server Settings → Integrations |
| Model file | lambdamart_v11.json | ได้จาก training pipeline |

---

<a name="directory-structure"></a>
## Directory Structure

```
hsh_ml_trader/
├── README.md                       ← (ไฟล์นี้)
├── requirements.txt                ← Python dependencies + pinned versions
├── .env.example                    ← Template สำหรับ environment variables
├── .env                            ← Secrets จริง (ห้าม commit)
├── .gitignore
├── main.py                         ← Entry point
│
├── config/
│   └── settings.py                 ← All constants (ห้าม hardcode ใน logic)
│
├── core/
│   ├── candle_builder.py           ← Phase 1
│   ├── feature_engine.py           ← Phase 2
│   ├── model_inference.py          ← Phase 3
│   ├── signal_gate.py              ← Phase 4
│   ├── order_simulator.py          ← Phase 5
│   ├── tp_sl_calculator.py         ← Phase 6
│   └── position_monitor.py         ← Phase 7
│
├── db/
│   ├── supabase_writer.py          ← Phase 8
│   └── supabase_schema.sql         ← DDL
│
├── notifier/
│   └── discord_notifier.py         ← Phase 9
│
├── scheduler/
│   └── orchestrator.py             ← Phase 10
│
├── models/
│   ├── lambdamart_v11.json         ← Trained model (XGBoost native format)
│   └── lambdamart_v11_meta.json    ← Feature list, training date, version
│
├── logs/                           ← Auto-created at runtime
│   ├── system.log
│   └── trading.log
│
├── fallback/                       ← Auto-created สำหรับ Supabase fail
│   └── pending_inserts.jsonl
│
└── tests/
    ├── test_candle_builder.py
    ├── test_feature_engine.py
    ├── test_signal_gate.py
    ├── test_order_simulator.py
    └── test_tp_sl_calculator.py
```

---

<a name="phase-0"></a>
## Phase 0 — Infrastructure & Config

### `requirements.txt`

```txt
# Core
xgboost==2.0.3
pandas==2.2.2
numpy==1.26.4
scipy==1.13.0

# Database
supabase==2.4.0

# Scheduling
APScheduler==3.10.4

# HTTP
httpx==0.27.0

# Config
python-dotenv==1.0.1

# Logging
structlog==24.1.0

# Testing
pytest==8.2.0
pytest-mock==3.14.0
```

---

### `.env.example`

```bash
# ─── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL=https://xxxxxxxxxxxxxxxxxxxx.supabase.co
SUPABASE_KEY=eyJ...                          # service role key (ไม่ใช่ anon key)

# ─── Discord ───────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
DISCORD_MENTION_ID=123456789012345678        # user ID สำหรับ @mention ตอน SL hit

# ─── Mode ──────────────────────────────────────────────────────────────────────
DRY_RUN=false                                # true = paper trading (ไม่เขียน DB)
LOG_LEVEL=INFO                               # DEBUG | INFO | WARNING | ERROR
TIMEZONE=Asia/Bangkok
```

---

### `config/settings.py`

```python
import os
from dotenv import load_dotenv

load_dotenv()

# ─── Mode ─────────────────────────────────────────────────────────────────────
DRY_RUN     = os.getenv("DRY_RUN", "false").lower() == "true"
LOG_LEVEL   = os.getenv("LOG_LEVEL", "INFO")
TIMEZONE    = os.getenv("TIMEZONE", "Asia/Bangkok")

# ─── Model ────────────────────────────────────────────────────────────────────
MODEL_PATH      = "models/lambdamart_v11.json"
MODEL_META_PATH = "models/lambdamart_v11_meta.json"
SIGNAL_THRESHOLD    = 0.65          # ranker score ≥ this → BUY
TIMEFRAME_MIN       = 10            # M10
LOOKBACK_BARS       = 2200          # bars to load (≥ OLS_WINDOW 2016)

# ─── Gold Constants ───────────────────────────────────────────────────────────
WEIGHT_TH_BAHT      = 15.244        # grams per 1 บาทไทย
WEIGHT_TROY_OUNCE   = 31.1035       # grams per troy oz
PURITY_TH_GOLD      = 0.965
PURITY_GLOBAL_GOLD  = 0.995
CONV_FACTOR         = (WEIGHT_TH_BAHT / WEIGHT_TROY_OUNCE) * (PURITY_TH_GOLD / PURITY_GLOBAL_GOLD)
# ≈ 0.4744

GOLD_WEIGHT_DECIMALS = 5            # truncate (ไม่ใช่ round) ทศนิยม 5 ตำแหน่ง

# ─── Trade Sizing ─────────────────────────────────────────────────────────────
INVESTMENT_AMOUNT_THB = 1_000.0
MAX_CONCURRENT_TRADES = 1

# ─── TP/SL ────────────────────────────────────────────────────────────────────
TP_ATR_MULTIPLIER   = 1.5
SL_ATR_MULTIPLIER   = 1.0
MIN_TP_DISTANCE_THB = 50.0
MAX_SL_DISTANCE_THB = 200.0

# ─── Session Definitions (M10 bars) ───────────────────────────────────────────
# Morning:   09:00–10:30 → 9 bars × 10min  = 90 min
# Afternoon: 13:00–15:20 → 14 bars × 10min = 140 min
# Night:     18:00–22:00 → 24 bars × 10min = 240 min
SESSION_HOURS = {
    "Morning"   : (9*60,   9*60 + 90),   # 540–630 นาทีนับจากเที่ยงคืน
    "Afternoon" : (13*60,  13*60 + 140), # 780–920
    "Night"     : (18*60,  18*60 + 240), # 1080–1320
}
SESSION_EXPECTED_BARS = {
    "Morning"   : 9,
    "Afternoon" : 14,
    "Night"     : 24,
}

# ─── Feature Windows (M10) ────────────────────────────────────────────────────
OLS_WINDOW          = 2016   # 2016 × 10min ≈ 2 สัปดาห์
ATR_WINDOW          = 48     # 48 × 10min  = 8 ชั่วโมง
CORR_WINDOW         = 18
VOL_WINDOW          = 144
SPREAD_NORM_WINDOW  = 144

# ─── Supabase ─────────────────────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# ─── Discord ──────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_MENTION_ID  = os.getenv("DISCORD_MENTION_ID", "")
```

> **หมายเหตุ:** Session Afternoon ถูกกำหนดเป็น 13:00–15:20 (14 bars × 10min = 140 นาที) ไม่ใช่จนถึง 17:30 เพื่อให้สอดคล้องกับ `SESSION_EXPECTED_BARS`

---

### `models/lambdamart_v11_meta.json`

```json
{
  "model_name": "lambdamart_v11",
  "trained_at": "2025-07-15T10:00:00+07:00",
  "timeframe": "M10",
  "n_trees": 420,
  "feature_cols": [
    "F_Syn_Price", "F_Thai_Premium", "F_Corr_XAU_USD",
    "F_XAU_Mom_Short", "F_XAU_Mom_Mid", "F_USD_Mom",
    "F_ATR_48", "F_Regime", "F_FSP", "F_SA_TWAP_Dev",
    "F_SA_MDD", "F_SA_Vol", "F_SA_Range", "F_SA_Position",
    "F_Historical_Vol_THB", "F_Remaining_Vol", "F_SRVR",
    "F_Price_Vs_Open", "F_Mom_1bar", "F_Mom_3bar",
    "F_SA_Drawdown_Pct", "F_HSH_vs_THBGold_Dev",
    "F_DayOfWeek", "F_MinuteOfDay",
    "F_RSI_14", "F_RSI_6", "F_BB_Pos", "F_XAU_Spread_Norm",
    "F_Hour_Sin", "F_Hour_Cos", "F_Session_Type",
    "F_HSH_Spread", "F_Spread_Cost_Pct", "F_Spread_vs_ATR"
  ],
  "signal_threshold": 0.65,
  "notes": "Retrained on M10 data. Dropped F_SA_Vol from v10."
}
```

> **สำคัญ:** `feature_cols` ใน metadata นี้คือ **แหล่งความจริงเดียว** สำหรับ feature list ห้าม hardcode ใน `model_inference.py`

---

<a name="phase-1"></a>
## Phase 1 — M10 Candle Builder

**จุดประสงค์:** ดึงราคา HSH (bid/ask), XAU/USD, USD/THB จาก DB → aggregate เป็น M10 OHLCV rolling buffer

### Input Tables

| Source | ตาราง | ข้อมูลที่ต้องการ |
|--------|-------|-----------------|
| Supabase | `hsh_prices` (second-level) | `timestamp`, `bid`, `ask` |
| Supabase | `xau_prices` (second-level) | `timestamp`, `open`, `high`, `low`, `close`, `spread` |
| Supabase | `usd_thb_prices` (second-level) | `timestamp`, `close` |

### M10 Aggregation Query (PostgreSQL-compatible)

`FIRST()`/`LAST()` ไม่มีใน PostgreSQL ใช้ CTE + `ROW_NUMBER()` แทน:

```sql
WITH ranked AS (
    SELECT
        timestamp,
        ask,
        bid,
        date_trunc('minute', timestamp)
            - INTERVAL '1 minute' * (EXTRACT(MINUTE FROM timestamp)::int % 10)
            AS bar_time,
        ROW_NUMBER() OVER (
            PARTITION BY date_trunc('minute', timestamp)
                - INTERVAL '1 minute' * (EXTRACT(MINUTE FROM timestamp)::int % 10)
            ORDER BY timestamp ASC
        ) AS rn_asc,
        ROW_NUMBER() OVER (
            PARTITION BY date_trunc('minute', timestamp)
                - INTERVAL '1 minute' * (EXTRACT(MINUTE FROM timestamp)::int % 10)
            ORDER BY timestamp DESC
        ) AS rn_desc
    FROM hsh_prices
    WHERE timestamp >= NOW() - INTERVAL '22000 minutes'
)
SELECT
    bar_time,
    MAX(CASE WHEN rn_asc  = 1 THEN ask END) AS open_ask,
    MAX(ask)                                 AS high_ask,
    MIN(ask)                                 AS low_ask,
    MAX(CASE WHEN rn_desc = 1 THEN ask END) AS close_ask,
    MAX(CASE WHEN rn_asc  = 1 THEN bid END) AS open_bid,
    MAX(bid)                                 AS high_bid,
    MIN(bid)                                 AS low_bid,
    MAX(CASE WHEN rn_desc = 1 THEN bid END) AS close_bid
FROM ranked
GROUP BY bar_time
ORDER BY bar_time ASC;
```

> **หรือใช้ pandas resample** ถ้าดึงข้อมูลมา Python แล้ว:
> ```python
> candles = raw_df.resample("10T").agg({"ask": ["first", "max", "min", "last"]})
> ```

### Output Format — `candles_df`

```
Index  : DatetimeIndex (UTC+7, freq='10T')
Shape  : (LOOKBACK_BARS,) × 15 columns

Columns:
  bar_time        : datetime64[ns, Asia/Bangkok]
  hsh_open_ask    : float64   ← ราคาขายออก (ask) เปิด
  hsh_high_ask    : float64
  hsh_low_ask     : float64
  hsh_close_ask   : float64   ← entry price
  hsh_open_bid    : float64
  hsh_high_bid    : float64
  hsh_low_bid     : float64
  hsh_close_bid   : float64   ← mark-to-market / TP-SL check
  xau_open        : float64
  xau_high        : float64
  xau_low         : float64
  xau_close       : float64
  xau_spread      : float64
  usd_close       : float64
```

### Validation Rules

```python
assert len(candles_df) >= OLS_WINDOW + 50,    "ข้อมูลไม่พอสำหรับ OLS"
assert candles_df.index.is_monotonic_increasing, "Candles ต้องเรียงตามเวลา"
assert candles_df["hsh_close_ask"].notna().all(), "ห้ามมี NaN ใน close_ask"
assert (candles_df["hsh_close_ask"] > candles_df["hsh_close_bid"]).all(), "Ask > Bid เสมอ"
```

---

<a name="phase-2"></a>
## Phase 2 — Feature Engine (M10)

**จุดประสงค์:** คำนวณ 34 features จาก `candles_df` → return แถวล่าสุด (แท่ง M10 ปัจจุบัน)

### TypedDict สำหรับ features_row

```python
from typing import TypedDict

class FeaturesRow(TypedDict):
    # ─── Meta ──────────────────────────────────────────────────────────────────
    bar_time        : str
    session         : str    # Morning / Afternoon / Night / Closed
    # ─── Synthetic ─────────────────────────────────────────────────────────────
    F_Syn_Price     : float
    F_Thai_Premium  : float
    # ─── Macro ─────────────────────────────────────────────────────────────────
    F_Corr_XAU_USD  : float
    F_XAU_Mom_Short : float
    F_XAU_Mom_Mid   : float
    F_USD_Mom       : float
    F_ATR_48        : float
    F_Regime        : int    # -1 or +1
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
    F_Session_Type  : int    # 0=Morning, 1=Afternoon, 2=Night
    F_HSH_Spread    : float
    F_Spread_Cost_Pct: float
    F_Spread_vs_ATR : float
    # ─── Pass-through (ไม่เข้า model) ──────────────────────────────────────────
    hsh_close_ask   : float
    hsh_close_bid   : float
    xau_close       : float
    usd_close       : float
```

### Session Assignment (M10)

```python
from config.settings import SESSION_HOURS

def assign_session(bar_time: datetime) -> str:
    minutes = bar_time.hour * 60 + bar_time.minute
    for name, (start, end) in SESSION_HOURS.items():
        if start <= minutes < end:
            return name
    return "Closed"
```

### Feature Windows (M5 → M10 Mapping)

| Feature | Window M5 (เดิม) | Window M10 (ใหม่) | ความหมาย |
|---------|-----------------|---------------------|----------|
| `F_Corr_XAU_USD` | 18 bars (90m) | 18 bars (3h) | rolling corr |
| `F_XAU_Mom_Short` | 3 bars (15m) | 3 bars (30m) | short momentum |
| `F_XAU_Mom_Mid` | 12 bars (1h) | 12 bars (2h) | mid momentum |
| `F_USD_Mom` | 6 bars (30m) | 6 bars (1h) | USD momentum |
| `F_ATR_48` | 48 bars (4h) | 48 bars (8h) | volatility base |
| `F_FSP` (Morning) | 18 bars | 9 bars | session progress |
| `F_FSP` (Afternoon) | 27 bars | 14 bars | session progress |
| `F_FSP` (Night) | 48 bars | 24 bars | session progress |
| `F_Historical_Vol_THB` | 144 bars (12h) | 144 bars (24h) | rolling std |
| `F_XAU_Spread_Norm` | 144 bars | 144 bars (24h) | spread normalization |
| OLS rolling window | 2016 bars (1w) | 2016 bars (2w) | synthetic price |

---

<a name="phase-3"></a>
## Phase 3 — Model Inference

**จุดประสงค์:** โหลด LambdaMART v11 → score แถวปัจจุบัน → ส่ง score ไป Phase 4

### Model Loading (ใช้ XGBoost native format แทน pickle)

```python
import json
import xgboost as xgb
import pandas as pd
from config.settings import MODEL_PATH, MODEL_META_PATH

# โหลดครั้งเดียวตอน startup
model = xgb.XGBRanker()
model.load_model(MODEL_PATH)               # .json format, portable ข้าม Python version

with open(MODEL_META_PATH) as f:
    meta = json.load(f)

FEATURE_COLS = meta["feature_cols"]        # source of truth จาก metadata
MODEL_VERSION = meta["model_name"]

def run_inference(features_row: FeaturesRow) -> dict:
    X = pd.DataFrame([features_row])[FEATURE_COLS]

    # Validate ก่อน inference
    missing = [c for c in FEATURE_COLS if c not in features_row]
    if missing:
        raise ValueError(f"Missing features: {missing}")

    nan_cols = X.columns[X.isna().any()].tolist()
    if nan_cols:
        raise ValueError(f"NaN in critical features: {nan_cols}")

    score = float(model.predict(X)[0])
    return {
        "bar_time"      : features_row["bar_time"],
        "ranker_score"  : score,
        "model_version" : MODEL_VERSION,
        "features_snap" : dict(features_row),
    }
```

> **ทำไมไม่ใช้ pickle:** pickle ไม่ portable ข้าม Python version, มีความเสี่ยง security (arbitrary code execution เมื่อโหลดไฟล์จากแหล่งที่ไม่น่าเชื่อถือ) XGBoost native `.json` format แก้ทั้ง 2 ปัญหา

### Output Format

```python
{
    "bar_time"      : "2025-08-01T09:50:00+07:00",
    "ranker_score"  : 0.7823,
    "model_version" : "lambdamart_v11",
    "features_snap" : { ...34 features... }
}
```

---

<a name="phase-4"></a>
## Phase 4 — Signal Gate

**จุดประสงค์:** กรองสัญญาณที่ไม่เหมาะสมออก → ผ่านเฉพาะ BUY ที่ถูกต้อง

### Gate Conditions (ทุกข้อต้อง `True` จึงผ่าน)

```python
from config.settings import SIGNAL_THRESHOLD, DRY_RUN

def evaluate_signal_gate(inference_result: dict, features_row: FeaturesRow) -> dict:
    score   = inference_result["ranker_score"]
    session = features_row["session"]
    F_SRVR  = features_row["F_SRVR"]
    F_XAU_Spread_Norm = features_row["F_XAU_Spread_Norm"]
    F_Regime = features_row["F_Regime"]

    gates = {
        "score_gate"       : score >= SIGNAL_THRESHOLD,
        "no_open_position" : count_open_positions() == 0,
        "market_open"      : session != "Closed",
        "srvr_gate"        : F_SRVR >= 0.15,
        "spread_gate"      : F_XAU_Spread_Norm < 2.5,
        "regime_gate"      : F_Regime == 1,
    }

    passed = all(gates.values())
    reject_reason = None if passed else next(k for k, v in gates.items() if not v)

    return {
        "signal_id"     : f"sig_{features_row['bar_time'][:19].replace('-','').replace(':','').replace('T','_')}",
        "bar_time"      : features_row["bar_time"],
        "session"       : session,
        "signal_type"   : "BUY",
        "ranker_score"  : score,
        "gates_passed"  : gates,
        "passed"        : passed,
        "reject_reason" : reject_reason,
        "dry_run"       : DRY_RUN,
        "features_snap" : inference_result["features_snap"],
    }
```

---

<a name="phase-5"></a>
## Phase 5 — Order Simulator (Fractional Gold)

**จุดประสงค์:** คำนวณน้ำหนักทองและต้นทุนจริงสำหรับ investment amount ที่กำหนด

### Fractional Gold Calculation

```python
import math
from config.settings import (
    INVESTMENT_AMOUNT_THB, CONV_FACTOR,
    WEIGHT_TH_BAHT, WEIGHT_TROY_OUNCE, GOLD_WEIGHT_DECIMALS
)

def simulate_buy(ask_price: float, bid_price: float,
                 investment_thb: float = INVESTMENT_AMOUNT_THB) -> dict:

    # น้ำหนักทอง = (investment / ask_price) truncate ไม่ใช่ round
    raw_weight   = investment_thb / ask_price
    gold_weight  = math.floor(raw_weight * 10**GOLD_WEIGHT_DECIMALS) / 10**GOLD_WEIGHT_DECIMALS

    actual_cost  = gold_weight * ask_price
    spread_cost  = gold_weight * (ask_price - bid_price)
    mtm_value    = gold_weight * bid_price     # mark-to-market ณ เวลาซื้อ
    breakeven_bid = ask_price                   # ต้องขายที่ ask เก่าหรือสูงกว่าจึงจะ break even

    return {
        "entry_ask_price" : ask_price,
        "entry_bid_price" : bid_price,
        "hsh_spread"      : ask_price - bid_price,
        "investment_thb"  : investment_thb,
        "gold_weight"     : gold_weight,
        "actual_cost_thb" : actual_cost,
        "spread_cost_thb" : spread_cost,
        "mtm_value_thb"   : mtm_value,
        "breakeven_bid"   : breakeven_bid,
    }
```

---

<a name="phase-6"></a>
## Phase 6 — TP/SL Calculator

**จุดประสงค์:** คำนวณ TP/SL จาก ATR → validate ก่อนเปิด position

```python
from config.settings import (
    TP_ATR_MULTIPLIER, SL_ATR_MULTIPLIER,
    MIN_TP_DISTANCE_THB, MAX_SL_DISTANCE_THB
)

def calculate_tp_sl(order: dict, atr_48: float) -> dict:
    entry_ask = order["entry_ask_price"]
    entry_bid = order["entry_bid_price"]

    tp_distance = atr_48 * TP_ATR_MULTIPLIER
    sl_distance = atr_48 * SL_ATR_MULTIPLIER

    tp_bid = entry_bid + tp_distance
    sl_bid = entry_bid - sl_distance

    # P&L คำนวณจาก bid (ราคารับซื้อ) เทียบกับ entry ask
    tp_pnl = (tp_bid - entry_ask) * order["gold_weight"]
    sl_pnl = (sl_bid - entry_ask) * order["gold_weight"]
    rr     = tp_distance / sl_distance if sl_distance > 0 else 0

    # Validation
    valid = (tp_distance >= MIN_TP_DISTANCE_THB and sl_distance <= MAX_SL_DISTANCE_THB)

    return {
        **order,
        "atr_used"          : atr_48,
        "tp_bid_price"      : tp_bid,
        "sl_bid_price"      : sl_bid,
        "tp_distance_thb"   : tp_distance,
        "sl_distance_thb"   : sl_distance,
        "tp_pnl_thb"        : tp_pnl,
        "sl_pnl_thb"        : sl_pnl,
        "risk_reward_ratio" : rr,
        "tp_sl_valid"       : valid,
        "reject_reason"     : None if valid else "invalid_tp_sl",
    }
```

---

<a name="phase-7"></a>
## Phase 7 — Position Monitor

**จุดประสงค์:** ตรวจสอบ open positions ทุก 1 นาที → ถ้า bid ถึง TP หรือ SL → ปิด position

### Helper Functions (ที่ต้องกำหนดชัดเจน)

```python
from config.settings import SESSION_HOURS
from datetime import datetime
import pytz

TZ = pytz.timezone("Asia/Bangkok")

def is_market_hours(dt: datetime) -> bool:
    """คืนค่า True ถ้าตลาดเปิดอยู่ (ไม่ใช่ Closed)"""
    minutes = dt.hour * 60 + dt.minute
    return any(start <= minutes < end for start, end in SESSION_HOURS.values())

def get_current_session(dt: datetime) -> str:
    minutes = dt.hour * 60 + dt.minute
    for name, (start, end) in SESSION_HOURS.items():
        if start <= minutes < end:
            return name
    return "Closed"

def position_opened_this_session(pos: dict, current_time: datetime) -> bool:
    """True ถ้า position ถูกเปิดใน session เดียวกับ current_time"""
    entry_time = datetime.fromisoformat(pos["entry_time"]).astimezone(TZ)
    return get_current_session(entry_time) == get_current_session(current_time)

def monitor_positions(current_bid: float, current_time: datetime) -> list[dict]:
    open_positions = fetch_open_positions_from_supabase()
    results = []

    for pos in open_positions:
        close_event = None

        if current_bid >= pos["tp_bid_price"]:
            close_event = {"close_reason": "TP", "close_bid_price": current_bid}

        elif current_bid <= pos["sl_bid_price"]:
            close_event = {"close_reason": "SL", "close_bid_price": current_bid}

        elif (not is_market_hours(current_time)
              and position_opened_this_session(pos, current_time)):
            close_event = {"close_reason": "SESSION_END", "close_bid_price": current_bid}

        if close_event:
            pnl_thb = (close_event["close_bid_price"] - pos["entry_ask_price"]) * pos["gold_weight"]
            results.append({
                "position_id"      : pos["id"],
                "close_at"         : current_time,
                "realized_pnl_thb" : pnl_thb,
                "pnl_pct"          : pnl_thb / pos["actual_cost_thb"] * 100,
                **close_event,
            })

    return results
```

---

<a name="phase-8"></a>
## Phase 8 — Supabase Schema & Writer

### DDL Schema

```sql
-- ─── Table 1: signals ──────────────────────────────────────────────────────
CREATE TABLE signals (
    id              TEXT PRIMARY KEY,          -- "sig_YYYYMMDD_HHMMSS"
    bar_time        TIMESTAMPTZ NOT NULL,
    session         TEXT NOT NULL,
    signal_type     TEXT NOT NULL DEFAULT 'BUY',
    ranker_score    NUMERIC(10,6) NOT NULL,
    passed          BOOLEAN NOT NULL,
    reject_reason   TEXT,
    dry_run         BOOLEAN NOT NULL DEFAULT false,
    features_snap   JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Table 2: positions ────────────────────────────────────────────────────
CREATE TABLE positions (
    id                  TEXT PRIMARY KEY,
    signal_id           TEXT REFERENCES signals(id),
    status              TEXT NOT NULL DEFAULT 'OPEN',

    entry_ask_price     NUMERIC(10,2) NOT NULL,
    entry_bid_price     NUMERIC(10,2) NOT NULL,
    hsh_spread          NUMERIC(10,2) NOT NULL,
    entry_time          TIMESTAMPTZ NOT NULL,
    investment_thb      NUMERIC(12,2) NOT NULL,
    gold_weight         NUMERIC(12,5) NOT NULL,
    actual_cost_thb     NUMERIC(12,4) NOT NULL,
    spread_cost_thb     NUMERIC(12,4) NOT NULL,
    breakeven_bid       NUMERIC(10,2) NOT NULL,
    atr_used            NUMERIC(10,2),

    tp_bid_price        NUMERIC(10,2),
    sl_bid_price        NUMERIC(10,2),
    tp_distance_thb     NUMERIC(10,2),
    sl_distance_thb     NUMERIC(10,2),
    tp_pnl_thb          NUMERIC(12,4),
    sl_pnl_thb          NUMERIC(12,4),
    risk_reward_ratio   NUMERIC(6,2),

    close_bid_price     NUMERIC(10,2),
    close_at            TIMESTAMPTZ,
    close_reason        TEXT,              -- TP / SL / SESSION_END / MANUAL
    realized_pnl_thb    NUMERIC(12,4),
    pnl_pct             NUMERIC(8,4),

    dry_run             BOOLEAN NOT NULL DEFAULT false,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Table 3: bar_logs (optional — debug และ retrain) ──────────────────────
CREATE TABLE bar_logs (
    id              BIGSERIAL PRIMARY KEY,
    bar_time        TIMESTAMPTZ NOT NULL UNIQUE,
    session         TEXT,
    ranker_score    NUMERIC(10,6),
    signal_passed   BOOLEAN,
    hsh_close_ask   NUMERIC(10,2),
    hsh_close_bid   NUMERIC(10,2),
    atr_48          NUMERIC(10,2),
    features_snap   JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
) PARTITION BY RANGE (created_at);

-- Retention: เก็บ 90 วัน, สร้าง partition ทุกเดือน
CREATE TABLE bar_logs_2025_08 PARTITION OF bar_logs
    FOR VALUES FROM ('2025-08-01') TO ('2025-09-01');
-- ลบ partition เก่า: DROP TABLE bar_logs_YYYY_MM;

-- ─── Indexes ──────────────────────────────────────────────────────────────
CREATE INDEX idx_positions_status     ON positions(status) WHERE status = 'OPEN';
CREATE INDEX idx_positions_entry_time ON positions(entry_time DESC);
CREATE INDEX idx_signals_bar_time     ON signals(bar_time DESC);
```

### Writer Functions (DRY_RUN aware)

```python
# db/supabase_writer.py
import json
from pathlib import Path
from datetime import datetime
from config.settings import DRY_RUN
from supabase import create_client
import logging

logger = logging.getLogger("trading")

def _safe_upsert(table: str, data: dict, conflict_col: str = "id") -> bool:
    """INSERT with retry. DRY_RUN → log เท่านั้น"""
    if DRY_RUN:
        logger.info(f"[DRY_RUN] Would INSERT into {table}: {data.get('id', data.get('bar_time'))}")
        return True

    for attempt in range(3):
        try:
            supabase.table(table).upsert(data, on_conflict=conflict_col).execute()
            return True
        except Exception as e:
            if attempt == 2:
                _write_fallback(table, data, str(e))
                return False
            time.sleep(2 ** attempt)

def _write_fallback(table: str, data: dict, error: str) -> None:
    """เขียนลง local JSONL เมื่อ Supabase fail หลัง retry ครบ"""
    Path("fallback").mkdir(exist_ok=True)
    with open("fallback/pending_inserts.jsonl", "a") as f:
        f.write(json.dumps({"table": table, "data": data, "error": error,
                            "ts": datetime.utcnow().isoformat()}) + "\n")

def insert_signal(signal: dict) -> None:
    _safe_upsert("signals", signal)

def insert_position(order: dict) -> None:
    _safe_upsert("positions", order)

def close_position(position_id: str, close_event: dict) -> None:
    if DRY_RUN:
        logger.info(f"[DRY_RUN] Would CLOSE position {position_id}: {close_event['close_reason']}")
        return
    supabase.table("positions").update({
        "status"           : "CLOSED",
        "close_bid_price"  : close_event["close_bid_price"],
        "close_at"         : close_event["close_at"].isoformat(),
        "close_reason"     : close_event["close_reason"],
        "realized_pnl_thb" : close_event["realized_pnl_thb"],
        "pnl_pct"          : close_event["pnl_pct"],
        "updated_at"       : datetime.now(TZ).isoformat(),
    }).eq("id", position_id).execute()

def count_open_positions() -> int:
    if DRY_RUN:
        return 0   # paper trading → ไม่มี open position จริง
    res = supabase.table("positions").select("id", count="exact").eq("status", "OPEN").execute()
    return res.count or 0

def fetch_open_positions_from_supabase() -> list[dict]:
    if DRY_RUN:
        return []
    res = supabase.table("positions").select("*").eq("status", "OPEN").execute()
    return res.data or []
```

---

<a name="phase-9"></a>
## Phase 9 — Discord Notifier

**จุดประสงค์:** ส่ง webhook notification ทุก event สำคัญ

```python
# notifier/discord_notifier.py
import httpx
import logging
from config.settings import DISCORD_WEBHOOK_URL, DISCORD_MENTION_ID, DRY_RUN

logger = logging.getLogger("trading")

def send_discord(content: str) -> None:
    """Base function — fire and forget, ไม่ block trading logic"""
    if not DISCORD_WEBHOOK_URL:
        return
    dry_prefix = "[DRY RUN] " if DRY_RUN else ""
    try:
        httpx.post(DISCORD_WEBHOOK_URL, json={"content": dry_prefix + content}, timeout=10)
    except Exception as e:
        logger.warning(f"Discord webhook failed (non-critical): {e}")
```

### Event Types

| Event | Trigger | ใครต้องรู้ |
|-------|---------|-----------|
| `BUY` | signal passed + position opened | ทุกคน |
| `TP` | bid ≥ tp_bid_price | ทุกคน |
| `SL` | bid ≤ sl_bid_price | @mention ผู้ดูแล |
| `SESSION_END` | position ค้างจนปิด session | ทุกคน |
| `HEARTBEAT` | ทุก 1 ชั่วโมงในช่วงตลาดเปิด | ทุกคน |
| `ERROR` | exception ใน pipeline | @mention ผู้ดูแล |

### Message Templates

#### BUY Signal

```
🟡 **BUY SIGNAL — HSH Gold**
━━━━━━━━━━━━━━━━━━━━━━━━━
📊 **Score:** 0.7823  (threshold: 0.65)
⏰ **Bar:** 01 Aug 09:50 (Morning)

💰 **Entry**
  • Ask : ฿70,100.00 · Bid : ฿70,000.00
  • Gold: 0.01427 บาทไทย · Cost: ฿999.89

🎯 **TP/SL**
  • TP : ฿70,569  (+฿469 · R/R 1.5)
  • SL : ฿69,788  (−฿313)

📈 Regime: ↑ · SRVR: 0.20 · RSI14: 58.2
🆔 sig_20250801_095000
```

#### TP/SL Hit

```
✅ **TAKE PROFIT — HSH Gold**
🕐 10:30 · ฿70,580 · Hold: 40m
💵 P&L: **+฿6.84** (+0.685%)

❌ **STOP LOSS — HSH Gold** <@DISCORD_MENTION_ID>
🕐 10:15 · ฿69,790 · Hold: 25m
💵 P&L: **−฿4.44** (−0.444%)
```

#### Heartbeat

```
💚 HSH Trader — 10:00 · Morning · 2 bars run · No open position
```

---

<a name="phase-10"></a>
## Phase 10 — Scheduler Orchestrator

```python
# scheduler/orchestrator.py
from apscheduler.schedulers.blocking import BlockingScheduler
from config.settings import DRY_RUN, TIMEZONE
from datetime import datetime
import pytz, logging

logger  = logging.getLogger("system")
TZ      = pytz.timezone(TIMEZONE)
scheduler = BlockingScheduler(timezone=TIMEZONE)

# ─── Job A: Signal Pipeline (ทุก 10 นาที) ────────────────────────────────────
@scheduler.scheduled_job("cron", minute="0,10,20,30,40,50", id="signal_pipeline")
def run_signal_pipeline():
    try:
        candles_df   = build_m10_candles()
        features_row = compute_features(candles_df)

        if features_row["session"] == "Closed":
            return

        inference_res = run_inference(features_row)
        signal        = evaluate_signal_gate(inference_res, features_row)

        insert_bar_log(features_row, signal)
        insert_signal(signal)

        if signal["passed"]:
            order = simulate_buy(
                ask_price=features_row["hsh_close_ask"],
                bid_price=features_row["hsh_close_bid"],
            )
            order = calculate_tp_sl(order, features_row["F_ATR_48"])

            if not order["tp_sl_valid"]:
                logger.info(f"Signal rejected: {order['reject_reason']}")
                return

            insert_position(order)
            send_discord_buy_alert(order, signal)

    except Exception as e:
        send_discord(f"⚠️ **Pipeline Error** <@{DISCORD_MENTION_ID}>\n```{e}```")
        logger.exception("Signal pipeline failed")

# ─── Job B: Position Monitor (ทุก 1 นาที) ────────────────────────────────────
@scheduler.scheduled_job("interval", minutes=1, id="position_monitor")
def run_position_monitor():
    try:
        open_positions = fetch_open_positions_from_supabase()
        if not open_positions:
            return

        current_bid  = fetch_latest_bid()
        current_time = datetime.now(TZ)
        close_events = monitor_positions(current_bid, current_time)

        for event in close_events:
            close_position(event["position_id"], event)
            send_discord_close_alert(event)

    except Exception as e:
        logger.exception("Position monitor failed")

# ─── Job C: Heartbeat (ทุก 1 ชั่วโมง ระหว่างตลาดเปิด) ──────────────────────
@scheduler.scheduled_job("cron", minute=0, id="heartbeat")
def run_heartbeat():
    now = datetime.now(TZ)
    if not is_market_hours(now):
        return
    session = get_current_session(now)
    open_ct = count_open_positions()
    mode    = "DRY RUN" if DRY_RUN else "LIVE"
    send_discord(f"💚 HSH Trader [{mode}] — {now:%H:%M} · {session} · Open positions: {open_ct}")
```

### Startup Sequence

```python
# main.py
import logging
from core.model_inference import model, FEATURE_COLS, MODEL_VERSION
from db.supabase_writer import supabase
from notifier.discord_notifier import send_discord
from scheduler.orchestrator import scheduler
from config.settings import DRY_RUN
from logger_setup import setup_logging

if __name__ == "__main__":
    setup_logging()
    logger = logging.getLogger("system")

    mode = "DRY RUN (Paper Trading)" if DRY_RUN else "LIVE"
    logger.info(f"Starting HSH ML Trader — Mode: {mode}")
    logger.info(f"Model: {MODEL_VERSION} · Features: {len(FEATURE_COLS)}")

    # 1. Verify DB connection
    supabase.table("signals").select("id").limit(1).execute()

    # 2. Startup notification
    send_discord(f"🚀 **HSH ML Trader Started** [{mode}]\nModel: `{MODEL_VERSION}` · Features: {len(FEATURE_COLS)}")

    # 3. Start scheduler
    scheduler.start()
```

---

<a name="feature-engineering"></a>
## Feature Engineering Deep Dive (M10)

ส่วนนี้อธิบาย logic เบื้องหลังแต่ละ feature สำหรับ M10 timeframe

### Conversion Factor

```
conv_factor = (15.244 / 31.1035) × (0.965 / 0.995) ≈ 0.4744
```

ใช้แปลง XAU (USD/oz) → ราคาทองไทย (THB/บาท) ก่อนคำนวณ features

---

### Group 1 — Synthetic Price & Thai Premium

#### `F_Syn_Price` — ราคาทองไทยเชิงทฤษฎี (Rolling OLS, 2016 bars)

ใช้ Rolling OLS ขนาด 2016 แท่ง M10 (≈ 2 สัปดาห์) ประมาณความสัมพันธ์ระหว่าง:
- `x` = XAU_Close × conv_factor × USD_Close → ราคาทองในหน่วย THB/บาท ถ้าไม่มี premium
- `y` = HSH_close_ask (ราคาขายจริง)

```
F_Syn_Price = slope × x + intercept
```

**ทำไมใช้ OLS แทนการ convert ตรง:** conv_factor ที่ static ไม่สะท้อน structural change เช่น ค่าธรรมเนียม หรือ spread นโยบายที่เปลี่ยนตามเวลา OLS ปรับ slope/intercept ตาม window จริง

**Anti-lookahead:** OLS ใช้เฉพาะข้อมูลย้อนหลัง (sliding window), cold start 2016 bars แรก drop ออก

---

#### `F_Thai_Premium` — ส่วนต่างราคาจริงกับทฤษฎี

```
F_Thai_Premium = hsh_close_ask − F_Syn_Price
```

| ค่า | ความหมาย |
|-----|----------|
| บวก | HSH ขายแพงกว่าทฤษฎี (premium สูง, ความตึงตัวของตลาดไทยสูง) |
| ลบ | HSH ขายถูกกว่าทฤษฎี (หายาก, อาจเกิดช่วง distress) |

---

### Group 2 — Macro Features

#### `F_Corr_XAU_USD` — Correlation XAU vs USD (18 bars = 3h)

```python
F_Corr_XAU_USD = rolling_corr(XAU_ret, USD_ret, window=18)
```

โดยปกติ XAU และ USD มี negative correlation ถ้า correlation เป็นบวก → ตลาดผิดปกติ (risk-off event)
ใช้ `safe_pct_change` เพื่อไม่คำนวณข้าม session boundary

---

#### `F_XAU_Mom_Short` / `F_XAU_Mom_Mid`

| Feature | Period | กรอบเวลา M10 |
|---------|--------|-------------|
| `F_XAU_Mom_Short` | 3 bars | 30 นาที |
| `F_XAU_Mom_Mid` | 12 bars | 2 ชั่วโมง |

ทั้งสองช่วยตรวจจับ **divergence**: Short momentum กลับทิศแต่ Mid ยังขึ้น → อาจแค่ retracement

---

#### `F_USD_Mom` — USD Momentum (6 bars = 1h)

```python
F_USD_Mom = safe_pct_change(usd_close, periods=6)
```

---

#### `F_ATR_48` — Average True Range (48 bars = 8h)

```
TR      = max(High − Low, |High − PrevClose|, |Low − PrevClose|)
F_ATR_48 = rolling_mean(TR, 48)
```

ใช้เป็น **denominator** ใน `F_SRVR` และ `F_Spread_vs_ATR` และเป็น base สำหรับคำนวณ TP/SL ใน Phase 6

**Anti-lookahead:** candle แรกของ session ไม่มี PrevClose → ใช้ High−Low แทน

---

#### `F_Regime` — Trend Regime (EMA Crossover)

```python
F_Regime = np.sign(EMA_20 − EMA_50)   # +1 = Uptrend, -1 = Downtrend
```

Signal Gate ใช้ `F_Regime == 1` เป็น gate condition (ปรับปิดได้ถ้าต้องการ trade ทุก regime)

---

### Group 3 — Session-Aware Features

ทุก feature ในกลุ่มนี้คำนวณ **ภายใน Session เดียว** (groupby `Session_ID`) ป้องกัน cross-session contamination

#### `F_FSP` — Fractional Session Progress

```python
F_FSP = Bar_In_Session / (SESSION_EXPECTED_BARS[session] − 1)   # clip [0, 1]
```

| Session | Expected bars (M10) | ตัวอย่าง F_FSP |
|---------|---------------------|---------------|
| Morning | 9 | Bar 3 → 0.375 |
| Afternoon | 14 | Bar 7 → 0.538 |
| Night | 24 | Bar 12 → 0.565 |

**Anti-lookahead:** ใช้ expected bars (constant) แทน actual length (รู้ได้เมื่อปิด session แล้ว)

---

#### `F_SA_TWAP_Dev` — Session TWAP Deviation

```python
F_SA_TWAP_Dev = price − expanding_mean(price)   # expanding ภายใน session
```

| ค่า | ความหมาย |
|-----|----------|
| บวก | ราคาสูงกว่า TWAP ของ session (ปัจจุบัน) |
| ลบ | ราคาต่ำกว่า TWAP |

---

#### `F_SA_MDD` — Max Drawdown ภายใน Session

```python
F_SA_MDD = price − expanding_max(price)   # ≤ 0 เสมอ
```

ตรวจจับ pullback ภายใน session

---

#### `F_SA_Range` / `F_SA_Position`

```python
F_SA_Range    = expanding_max − expanding_min
F_SA_Position = (price − expanding_min) / F_SA_Range   # [0, 1]
```

`F_SA_Position ≈ 0` = ราคาใกล้จุดต่ำสุด session, `≈ 1` = ใกล้จุดสูงสุด

---

#### `F_Historical_Vol_THB` — Volatility ในหน่วย THB (144 bars = 24h)

```python
xau_ret_std          = rolling_std(XAU_ret, 144)
F_Historical_Vol_THB = xau_ret_std × xau_close × CONV_FACTOR × usd_close
```

แปลง volatility ของ XAU ให้อยู่ในหน่วย THB/บาท ตรงกับ P&L จริง

---

#### `F_Remaining_Vol` — Volatility ที่คาดในช่วงที่เหลือ

```python
F_Remaining_Vol = F_Historical_Vol_THB × (1 − F_FSP)
```

---

#### `F_SRVR` — Session Remaining Volatility Ratio

```python
F_SRVR = F_Remaining_Vol / F_ATR_48
```

Composite feature ที่ encode ทั้ง session progress และ volatility ไว้ในตัวเลขเดียว Signal Gate ใช้ `F_SRVR >= 0.15`

---

#### `F_Price_Vs_Open`

```python
F_Price_Vs_Open = (price − session_open) / session_open   # %
```

---

#### `F_Mom_1bar` / `F_Mom_3bar` — HSH Short Momentum (M10)

| Feature | Period | กรอบเวลา |
|---------|--------|---------|
| `F_Mom_1bar` | 1 bar | 10 นาที |
| `F_Mom_3bar` | 3 bars | 30 นาที |

ใช้ `safe_pct_change` ป้องกัน cross-session calculation

---

#### `F_SA_Drawdown_Pct`

```python
F_SA_Drawdown_Pct = (price − expanding_max) / expanding_max   # % ≤ 0
```

Normalize เป็น % เพื่อเปรียบเทียบข้าม session ได้

---

#### `F_HSH_vs_THBGold_Dev` — HSH vs THB Gold Lag (6 bars = 1h)

```python
thb_gold_ret          = safe_pct_change(xau_close × usd_close, 1)
hsh_ret               = safe_pct_change(hsh_close_ask, 1)
F_HSH_vs_THBGold_Dev  = rolling_mean(hsh_ret − thb_gold_ret, 6)
```

| ค่า | ความหมาย |
|-----|----------|
| บวก | HSH ขึ้นเร็วกว่า XAU (premium expanding) |
| ลบ | HSH lag อยู่ อาจมีโอกาส catch-up |

---

### Group 4 — Technical Features

#### `F_RSI_14` / `F_RSI_6`

```python
RSI = 100 − 100 / (1 + avg_gain / avg_loss)
```

| Feature | Period | จุดประสงค์ |
|---------|--------|-----------|
| `F_RSI_14` | 14 bars | Standard RSI (70+ overbought, 30− oversold) |
| `F_RSI_6` | 6 bars | Fast RSI สำหรับ short-term reversal |

ใช้ `safe_diff` เพื่อไม่คำนวณ gain/loss ข้าม session boundary

---

#### `F_BB_Pos` — Bollinger Band Position

```python
bb_mid   = rolling_mean(price, 20)
bb_std   = rolling_std(price, 20)
F_BB_Pos = (price − bb_mid) / (2 × bb_std)
```

Normalize แล้ว: > 1.0 = overbought, < −1.0 = oversold

---

#### `F_XAU_Spread_Norm` — Normalized XAU Spread (144 bars = 24h)

```python
F_XAU_Spread_Norm = xau_spread / rolling_mean(xau_spread, 144)
```

Signal Gate ใช้ `F_XAU_Spread_Norm < 2.5` (spread ผิดปกติ → liquidity ต่ำ)

---

#### `F_Hour_Sin` / `F_Hour_Cos` — Circular Time Encoding

```python
hour        = bar_time.hour + bar_time.minute / 60
F_Hour_Sin  = sin(2π × hour / 24)
F_Hour_Cos  = cos(2π × hour / 24)
```

**ทำไมต้อง Sin/Cos:** ชั่วโมง 23 และ 0 ใกล้กันในความเป็นจริง แต่ตัวเลขดิบจะห่างกันมาก Circular encoding แก้ปัญหานี้

---

#### `F_Session_Type`

```python
F_Session_Type = {"Morning": 0, "Afternoon": 1, "Night": 2}[session]
```

---

#### Spread Features

| Feature | สูตร | ความหมาย |
|---------|------|----------|
| `F_HSH_Spread` | `ask − bid` | Spread ดิบ (THB) |
| `F_Spread_Cost_Pct` | `spread / ask` | ต้นทุน spread เป็น % |
| `F_Spread_vs_ATR` | `spread / F_ATR_48` | Spread เทียบ volatility → ถ้าสูง ทำกำไรยาก |

---

### Anti-Lookahead Mechanisms

| กลไก | ใช้ใน Feature |
|------|--------------|
| `safe_pct_change()` — return = 0 ที่ session boundary | Momentum, Corr, Vol, HSH Dev |
| `safe_diff()` — diff = 0 ที่ session boundary | RSI |
| `expanding()` แทน `rolling()` ภายใน session | TWAP, MDD, Range, Position, Drawdown |
| `SESSION_EXPECTED_BARS` แทน actual length | FSP, Remaining Vol, SRVR |
| OLS sliding window (ข้อมูลอดีตเท่านั้น) | F_Syn_Price |

---

### Feature Summary Table

| Feature | กลุ่ม | ประเภท | Range |
|---------|-------|--------|-------|
| `F_Syn_Price` | Synthetic | Continuous | THB/บาท |
| `F_Thai_Premium` | Synthetic | Continuous | THB |
| `F_Corr_XAU_USD` | Macro | Continuous | [−1, 1] |
| `F_XAU_Mom_Short` | Macro | Continuous | % |
| `F_XAU_Mom_Mid` | Macro | Continuous | % |
| `F_USD_Mom` | Macro | Continuous | % |
| `F_ATR_48` | Macro | Continuous | THB |
| `F_Regime` | Macro | Categorical | {−1, +1} |
| `F_FSP` | Session | Continuous | [0, 1] |
| `F_SA_TWAP_Dev` | Session | Continuous | THB |
| `F_SA_MDD` | Session | Continuous | THB ≤ 0 |
| `F_SA_Vol` | Session | Continuous | THB |
| `F_SA_Range` | Session | Continuous | THB |
| `F_SA_Position` | Session | Continuous | [0, 1] |
| `F_Historical_Vol_THB` | Session | Continuous | THB |
| `F_Remaining_Vol` | Session | Continuous | THB |
| `F_SRVR` | Session | Continuous | ratio |
| `F_Price_Vs_Open` | Session | Continuous | % |
| `F_Mom_1bar` | Session | Continuous | % |
| `F_Mom_3bar` | Session | Continuous | % |
| `F_SA_Drawdown_Pct` | Session | Continuous | % ≤ 0 |
| `F_HSH_vs_THBGold_Dev` | Session | Continuous | diff |
| `F_DayOfWeek` | Time | Ordinal | [0, 4] |
| `F_MinuteOfDay` | Time | Ordinal | [0, 1439] |
| `F_RSI_14` | Technical | Continuous | [0, 100] |
| `F_RSI_6` | Technical | Continuous | [0, 100] |
| `F_BB_Pos` | Technical | Continuous | ratio |
| `F_XAU_Spread_Norm` | Technical | Continuous | ratio |
| `F_Hour_Sin` | Technical | Continuous | [−1, 1] |
| `F_Hour_Cos` | Technical | Continuous | [−1, 1] |
| `F_Session_Type` | Technical | Categorical | {0, 1, 2} |
| `F_HSH_Spread` | Technical | Continuous | THB |
| `F_Spread_Cost_Pct` | Technical | Continuous | % |
| `F_Spread_vs_ATR` | Technical | Continuous | ratio |

---

<a name="logging"></a>
## Logging Strategy

### `logger_setup.py`

```python
import logging
import logging.handlers
from config.settings import LOG_LEVEL

def setup_logging():
    Path("logs").mkdir(exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # ─── system.log — lifecycle, errors, scheduler events ──────────────────────
    system_handler = logging.handlers.TimedRotatingFileHandler(
        "logs/system.log", when="midnight", backupCount=30, encoding="utf-8"
    )
    system_handler.setFormatter(fmt)

    # ─── trading.log — signals, trades, P&L ────────────────────────────────────
    trading_handler = logging.handlers.TimedRotatingFileHandler(
        "logs/trading.log", when="midnight", backupCount=90, encoding="utf-8"
    )
    trading_handler.setFormatter(fmt)

    # ─── Console ───────────────────────────────────────────────────────────────
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)

    # ─── Assign loggers ────────────────────────────────────────────────────────
    system_logger  = logging.getLogger("system")
    trading_logger = logging.getLogger("trading")

    system_logger.addHandler(system_handler)
    system_logger.addHandler(console_handler)
    system_logger.setLevel(LOG_LEVEL)

    trading_logger.addHandler(trading_handler)
    trading_logger.addHandler(console_handler)
    trading_logger.setLevel(LOG_LEVEL)
```

### Log Conventions

| Logger | ใช้สำหรับ |
|--------|---------|
| `logging.getLogger("system")` | Startup, shutdown, scheduler events, DB errors |
| `logging.getLogger("trading")` | Signals, trades, TP/SL, P&L, gate decisions |

ห้ามใช้ logger เดียวกันสองตัว (เพื่อให้ `trading.log` มีเฉพาะ trading events)

---

<a name="deployment"></a>
## Deployment Guide

### Option A — systemd (แนะนำสำหรับ VPS/Linux)

```ini
# /etc/systemd/system/hsh-trader.service
[Unit]
Description=HSH ML Gold Trader
After=network.target

[Service]
Type=simple
User=trader
WorkingDirectory=/home/trader/hsh_ml_trader
ExecStart=/home/trader/hsh_ml_trader/.venv/bin/python main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
EnvironmentFile=/home/trader/hsh_ml_trader/.env

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable hsh-trader
sudo systemctl start hsh-trader
sudo journalctl -u hsh-trader -f    # ดู logs
```

### Option B — Docker (สำหรับ containerized deployment)

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
```

```bash
docker build -t hsh-trader .
docker run -d --name hsh-trader --env-file .env hsh-trader
```

### Monitoring Checklist

- [ ] systemd service หรือ Docker restart policy ตั้งค่าแล้ว
- [ ] Discord heartbeat Job C เปิดใช้งาน
- [ ] logs/ directory มี disk space เพียงพอ (≥ 1 GB)
- [ ] Supabase quotas ตรวจสอบ (rows, requests/day)
- [ ] ทดสอบ `DRY_RUN=true` อย่างน้อย 1 trading day ก่อน go live

---

<a name="data-flow"></a>
## Data Flow Summary

```
hsh_prices (second-level) ──┐
xau_prices (second-level)   ├──▶ [P1] M10 Candle Builder
usd_thb_prices              │         │ candles_df (2200 bars × 15 cols)
                            │         ▼
                            │    [P2] Feature Engine
                            │         │ FeaturesRow (34 features)
                            │         ▼
                            │    [P3] XGBoost Inference
                            │         │ ranker_score: float
                            │         ▼
                            │    [P4] Signal Gate ──── REJECT ──▶ [P8] signals(passed=False)
                            │         │ PASS
                            │         ▼
                            │    [P5] Order Simulator
                            │         │ gold_weight, actual_cost, spread_cost
                            │         ▼
                            │    [P6] TP/SL Calculator ──── INVALID ──▶ skip
                            │         │ VALID
                            │         ▼
                            │    [P8] INSERT positions + signals
                            │         │
                            │         ▼
                            │    [P9] Discord BUY Alert
                            │
                            └──▶ [P7] Position Monitor (every 1 min)
                                      │ bid ≥ TP or bid ≤ SL or session end?
                                      │ YES
                                      ▼
                                 [P8] UPDATE positions (CLOSED)
                                      │
                                      ▼
                                 [P9] Discord TP/SL Alert

[Job C] Heartbeat (every 1h during market hours) ──▶ [P9] Discord
```

---

<a name="errors"></a>
## Error Handling & Failsafes

| สถานการณ์ | การจัดการ |
|-----------|---------|
| DB timeout ตอน fetch candles | retry 3 ครั้ง exponential backoff → log → ข้าม bar นั้น |
| Feature NaN ใน critical features | validate ก่อน inference → raise ValueError → reject signal |
| XGBoost predict fail | try/except → Discord alert → ไม่เปิด position |
| Supabase INSERT fail | retry 3 ครั้ง → เขียน `fallback/pending_inserts.jsonl` |
| Discord webhook fail | log warning เท่านั้น → ไม่กระทบ trading logic |
| TP/SL distance ไม่ผ่าน validation | reject signal → log reason "invalid_tp_sl" |
| Duplicate signal (scheduler overlap) | `signal_id` เป็น PRIMARY KEY → INSERT conflict → idempotent |
| ตลาดปิด (session = Closed) | Phase 4 gate block + Job A early return |
| Position ค้างข้าม session | Phase 7 SESSION_END close event |
| FEATURE_COLS drift (model vs code) | metadata.json เป็น source of truth + startup validation |
| Process crash | systemd Restart=always หรือ Docker restart policy |
| ไม่มี heartbeat | ระบบ offline → Discord ไม่ส่ง → ทีมต้อง check |

---

<a name="testing"></a>
## Testing & Paper Trading

### Paper Trading Mode

```bash
DRY_RUN=true python main.py
```

เมื่อ `DRY_RUN=true`:
- Signal pipeline รันปกติ (candle, feature, inference, gate)
- `[DRY RUN]` prefix ติด Discord message ทุกข้อความ
- ไม่มีการ INSERT/UPDATE Supabase
- `count_open_positions()` คืนค่า 0 เสมอ
- ทุก action ถูก log เป็น INFO

**แนะนำ:** รัน dry run อย่างน้อย 3 trading days ก่อน go live

### Unit Tests

```bash
pytest tests/ -v
```

```python
# tests/test_order_simulator.py
def test_gold_weight_truncation():
    """ต้อง truncate ไม่ใช่ round"""
    order = simulate_buy(ask_price=70123.456, bid_price=70023.456, investment_thb=1000)
    assert order["gold_weight"] == math.floor(order["gold_weight"] * 1e5) / 1e5

def test_actual_cost_leq_investment():
    """actual cost ต้องไม่เกิน investment"""
    order = simulate_buy(ask_price=70000, bid_price=69900, investment_thb=1000)
    assert order["actual_cost_thb"] <= 1000

# tests/test_feature_engine.py
def test_no_cross_session_momentum():
    """momentum ที่ session boundary ต้องเป็น 0"""
    ...

def test_fsp_clips_to_one():
    """F_FSP ต้องไม่เกิน 1.0 แม้ session ยาวกว่า expected"""
    ...
```

---

<a name="build-order"></a>
## Build Order

```
Week 1 — Foundation
  [x] Phase 0  — Config, requirements.txt, .env.example
  [x] Phase 8  — Supabase DDL Schema
  [x] Phase 1  — M10 Candle Builder + SQL ทดสอบ
  [x] logger_setup.py

Week 2 — Core Pipeline
  [x] Phase 2  — Feature Engine (port M5 → M10, anti-lookahead)
  [x] Phase 3  — Model Inference (JSON format, metadata)
  [x] Phase 4  — Signal Gate

Week 3 — Trade Logic
  [x] Phase 5  — Order Simulator (fractional gold, truncation)
  [x] Phase 6  — TP/SL Calculator (validation)
  [x] Phase 7  — Position Monitor (is_session_closed, SESSION_END)

Week 4 — Integration & Testing
  [x] Phase 9  — Discord Notifier (all event types)
  [x] Phase 10 — Scheduler (Job A + B + C heartbeat)
  [ ] Unit tests (tests/)
  [ ] DRY_RUN paper trading — 3 trading days minimum
  [ ] Deployment setup (systemd หรือ Docker)
  [ ] Go live
```

---

*Architecture Version: 2.0 · Last Updated: 2025-08-01 · Timeframe: M10 · Model: LambdaMART v11*
*Changes from v1.0: Fixed SQL FIRST/LAST, pickle→JSON, FEATURE_COLS from metadata, DRY_RUN mode, heartbeat job, session time consistency, bar_logs partitioning, missing function implementations, TypedDict for FeaturesRow*