# 📖 Src_V2 — นักขุดทอง v2.1 (XGBoost-based Gold Trading Signal System)

## 1. ภาพรวม (Overview)

`Src_V2` คือระบบ **สร้างสัญญาณซื้อ-ขายทองคำไทย** แบบอัตโนมัติ ที่ขับเคลื่อนด้วย **Dual-Model XGBoost** (ไม่ใช่ Generative AI / LLM)
โดยทำงานเป็น loop ต่อเนื่องทุก 15 นาที ดึงข้อมูลตลาดแบบ real-time แล้วให้โมเดล ML ตัดสินใจว่าควร **BUY**, **SELL** หรือ **HOLD**

### สิ่งที่ระบบทำ (High-Level)
1. **ดึงข้อมูลตลาด** — ราคาทองไทย (ฮั่วเซ่งเฮง/Intergold), ราคา Spot Gold (XAU/USD), อัตราแลกเปลี่ยน USD/THB, OHLCV, ข่าวสาร
2. **คำนวณ Technical Indicators** — RSI, MACD, Bollinger Bands, ATR, EMA/Trend
3. **สกัด Feature Vector** → 26 ตัวแปร ตาม schema `models/feature_columns.json`
4. **XGBoost Dual-Model Predict** → `model_buy.pkl` + `model_sell.pkl` ทำนาย probability → ตัดสิน BUY/SELL/HOLD
5. **Gates (Risk + Session)** — กรองสัญญาณผ่าน RiskManager + SessionGate แบบ concurrent
6. **Market Monitoring** — ใช้ WatcherEngine เฝ้าดูตลาดระหว่าง Sleep เพื่อปลุก AI เมื่อเกิดเหตุการณ์สำคัญ (RSI Extreme, SL Hit)
7. **แจ้งเตือน + บันทึก** — ส่ง Discord/Telegram (ถ้า ALL PASS) และบันทึกทุกรอบลง PostgreSQL

---

## 2. สถาปัตยกรรม (Architecture)

```
                          ┌─────────────────────────────┐
                          │         main.py              │
                          │    (Orchestration Loop)      │
                          └──────────┬──────────┬───────┘
                                     │          │
            ┌────────────────────────┼──────────┴─────────────┐
            ▼                        ▼                        ▼
   ┌─────────────────┐    ┌──────────────────┐     ┌─────────────────────┐
   │   data_engine/   │    │    ml_core/       │     │    watch_engine/    │
   │   orchestrator   │    │    signal.py      │     │    watcher.py       │
   │                  │    │  (XGBoostPredictor)│     │ (Sleep Monitoring)  │
   └────────┬────────┘    └────────┬─────────┘     └──────────┬──────────┘
            │                      │                          │
   ┌────────┴────────┐             │                 ┌────────┴──────────┐
   │  fetcher.py     │             │                 │ _AnalysisAdapter  │
   │  indicators.py  │             │                 └────────┬──────────┘
   │  newsfetcher.py │             │                          │
   │  ohlcv_fetcher  │             │              ┌───────────▼──────────┐
   │  interceptor    │             │              │       core.py        │
   │  extract_features│            │              │    (CoreDecision)    │
   └─────────────────┘             │              └───────────┬──────────┘
                                   │                          │
                     ┌─────────────┴──────────────┐   ┌───────┴──────────┐
                     │        notification/        │   │     risk.py      │
                     │  discord_notifier.py        │   │  session_gate.py │
                     │  telegram_notifier.py       │   └──────────────────┘
                     └─────────────────────────────┘
                                   │
                     ┌─────────────┴──────────────┐
                     │        database/            │
                     │  database.py (PostgreSQL)   │
                     └─────────────────────────────┘
```

---

## 3. Pipeline Flow (ขั้นตอนการทำงาน)

ระบบมีการทำงาน 2 โหมดขนานกัน:

### A. Scheduled Cycle (ทุก 15 นาที)
1. **Fetch → Predict → Decide → Action** ตามปกติ
2. เมื่อจบ Cycle ระบบจะเข้าสู่โหมด **Sleep**

### B. Event-Driven Monitoring (ระหว่าง Sleep)
1. **WatcherEngine** ทำงานเบื้องหลัง (Thread แยก) ตรวจตลาดทุก 30 วินาที
2. **Trigger Points**: RSI ต่ำ/สูงเกินไป, ราคาชน Trailing Stop, หรือราคาเปลี่ยนแรง
3. **Action**: ถ้าเข้าเงื่อนไข Watcher จะใช้ **Adapter** ปลุก Loop หลักให้รัน `run_analysis_once` ทันทีโดยไม่ต้องรอนาทีที่ 15

---

## 4. โครงสร้างไดเรกทอรี (Directory Structure)

