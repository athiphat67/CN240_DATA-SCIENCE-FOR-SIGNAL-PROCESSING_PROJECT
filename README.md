<div align="center">

# 🏅 นักขุดทอง — Gold Trading AI Signal Generator

> **Course:** CN240 Data Science for Signal Processing  
> **Department of Computer Engineering, Thammasat University**  
> **Advisor:** Professor Dr. Charturong Tantibundhit

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![XGBoost](https://img.shields.io/badge/XGBoost-LambdaMART-orange)](https://xgboost.readthedocs.io)
[![Supabase](https://img.shields.io/badge/Database-Supabase-3ECF8E?logo=supabase)](https://supabase.com)
[![License](https://img.shields.io/badge/License-Academic%20Use%20Only-lightgrey)]()

**ระบบ AI Signal Generator สำหรับการเทรดทองคำ HSH965 โดยใช้ Machine Learning และ LLM Agent**

---

[🚀 เริ่มต้นใช้งาน](#-quick-start) · [🏗️ สถาปัตยกรรม](#️-สถาปัตยกรรมระบบ) · [📁 โครงสร้างโปรเจกต์](#-โครงสร้างโปรเจกต์) · [⚙️ การติดตั้ง](#️-การติดตั้ง) · [🧪 การทดสอบ](#-การทดสอบ) · [👥 ทีมงาน](#-ทีมงาน)

</div>

---

## 📌 ภาพรวมโปรเจกต์

**นักขุดทอง** คือระบบ Signal Generator ที่วิเคราะห์ราคาทองคำ HSH965 แล้วส่งสัญญาณ BUY / SELL ให้ผู้ใช้ตัดสินใจเทรดเอง ระบบ **ไม่ได้เทรดอัตโนมัติ** — บอทเพียงบอกว่า "ตอนนี้น่าซื้อ" หรือ "ตอนนี้น่าขาย" ทุก 10 นาที ผ่าน Discord

โปรเจกต์นี้มี 2 ระบบคู่ขนาน:

| | **Src_V4** (ระบบหลัก) | **Src/** (ระบบสำรอง) |
|---|---|---|
| **แนวทาง** | Machine Learning (XGBoost LambdaMART) | ReAct LLM Agent + News Sentiment |
| **Model** | LambdaMART v11 · 420 trees · Timeframe M10 | Gemini / Groq + FinBERT |
| **Output** | BUY / SELL signal ทุก 10 นาที | BUY / SELL / HOLD พร้อม rationale |
| **Database** | Supabase (PostgreSQL) | PostgreSQL |
| **แจ้งเตือน** | Discord Webhook | Discord + Telegram |

---

## 🏗️ สถาปัตยกรรมระบบ

### Src_V4 — ML Pipeline (ระบบหลัก)

```
HSH965 tick (WebSocket)
    │
    ▼
[Phase 1] M10 Candle Builder
    │  สร้าง OHLCV candle จาก tick data ทุก 10 นาที
    │
    ▼
[Phase 2] Feature Engine
    │  คำนวณ 40+ features: RSI, EMA, OLS Slope, Volume Profile ฯลฯ
    │
    ▼
[Phase 3] LambdaMART v11 Inference
    │  XGBoost Ranker · 420 trees · score → BUY / SELL
    │
    ▼
[Phase 4] Signal Gate + State Manager
    │  กรอง signal + State Guard (EMPTY / HOLDING)
    │
    ▼
[Phase 5] Signal Recorder
    │
    ├─► Supabase (PostgreSQL)   ← บันทึก signals, features, system_state
    └─► Discord Webhook         ← แจ้งเตือน @mention พร้อม rationale
```

### Src/ — LLM Agent Pipeline (ระบบสำรอง)

```
Market Data (TwelveData / yfinance)  +  News (GDELT / Finnhub)
    │
    ▼
[Data Engine] Orchestrator
    │  fetch indicators + sentiment + macro news
    │
    ▼
[Agent Core] ReAct Loop (LLM)
    │  Gemini / Groq + FinBERT sentiment
    │  วิเคราะห์และ debate ผ่าน Tool calls
    │
    ▼
[Risk Manager] → BUY / SELL / HOLD + written rationale
    │
    ├─► PostgreSQL
    ├─► Discord + Telegram
    └─► Gradio Dashboard (UI)
```

---

## 📁 โครงสร้างโปรเจกต์

```
นักขุดทอง/
│
├── Src_V4/                         ← ระบบหลัก (XGBoost ML Signal Generator)
│   ├── core/
│   │   ├── candle_builder.py       ← สร้าง M10 candle จาก tick data
│   │   ├── feature_engine.py       ← คำนวณ 40+ features
│   │   ├── model_inference.py      ← LambdaMART inference
│   │   ├── signal_gate.py          ← กรอง signal + state guard
│   │   ├── state_manager.py        ← จัดการสถานะ EMPTY / HOLDING
│   │   └── dynamic_tp_manager.py   ← ติดตาม TP แบบ dynamic
│   ├── db/
│   │   ├── supabase_schema.sql     ← DDL ทั้งหมด (v3)
│   │   └── supabase_writer.py      ← เขียน signal / state / features ลง DB
│   ├── scheduler/
│   │   └── orchestrator.py         ← APScheduler (Job A: M10, Job C: heartbeat)
│   ├── notifier/
│   │   └── discord_notifier.py     ← Discord Webhook notification
│   ├── rationale/
│   │   └── generator.py            ← สร้าง human-readable rationale
│   ├── monitoring/
│   │   └── pipeline_monitor.py     ← ตรวจสอบ pipeline health
│   ├── models/
│   │   └── lambdamart_v11.json     ← Trained model
│   ├── tests/                      ← Test suite (pytest)
│   ├── main.py                     ← Entry point
│   ├── .env.example
│   └── requirements.txt
│
├── Src/                            ← ระบบสำรอง (ReAct LLM Agent)
│   ├── agent_core/                 ← ReAct loop, LLM clients, RiskManager
│   │   ├── core/prompt.py          ← Prompt engineering
│   │   ├── core/react.py           ← ReAct agent loop
│   │   ├── core/risk.py            ← Risk management
│   │   └── llm/client.py           ← Multi-provider LLM client
│   ├── data_engine/                ← Orchestrator, indicators, news fetcher
│   │   ├── orchestrator.py
│   │   ├── indicators.py
│   │   ├── newsfetcher.py
│   │   └── analysis_tools/
│   ├── engine/engine.py            ← WatcherEngine (event-driven)
│   ├── backtest/                   ← Backtest pipeline
│   │   ├── engine/
│   │   ├── metrics/
│   │   └── run_main_backtest.py
│   ├── frontend/                   ← React + TypeScript Dashboard
│   │   ├── components/
│   │   └── api/main.py             ← FastAPI backend
│   ├── notification/               ← Discord + Telegram
│   ├── ui/dashboard.py             ← Gradio Dashboard (legacy)
│   ├── main.py                     ← Entry point
│   └── requirements.txt
│
├── Src_V2/                         ← เวอร์ชัน 2 (archived)
│
├── Data/
│   └── Raw/
│       ├── CBOE_Gold_Volatility_Historical_Data.csv
│       ├── USDTHB_Daily_*.csv
│       ├── VIX_History.csv
│       └── XAUUSD_Daily_*.csv
│
├── Documentation/
│   ├── Phase2_EDA.ipynb
│   ├── Phase2_FeatureEngineering.ipynb
│   ├── Papers/
│   │   └── Phase1_Discovery_Report_Version1.pdf
│   └── Presentations/
│       ├── CN240_Presentation_Iteration1.pdf
│       ├── CN240_Presentation_Iteration2.pdf
│       └── CN240_Presentation_Iteration3.pdf
│
├── news_api_backtest/              ← Historical news pipeline
├── public/
│   └── logo.png
└── README.md
```

---

## ⚙️ การติดตั้ง

### Prerequisites

| สิ่งที่ต้องมี | Version | หมายเหตุ |
|---|---|---|
| Python | 3.11+ | ทดสอบบน 3.11.x |
| Supabase project | — | ต้องมี service role key |
| Discord Webhook | — | Server Settings → Integrations |
| Model file | lambdamart_v11.json | ได้จาก training pipeline |

---

### 🤖 Src_V4 — ระบบหลัก (ML)

```bash
# 1. เข้าโฟลเดอร์
cd Src_V4

# 2. สร้าง virtual environment
python3.11 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows

# 3. ติดตั้ง dependencies
pip install -r requirements.txt

# 4. ตั้งค่า environment variables
cp .env.example .env
# แก้ไข .env ด้วย credentials จริง

# 5. สร้าง Supabase schema
psql $DATABASE_URL < db/supabase_schema.sql

# 6. ตั้งค่า initial state (ถ้าไม่มีทองในมือ)
python -c "from db.supabase_writer import init_state; init_state('EMPTY')"

# 7. ทดสอบด้วย dry run ก่อน
DRY_RUN=true python main.py

# 8. รัน live
python main.py
```

**Environment Variables (`.env`):**

```bash
# Supabase
SUPABASE_URL=https://xxxxxxxxxxxxxxxxxxxx.supabase.co
SUPABASE_KEY=eyJ...                          # service role key

# Discord
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
DISCORD_MENTION_ID=123456789012345678        # user ID สำหรับ @mention

# Mode
DRY_RUN=false                                # true = paper trading
LOG_LEVEL=INFO                               # DEBUG | INFO | WARNING | ERROR
TIMEZONE=Asia/Bangkok
```

---

### 🧠 Src/ — ระบบสำรอง (LLM Agent)

```bash
# 1. เข้าโฟลเดอร์
cd Src

# 2. สร้าง virtual environment และติดตั้ง
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. ตั้งค่า environment variables
cp .env.example .env
# ใส่ Gemini / Groq API key, PostgreSQL URL, TwelveData API key

# 4. รัน one-shot analysis
python main.py --provider gemini --skip-fetch

# 5. รัน Gradio dashboard (UI)
python ui/dashboard.py

# 6. รัน React frontend (ต้องมี Node.js)
cd frontend
npm install
npm run dev
```

---

## 🧪 การทดสอบ

```bash
# Src_V4 — รัน test suite ทั้งหมด
cd Src_V4
pytest

# รัน test เฉพาะไฟล์
pytest tests/test_signal_gate.py -v

# รัน paper trading dry-run
DRY_RUN=true python main.py

# ทดสอบ sell scenarios
python test_sell_scenarios_dryrun.py
```

**Test Coverage (Src_V4):**

| Test File | ครอบคลุม |
|---|---|
| `test_candle_builder.py` | M10 candle construction |
| `test_feature_engine.py` | Feature calculation parity |
| `test_signal_gate.py` | Signal filtering logic |
| `test_state_manager.py` | EMPTY / HOLDING state transitions |
| `test_e2e_mock_state_machine.py` | End-to-end flow |
| `test_snapshot_alignment.py` | Feature snapshot consistency |

---

## 🔧 Tech Stack

### Src_V4 (ML)

| Category | Library |
|---|---|
| **ML Model** | `xgboost==2.0.3` (LambdaMART Ranker) |
| **Data Processing** | `pandas`, `numpy`, `scipy` |
| **Database** | `supabase==2.4.0` (PostgreSQL) |
| **Scheduling** | `APScheduler==3.10.4` |
| **HTTP** | `httpx` |
| **Logging** | `structlog` |
| **Testing** | `pytest`, `pytest-mock` |

### Src/ (LLM Agent)

| Category | Library |
|---|---|
| **LLM Providers** | `google-genai`, `groq`, `anthropic`, `openai`, `ollama` |
| **ML / NLP** | `xgboost`, `scikit-learn`, `transformers` (FinBERT) |
| **Data** | `pandas`, `numpy`, `pandas-ta`, `yfinance` |
| **Backend API** | `fastapi`, `uvicorn`, `SQLAlchemy` |
| **Frontend** | React + TypeScript + Vite + Tailwind CSS |
| **Dashboard** | `gradio` |
| **Database** | `supabase`, `psycopg2-binary` |
| **Notifications** | Discord Webhook, Telegram Bot API |

---

## 📊 Feature Engineering (Src_V4)

ระบบคำนวณ **40+ features** จาก M10 candle:

| กลุ่ม | Features |
|---|---|
| **Trend** | EMA(9), EMA(21), EMA(50), OLS Slope |
| **Momentum** | RSI(14), MACD, Stochastic |
| **Volatility** | ATR(14), Bollinger Bands width |
| **Volume** | Volume Profile, VWAP deviation |
| **Pattern** | Candle body ratio, wick ratio, gap |
| **Market Context** | Session (Asia/London/NY), Day of week |

---

## 📚 เอกสารและ Presentation

| Iteration | เอกสาร |
|---|---|
| Phase 1 | [Discovery Report](Documentation/Papers/Phase1_Discovery_Report_Version1.pdf) · [Presentation Iteration 1](Documentation/Presentations/CN240_Presentation_Iteration1.pdf) |
| Phase 2 | [EDA Notebook](Documentation/Phase2_EDA.ipynb) · [Feature Engineering](Documentation/Phase2_FeatureEngineering.ipynb) · [Presentation Iteration 2](Documentation/Presentations/CN240_Presentation_Iteration2.pdf) |
| Phase 3 | [Presentation Iteration 3](Documentation/Presentations/CN240_Presentation_Iteration3.pdf) |
| Architecture | [hsh_ml_trading_architecture_v4.md](Src_V4/hsh_ml_trading_architecture_v4.md) |

---

## ⚠️ Disclaimer

> ระบบนี้พัฒนาขึ้นเพื่อ **วัตถุประสงค์ทางการศึกษาเท่านั้น** ไม่ใช่คำแนะนำทางการเงินหรือการลงทุน  
> การเทรดทองคำมีความเสี่ยงสูง ผู้ใช้รับผิดชอบการตัดสินใจเองทั้งหมด

---

## 👥 ทีมงาน

| ชื่อ | Student ID |
|---|---|
| Athiphat Sunsit | 6710615292 |
| Purich Ampawa | 6710615185 |
| Theepop Rattanasubsiri | 6710685014 |
| Chotiwit Daugstan | 6710615060 |
| Napattira Loaklemhung | 6710545010 |
| Benchaphon Pinakasa | 6710625028 |
| Lalita Thatsananunchai | 6710615243 |
| Phatcharaphon Malaisri | 6710685055 |
| Sitthipong Kamngam | 6710615284 |
| Panithan Tuntue | 6710615144 |

---

<div align="center">

**Department of Computer Engineering · Thammasat University · 2026**

</div>