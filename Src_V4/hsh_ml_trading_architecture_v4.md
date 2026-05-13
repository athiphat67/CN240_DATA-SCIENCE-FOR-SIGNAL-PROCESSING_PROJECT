# HSH ML Trading System — Signal Generator Architecture

**ฮั่วเซ่งเฮง Gold · XGBoost Ranker Signal · State-Based BUY/SELL · Supabase + Discord**

> **Stack:** Python 3.11 · PostgreSQL (Supabase) · APScheduler · Discord Webhook
> **Model:** LambdaMART v11 (XGBoost Ranker · 420 trees) · Timeframe M10
> **Mode:** Signal Generator Only — ไม่มี TP/SL อัตโนมัติ · ผู้ใช้ตั้ง TP/SL เอง
> **Architecture:** v3.0 — Signal-Only Mode (เปลี่ยนจาก v2.0 ที่มี Position Monitor)

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Directory Structure](#directory-structure)
3. [Phase 0 — Infrastructure & Config](#phase-0)
4. [Phase 1 — M10 Candle Builder](#phase-1)
5. [Phase 2 — Feature Engine (M10)](#phase-2)
6. [Phase 3 — Model Inference](#phase-3)
7. [Phase 4 — Signal Gate & State Manager](#phase-4)
8. [Phase 5 — Signal Recorder](#phase-5)
9. [Phase 6 — Supabase Schema & Writer](#phase-6)
10. [Phase 7 — Discord Notifier](#phase-7)
11. [Phase 8 — Scheduler Orchestrator](#phase-8)
12. [Feature Engineering Deep Dive (M10)](#feature-engineering)
13. [Logging Strategy](#logging)
14. [Deployment Guide](#deployment)
15. [Data Flow Summary](#data-flow)
16. [Error Handling & Failsafes](#errors)
17. [Testing & Paper Trading](#testing)
18. [Build Order](#build-order)

---

## สิ่งที่เปลี่ยนแปลงจาก v2.0 → v3.0

| ลบออก | เพิ่มเข้า | เปลี่ยนแปลง |
|-------|----------|------------|
| `core/tp_sl_calculator.py` | `core/state_manager.py` | Phase 4 รองรับ BUY และ SELL |
| `core/position_monitor.py` | `system_state` table ใน DB | Phase 5 กลายเป็น Signal Recorder |
| Job B (1-min monitor) | — | Scheduler เหลือแค่ Job A + Job C |
| TP/SL columns ใน `positions` | `current_position` ใน `system_state` | signals table รองรับ signal_type = BUY/SELL |

**เหตุผล:** ระบบนี้ทำหน้าที่เป็น Signal Generator เท่านั้น ผู้ใช้เป็นคนกดซื้อ/ขายเองและตั้ง TP/SL เอง บอทเพียงแจ้งว่า "ตอนนี้น่าซื้อ" หรือ "ตอนนี้น่าขาย" ทุก 10 นาที ทำให้ระบบเบาลงมหาศาล

---

<a name="quick-start"></a>
## Quick Start

```bash
# 1. Clone repo
git clone <repo-url> hsh_ml_trader
cd hsh_ml_trader

# 2. Create virtual environment
python3.11 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Setup environment variables
cp .env.example .env
# แก้ไข .env ด้วย credentials จริง

# 5. ตรวจสอบ Supabase schema (DDL ใหม่ v3)
psql $DATABASE_URL < db/supabase_schema.sql

# 6. ตั้งค่า initial state (ถ้าไม่มีทองอยู่ในมือ)
python -c "from db.supabase_writer import init_state; init_state('EMPTY')"

# 7. รัน paper trading (dry run) ก่อน
DRY_RUN=true python main.py

# 8. รัน live (เมื่อ test ผ่านแล้ว)
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
├── README.md
├── requirements.txt
├── .env.example
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
│   ├── signal_gate.py              ← Phase 4 (state-aware)
│   ├── state_manager.py            ← Phase 4 helper (NEW)
│   └── signal_recorder.py          ← Phase 5 (เปลี่ยนจาก order_simulator)
│
├── db/
│   ├── supabase_writer.py          ← Phase 6
│   └── supabase_schema.sql         ← DDL v3
│
├── notifier/
│   └── discord_notifier.py         ← Phase 7
│
├── scheduler/
│   └── orchestrator.py             ← Phase 8
│
├── models/
│   ├── lambdamart_v11.json
│   └── lambdamart_v11_meta.json
│
├── logs/
│   ├── system.log
│   └── trading.log
│
├── fallback/
│   └── pending_inserts.jsonl
│
└── tests/
    ├── test_candle_builder.py
    ├── test_feature_engine.py
    ├── test_signal_gate.py
    └── test_state_manager.py
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
DISCORD_MENTION_ID=123456789012345678        # user ID สำหรับ @mention เมื่อมีสัญญาณ

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
MODEL_PATH          = "models/lambdamart_v11.json"
MODEL_META_PATH     = "models/lambdamart_v11_meta.json"
SIGNAL_THRESHOLD    = 0.65          # ranker score ≥ this → trigger BUY/SELL check
TIMEFRAME_MIN       = 10            # M10
LOOKBACK_BARS       = 2200          # bars to load (≥ OLS_WINDOW 2016)

# ─── Gold Constants ───────────────────────────────────────────────────────────
WEIGHT_TH_BAHT      = 15.244        # grams per 1 บาทไทย
WEIGHT_TROY_OUNCE   = 31.1035       # grams per troy oz
PURITY_TH_GOLD      = 0.965
PURITY_GLOBAL_GOLD  = 0.995
CONV_FACTOR         = (WEIGHT_TH_BAHT / WEIGHT_TROY_OUNCE) * (PURITY_TH_GOLD / PURITY_GLOBAL_GOLD)
# ≈ 0.4744

# ─── State ────────────────────────────────────────────────────────────────────
STATE_EMPTY   = "EMPTY"             # ไม่มีทองในมือ → อนุญาตเฉพาะ BUY
STATE_HOLDING = "HOLDING"           # มีทองในมืออยู่ → อนุญาตเฉพาะ SELL

# ─── Session Definitions (M10 bars) ───────────────────────────────────────────
SESSION_HOURS = {
    "Morning"   : (9*60,   9*60 + 90),    # 540–630
    "Afternoon" : (13*60,  13*60 + 140),  # 780–920
    "Night"     : (18*60,  18*60 + 240),  # 1080–1320
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

# ─── Signal Gate Thresholds ───────────────────────────────────────────────────
GATE_SRVR_MIN           = 0.15
GATE_SPREAD_NORM_MAX    = 2.5
GATE_REGIME_REQUIRED    = 1

# ─── Supabase ─────────────────────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# ─── Discord ──────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_MENTION_ID  = os.getenv("DISCORD_MENTION_ID", "")
```

> **หมายเหตุ:** ไม่มี TP/SL constants อีกต่อไป เพราะผู้ใช้เป็นคนตั้ง TP/SL เองที่หน้างาน

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

> **สำคัญ:** `feature_cols` ใน metadata คือ **แหล่งความจริงเดียว** สำหรับ feature list ห้าม hardcode ใน `model_inference.py`

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
  hsh_open_ask    : float64
  hsh_high_ask    : float64
  hsh_low_ask     : float64
  hsh_close_ask   : float64   ← entry price reference
  hsh_open_bid    : float64
  hsh_high_bid    : float64
  hsh_low_bid     : float64
  hsh_close_bid   : float64   ← exit price reference
  xau_open        : float64
  xau_high        : float64
  xau_low         : float64
  xau_close       : float64
  xau_spread      : float64
  usd_close       : float64
```

### Validation Rules

```python
assert len(candles_df) >= OLS_WINDOW + 50,       "ข้อมูลไม่พอสำหรับ OLS"
assert candles_df.index.is_monotonic_increasing,  "Candles ต้องเรียงตามเวลา"
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

### Model Loading (XGBoost native JSON format)

```python
import json
import xgboost as xgb
import pandas as pd
from config.settings import MODEL_PATH, MODEL_META_PATH

# โหลดครั้งเดียวตอน startup
model = xgb.XGBRanker()
model.load_model(MODEL_PATH)

with open(MODEL_META_PATH) as f:
    meta = json.load(f)

FEATURE_COLS  = meta["feature_cols"]    # source of truth
MODEL_VERSION = meta["model_name"]

def run_inference(features_row: FeaturesRow) -> dict:
    X = pd.DataFrame([features_row])[FEATURE_COLS]

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

> **ทำไมไม่ใช้ pickle:** pickle ไม่ portable ข้าม Python version และมีความเสี่ยง security (arbitrary code execution) XGBoost native `.json` format แก้ทั้ง 2 ปัญหา

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
## Phase 4 — Signal Gate & State Manager

**จุดประสงค์:** ตรวจสอบสถานะปัจจุบัน (EMPTY/HOLDING) + กรองสัญญาณ → ตัดสินใจส่ง BUY หรือ SELL

### `core/state_manager.py`

State Manager ทำหน้าที่อ่าน/เขียนสถานะจาก Supabase และให้ Manual Override ได้

```python
# core/state_manager.py
import logging
from config.settings import STATE_EMPTY, STATE_HOLDING, DRY_RUN
from db.supabase_writer import get_supabase_client

logger = logging.getLogger("trading")

def get_current_state() -> str:
    """
    อ่าน state ปัจจุบันจาก system_state table
    คืนค่า 'EMPTY' หรือ 'HOLDING'
    """
    if DRY_RUN:
        return STATE_EMPTY  # paper trading → เริ่มจาก EMPTY เสมอ

    client = get_supabase_client()
    res = client.table("system_state").select("current_position").eq("id", 1).execute()
    if not res.data:
        raise RuntimeError("system_state ไม่มีข้อมูล — รัน init_state() ก่อน")
    return res.data[0]["current_position"]

def set_state(new_state: str) -> None:
    """
    อัปเดต state → 'EMPTY' หรือ 'HOLDING'
    เรียกพร้อมกับการ INSERT signal เสมอ (atomic logic)
    """
    if new_state not in (STATE_EMPTY, STATE_HOLDING):
        raise ValueError(f"Invalid state: {new_state}")

    if DRY_RUN:
        logger.info(f"[DRY_RUN] Would SET state → {new_state}")
        return

    client = get_supabase_client()
    client.table("system_state").update({
        "current_position": new_state,
        "updated_at": "now()"
    }).eq("id", 1).execute()
    logger.info(f"State updated → {new_state}")

def init_state(initial: str = STATE_EMPTY) -> None:
    """
    ตั้งค่า initial state ครั้งแรก หรือ reset หลัง manual trade
    เรียกผ่าน CLI: python -c "from db.supabase_writer import init_state; init_state('EMPTY')"
    """
    client = get_supabase_client()
    client.table("system_state").upsert({
        "id": 1,
        "current_position": initial,
    }, on_conflict="id").execute()
    print(f"✅ State initialized → {initial}")
```

### `core/signal_gate.py`

```python
# core/signal_gate.py
from config.settings import (
    SIGNAL_THRESHOLD, DRY_RUN,
    STATE_EMPTY, STATE_HOLDING,
    GATE_SRVR_MIN, GATE_SPREAD_NORM_MAX, GATE_REGIME_REQUIRED,
)
from core.state_manager import get_current_state

def evaluate_signal_gate(inference_result: dict, features_row: FeaturesRow) -> dict:
    """
    ตรวจสอบเงื่อนไขต่างๆ แล้วตัดสินใจว่าจะส่งสัญญาณอะไร

    Logic หลัก:
      state == EMPTY   → โมเดล strong? → BUY
      state == HOLDING → โมเดล weak?   → SELL
    """
    score   = inference_result["ranker_score"]
    session = features_row["session"]
    F_SRVR  = features_row["F_SRVR"]
    F_XAU_Spread_Norm = features_row["F_XAU_Spread_Norm"]
    F_Regime = features_row["F_Regime"]

    current_state = get_current_state()

    # ─── Gate ที่ใช้ร่วมกัน ────────────────────────────────────────────────────
    base_gates = {
        "market_open"  : session != "Closed",
        "spread_gate"  : F_XAU_Spread_Norm < GATE_SPREAD_NORM_MAX,
    }

    # ─── BUY Logic (state = EMPTY) ────────────────────────────────────────────
    if current_state == STATE_EMPTY:
        buy_gates = {
            **base_gates,
            "score_gate"   : score >= SIGNAL_THRESHOLD,
            "srvr_gate"    : F_SRVR >= GATE_SRVR_MIN,
            "regime_gate"  : F_Regime == GATE_REGIME_REQUIRED,
        }
        passed = all(buy_gates.values())
        signal_type   = "BUY" if passed else None
        gates_detail  = buy_gates
        reject_reason = None if passed else next(k for k, v in buy_gates.items() if not v)

    # ─── SELL Logic (state = HOLDING) ─────────────────────────────────────────
    elif current_state == STATE_HOLDING:
        sell_gates = {
            **base_gates,
            "score_below_threshold" : score < SIGNAL_THRESHOLD,  # โมเดลอ่อน → ขาย
        }
        passed = all(sell_gates.values())
        signal_type   = "SELL" if passed else None
        gates_detail  = sell_gates
        reject_reason = None if passed else next(k for k, v in sell_gates.items() if not v)

    else:
        raise RuntimeError(f"Unknown state: {current_state}")

    signal_id = (
        f"sig_{features_row['bar_time'][:19].replace('-','').replace(':','').replace('T','_')}"
    )

    return {
        "signal_id"      : signal_id,
        "bar_time"       : features_row["bar_time"],
        "session"        : session,
        "signal_type"    : signal_type,   # "BUY" | "SELL" | None
        "ranker_score"   : score,
        "state_before"   : current_state,
        "gates_detail"   : gates_detail,
        "passed"         : passed,
        "reject_reason"  : reject_reason,
        "dry_run"        : DRY_RUN,
        "features_snap"  : inference_result["features_snap"],
        # ─── ราคาประกอบการตัดสินใจ (ส่งไปใน Discord) ───────────────────────────
        "hsh_ask"        : features_row["hsh_close_ask"],
        "hsh_bid"        : features_row["hsh_close_bid"],
        "xau_close"      : features_row["xau_close"],
        "atr_48"         : features_row["F_ATR_48"],
    }
```

### Gate Logic Summary

```
State = EMPTY
  ├─ score ≥ 0.65   ✓
  ├─ market_open    ✓
  ├─ spread_gate    ✓
  ├─ srvr_gate      ✓
  └─ regime_gate    ✓
       → Signal: BUY ✅

State = EMPTY, แต่ไม่ผ่าน gate
       → No Signal, log reject_reason ⏩

State = HOLDING
  ├─ score < 0.65   ✓ (โมเดลอ่อนแล้ว)
  ├─ market_open    ✓
  └─ spread_gate    ✓
       → Signal: SELL ✅

State = HOLDING, แต่ score ยังสูงอยู่
       → No Signal, ถือต่อ ⏩
```

---

<a name="phase-5"></a>
## Phase 5 — Signal Recorder

**จุดประสงค์:** บันทึกราคา ณ เวลาที่ส่งสัญญาณ เพื่อใช้ติดตามประสิทธิภาพ (ไม่คำนวณ P&L จริง)

> **เปลี่ยนจาก v2.0:** ไม่มีการคำนวณ gold_weight, fractional buy, spread_cost อีกต่อไป เหลือแค่ "บันทึกว่าตอนนั้นราคาเท่าไหร่"

```python
# core/signal_recorder.py
from datetime import datetime
import pytz

TZ = pytz.timezone("Asia/Bangkok")

def build_signal_record(gate_result: dict) -> dict:
    """
    สร้าง record สำหรับ INSERT ลง signals table
    เก็บราคา ask/bid ณ เวลาส่งสัญญาณ เพื่อวิเคราะห์ย้อนหลัง
    """
    return {
        "id"            : gate_result["signal_id"],
        "bar_time"      : gate_result["bar_time"],
        "session"       : gate_result["session"],
        "signal_type"   : gate_result["signal_type"],   # "BUY" | "SELL"
        "ranker_score"  : gate_result["ranker_score"],
        "state_before"  : gate_result["state_before"],
        "hsh_ask_price" : gate_result["hsh_ask"],
        "hsh_bid_price" : gate_result["hsh_bid"],
        "xau_price"     : gate_result["xau_close"],
        "atr_at_signal" : gate_result["atr_48"],
        "passed"        : gate_result["passed"],
        "reject_reason" : gate_result["reject_reason"],
        "dry_run"       : gate_result["dry_run"],
        "features_snap" : gate_result["features_snap"],
        "created_at"    : datetime.now(TZ).isoformat(),
    }
```

---

<a name="phase-6"></a>
## Phase 6 — Supabase Schema & Writer

### DDL Schema (v3)

```sql
-- ─── Table 1: system_state ─────────────────────────────────────────────────
-- เก็บสถานะปัจจุบันของระบบ (มีทองหรือไม่มี)
-- มีแค่ 1 row เสมอ (id = 1)
CREATE TABLE system_state (
    id                  INT PRIMARY KEY DEFAULT 1,
    current_position    TEXT NOT NULL DEFAULT 'EMPTY',  -- 'EMPTY' | 'HOLDING'
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    note                TEXT  -- สำหรับ manual note เช่น "ขายไปก่อนที่บอทจะสั่ง"
);

-- Seed initial state
INSERT INTO system_state (id, current_position) VALUES (1, 'EMPTY')
ON CONFLICT (id) DO NOTHING;

-- ─── Table 2: signals ──────────────────────────────────────────────────────
CREATE TABLE signals (
    id              TEXT PRIMARY KEY,          -- "sig_YYYYMMDD_HHMMSS"
    bar_time        TIMESTAMPTZ NOT NULL,
    session         TEXT NOT NULL,
    signal_type     TEXT,                      -- 'BUY' | 'SELL' | NULL (ถ้า reject)
    ranker_score    NUMERIC(10,6) NOT NULL,
    state_before    TEXT NOT NULL,             -- 'EMPTY' | 'HOLDING' ก่อนส่งสัญญาณ
    hsh_ask_price   NUMERIC(10,2),             -- ราคาขายออก ณ เวลาสัญญาณ
    hsh_bid_price   NUMERIC(10,2),             -- ราคารับซื้อ ณ เวลาสัญญาณ
    xau_price       NUMERIC(10,4),             -- XAU/USD ณ เวลาสัญญาณ
    atr_at_signal   NUMERIC(10,2),             -- ATR(48) ณ เวลาสัญญาณ
    passed          BOOLEAN NOT NULL,
    reject_reason   TEXT,
    dry_run         BOOLEAN NOT NULL DEFAULT false,
    features_snap   JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Table 3: bar_logs (optional — debug และ retrain) ──────────────────────
CREATE TABLE bar_logs (
    id              BIGSERIAL PRIMARY KEY,
    bar_time        TIMESTAMPTZ NOT NULL UNIQUE,
    session         TEXT,
    state_at_bar    TEXT,                      -- 'EMPTY' | 'HOLDING'
    ranker_score    NUMERIC(10,6),
    signal_passed   BOOLEAN,
    signal_type     TEXT,
    hsh_close_ask   NUMERIC(10,2),
    hsh_close_bid   NUMERIC(10,2),
    atr_48          NUMERIC(10,2),
    features_snap   JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
) PARTITION BY RANGE (created_at);

-- Retention: เก็บ 90 วัน
CREATE TABLE bar_logs_2025_08 PARTITION OF bar_logs
    FOR VALUES FROM ('2025-08-01') TO ('2025-09-01');

-- ─── Indexes ───────────────────────────────────────────────────────────────
CREATE INDEX idx_signals_bar_time    ON signals(bar_time DESC);
CREATE INDEX idx_signals_type        ON signals(signal_type) WHERE passed = true;
CREATE INDEX idx_bar_logs_bar_time   ON bar_logs(bar_time DESC);
```

> **หมายเหตุ:** ไม่มี `positions` table อีกต่อไป เพราะระบบไม่ track position เอง ผู้ใช้ถือครองเองและตั้ง TP/SL เอง

### Manual Override (สำคัญมาก)

ถ้าบอทสั่ง BUY แต่คุณไม่ได้ซื้อตาม หรือคุณขายไปก่อน ให้แก้ State ผ่าน:

```bash
# วิธีที่ 1: ผ่าน Python CLI
python -c "from core.state_manager import set_state; set_state('EMPTY')"
python -c "from core.state_manager import set_state; set_state('HOLDING')"

# วิธีที่ 2: ผ่าน Supabase Dashboard (SQL Editor)
UPDATE system_state
SET current_position = 'EMPTY',
    note = 'Manual: ขายด้วยมือก่อนที่บอทจะสั่ง',
    updated_at = NOW()
WHERE id = 1;
```

### `db/supabase_writer.py`

```python
# db/supabase_writer.py
import json
import time
from pathlib import Path
from datetime import datetime
from config.settings import DRY_RUN, SUPABASE_URL, SUPABASE_KEY
from supabase import create_client, Client
import logging

logger = logging.getLogger("trading")
_client: Client | None = None

def get_supabase_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client

def _safe_upsert(table: str, data: dict, conflict_col: str = "id") -> bool:
    """INSERT with retry. DRY_RUN → log เท่านั้น"""
    if DRY_RUN:
        logger.info(f"[DRY_RUN] Would INSERT into {table}: {data.get('id', data.get('bar_time'))}")
        return True

    for attempt in range(3):
        try:
            get_supabase_client().table(table).upsert(
                data, on_conflict=conflict_col
            ).execute()
            return True
        except Exception as e:
            if attempt == 2:
                _write_fallback(table, data, str(e))
                return False
            time.sleep(2 ** attempt)

def _write_fallback(table: str, data: dict, error: str) -> None:
    Path("fallback").mkdir(exist_ok=True)
    with open("fallback/pending_inserts.jsonl", "a") as f:
        f.write(json.dumps({
            "table": table, "data": data, "error": error,
            "ts": datetime.utcnow().isoformat()
        }) + "\n")

def insert_signal(signal: dict) -> None:
    _safe_upsert("signals", signal)

def insert_bar_log(log: dict) -> None:
    _safe_upsert("bar_logs", log, conflict_col="bar_time")

def update_state(new_state: str) -> None:
    """อัปเดต system_state — เรียกหลัง insert_signal เสมอ"""
    if DRY_RUN:
        logger.info(f"[DRY_RUN] Would UPDATE system_state → {new_state}")
        return
    get_supabase_client().table("system_state").update({
        "current_position": new_state,
        "updated_at": "now()"
    }).eq("id", 1).execute()
```

---

<a name="phase-7"></a>
## Phase 7 — Discord Notifier

**จุดประสงค์:** แจ้งเตือนทุก event สำคัญผ่าน Discord webhook พร้อมข้อมูลประกอบการตัดสินใจ

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
    dry_prefix = "🧪 **[DRY RUN]** " if DRY_RUN else ""
    try:
        httpx.post(
            DISCORD_WEBHOOK_URL,
            json={"content": dry_prefix + content},
            timeout=10
        )
    except Exception as e:
        logger.warning(f"Discord webhook failed: {e}")

def notify_buy_signal(gate_result: dict) -> None:
    """
    ส่งแจ้งเตือน BUY — พร้อมข้อมูลประกอบการตัดสินใจ
    ผู้ใช้เป็นคนตั้ง TP/SL เองที่หน้างาน
    """
    mention = f"<@{DISCORD_MENTION_ID}>" if DISCORD_MENTION_ID else ""
    atr     = gate_result.get("atr_48", 0)

    msg = (
        f"{mention}\n"
        f"🟢 **BUY SIGNAL** — {gate_result['bar_time']}\n"
        f"```\n"
        f"Session     : {gate_result['session']}\n"
        f"Score       : {gate_result['ranker_score']:.4f}\n"
        f"HSH Ask     : {gate_result['hsh_ask']:,.2f} THB  ← ราคาซื้อ\n"
        f"HSH Bid     : {gate_result['hsh_bid']:,.2f} THB\n"
        f"XAU/USD     : {gate_result['xau_close']:.2f}\n"
        f"ATR(48)     : {atr:.2f} THB  ← ใช้ตั้ง TP/SL\n"
        f"TP แนะนำ    : {gate_result['hsh_bid'] + atr * 1.5:,.2f} (1.5× ATR)\n"
        f"SL แนะนำ    : {gate_result['hsh_bid'] - atr * 1.0:,.2f} (1.0× ATR)\n"
        f"```"
    )
    send_discord(msg)

def notify_sell_signal(gate_result: dict) -> None:
    """
    ส่งแจ้งเตือน SELL
    """
    mention = f"<@{DISCORD_MENTION_ID}>" if DISCORD_MENTION_ID else ""

    msg = (
        f"{mention}\n"
        f"🔴 **SELL SIGNAL** — {gate_result['bar_time']}\n"
        f"```\n"
        f"Session     : {gate_result['session']}\n"
        f"Score       : {gate_result['ranker_score']:.4f} (ต่ำกว่า threshold)\n"
        f"HSH Bid     : {gate_result['hsh_bid']:,.2f} THB  ← ราคาขาย\n"
        f"XAU/USD     : {gate_result['xau_close']:.2f}\n"
        f"```"
    )
    send_discord(msg)

def notify_heartbeat(state: str, last_bar: str, score: float) -> None:
    msg = (
        f"💓 **Heartbeat** — บอททำงานปกติ\n"
        f"State: `{state}` · Last bar: `{last_bar}` · Score: `{score:.4f}`"
    )
    send_discord(msg)

def notify_error(context: str, error: str) -> None:
    msg = f"⚠️ **ERROR** [{context}]\n```{error}```"
    send_discord(msg)
```

---

<a name="phase-8"></a>
## Phase 8 — Scheduler Orchestrator

**จุดประสงค์:** ควบคุมการทำงานของ pipeline — ตื่นทุก 10 นาที ประมวลผล ส่งสัญญาณ แล้วหลับต่อ

> **เปลี่ยนจาก v2.0:** ไม่มี Job B (1-min position monitor) อีกต่อไป เหลือแค่ Job A และ Job C

### Jobs

| Job | ชื่อ | ความถี่ | หน้าที่ |
|-----|------|---------|---------|
| Job A | `signal_pipeline` | ทุก 10 นาที (นาทีที่ลงท้ายด้วย 0) | รัน pipeline ทั้งหมด |
| Job C | `heartbeat` | ทุก 1 ชั่วโมง (ตอนตลาดเปิด) | แจ้งว่าบอทยังมีชีวิตอยู่ |

### `scheduler/orchestrator.py`

```python
# scheduler/orchestrator.py
import logging
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from config.settings import TIMEZONE, DRY_RUN, STATE_EMPTY, STATE_HOLDING
from core.candle_builder import build_candles
from core.feature_engine import compute_features
from core.model_inference import run_inference
from core.signal_gate import evaluate_signal_gate
from core.signal_recorder import build_signal_record
from core.state_manager import get_current_state, set_state
from db.supabase_writer import insert_signal, insert_bar_log, update_state
from notifier.discord_notifier import (
    notify_buy_signal, notify_sell_signal,
    notify_heartbeat, notify_error
)

TZ = pytz.timezone(TIMEZONE)
system_log  = logging.getLogger("system")
trading_log = logging.getLogger("trading")

# ─── ตัวแปร in-memory สำหรับ heartbeat ──────────────────────────────────────
_last_bar_time : str   = "N/A"
_last_score    : float = 0.0


def run_signal_pipeline() -> None:
    """
    Job A — รันทุก 10 นาที
    ลำดับ: Candle → Feature → Inference → Gate → Record → Notify
    """
    global _last_bar_time, _last_score
    now = datetime.now(TZ)
    system_log.info(f"[Job A] Pipeline started at {now.strftime('%H:%M:%S')}")

    try:
        # ─── P1: Build candles ────────────────────────────────────────────────
        candles_df = build_candles()

        # ─── P2: Compute features ─────────────────────────────────────────────
        features_row = compute_features(candles_df)

        # Early exit ถ้าตลาดปิด
        if features_row["session"] == "Closed":
            system_log.info("[Job A] Market closed — skipping")
            return

        # ─── P3: Model inference ──────────────────────────────────────────────
        inference_result = run_inference(features_row)
        _last_bar_time = features_row["bar_time"]
        _last_score    = inference_result["ranker_score"]

        # ─── P4: Signal gate + state check ───────────────────────────────────
        gate_result = evaluate_signal_gate(inference_result, features_row)

        # ─── P5: Build signal record ──────────────────────────────────────────
        signal_record = build_signal_record(gate_result)

        # ─── P6: Write to DB (always — ทั้ง pass และ reject) ─────────────────
        insert_signal(signal_record)

        # ─── Optional: bar_log ────────────────────────────────────────────────
        insert_bar_log({
            "bar_time"      : features_row["bar_time"],
            "session"       : features_row["session"],
            "state_at_bar"  : gate_result["state_before"],
            "ranker_score"  : inference_result["ranker_score"],
            "signal_passed" : gate_result["passed"],
            "signal_type"   : gate_result["signal_type"],
            "hsh_close_ask" : features_row["hsh_close_ask"],
            "hsh_close_bid" : features_row["hsh_close_bid"],
            "atr_48"        : features_row["F_ATR_48"],
            "features_snap" : inference_result["features_snap"],
        })

        # ─── ถ้าสัญญาณผ่าน → อัปเดต State + แจ้ง Discord ────────────────────
        if gate_result["passed"] and gate_result["signal_type"]:
            signal_type = gate_result["signal_type"]

            if signal_type == "BUY":
                new_state = STATE_HOLDING
                update_state(new_state)   # DB
                set_state(new_state)       # in-process validation
                notify_buy_signal(gate_result)
                trading_log.info(
                    f"BUY signal sent | score={_last_score:.4f} | "
                    f"ask={features_row['hsh_close_ask']:.2f}"
                )

            elif signal_type == "SELL":
                new_state = STATE_EMPTY
                update_state(new_state)
                set_state(new_state)
                notify_sell_signal(gate_result)
                trading_log.info(
                    f"SELL signal sent | score={_last_score:.4f} | "
                    f"bid={features_row['hsh_close_bid']:.2f}"
                )
        else:
            trading_log.info(
                f"No signal | state={gate_result['state_before']} | "
                f"score={_last_score:.4f} | reject={gate_result['reject_reason']}"
            )

    except Exception as e:
        system_log.error(f"[Job A] Pipeline error: {e}", exc_info=True)
        notify_error("Job A — signal_pipeline", str(e))


def run_heartbeat() -> None:
    """
    Job C — รันทุก 1 ชั่วโมง (ตอนตลาดเปิด)
    """
    try:
        state = get_current_state()
        notify_heartbeat(state, _last_bar_time, _last_score)
        system_log.info(f"[Job C] Heartbeat sent | state={state}")
    except Exception as e:
        system_log.warning(f"[Job C] Heartbeat error: {e}")


def start_scheduler() -> None:
    scheduler = BlockingScheduler(timezone=TZ)

    # Job A — ทุก 10 นาที (09:00–22:10 วันจันทร์–ศุกร์)
    scheduler.add_job(
        run_signal_pipeline,
        CronTrigger(
            minute="0,10,20,30,40,50",
            hour="9-22",
            day_of_week="mon-fri",
            timezone=TZ,
        ),
        id="signal_pipeline",
        name="M10 Signal Pipeline",
        max_instances=1,       # ป้องกัน overlap
        misfire_grace_time=60, # ถ้า delay ≤ 60s ยังรันได้
    )

    # Job C — heartbeat ทุกชั่วโมง ตอนตลาดเปิด
    scheduler.add_job(
        run_heartbeat,
        CronTrigger(
            minute=0,
            hour="9-22",
            day_of_week="mon-fri",
            timezone=TZ,
        ),
        id="heartbeat",
        name="System Heartbeat",
    )

    system_log.info(
        f"Scheduler started | DRY_RUN={DRY_RUN} | "
        f"Jobs: signal_pipeline (10min), heartbeat (1h)"
    )
    scheduler.start()
```

### `main.py`

```python
# main.py
import logging
from logger_setup import setup_logging
from scheduler.orchestrator import start_scheduler
from config.settings import DRY_RUN

setup_logging()
log = logging.getLogger("system")

if __name__ == "__main__":
    log.info("=" * 60)
    log.info("HSH ML Trader v3.0 — Signal Generator Mode")
    log.info(f"DRY_RUN = {DRY_RUN}")
    log.info("=" * 60)
    start_scheduler()
```

---

<a name="feature-engineering"></a>
## Feature Engineering Deep Dive (M10)

ดูรายละเอียดฉบับเต็มใน `core/feature_engine.py` — สรุปสำคัญ:

- **Anti-lookahead:** ทุก feature ใช้ `.shift(1)` ก่อน compute เพื่อป้องกัน data leakage
- **Session boundary:** momentum features ถูก reset ที่ขอบ session (ไม่ข้าม session)
- **F_FSP:** clip ที่ 1.0 เสมอ แม้ session จะยาวกว่า expected
- **OLS window:** 2016 bars × 10 min ≈ 2 สัปดาห์ → ต้องมีข้อมูลอย่างน้อย 2016 + 50 bars

---

<a name="logging"></a>
## Logging Strategy

```python
# logger_setup.py
import logging
import logging.handlers
from pathlib import Path
from config.settings import LOG_LEVEL

def setup_logging():
    Path("logs").mkdir(exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # ─── system.log ────────────────────────────────────────────────────────────
    system_handler = logging.handlers.TimedRotatingFileHandler(
        "logs/system.log", when="midnight", backupCount=30, encoding="utf-8"
    )
    system_handler.setFormatter(fmt)

    # ─── trading.log ───────────────────────────────────────────────────────────
    trading_handler = logging.handlers.TimedRotatingFileHandler(
        "logs/trading.log", when="midnight", backupCount=90, encoding="utf-8"
    )
    trading_handler.setFormatter(fmt)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)

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
| `logging.getLogger("system")` | Startup, shutdown, scheduler events, DB errors, pipeline errors |
| `logging.getLogger("trading")` | Signals (BUY/SELL/reject), state changes, heartbeat |

ห้ามใช้ logger เดียวกันสองตัว — `trading.log` ต้องมีเฉพาะ trading events เพื่อวิเคราะห์ประสิทธิภาพ

---

<a name="deployment"></a>
## Deployment Guide

### Option A — systemd (แนะนำสำหรับ VPS/Linux)

```ini
# /etc/systemd/system/hsh-trader.service
[Unit]
Description=HSH ML Gold Trader v3.0 — Signal Generator
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
sudo journalctl -u hsh-trader -f    # ดู live logs
```

### Option B — Docker

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
docker run -d \
  --name hsh-trader \
  --restart always \
  --env-file .env \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/fallback:/app/fallback \
  hsh-trader
```

### Monitoring Checklist (Production Go-Live)

- [ ] `DRY_RUN=false` ใน `.env`
- [ ] `init_state()` รันแล้ว — state ตรงกับความเป็นจริง (EMPTY หรือ HOLDING)
- [ ] systemd/Docker restart policy ตั้งค่าแล้ว
- [ ] Discord heartbeat Job C ทดสอบแล้ว
- [ ] logs/ directory มี disk space เพียงพอ (≥ 1 GB)
- [ ] Supabase quotas ตรวจสอบ (rows, requests/day)
- [ ] ทดสอบ `DRY_RUN=true` อย่างน้อย 3 trading days ก่อน go live
- [ ] ทดสอบ Manual Override ได้จริง (แก้ state ผ่าน CLI/Dashboard)

---

<a name="data-flow"></a>
## Data Flow Summary

```
hsh_prices, xau_prices, usd_thb_prices
     │
     ▼
[P1] M10 Candle Builder (ทำงานทุก 10 นาที)
     │ candles_df
     ▼
[P2] Feature Engine
     │ FeaturesRow (34 features)
     ▼
[P3] XGBoost Inference
     │ ranker_score
     ▼
[P4] Signal Gate & State Check ◄──── [DB: system_state]
     │                                (EMPTY = ไม่มีทอง, HOLDING = มีทอง)
     │
     ├─ State == EMPTY
     │    ├─ ผ่าน gate (score สูง, spread ดี, regime ดี) ──▶ Signal: BUY
     │    │                                                    │
     │    │                                         [P5] INSERT signal (BUY)
     │    │                                         [P6] UPDATE state → HOLDING
     │    │                                         [P7] Discord: 🟢 BUY Signal!
     │    │
     │    └─ ไม่ผ่าน gate ──▶ INSERT signal (passed=False) · log reject_reason
     │
     └─ State == HOLDING
          ├─ score ต่ำกว่า threshold ──▶ Signal: SELL
          │                               │
          │                    [P5] INSERT signal (SELL)
          │                    [P6] UPDATE state → EMPTY
          │                    [P7] Discord: 🔴 SELL Signal!
          │
          └─ score ยังสูง ──▶ INSERT signal (passed=False, reject=score_not_low) · ถือต่อ

[Job C] Heartbeat (every 1h ตอนตลาดเปิด) ──▶ [P7] Discord แจ้ง state + last score
```

**สิ่งที่ไม่มีอีกต่อไป (เทียบกับ v2.0):**
- ~~Job B (1-min position monitor)~~ → ไม่ต้องเฝ้าราคาทุก 1 นาที
- ~~TP/SL Calculator~~ → ผู้ใช้ตั้งเอง (Discord แสดง ATR reference ให้)
- ~~positions table~~ → บอทไม่ track position ระดับ trade

---

<a name="errors"></a>
## Error Handling & Failsafes

| สถานการณ์ | การจัดการ |
|-----------|---------|
| DB timeout ตอน fetch candles | retry 3 ครั้ง exponential backoff → log → ข้าม bar นั้น |
| Feature NaN ใน critical features | validate ก่อน inference → raise ValueError → reject signal |
| XGBoost predict fail | try/except → Discord alert → ไม่อัปเดต state |
| Supabase INSERT fail | retry 3 ครั้ง → เขียน `fallback/pending_inserts.jsonl` |
| State อ่านไม่ได้ (system_state ว่าง) | raise RuntimeError → Discord alert → Job A หยุดรัน bar นั้น |
| Discord webhook fail | log warning เท่านั้น → ไม่กระทบ trading logic |
| Duplicate signal (scheduler overlap) | `signal_id` เป็น PRIMARY KEY → INSERT conflict → idempotent |
| ตลาดปิด (session = Closed) | Phase 4 early return ก่อนเรียก gate |
| FEATURE_COLS drift (model vs code) | `lambdamart_v11_meta.json` เป็น source of truth + startup validation |
| Process crash | systemd Restart=always หรือ Docker restart policy |
| **State drift** (บอทบอก BUY แต่คุณไม่ซื้อ) | **Manual Override** ผ่าน CLI หรือ Supabase Dashboard |
| ไม่มี heartbeat | ระบบ offline → ตรวจสอบ systemd/Docker |

### Startup Validation

เพิ่มใน `main.py` ก่อนเรียก `start_scheduler()`:

```python
# ตรวจสอบ state ก่อน start
from core.state_manager import get_current_state
state = get_current_state()
log.info(f"Current state on startup: {state}")
# แจ้ง Discord ว่าบอท (re)start พร้อม state ปัจจุบัน
from notifier.discord_notifier import send_discord
send_discord(f"🚀 HSH Trader v3.0 started | State: `{state}` | DRY_RUN: `{DRY_RUN}`")
```

---

<a name="testing"></a>
## Testing & Paper Trading

### Paper Trading Mode

```bash
DRY_RUN=true python main.py
```

เมื่อ `DRY_RUN=true`:
- Signal pipeline รันปกติ (candle → feature → inference → gate)
- `[DRY RUN]` prefix ติด Discord message ทุกข้อความ
- ไม่มีการ INSERT/UPDATE Supabase จริง
- State ถูก mock เป็น EMPTY เสมอ
- ทุก action ถูก log เป็น INFO

**แนะนำ:** รัน dry run อย่างน้อย 3 trading days ก่อน go live

### Unit Tests

```bash
pytest tests/ -v
```

```python
# tests/test_signal_gate.py
def test_buy_signal_when_empty_and_high_score():
    """EMPTY state + high score → BUY"""
    # mock get_current_state() → 'EMPTY'
    # mock features score = 0.80
    gate = evaluate_signal_gate(...)
    assert gate["passed"] == True
    assert gate["signal_type"] == "BUY"

def test_no_buy_when_holding():
    """HOLDING state → ต้องไม่ส่ง BUY ไม่ว่า score จะสูงแค่ไหน"""
    # mock get_current_state() → 'HOLDING'
    gate = evaluate_signal_gate(...)
    assert gate["signal_type"] != "BUY"

def test_sell_signal_when_holding_and_low_score():
    """HOLDING state + low score → SELL"""
    # mock get_current_state() → 'HOLDING'
    # mock features score = 0.40
    gate = evaluate_signal_gate(...)
    assert gate["passed"] == True
    assert gate["signal_type"] == "SELL"

def test_no_signal_when_market_closed():
    """Closed session → ไม่มีสัญญาณไม่ว่า state จะเป็นอะไร"""
    # features_row["session"] = "Closed"
    gate = evaluate_signal_gate(...)
    assert gate["passed"] == False

# tests/test_state_manager.py
def test_init_state_creates_row():
    """init_state ต้องสร้างหรือ upsert row id=1"""
    ...

def test_invalid_state_raises():
    """set_state ด้วยค่าที่ไม่รู้จักต้องเกิด ValueError"""
    with pytest.raises(ValueError):
        set_state("UNKNOWN")
```

---

<a name="build-order"></a>
## Build Order

```
Week 1 — Foundation
  [x] Phase 0  — Config, requirements.txt, .env.example
  [x] Phase 6  — Supabase DDL Schema v3 (system_state + signals + bar_logs)
  [x] Phase 1  — M10 Candle Builder + SQL ทดสอบ
  [x] logger_setup.py

Week 2 — Core Pipeline
  [x] Phase 2  — Feature Engine (anti-lookahead, session boundary)
  [x] Phase 3  — Model Inference (JSON format, metadata)
  [x] Phase 4  — Signal Gate + State Manager (EMPTY/HOLDING logic)

Week 3 — Integration
  [x] Phase 5  — Signal Recorder
  [x] Phase 7  — Discord Notifier (BUY, SELL, heartbeat, error)
  [x] Phase 8  — Scheduler (Job A 10min + Job C 1h)
  [x] main.py  — startup validation + state display

Week 4 — Testing & Deployment
  [ ] Unit tests (tests/) — gate logic, state manager, edge cases
  [ ] DRY_RUN paper trading — 3 trading days minimum
  [ ] ทดสอบ Manual Override (CLI + Supabase Dashboard)
  [ ] Deployment setup (systemd หรือ Docker)
  [ ] Go live 🚀
```

---

*Architecture Version: 3.0 · Signal Generator Mode · Last Updated: 2025-08-01*
*Model: LambdaMART v11 · Timeframe: M10*
*Changes from v2.0: ตัด Phase 6 (TP/SL Calculator) และ Phase 7 (Position Monitor) ออก · เพิ่ม State Manager (EMPTY/HOLDING) · signals table รองรับ BUY และ SELL · Scheduler เหลือ Job A + Job C · Discord แสดง ATR reference สำหรับให้ผู้ใช้ตั้ง TP/SL เอง*