```
Src_V2/
├── main.py                     # Entry point — orchestration loop + Watcher integration
├── core.py                     # CoreDecision (fan-out gates → fan-in)
├── .env                        # Environment variables (API keys, DB URL)
├── requirements.txt            # Python dependencies
│
├── data_engine/                # === Data Layer ===
│   ├── orchestrator.py         # GoldTradingOrchestrator — conductor หลัก
│   ├── fetcher.py              # GoldDataFetcher — ดึงราคา spot, forex, ทองไทย
│   ├── ohlcv_fetcher.py        # OHLCVFetcher — ดึงกราฟแท่งเทียน
│   ├── indicators.py           # TechnicalIndicators
│   ├── extract_features.py     # สกัด 26 features สำหรับ XGBoost
│   └── newsfetcher.py          # GoldNewsFetcher — ข่าว + FinBERT sentiment
│
├── ml_core/                    # === ML / Decision Layer ===
│   ├── signal.py               # XGBoostPredictor — dual-model predict
│   ├── risk.py                 # RiskManager — (V5) กฎการเทรดและ Stop Loss
│   └── session_gate.py         # SessionGate — ตรวจช่วงเวลาเทรด
│
├── watch_engine/               # === Monitoring Layer ===
│   ├── watcher.py              # WatcherEngine — เฝ้าราคาและ RSI ระหว่าง sleep
│   └── indicators.py           # Indicators สำหรับ watcher
│
├── database/                   # === Persistence Layer ===
│   └── database.py             # RunDatabase — PostgreSQL (connection pool)
│
├── notification/               # === Notification Layer ===
│   ├── discord_notifier.py     
│   └── telegram_notifier.py    
│
└── logs/                       # === Logging & Analytics ===
    ├── logger_setup.py         # sys_logger configuration
    └── api_logger.py           # Trade log API sender & result wrappers
```

---

## 5. รายละเอียดแต่ละ Module (อัปเดต v2.1)

### 5.1 `main.py` — The Heart
- **Hybrid Loop**: ผสมผสานระบบ Timer (15 นาที) กับ Event-driven (Watcher)
- **Watcher Integration**: ใช้ `_AnalysisServiceAdapter` เพื่อให้ Watcher สามารถเรียกใช้ Pipeline การวิเคราะห์ของ v2 ได้
- **Modular Config**: เลิก Hardcode ค่า Risk ใน main แล้วดึงจาก Default ของ `risk.py` แทน

### 5.2 `ml_core/risk.py` — RiskManager (Single Source of Truth)
- เป็นที่เก็บ Config หลักของระบบเทรด (V5 Scalping Edition)
- **ATR 2.5**, **RRR 1.5**, **Confidence 0.60**, **Max Daily Loss 500 THB**
- `main.py` จะดึงค่าจากที่นี่ไปใช้โดยตรง

### 5.3 `logs/api_logger.py` — Unified Logging
- **Modularized**: ย้ายโค้ดเตรียมข้อมูล Log ออกจาก `main.py` มาไว้ที่นี่
- ฟังก์ชัน `send_trade_log_from_result` ทำหน้าที่แพ็กข้อมูล Decision และ Market State ส่งเข้า API

### 5.4 `watch_engine/watcher.py` — The Guard
- ทำงานเฉพาะตอน Loop หลักกำลัง "นอน"
- ตรวจสอบราคาและ RSI ทุก 30 วินาที
- **Trailing Stop**: เลื่อน SL อัตโนมัติเมื่อกำไรวิ่งไปแล้ว
- **Cooldown**: มีระบบป้องกันไม่ให้ปลุก AI ถี่เกินไป (5 นาที)

---

## 6. Key Design Decisions (อัปเดต)

1. **Dual-Model Predict**: แยก BUY/SELL เป็น 2 โมเดลเพื่อความแม่นยำ
2. **Hybrid Execution**: ไม่รอรอบเวลาอย่างเดียว แต่ใช้ความไวของ Watcher Engine มาเสริม
3. **Single Source of Truth**: ย้ายการตั้งค่ากฎการเทรดไปไว้ที่ `risk.py` ที่เดียว
4. **Adapter Pattern**: ใช้ `_AnalysisServiceAdapter` เชื่อมต่อ Module เก่า (Watcher) เข้ากับ Pipeline ใหม่ (XGBoost)
5. **Decoupled Logging**: แยกตรรกะการส่ง Log ออกไปเพื่อให้ `main.py` โฟกัสเฉพาะเรื่องกลยุทธ์

---

## 7. ความแตกต่างจาก Src (v1)

| หัวข้อ | Src (v1) | Src_V2 (v2.1) |
|--------|----------|---------------|
| **Engine** | LLM-based | Pure ML (XGBoost) |
| **Logic Flow** | รอรอบเวลา | Hybrid (Scheduled + Event-driven) |
| **Configuration** | กระจัดกระจาย | Centralized ใน risk.py |
| **Execution** | Sequential | Concurrent Gates + Threaded Watcher |
| **Log Prep** | เขียนใน main | แยกเป็น Module อิสระ |
