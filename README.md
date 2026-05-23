# นักขุดทอง — Gold Trading AI Agent

> **Course:** CN240 Data Science for Signal Processing
> **Institution:** Department of Computer Engineering, Thammasat University
> **Lecturer:** Professor Dr. Charturong Tantibundhit

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue)]()
[![License](https://img.shields.io/badge/License-Academic%20Use%20Only-lightgrey)]()

---

## Overview

ระบบ Signal Generator สำหรับเทรดทองคำ HSH965 รวม 2 แนวทาง:

| | Src_V4 (หลัก) | Src/ (สำรอง) |
|---|---|---|
| **แนวทาง** | XGBoost LambdaMART (ML) | ReAct LLM Agent + News Sentiment |
| **Model** | LambdaMART v11 · 420 trees · M10 timeframe | Gemini / Groq + FinBERT |
| **Output** | BUY / SELL signal ทุก 10 นาที | BUY / SELL / HOLD พร้อม rationale |
| **DB** | Supabase (PostgreSQL) | PostgreSQL |
| **Notify** | Discord Webhook | Discord + Telegram |

---

## โครงสร้างโปรเจกต์

```
Src_V4/                        ← ระบบหลัก (XGBoost ML Signal Generator)
├── core/
│   ├── candle_builder.py      ← สร้าง M10 candle จาก tick data
│   ├── feature_engine.py      ← คำนวณ 40+ features (RSI, EMA, OLS slope ฯลฯ)
│   ├── model_inference.py     ← LambdaMART inference
│   ├── signal_gate.py         ← กรอง signal + state guard
│   ├── state_manager.py       ← จัดการสถานะ EMPTY / HOLDING
│   └── dynamic_tp_manager.py  ← ติดตาม TP แบบ dynamic
├── db/
│   ├── supabase_schema.sql    ← DDL ทั้งหมด
│   └── supabase_writer.py     ← เขียน signal / state / features ลง DB
├── scheduler/orchestrator.py  ← APScheduler — Job A (M10) + Job C (heartbeat)
├── models/lambdamart_v11.json ← trained model
├── tests/                     ← test suite (pytest)
├── main.py                    ← entry point
└── requirements.txt

Src/                           ← ระบบสำรอง (ReAct LLM Agent)
├── agent_core/                ← ReAct loop, LLM clients, RiskManager
├── data_engine/               ← orchestrator, indicators, news fetcher
├── engine/engine.py           ← WatcherEngine (event-driven trigger)
├── backtest/                  ← backtest pipeline
└── main.py                    ← entry point
```

---

## วิธีรัน

### Src_V4 (ML หลัก)

```bash
cd Src_V4
pip install -r requirements.txt
cp .env.example .env          # ใส่ DATABASE_URL + DISCORD_WEBHOOK_URL

# paper trading (dry run)
DRY_RUN=true python main.py

# live
python main.py
```

### Src/ (LLM สำรอง)

```bash
cd Src
pip install -r requirements.txt
cp .env.example .env          # ใส่ Gemini/Groq API key, PostgreSQL, TwelveData

# one-shot analysis
python main.py --provider gemini --skip-fetch

# Gradio dashboard
python ui/dashboard.py
```

### Tests (Src_V4)

```bash
cd Src_V4
pytest
```

---

## Data Flow (Src_V4)

```
HSH965 tick (WebSocket)
    → M10 Candle Builder
    → Feature Engine (40+ features)
    → LambdaMART v11 inference
    → Signal Gate (state guard + confidence threshold)
    → Supabase  +  Discord notification
```

---

## ทีมงาน

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
