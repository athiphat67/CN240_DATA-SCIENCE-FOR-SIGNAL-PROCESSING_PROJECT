<div align="center">

# 🏅 นักขุดทอง — Gold Trading AI Signal Generator

> **Course:** CN240 Data Science for Signal Processing  
> **Department of Computer Engineering, Thammasat University**  
> **Advisor:** Professor Dr. Charturong Tantibundhit

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![XGBoost](https://img.shields.io/badge/XGBoost-LambdaMART-orange)](https://xgboost.readthedocs.io)
[![Supabase](https://img.shields.io/badge/Database-Supabase-3ECF8E?logo=supabase)](https://supabase.com)
[![License](https://img.shields.io/badge/License-Academic%20Use%20Only-lightgrey)]()

**An AI Signal Generator for HSH965 gold trading, powered by Machine Learning and an LLM Agent**

---

[🚀 Getting Started](#️-installation) · [🏗️ Architecture](#️-system-architecture) · [📁 Project Structure](#-project-structure) · [⚙️ Installation](#️-installation) · [👥 Team](#-team)

</div>

---

## 📌 Overview

**นักขุดทอง (Gold Digger)** is a signal generator that analyzes HSH965 gold prices and sends BUY / SELL signals for the user to make their own trading decisions. The system **does not trade automatically** — the bot simply tells you "now looks like a good time to buy" or "now looks like a good time to sell" every 10 minutes via Discord.

The project runs two parallel systems:

| | **Src_V4** (Main) | **Src/** (Fallback) |
|---|---|---|
| **Approach** | Machine Learning (XGBoost LambdaMART) | ReAct LLM Agent + News Sentiment |
| **Model** | LambdaMART v11 · 420 trees · M10 timeframe | Gemini / Groq + FinBERT |
| **Output** | BUY / SELL signal every 10 minutes | BUY / SELL / HOLD with rationale |
| **Database** | Supabase (PostgreSQL) | PostgreSQL |
| **Notifications** | Discord Webhook | Discord + Telegram |

---

## 🏗️ System Architecture

### 1️⃣ Src_V4 — ML Pipeline (Main System)

The primary production system. It streams live HSH965 tick data over WebSocket, builds M10 candles, engineers 40+ technical features, and feeds them into a trained LambdaMART (XGBoost Ranker) model that scores each new bar into a BUY / SELL signal. Every signal passes a state-guarded signal gate (EMPTY / HOLDING) before being recorded to Supabase and broadcast through a Discord webhook with a human-readable rationale.

![LambdaMART ML architecture](Documentation/Pigture/System%20arhcitecture%20ML.png)

```
HSH965 tick (WebSocket)
    │
    ▼
[Phase 1] M10 Candle Builder
    │  Builds OHLCV candles from tick data every 10 minutes
    │
    ▼
[Phase 2] Feature Engine
    │  Computes 40+ features: RSI, EMA, OLS Slope, Volume Profile, etc.
    │
    ▼
[Phase 3] LambdaMART v11 Inference
    │  XGBoost Ranker · 420 trees · score → BUY / SELL
    │
    ▼
[Phase 4] Signal Gate + State Manager
    │  Signal filtering + State Guard (EMPTY / HOLDING)
    │
    ▼
[Phase 5] Signal Recorder
    │
    ├─► Supabase (PostgreSQL)   ← stores signals, features, system_state
    └─► Discord Webhook         ← @mention notification with rationale
```

### 2️⃣ Src/ — ReAct LLM Agent Pipeline (Fallback System)

The fallback system. A ReAct-based LLM agent (Gemini / Groq) that runs an iterative reasoning loop over live market data and macro news: the Data Engine gathers indicators and FinBERT news sentiment, the ReAct loop analyzes and debates through tool calls, and the Risk Manager validates the final BUY / SELL / HOLD decision with a written rationale before logging to PostgreSQL and notifying via Discord / Telegram and the Gradio dashboard.

![ReAct loop architecture](Documentation/Pigture/System%20Architecture%20React%20Loop.png)

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
    │  analyzes and debates through tool calls
    │
    ▼
[Risk Manager] → BUY / SELL / HOLD + written rationale
    │
    ├─► PostgreSQL
    ├─► Discord + Telegram
    └─► Gradio Dashboard (UI)
```

---

## 📁 Project Structure

```
นักขุดทอง/
│
├── Src_V4/                         ← Main system (XGBoost ML Signal Generator)
│   ├── core/
│   │   ├── candle_builder.py       ← Builds M10 candles from tick data
│   │   ├── feature_engine.py       ← Computes 40+ features
│   │   ├── model_inference.py      ← LambdaMART inference
│   │   ├── signal_gate.py          ← Signal filtering + state guard
│   │   ├── state_manager.py        ← Manages EMPTY / HOLDING state
│   │   └── dynamic_tp_manager.py   ← Dynamic take-profit tracking
│   ├── db/
│   │   ├── supabase_schema.sql     ← Full DDL (v3)
│   │   └── supabase_writer.py      ← Writes signal / state / features to DB
│   ├── scheduler/
│   │   └── orchestrator.py         ← APScheduler (Job A: M10, Job C: heartbeat)
│   ├── notifier/
│   │   └── discord_notifier.py     ← Discord Webhook notification
│   ├── rationale/
│   │   └── generator.py            ← Generates human-readable rationale
│   ├── monitoring/
│   │   └── pipeline_monitor.py     ← Pipeline health monitoring
│   ├── models/
│   │   └── lambdamart_v11.json     ← Trained model
│   ├── main.py                     ← Entry point
│   ├── .env.example
│   └── requirements.txt
│
├── Src/                            ← Fallback system (ReAct LLM Agent)
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
├── Src_V2/                         ← Version 2 (archived)
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

## ⚙️ Installation

### Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | Tested on 3.11.x |
| Supabase project | — | Requires service role key |
| Discord Webhook | — | Server Settings → Integrations |
| Model file | lambdamart_v11.json | Produced by the training pipeline |

---

### 🤖 Src_V4 — Main System (ML)

```bash
# 1. Enter the folder
cd Src_V4

# 2. Create a virtual environment
python3.11 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate         # Windows

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment variables
cp .env.example .env
# edit .env with real credentials

# 5. Create the Supabase schema
psql $DATABASE_URL < db/supabase_schema.sql

# 6. Set the initial state (if not holding any gold)
python -c "from db.supabase_writer import init_state; init_state('EMPTY')"

# 7. Try a dry run first
DRY_RUN=true python main.py

# 8. Run live
python main.py
```

**Environment Variables (`.env`):**

```bash
# Supabase
SUPABASE_URL=https://xxxxxxxxxxxxxxxxxxxx.supabase.co
SUPABASE_KEY=eyJ...                          # service role key

# Discord
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
DISCORD_MENTION_ID=123456789012345678        # user ID for @mention

# Mode
DRY_RUN=false                                # true = paper trading
LOG_LEVEL=INFO                               # DEBUG | INFO | WARNING | ERROR
TIMEZONE=Asia/Bangkok
```

---

### 🧠 Src/ — Fallback System (LLM Agent)

```bash
# 1. Enter the folder
cd Src

# 2. Create a virtual environment and install
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Configure environment variables
cp .env.example .env
# fill in Gemini / Groq API key, PostgreSQL URL, TwelveData API key

# 4. Run a one-shot analysis
python main.py --provider gemini --skip-fetch

# 5. Run the Gradio dashboard (UI)
python ui/dashboard.py

# 6. Run the React frontend (requires Node.js)
cd frontend
npm install
npm run dev
```

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

The system computes **40+ features** from each M10 candle:

| Group | Features |
|---|---|
| **Trend** | EMA(9), EMA(21), EMA(50), OLS Slope |
| **Momentum** | RSI(14), MACD, Stochastic |
| **Volatility** | ATR(14), Bollinger Bands width |
| **Volume** | Volume Profile, VWAP deviation |
| **Pattern** | Candle body ratio, wick ratio, gap |
| **Market Context** | Session (Asia/London/NY), Day of week |

---

## 📚 Documentation & Presentations

| Iteration | Documents |
|---|---|
| Phase 1 | [Discovery Report](Documentation/Papers/Phase1_Discovery_Report_Version1.pdf) · [Presentation Iteration 1](Documentation/Presentations/CN240_Presentation_Iteration1.pdf) |
| Phase 2 | [EDA Notebook](Documentation/Phase2_EDA.ipynb) · [Feature Engineering](Documentation/Phase2_FeatureEngineering.ipynb) · [Presentation Iteration 2](Documentation/Presentations/CN240_Presentation_Iteration2.pdf) |
| Phase 3 | [Presentation Iteration 3](Documentation/Presentations/CN240_Presentation_Iteration3.pdf) |
| Architecture | [hsh_ml_trading_architecture_v4.md](Src_V4/hsh_ml_trading_architecture_v4.md) |

---

## ⚠️ Disclaimer

> This system was developed for **educational purposes only**. It is not financial or investment advice.  
> Gold trading carries high risk; users are fully responsible for their own decisions.

---

## 👥 Team

| Name | Student ID |
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
