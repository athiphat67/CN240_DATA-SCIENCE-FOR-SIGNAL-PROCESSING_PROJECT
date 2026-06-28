# about_src.md — GoldTrader Agent · ภาพรวมซอร์สโค้ด

> เวอร์ชัน: v3.4 | แพลตฟอร์ม: ออม NOW (Hua Seng Heng) | งบต้น: ฿1,500 THB

---

## สารบัญ

1. [ภาพรวมระบบ](#1-ภาพรวมระบบ)
2. [Architecture Diagram](#2-architecture-diagram)
3. [รายละเอียดไฟล์ทีละตัว](#3-รายละเอียดไฟล์ทีละตัว)
4. [Data Flow — Live Trading](#4-data-flow--live-trading)
5. [Data Flow — Backtest](#5-data-flow--backtest)
6. [ReAct Loop อธิบายละเอียด](#6-react-loop-อธิบายละเอียด)
7. [Risk Management Rules](#7-risk-management-rules)
8. [LLM Clients ที่รองรับ](#8-llm-clients-ที่รองรับ)
9. [Database Schema](#9-database-schema)
10. [Environment Variables](#10-environment-variables)
11. [การรันระบบ](#11-การรันระบบ)
12. [Project Structure](#12-project-structure)
13. [Main Flow — ลำดับการทำงานแบบ Step-by-Step](#13-main-flow--ลำดับการทำงานแบบ-step-by-step)

---

## 1. ภาพรวมระบบ

GoldTrader เป็น **AI Trading Agent** สำหรับซื้อขายทองคำบนแพลตฟอร์ม ออม NOW (Hua Seng Heng) โดยใช้ **ReAct Loop** (Reasoning + Acting) เชื่อมกับ LLM หลายตัว ระบบวิเคราะห์ตัวชี้วัดทางเทคนิค (RSI, MACD, EMA, Bollinger Bands, ATR) ประกอบกับ Sentiment ของข่าว แล้วตัดสินใจ BUY / SELL / HOLD

**ข้อจำกัดหลัก (Hard Rules)**

| กฎ | ค่า |
|---|---|
| เงินต้น | ฿1,500 THB |
| ขนาด Order | ฿1,400 THB ต่อครั้ง (คงที่) |
| ซื้อได้เมื่อ | Cash ≥ ฿1,408 (position 1,400 + fee 8) และไม่มีทองอยู่ในมือ |
| Dead Zone (ห้ามเทรด) | 02:00–06:14 น. (ตลาดปิด) |
| Confidence ขั้นต่ำ | 0.60 (LLM) / 0.75 (BUY signal) |

---

## 2. Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                        Entry Points                         │
│   main.py (CLI loop)        dashboard.py (Gradio Web UI)    │
└──────────────────────────┬──────────────────────────────────┘
                           │
                    services.py
                    AnalysisService
                           │
          ┌────────────────┼────────────────┐
          │                │                │
    orchestrator.py    prompt.py        client.py
    (Market Data)     (PromptBuilder)  (LLMClient)
          │                │                │
    ┌─────┴──────┐   ┌─────┴──────┐   ┌────┴─────────────────┐
    │ fetcher.py │   │  react.py  │   │ Gemini/OpenAI/        │
    │newsfetcher │   │ (ReAct Loop│   │ Claude/Groq/          │
    │            │   │ + extract) │   │ Ollama/DeepSeek/      │
    └─────┬──────┘   └─────┬──────┘   │ OpenRouter/Mock       │
          │                │           └──────────────────────┘
          │          ┌─────┴──────┐
          │          │  risk.py   │
          │          │(RiskManager│
          │          │ TP/SL/Dead)│
          │          └────────────┘
          │
    ┌─────┴────────────────────────────┐
    │     database.py                  │
    │  runs / llm_logs / portfolio     │
    │  trade_log                       │
    └──────────────────────────────────┘
          │
    ┌─────┴──────────────────────┐
    │   Notifications            │
    │  discord_notifier.py       │
    │  telegram_notifier.py      │
    └────────────────────────────┘
```

---

## 3. รายละเอียดไฟล์ทีละตัว

### 🔵 Core Layer

#### `prompt.py` — Part C: Prompt System

สร้าง `PromptPackage` ที่ส่งระหว่าง PromptBuilder → LLMClient

**คลาสหลัก:**

| คลาส | หน้าที่ |
|---|---|
| `PromptPackage` | Data container: `system`, `user`, `step_label` |
| `AIRole` (Enum) | `ANALYST` / `RISK_MANAGER` / `TRADER` |
| `Skill` | ชื่อ + description + tools list |
| `SkillRegistry` | โหลด/ลงทะเบียน Skills จาก `skills.json` |
| `RoleDefinition` | System prompt template + available skills |
| `RoleRegistry` | โหลด/ลงทะเบียน Roles จาก `roles.json` |
| `PromptBuilder` | สร้าง prompt สำหรับ THOUGHT step และ FINAL_DECISION step |

**Method สำคัญ:**

- `build_thought(market_state, tool_results, iteration)` — สร้าง prompt สำหรับแต่ละ iteration ของ ReAct พร้อม action guidance ตาม iteration (1=บังคับ CALL_TOOL/CALL_TOOLS, 2=เลือกได้, 3+=บังคับ FINAL_DECISION)
- `build_final_decision(market_state, tool_results)` — สร้าง prompt สำหรับ force final decision เมื่อ iteration เต็ม
- `_format_market_state(state)` — แปลง market state dict เป็น text รวมถึง Dead Zone warning, Portfolio PnL status, Session Gate context และ Backtest directive

**การเปลี่ยนแปลงสำคัญ v3.4:**
- `MIN_BUY_CASH = 1408` (position 1,400 + fee 8)
- `position_size_thb` ใน prompt = 1,400 (ไม่ใช่ 1,000)
- รองรับ `CALL_TOOLS` (parallel) format นอกเหนือจาก `CALL_TOOL` (P10)

---

#### `react.py` — Part B: ReAct Orchestration Loop

ควบคุม Thought → Action → Observation → FINAL_DECISION

**คลาสหลัก:**

| คลาส | หน้าที่ |
|---|---|
| `ReadinessConfig` | inject required_indicators จากภายนอก (P1) |
| `ReactConfig` | `max_iterations`, `max_tool_calls`, `timeout_seconds`, `readiness` |
| `ToolResult` | ผลจาก tool: `tool_name`, `status`, `data`, `error` |
| `ReactState` | State ระหว่าง loop: `market_state`, `tool_results`, `iteration` |
| `AgentDecision` | Pydantic model validate + normalise LLM output (P2) |
| `StateReadinessChecker` | ตรวจข้อมูลพร้อมหรือไม่ก่อน tool loop (P1) |
| `ReactOrchestrator` | Run loop หลัก + dependency injection |

**Fast Path (max_tool_calls = 0):** ข้าม loop ไปเรียก LLM ครั้งเดียวทันที — ใช้ใน production ปัจจุบัน

**Full ReAct Path:** วนลูปจนถึง max_iterations หรือ LLM ส่ง `"action": "FINAL_DECISION"` กลับมา

**Actions ที่ LLM ส่งได้:**
- `FINAL_DECISION` — ตัดสินใจสัญญาณ
- `CALL_TOOL` — เรียก tool เดียว (sequential)
- `CALL_TOOLS` — เรียกหลาย tool พร้อมกัน (parallel, P10)

**Helper functions:**
- `parse_agent_response(raw)` — parse + validate ด้วย Pydantic แทน extract_json (P2)
- `_extract_json_objects(text)` — balanced-brace scanner รองรับ nested JSON (P2)
- `_lenient_loads(text)` — json.loads + strip trailing comma (P2)
- `_make_llm_log(step, iteration, llm_resp, parsed)` — สร้าง trace entry พร้อม token metadata
- `extract_json(raw)` — [LEGACY] เก็บไว้ backward compat

**P1 — StateReadinessChecker:** ตรวจ technical_indicators ครบตาม `required_indicators` และ HTF coverage ก่อนวน tool loop — ถ้าข้อมูลพร้อมแล้วข้ามไป FINAL_DECISION เลยเพื่อประหยัด LLM call

**P10 — Parallel Tool Execution:** `_execute_tools_parallel()` ใช้ asyncio.gather + to_thread รัน tool หลายตัวพร้อมกัน exception ต่อ tool แปลงเป็น ToolResult(status="error") ไม่ crash loop

---

#### `risk.py` — RiskManager

ทำหน้าที่ "ยามเฝ้าประตู" ก่อนส่ง signal ออกไปจริง

**ด่านตรวจ (ตามลำดับ):**

```
ด่าน 0: Hard Rules
  → Dead Zone 02:00-06:14 → REJECT ทันที
  → TP/SL Price Hit (check_price vs tp_price/sl_price) → OVERRIDE เป็น SELL

ด่าน 1: Confidence Filter
  → confidence < min_confidence (0.60) → REJECT

ด่าน 2: Daily Loss Limit
  → accumulated loss ≥ max_daily_loss_thb (500 THB) → REJECT BUY

ด่าน 3: Signal Processing
  → BUY: คำนวณ SL/TP จาก ATR × multiplier (default 2.0 / RR 1.5)
         investment_thb = 1,400 (คงที่)
  → SELL: คำนวณ gold_value จาก gold_grams × sell_price
  → HOLD: ผ่านตรง
```

**Parameters:**

| Parameter | Default | ความหมาย |
|---|---|---|
| `atr_multiplier` | 2.0 | ATR × 2 = ระยะ Stop Loss |
| `risk_reward_ratio` | 1.5 | SL distance × 1.5 = ระยะ Take Profit |
| `min_confidence` | 0.60 | Confidence ขั้นต่ำ |
| `min_trade_thb` | 1400.0 | ขนาด order ขั้นต่ำ |
| `micro_port_threshold` | 2000.0 | Threshold portfolio ขนาดเล็ก |
| `max_daily_loss_thb` | 500.0 | ขาดทุนสะสมสูงสุดต่อวัน |
| `max_trade_risk_pct` | 0.30 | Risk สูงสุดต่อ trade (% of portfolio) |

---

#### `session_gate.py` — Session Gate

ตรวจสอบและแนบบริบทของ session เทรดก่อนส่งเข้า LLM

**หน้าที่:**
- ตรวจเวลาปัจจุบันว่าอยู่ใน session window ไหน (night/morning/noon/evening/weekend)
- แนบ `session_gate` dict เข้า market_state เพื่อให้ LLM รู้ว่าเหลือเวลาเท่าไหร่ในรอบ
- ถ้า `quota_urgent=True` (เหลือ ≤ 15 นาที) → แนะนำ LLM ใช้โหมด Quota (conf ≥ 0.55)
- ถ้าอยู่นอก session → `apply_gate=False` ไม่แนบ context

**Session Windows (วันธรรมดา):**

| Session | ช่วงเวลา | Quota Group |
|---|---|---|
| night | 00:00–01:59 | night_morning |
| morning | 06:15–11:59 | night_morning |
| noon | 12:00–17:59 | noon |
| evening | 18:00–23:59 | evening |

**Session Windows (เสาร์–อาทิตย์):** 09:30–17:30 (weekend)

**Functions หลัก:**
- `resolve_session_gate(now, force_bypass, urgent_threshold_minutes)` → `SessionGateResult`
- `attach_session_gate_to_market_state(market_state, result)` — อัพเดต market_state ในที่เดียว

---

#### `client.py` — LLM Client Layer

Abstract base class + concrete implementations สำหรับ LLM ทุกตัว

**Return type:** ทุก client คืน `LLMResponse` ที่มี:

```python
text          # raw text response (JSON string)
prompt_text   # full prompt ที่ส่งไป
token_input   # จำนวน input tokens
token_output  # จำนวน output tokens
token_total   # รวม
model         # model name
provider      # provider name
```

**Clients ที่รองรับ:**

| Class | Provider | Default Model |
|---|---|---|
| `GeminiClient` | Google Gemini | `gemini-3.1-flash-lite-preview` |
| `OpenAIClient` | OpenAI GPT | `gpt-4o-mini` |
| `ClaudeClient` | Anthropic Claude | `claude-sonnet-4-5` |
| `GroqClient` | Groq LPU | `llama-3.3-70b-versatile` |
| `DeepSeekClient` | DeepSeek | `deepseek-chat` |
| `OllamaClient` | Ollama local | `qwen3.5:9b` |
| `OpenRouterClient` | OpenRouter | `google/gemini-3-flash-preview` |
| `MockClient` | Testing only | — |
| `FallbackChainClient` | Wrapper fallback chain | — |

**OpenRouterClient Shortcuts:**

| Shortcut | Full Model |
|---|---|
| `claude-haiku-4-5` | `anthropic/claude-haiku-4-5` |
| `claude-haiku-3-5` | `anthropic/claude-3.5-haiku` |
| `claude-sonnet-4-6` | `anthropic/claude-sonnet-4.6` |
| `gpt-5-mini` | `openai/gpt-5-mini` |
| `gpt-4o-mini` | `openai/gpt-4o-mini` |
| `llama-70b` | `meta-llama/llama-3.3-70b-instruct` |
| `grok-mini` | `x-ai/grok-3-mini` |
| `mistral-small` | `mistralai/mistral-small-3.2-24b-instruct-2506` |
| `gemini-3-flash-preview` | `google/gemini-3-flash-preview` |
| `gemini-2.5-flash-lite` | `google/gemini-2.5-flash-lite` |
| `deepseek-v-3-2` | `deepseek/deepseek-v3.2` |

**FallbackChainClient รองรับ Failure Domain:** ถ้า provider fail และมี `domain` กำกับ จะ skip provider ตัวอื่นใน domain เดียวกันทันที เช่น gemini fail → skip gemini ทุก tier โดยไม่ต้อง retry แต่ละตัว

---

### 🟢 Data Layer

#### `fetcher.py` — GoldDataFetcher

ดึงราคาทองและ Forex จาก API หลายแหล่งพร้อม consensus logic

**แหล่งข้อมูล:**

| ข้อมูล | แหล่งหลัก | Fallback |
|---|---|---|
| Gold Spot (USD) | TwelveData API | yfinance → gold-api.com |
| USD/THB | exchangerate-api.com | — |
| ราคาทองไทย (THB) | `latest_gold_price.json` (WebSocket) | คำนวณจากสูตร |

**Confidence Score:** คำนวณจาก deviation ระหว่างแหล่งข้อมูล ถ้า deviation > 0.5% → confidence ลด

---

#### `newsfetcher.py` — GoldNewsFetcher

ดึงและวิเคราะห์ sentiment ข่าวทองคำ

**8 หมวดหมู่ข่าว:**

| Category | Impact | แหล่งที่มา |
|---|---|---|
| `gold_price` | direct | Kitco RSS, yfinance GC=F |
| `usd_thb` | direct | FXStreet RSS, yfinance THB=X |
| `fed_policy` | high | Reuters RSS |
| `inflation` | high | Reuters RSS |
| `geopolitics` | high | Kitco + Reuters |
| `dollar_index` | medium | FXStreet |
| `thai_economy` | medium | Bangkok Post RSS |
| `thai_gold_market` | direct | Kitco + Bangkok Post |

**Sentiment:** FinBERT via Hugging Face API (ProsusAI/finbert)

**Smart Cache:** บันทึก `news_cache.json` แบ่งรอบ 00:00-11:59 / 12:00-23:59 — ไม่ดึงซ้ำในรอบเดิม

---

#### `orchestrator.py` — GoldTradingOrchestrator

รวม Fetcher + Indicators + NewsFetcher แล้ว output เป็น JSON Payload

**Method สำคัญ:**
- `run(save_to_file, history_days, interval)` — ดึงข้อมูลครบชุด
- `pack(full_state)` — **[Phase 5]** สกัด "essential state" เฉพาะข้อมูลที่จำเป็น เพื่อลด Token ก่อนส่งเข้า LLM บังคับให้ LLM เรียก tool มากขึ้น

**โครงสร้าง Payload:**

```json
{
  "meta": { ... },
  "data_quality": { "quality_score": "good|degraded", "warnings": [] },
  "market_data": {
    "spot_price_usd": { "price_usd_per_oz": ..., "confidence": ... },
    "forex": { "usd_thb": ... },
    "thai_gold_thb": { "sell_price_thb": ..., "buy_price_thb": ... },
    "recent_price_action": [ { "datetime", "open", "high", "low", "close", "volume" } ],
    "price_trend": { "current_close_usd", "prev_close_usd", "daily_change_pct", ... }
  },
  "technical_indicators": {
    "rsi": { "value": ..., "signal": "oversold|neutral|overbought" },
    "macd": { "macd_line", "signal_line", "histogram", "signal" },
    "trend": { "ema_20", "ema_50", "trend": "uptrend|downtrend|sideways" },
    "bollinger": { "upper", "lower", "mid" },
    "atr": { "value": ..., "unit": "THB_PER_BAHT_WEIGHT", "value_usd": ... }
  },
  "news": { "summary": { ... }, "by_category": { ... }, "latest_news": [...] }
}
```

**Background Thread:** เปิด WebSocket (`gold_interceptor_lite`) ดึงราคาทองไทยแบบ real-time ทันทีที่ class นี้ถูกสร้าง

---

### 🟡 Service Layer

#### `services.py` — Business Logic Layer

**3 Services หลัก:**

**`AnalysisService`** — หัวใจหลักของระบบ

```
1. Normalize provider name (gemini_2.5_flash → gemini, openrouter:xxx → pass-through)
2. Validate inputs (provider / period / intervals)
3. Check Thailand market hours (warn only)
4. Fetch market data via orchestrator
5. Attach portfolio state จาก DB
6. Run _run_single_interval() → ReAct loop (single interval, ไม่มี multi-vote แล้ว)
7. Build voting_result passthrough (backward compat structure)
8. Save to DB (runs + llm_logs)
9. Send Discord + Telegram notification
```

> **v3.4:** ตัด multi-interval weighted voting ออก — ใช้ interval เดียวเท่านั้น (ตัวแรกใน list) `voting_result` ยังมีอยู่เพื่อ backward compat แต่ไม่มี logic multi-vote จริง

**ATR Conversion (services.py):** แปลง ATR จาก USD/oz → THB/baht_weight ก่อนส่ง RiskManager
```
atr_thb = (atr_usd × usd_thb / 31.1035) × 15.244
```

**`PortfolioService`** — CRUD portfolio ใน DB

**`HistoryService`** — ดึง run history + LLM logs + statistics รวม method ใหม่ `get_llm_logs_for_run()`

---

### 🔴 Notification Layer

#### `discord_notifier.py` — Discord Webhook

ส่ง Embed message พร้อม:
- Signal + Confidence bar
- Entry / SL / TP levels
- ราคา ออม NOW (THB)
- Per-interval breakdown
- Voting summary
- Rationale

#### `telegram_notifier.py` — Telegram Bot API

ส่ง HTML-formatted message เนื้อหาเดียวกับ Discord

**Toggle:** `DISCORD_NOTIFY_HOLD` / `TELEGRAM_NOTIFY_HOLD` ควบคุมว่าจะแจ้ง HOLD หรือไม่

---

### 🟤 Backtest

#### `run_main_backtest.py` — MainPipelineBacktest

รัน full pipeline (Fetcher + ReAct + RiskManager) บน historical CSV data

**Components:**

| Class | หน้าที่ |
|---|---|
| `CandleCache` | Cache ผล LLM ต่อ candle ลง JSON file |
| `TimeEstimator` | คาดเดา ETA จาก rolling average |
| `MainPipelineBacktest` | Main class: load → run → metrics → export |

**Metrics ที่คำนวณ:**

- Directional Accuracy, Signal Sensitivity
- Win Rate, Profit Factor, Expectancy
- **MDD** (Maximum Drawdown) — พร้อม timestamp peak/trough
- **Sharpe Ratio** (annualized, risk-free rate 2%)
- **Sortino Ratio** (downside semi-deviation)
- Calmar Ratio
- Session Compliance %

**v3.4 เพิ่มใหม่:**
- `_compute_risk_metrics()` — คำนวณ MDD/Sharpe/Sortino จาก equity curve (`portfolio_total_value` column)
- Export CSV เพิ่ม 3 columns: `portfolio_total_value`, `portfolio_cash`, `portfolio_gold_grams`

---

### 🔧 Support Files

#### `database.py` — RunDatabase (PostgreSQL)

Connection pool (min=1, max=5) สำหรับ Render free tier

**4 Tables:**

| Table | เก็บอะไร |
|---|---|
| `runs` | ผล analysis ทุกครั้ง: signal, confidence, price levels, market snapshot, data quality |
| `llm_logs` | กระบวนการคิดทั้งหมด: full prompt, response, token usage, elapsed ms |
| `portfolio` | สถานะ portfolio ปัจจุบัน (1 row, UPSERT) |
| `trade_log` | ประวัติ BUY/SELL ทุกรายการพร้อม PnL per-trade |

**v3.4 columns ใหม่ใน runs:** `is_weekend`, `data_quality`, `macd_histogram`, `bb_pct_b`, `atr_thb`

#### `logger_setup.py`

- `sys_logger` → `system.log` (INFO)
- `llm_logger` → `llm_trace.log` (DEBUG)
- RotatingFileHandler (5MB × 3 backup)
- TH Time formatter (UTC+7)
- `@log_method(logger)` decorator จับเวลาอัตโนมัติ

#### `api_logger.py`

ส่ง trade log ไปยัง external API (`goldtrade-logs-api.poonnatuch.workers.dev`) ทุกครั้งที่มี signal

#### `technical_tools.py` / `fundamental_tools.py`

Tools สำหรับ ReAct loop ที่ LLM สามารถเรียกใช้ได้ (ส่วนใหญ่ยัง `not_implemented`)

---

## 4. Data Flow — Live Trading

```
main.py หรือ dashboard.py
    │
    ▼
AnalysisService.run_analysis()
    │
    ├─ GoldTradingOrchestrator.run()
    │      ├─ GoldDataFetcher.fetch_all()
    │      │      ├─ fetch_gold_spot_usd()  [TwelveData + yfinance + gold-api]
    │      │      ├─ fetch_usd_thb_rate()   [exchangerate-api.com]
    │      │      └─ calc_thai_gold_price() [latest_gold_price.json / fallback]
    │      ├─ TechnicalIndicators(ohlcv_df)
    │      └─ GoldNewsFetcher.to_dict()     [Cache / FinBERT]
    │
    ├─ resolve_session_gate() → attach_session_gate_to_market_state()
    │
    ├─ ATR conversion: USD/oz → THB/baht_weight
    │
    ├─ GoldTradingOrchestrator.pack(full_state)  ← slim state สำหรับ LLM
    │
    ├─ ReactOrchestrator.run(slim_state, ohlcv_df)
    │      ├─ [Fast Path] build_final_decision() → LLM → parse_agent_response()
    │      └─ [Full Path] StateReadinessChecker → tool loop → FINAL_DECISION
    │
    ├─ RiskManager.evaluate(llm_decision, market_state)
    │      ├─ Dead Zone check
    │      ├─ TP/SL override
    │      ├─ Confidence filter
    │      └─ ATR-based SL/TP calculation (investment_thb = 1,400)
    │
    ├─ RunDatabase.save_run() + save_llm_logs_batch()
    │
    └─ DiscordNotifier + TelegramNotifier
```

---

## 5. Data Flow — Backtest

```
run_main_backtest.py (CLI)
    │
    ├─ load_gold_csv() → aggregate to timeframe
    │
    └─ for each candle:
           ├─ TradingSessionManager.process_candle()  [Dead Zone / Session check]
           ├─ CandleCache.get()                        [Skip LLM ถ้า cached]
           ├─ MarketStateBuilder.build()               [สร้าง market_state]
           ├─ ReactOrchestrator.run(market_state)      [LLM → signal]
           ├─ RiskManager.evaluate()                   [Filter]
           ├─ SimPortfolio.execute_buy/sell()          [Simulate trades]
           └─ CandleCache.set()                        [บันทึก result]
```

---

## 6. ReAct Loop อธิบายละเอียด

```
Fast Path (max_tool_calls = 0) — ใช้ใน production ปัจจุบัน:
    build_final_decision() → LLM call → parse_agent_response() → RiskManager → done

Readiness Skip (P1):
    StateReadinessChecker.is_ready() == True → ข้ามทั้ง tool loop → FINAL_DECISION ทันที

Full Path (ถ้าเปิด tools):
    THOUGHT_1
        │
        ├── action = "FINAL_DECISION"  → exit
        ├── action = "CALL_TOOL"       → execute 1 tool → OBSERVATION → THOUGHT_2
        ├── action = "CALL_TOOLS"      → execute N tools parallel → OBSERVATION × N → THOUGHT_2
        └── unknown → fallback HOLD

    ... (repeat จนถึง max_iterations)

    THOUGHT_FINAL (forced) → parse_agent_response() → RiskManager → done
```

**JSON format ที่ LLM ต้อง output (FINAL_DECISION):**

```json
{
  "action": "FINAL_DECISION",
  "signal": "BUY" | "SELL" | "HOLD",
  "confidence": 0.0,
  "position_size_thb": 1400,
  "rationale": "..."
}
```

**JSON format สำหรับ CALL_TOOLS (parallel):**

```json
{
  "action": "CALL_TOOLS",
  "thought": "ต้องการ HTF trend และ news พร้อมกัน",
  "tools": [
    {"tool_name": "get_htf_trend", "tool_args": {}},
    {"tool_name": "get_deep_news_by_category", "tool_args": {"category": "fed_policy"}}
  ]
}
```

**AgentDecision validation (P2):**
- clamp confidence 0–1
- normalise signal uppercase
- degrade CALL_TOOL-without-tool_name → FINAL_DECISION/HOLD
- degrade CALL_TOOLS-without-tools → CALL_TOOL (ถ้ามี tool_name) หรือ HOLD
- parse_failed flag สำหรับ safe loop control

---

## 7. Risk Management Rules

### BUY Conditions (ใน roles.json + risk.py)

| เงื่อนไข | ค่า |
|---|---|
| Cash available | ≥ ฿1,408 (position 1,400 + fee 8) |
| Gold held | = 0 gram |
| Bullish signals | ≥ 3 จาก (RSI < 35, MACD Hist > 0, Price > EMA20, Bounce from Lower BB) |
| LLM Confidence | ≥ 0.75 |
| Dead Zone | ไม่อยู่ใน 02:00–06:14 |
| Daily loss | < ฿500 accumulated |

### SELL Conditions

| เงื่อนไข | ประเภท |
|---|---|
| TP price hit (check_price ≥ tp_price) | Hard Override |
| SL price hit (check_price ≤ sl_price) | Hard Override |
| RSI > 70 | LLM Technical |
| MACD Histogram < 0 | LLM Technical |
| Price breaks below EMA20 | LLM Technical |
| Trend switches to downtrend/sideways | LLM Technical |
| Time 01:30–01:59 (pre-close) | Warning to LLM |

---

## 8. LLM Clients ที่รองรับ

```python
from agent_core.llm.client import LLMClientFactory

client = LLMClientFactory.create("gemini")              # gemini-3.1-flash-lite-preview
client = LLMClientFactory.create("groq")
client = LLMClientFactory.create("claude")              # claude-sonnet-4-5
client = LLMClientFactory.create("openai", model="gpt-4o")
client = LLMClientFactory.create("ollama", model="qwen3.5:9b")
client = LLMClientFactory.create("deepseek")
client = LLMClientFactory.create("openrouter")          # default: gemini-3-flash-preview
client = LLMClientFactory.create("openrouter:claude-haiku-4-5")   # colon syntax
client = LLMClientFactory.create("openrouter:llama-70b")
client = LLMClientFactory.create("openrouter:anthropic/claude-haiku-4-5")  # full name
client = LLMClientFactory.create("mock")                # Testing
```

**Fallback Chain (with domain grouping):**

```python
from agent_core.llm.client import FallbackChainClient

chain = FallbackChainClient([
    ("gemini-3.1", GeminiClient(),            "google"),   # domain ใช้ skip ทั้ง google ถ้า fail
    ("groq",       GroqClient(),              "groq"),
    ("mock",       MockClient(),              None),
])
result = chain.call(prompt_package)
print(chain.active_provider)  # provider ที่ใช้จริง
print(chain.errors)           # log ของที่ fail ทั้งหมด
```

---

## 9. Database Schema

```sql
-- ผล analysis
runs (
    id, run_at, provider, interval_tf, period,
    signal, confidence,
    entry_price, stop_loss, take_profit,           -- THB/gram
    entry_price_thb, stop_loss_thb, take_profit_thb,  -- aliases
    usd_thb_rate, gold_price_thb,
    rationale, iterations_used, tool_calls_used,
    gold_price, rsi, macd_line, signal_line, trend,
    react_trace,      -- JSON array
    market_snapshot,  -- JSON
    -- v3.4 ใหม่:
    is_weekend,       -- BOOLEAN
    data_quality,     -- "good" | "degraded" | "unknown"
    macd_histogram,   -- REAL
    bb_pct_b,         -- REAL (%B ของ Bollinger Band)
    atr_thb           -- REAL (หลัง convert เป็น THB)
)

-- กระบวนการคิดของ LLM
llm_logs (
    id, run_id, logged_at, interval_tf,
    step_type, iteration, provider,
    signal, confidence, rationale,
    entry_price, stop_loss, take_profit,
    full_prompt, full_response, trace_json,
    token_input, token_output, token_total,
    elapsed_ms, iterations_used, tool_calls_used,
    is_fallback, fallback_from
)

-- สถานะ Portfolio (1 row)
portfolio (
    id, cash_balance, gold_grams,
    cost_basis_thb, current_value_thb,
    unrealized_pnl, trades_today, updated_at
)

-- ประวัติการเทรดทุกรายการ (v3.4 ใหม่)
trade_log (
    id, run_id, action,           -- "BUY" | "SELL"
    executed_at, price_thb, gold_grams, amount_thb,
    cash_before, cash_after, gold_before, gold_after,
    cost_basis_thb, pnl_thb, pnl_pct, note
)
```

---

## 10. Environment Variables

| Variable | ใช้ใน | ความหมาย |
|---|---|---|
| `DATABASE_URL` | database.py | PostgreSQL connection string |
| `GEMINI_API_KEY` | client.py | Google Gemini API key |
| `OPENAI_API_KEY` | client.py | OpenAI API key |
| `ANTHROPIC_API_KEY` | client.py | Claude API key |
| `GROQ_API_KEY` | client.py | Groq API key |
| `DEEPSEEK_API_KEY` | client.py | DeepSeek API key |
| `OPENROUTER_API_KEY` | client.py | OpenRouter API key |
| `OPENROUTER_MODEL` | client.py | Override default OpenRouter model |
| `OPENROUTER_APP_URL` | client.py | HTTP-Referer header |
| `OPENROUTER_APP_NAME` | client.py | X-Title header |
| `TWELVEDATA_API_KEY` | fetcher.py | TwelveData price API |
| `HF_TOKEN` | newsfetcher.py | Hugging Face (FinBERT) |
| `DISCORD_WEBHOOK_URL` | discord_notifier.py | Discord Webhook URL |
| `DISCORD_NOTIFY_ENABLED` | discord_notifier.py | `true` / `false` |
| `DISCORD_NOTIFY_HOLD` | discord_notifier.py | แจ้งสัญญาณ HOLD ด้วยหรือไม่ |
| `DISCORD_NOTIFY_MIN_CONF` | discord_notifier.py | Confidence ขั้นต่ำที่จะแจ้ง (0.0–1.0) |
| `TELEGRAM_BOT_TOKEN` | telegram_notifier.py | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | telegram_notifier.py | Chat ID เป้าหมาย |
| `TEAM_API_KEY` | main.py, dashboard.py | GoldTrade Logs API key |
| `OLLAMA_BASE_URL` | client.py | Ollama server URL (default: localhost:11434) |
| `OLLAMA_MODEL` | client.py | Ollama default model |
| `DASHBOARD_USER` | dashboard.py | Basic auth username |
| `DASHBOARD_PASS` | dashboard.py | Basic auth password |
| `PORT` | dashboard.py | Port สำหรับ Gradio server |

---

## 11. การรันระบบ

### Live Trading (CLI)

```bash
# รันด้วย Gemini (default)
python main.py --provider gemini-3.1-flash-lite-preview

# เลือก interval
python main.py --provider gemini-3.1-flash-lite-preview --intervals 1h

# ใช้ OpenRouter + shortcut
python main.py --provider openrouter:claude-haiku-4-5
python main.py --provider openrouter:llama-70b
python main.py --provider openrouter:gpt-5-mini

# ใช้ OpenRouter + full model name
python main.py --provider openrouter:anthropic/claude-haiku-4-5

# ดู shortcut ทั้งหมด
python main.py --list-models

# ข้าม session gate (สำหรับทดสอบนอกเวลาเทรด)
python main.py --provider gemini-3.1-flash-lite-preview --bypass-session-gate

# ข้าม fetch ใช้ข้อมูลเดิม
python main.py --provider gemini-3.1-flash-lite-preview --skip-fetch

# ไม่บันทึก DB
python main.py --provider groq --no-save
```

### Live Trading (Dashboard)

```bash
python dashboard.py
# เปิด browser: http://localhost:7860
```

### Backtest

```bash
python run_main_backtest.py \
  --gold-csv data/premium_hsh/Mock_HSH_OHLC.csv \
  --timeframe 5m \
  --days 1 \
  --provider gemini \
  --react-iter 5
```

### Orchestrator เดี่ยว (ดึงข้อมูลอย่างเดียว)

```bash
python orchestrator.py --history 30 --interval 5m
```

---

## หมายเหตุสำคัญสำหรับ Developer

- **ราคาใน DB เป็น THB/gram เสมอ** ไม่ใช่ USD/oz — อย่าแปลงซ้ำ
- **ATR จาก orchestrator มีหน่วย USD/oz** แต่ services.py แปลงเป็น THB/baht_weight ก่อนส่ง RiskManager แล้ว (`atr_node["unit"] = "THB_PER_BAHT_WEIGHT"`)
- **Order Size คงที่ที่ ฿1,400** — MIN_BUY_CASH = ฿1,408 (รวม fee ฿8)
- **Fast Path เท่านั้นที่ใช้ใน production** (`max_tool_calls = 0`) — full ReAct loop อยู่ระหว่างพัฒนา แต่ code พร้อมแล้ว
- **Multi-interval voting ถูกตัดออกใน v3.4** — ใช้ interval เดียว (ตัวแรกใน list) `voting_result` ยังมีอยู่เพื่อ backward compat กับ UI/DB
- **Session Gate inject เข้า market_state** ก่อน LLM ทุกครั้งถ้าอยู่ในช่วง session — LLM จะเห็น `quota_urgent`, `llm_mode`, `suggested_min_confidence`
- **FallbackChainClient** รองรับ Failure Domain — skip provider ทั้ง domain ถ้าตัวแรกพัง ลด latency กรณี API ทั้ง tier ล่ม
- **OpenRouter colon syntax** (`openrouter:model-name`) รองรับทั้งใน CLI และ services.py — `_normalize_provider()` จะ pass-through โดยไม่แตะ
- **Dead Zone** ถูก enforce ทั้งใน RiskManager (hard reject) และใน prompt (warning ให้ LLM รู้ล่วงหน้า)
- **`news_cache.json`** refresh ทุกครึ่งวัน ถ้าต้องการ force refresh ให้ลบไฟล์ออก
- **`StateReadinessChecker`** inject `require_htf=True` และ `required_indicators` ผ่าน `ReadinessConfig` — ปัจจุบัน production ใช้ `force_react_loop` ใน list เพื่อบังคับให้ผ่าน tool loop เสมอ (is_ready จะ return False)

---

## 12. Project Structure

```
Src/
│
├── main.py                          ← CLI entry point (while-loop, 5 min interval)
├── dashboard.py                     ← Gradio Web UI entry point
│
├── agent_core/                      ← AI Agent core
│   ├── config/
│   │   ├── roles.json               ← Role definitions + system prompts
│   │   └── skills.json              ← Skill definitions + tool lists
│   ├── core/
│   │   ├── prompt.py                ← PromptBuilder, RoleRegistry, SkillRegistry
│   │   ├── react.py                 ← ReactOrchestrator, AgentDecision (Pydantic)
│   │   ├── risk.py                  ← RiskManager (gate 0–3)
│   │   └── session_gate.py          ← Session window detection + quota context
│   └── llm/
│       └── client.py                ← LLMClient, FallbackChainClient, LLMClientFactory
│
├── data_engine/                     ← Market data pipeline
│   ├── orchestrator.py              ← GoldTradingOrchestrator (run + pack)
│   ├── ohlcv_fetcher.py             ← OHLCVFetcher (TwelveData / yfinance)
│   ├── indicators.py                ← TechnicalIndicators (RSI, MACD, EMA, BB, ATR)
│   ├── thailand_timestamp.py        ← Thai timezone helpers
│   ├── tools/
│   │   ├── tool_registry.py         ← TOOL_REGISTRY, AVAILABLE_TOOLS_INFO, call_tool()
│   │   ├── schema_validator.py      ← validate_market_state()
│   │   ├── interceptor_manager.py   ← WebSocket gold price interceptor
│   │   ├── fetch_price.py           ← Internal: fetch gold + forex
│   │   ├── fetch_indicators.py      ← Internal: compute indicators
│   │   └── fetch_news.py            ← Internal: merged news fetcher
│   └── analysis_tools/              ← LLM-callable tools
│       ├── technical_tools.py       ← 8 technical tools (RSI divergence, BB combo ฯลฯ)
│       └── fundamental_tools.py     ← 4 fundamental tools (news, calendar, ETF flow ฯลฯ)
│
├── database/
│   └── database.py                  ← RunDatabase (PostgreSQL, ThreadedConnectionPool)
│
├── ui/                              ← UI + business logic layer
│   ├── core/
│   │   ├── services.py              ← AnalysisService, PortfolioService, HistoryService
│   │   ├── config.py                ← PROVIDER_CHOICES, VALIDATION, fallback chains
│   │   ├── renderers.py             ← TraceRenderer, HistoryRenderer, StatsRenderer
│   │   ├── utils.py                 ← format_voting_summary, validate_portfolio_update
│   │   └── dashboard_css.py         ← CSS constants
│   └── navbar.py                    ← NavbarBuilder (Gradio tab structure)
│
├── notification/
│   ├── discord_notifier.py          ← Discord Webhook embed sender
│   └── telegram_notifier.py         ← Telegram Bot API sender
│
├── logs/
│   ├── logger_setup.py              ← sys_logger, llm_logger, log_method decorator
│   ├── api_logger.py                ← send_trade_log() → external API
│   ├── system.log                   ← rotating 5MB × 3
│   └── llm_trace.log                ← rotating 5MB × 3
│
├── backtest/
│   ├── run_main_backtest.py         ← MainPipelineBacktest entry point
│   ├── config/
│   │   ├── roles_forbacktest.json
│   │   └── skills_forbacktest.json
│   ├── engine/
│   │   ├── portfolio.py             ← SimPortfolio (BUY/SELL simulation)
│   │   ├── market_state_builder.py  ← MarketStateBuilder.build()
│   │   ├── session_manager.py       ← TradingSessionManager + compliance report
│   │   ├── csv_orchestrator.py      ← CSVOrchestrator (backtest data source)
│   │   └── news_provider.py         ← NullNewsProvider, CSVNewsProvider
│   ├── data/
│   │   └── csv_loader.py            ← load_gold_csv()
│   └── metrics/
│       ├── calculator.py            ← calculate_trade_metrics(), add_calmar()
│       └── deploy_gate.py           ← deploy_gate(), print_gate_report()
│
├── output/
│   ├── latest.json                  ← market payload ล่าสุด
│   ├── backtest_cache_main/         ← candle cache (JSON ต่อ candle)
│   └── backtest_results_main/       ← CSV export ผล backtest
│
└── data/
    ├── premium_hsh/
    │   ├── Mock_HSH_OHLC.csv        ← historical candle data
    │   └── Premium_Calculated_*.csv ← spot USD + USDTHB external data
    └── news_data/
        └── gold_macro_news_v1.csv   ← historical news สำหรับ backtest
```

**Layer สรุป:**

| Layer | โฟลเดอร์ | หน้าที่ |
|---|---|---|
| Entry | `main.py`, `dashboard.py` | CLI loop / Gradio UI |
| Business Logic | `ui/core/services.py` | orchestrate ทุกอย่าง |
| AI Agent | `agent_core/` | prompt, react loop, risk gate |
| Data | `data_engine/` | ดึงราคา, indicators, ข่าว |
| LLM | `agent_core/llm/client.py` | call LLM ทุก provider |
| Persistence | `database/database.py` | บันทึกผลลง PostgreSQL |
| Notification | `notification/` | Discord + Telegram |
| Backtest | `backtest/` | simulation บน CSV |

---

## 13. Main Flow — ลำดับการทำงานแบบ Step-by-Step

### 13.1 CLI Startup Flow (`main.py`)

```
python main.py --provider openrouter:claude-haiku-4-5 --intervals 1h
    │
    ├─ [1] Parse args
    │       provider = "openrouter:claude-haiku-4-5"
    │       intervals = ["1h"]
    │       period = "3d" (default)
    │
    ├─ [2] Load Registries
    │       SkillRegistry.load_from_json("agent_core/config/skills.json")
    │       RoleRegistry.load_from_json("agent_core/config/roles.json")
    │
    ├─ [3] Init singletons
    │       GoldTradingOrchestrator()  ← เปิด WebSocket background thread ทันที
    │       RunDatabase()              ← สร้าง connection pool (min=1, max=5)
    │
    ├─ [4] init_services() → { analysis, portfolio, history }
    │       สร้าง DiscordNotifier + TelegramNotifier
    │       inject ทุกอย่างเข้า AnalysisService
    │
    └─ [5] While True (interval_seconds = 300):
               analysis.run_analysis(provider, period, intervals)
               send_trade_log() → external API
               time.sleep(300)
```

---

### 13.2 Per-Cycle Analysis Flow (`AnalysisService.run_analysis`)

```
run_analysis(provider="openrouter:claude-haiku-4-5", period="3d", intervals=["1h"])
    │
    ├─ [A] Normalize provider
    │       _normalize_provider("openrouter:claude-haiku-4-5")
    │       → pass-through (colon syntax ไม่แตะ)
    │
    ├─ [B] Validate inputs
    │       validate_provider() / validate_period() / validate_intervals()
    │       → error → return {"status": "error", ...}
    │
    ├─ [C] Market hours check (warn only — ไม่ block)
    │       is_thailand_market_open() → False = weekend warning
    │
    ├─ [D] Fetch market data
    │       GoldTradingOrchestrator.run(history_days=3, interval="1h")
    │           ├─ call_tool("fetch_price")      → spot USD + USD/THB + ราคาไทย
    │           ├─ call_tool("fetch_indicators") → RSI, MACD, EMA, BB, ATR (USD/oz)
    │           └─ call_tool("fetch_news")       → 8 categories + FinBERT sentiment
    │       → market_state dict (รวม _raw_ohlcv DataFrame)
    │
    ├─ [E] Attach portfolio
    │       RunDatabase.get_portfolio()
    │       market_state["portfolio"] = { cash_balance, gold_grams, ... }
    │
    ├─ [F] Pop raw DataFrame
    │       ohlcv_df = market_state.pop("_raw_ohlcv")
    │       (เพื่อไม่ให้ DataFrame ติดไปใน DB save)
    │
    ├─ [G] _run_single_interval("1h")
    │       → ดู 13.3
    │
    ├─ [H] Build voting_result (passthrough — ไม่มี multi-vote)
    │       final_signal = interval_result["signal"]
    │       weighted_confidence = interval_result["confidence"]
    │
    ├─ [I] Save to DB
    │       RunDatabase.save_run(...)    → runs table → run_id
    │       RunDatabase.save_llm_logs_batch([...])  → llm_logs table
    │
    ├─ [J] Notify
    │       DiscordNotifier.notify(...)
    │       TelegramNotifier.notify(...)
    │
    └─ [K] Return result dict
            { status, data, voting_result, run_id, llm_log_ids, attempt, market_open }
```

---

### 13.3 Single Interval Analysis Flow (`_run_single_interval`)

```
_run_single_interval(provider, market_state, interval="1h", ohlcv_df)
    │
    ├─ [1] Build FallbackChainClient
    │       PROVIDER_FALLBACK_CHAIN["openrouter:claude-haiku-4-5"]
    │           → ["openrouter:claude-haiku-4-5", "gemini", "mock"]
    │       สร้าง client ต่อตัว พร้อม domain grouping
    │       FallbackChainClient([(name, client, domain), ...])
    │
    ├─ [2] Inject metadata
    │       market_state["interval"] = "1h"
    │       market_state["time"] = "HH:MM"  (จาก spot timestamp)
    │       market_state["date"] = "YYYY-MM-DD"
    │
    ├─ [3] Session Gate
    │       resolve_session_gate() → SessionGateResult
    │       attach_session_gate_to_market_state(market_state, gate_res)
    │       quota_urgent_fast = gate_res.quota_urgent
    │           True  → ReactConfig(max_iterations=1, max_tool_calls=0)  ← fast path
    │           False → ReactConfig(max_iterations=3, max_tool_calls=5)  ← full path
    │
    ├─ [4] ATR Conversion
    │       atr_usd (USD/oz) → atr_thb (THB/baht_weight)
    │       สูตร: atr_usd × usd_thb / 31.1035 × 15.244
    │       mutate: atr_node["value"] = atr_thb
    │               atr_node["unit"]  = "THB_PER_BAHT_WEIGHT"
    │               atr_node["value_usd"] = atr_usd  (เก็บ original ไว้)
    │
    ├─ [5] Pack state
    │       slim_state = GoldTradingOrchestrator.pack(market_state)
    │       ตัด recent_price_action, news detail ออก เก็บแค่ essentials
    │
    ├─ [6] ReactOrchestrator.run(slim_state, ohlcv_df)
    │       → ดู 13.4
    │
    ├─ [7] Extract result
    │       used_provider = llm_client.active_provider
    │       fallback_log  = llm_client.errors
    │       decision = react_result["final_decision"]
    │
    └─ [8] Return interval_result dict
            { signal, confidence, rationale, entry_price, stop_loss, take_profit,
              rejection_reason, trace, provider_used, elapsed_ms,
              token_input, token_output, token_total,
              iterations_used, tool_calls_used, full_prompt, full_response }
```

---

### 13.4 ReAct Loop Flow (`ReactOrchestrator.run`)

```
ReactOrchestrator.run(market_state, ohlcv_df)
    │
    ╔══════════════════════════════════════════════╗
    ║  FAST PATH (max_tool_calls == 0)             ║
    ╠══════════════════════════════════════════════╣
    ║  prompt = build_final_decision(state, [])    ║
    ║  llm_resp = llm_client.call(prompt)          ║
    ║  decision = parse_agent_response(llm_resp)   ║
    ║      │ Pydantic validate + normalise         ║
    ║      │ parse fail → HOLD safe fallback       ║
    ║  adjusted = RiskManager.evaluate(decision)   ║
    ║  return { final_decision, react_trace, ... } ║
    ╚══════════════════════════════════════════════╝
    │
    ╔══════════════════════════════════════════════╗
    ║  FULL PATH (max_tool_calls > 0)              ║
    ╠══════════════════════════════════════════════╣
    ║                                              ║
    ║  [P1] StateReadinessChecker.is_ready()?      ║
    ║       YES → skip loop → FINAL_DECISION       ║
    ║       NO  → enter while loop                 ║
    ║                                              ║
    ║  while iteration < max_iterations:           ║
    ║    iteration += 1                            ║
    ║                                              ║
    ║    prompt = build_thought(state, results, i) ║
    ║    llm_resp = llm_client.call(prompt)        ║
    ║    thought = parse_agent_response(llm_resp)  ║
    ║                                              ║
    ║    action = thought.action                   ║
    ║    │                                         ║
    ║    ├─ "FINAL_DECISION"                       ║
    ║    │       break → go to RiskManager         ║
    ║    │                                         ║
    ║    ├─ "CALL_TOOL"                            ║
    ║    │   tool_call_count >= max? → force final ║
    ║    │   else:                                 ║
    ║    │       _execute_tool(name, args)         ║
    ║    │       tool_results.append(observation)  ║
    ║    │       continue                          ║
    ║    │                                         ║
    ║    ├─ "CALL_TOOLS" [P10 parallel]            ║
    ║    │   trim to remaining budget              ║
    ║    │   asyncio.run(_execute_tools_parallel)  ║
    ║    │       └─ asyncio.gather(*tasks)         ║
    ║    │           each tool → to_thread()       ║
    ║    │   tool_results.extend(observations)     ║
    ║    │   continue                              ║
    ║    │                                         ║
    ║    └─ unknown → fallback HOLD → break        ║
    ║                                              ║
    ║  if final_decision is None:  (max_iter hit)  ║
    ║      force build_final_decision() → LLM      ║
    ║                                              ║
    ║  adjusted = RiskManager.evaluate(decision,   ║
    ║                                  market_state)║
    ║  return { final_decision, react_trace, ... } ║
    ╚══════════════════════════════════════════════╝
```

---

### 13.5 RiskManager Gate Flow (`RiskManager.evaluate`)

```
evaluate(llm_decision, market_state)
    │
    ├─ Parse inputs
    │       signal, confidence, rationale ← llm_decision
    │       current_time, cash, gold_grams, prices ← market_state
    │
    ├─ Gate 0: Dead Zone
    │       02:00–06:14 (120–374 min) → REJECT → return HOLD
    │
    ├─ Gate 0b: TP/SL Override  (เฉพาะถ้า gold_grams > 0)
    │       check_price >= tp_price → override signal = SELL
    │       check_price <= sl_price → override signal = SELL
    │       (เขียนทับ signal แล้วไหลลงด้านล่างต่อ)
    │
    ├─ Gate 1: Confidence Filter
    │       signal != HOLD AND confidence < 0.60 → REJECT → return HOLD
    │
    ├─ Gate 2: Daily Loss Limit
    │       _reset_daily_loss_if_new_day(trade_date)
    │       daily_loss >= 500 AND signal == BUY → REJECT → return HOLD
    │
    └─ Gate 3: Signal Processing
            HOLD  → return as-is
            │
            SELL  → gold_grams <= 0.0001 → REJECT
            │       gold_value = gold_grams × (sell_price / 15.244)
            │       return SELL + position_size_thb
            │
            BUY   → cash < 1400 → REJECT
                    sl_distance = atr_value × 2.0
                    tp_distance = sl_distance × 1.5
                    entry  = buy_price_thb
                    SL     = entry - sl_distance
                    TP     = entry + tp_distance
                    position_size_thb = 1400 (fixed)
                    return BUY + entry/SL/TP
```

---

### 13.6 Notification Flow

```
DiscordNotifier.notify(voting_result, interval_results, market_state, ...)
    │
    ├─ Check: enabled? webhook_url set? signal allowed? confidence >= min_conf?
    │       ไม่ผ่าน → return False
    │
    ├─ build_embed()
    │       color + emoji ตาม signal (BUY=teal, SELL=red, HOLD=gray)
    │       fields: Signal, Confidence bar, Entry/SL/TP
    │                ราคา ออม NOW (THB), Spot XAU/USD, USD/THB
    │                Per-Interval Breakdown, Voting Summary
    │                Rationale (max 900 chars), Meta
    │
    └─ POST → DISCORD_WEBHOOK_URL (timeout 10s)
              → return True / log error → return False

TelegramNotifier.notify(...)  ← เนื้อหาเดียวกัน format เป็น HTML
    └─ POST → api.telegram.org/bot{TOKEN}/sendMessage
```

---

### 13.7 Backtest Cycle Flow (ต่อ 1 candle)

```
for each candle (row) in agg_df:
    │
    ├─ [1] TradingSessionManager.process_candle(ts)
    │       → session_info { session_id, can_execute }
    │
    ├─ [2] CandleCache.get(ts)
    │       HIT  → inject session_info ใหม่ → skip LLM
    │       MISS → ไปต่อ
    │
    ├─ [3] NewsProvider.get(ts)
    │       NullNewsProvider → {} / CSVNewsProvider → ค้นจาก CSV
    │
    ├─ [4] MarketStateBuilder.build(row, past_5, portfolio, news, interval)
    │       สร้าง market_state จาก CSV row + indicators pre-computed
    │
    ├─ [5] Inject backtest_directive
    │       ไม่มีทอง → "STATE: No gold held. BUY if bullish..."
    │       มีทอง   → "STATE: Holding gold. BUY FORBIDDEN. Focus SELL..."
    │
    ├─ [6] ReactOrchestrator.run(market_state)  ← เหมือน live แต่ใช้ข้อมูล CSV
    │
    ├─ [7] _apply_to_portfolio(candle_result, ts)
    │       can_execute == False → skip (out of session)
    │       BUY  → SimPortfolio.execute_buy(price, pos_size)
    │              portfolio.set_open_tp_sl(tp, sl)
    │              session_manager.record_trade(ts)
    │       SELL → SimPortfolio.execute_sell(price)
    │              session_manager.record_trade(ts)
    │
    ├─ [8] Record equity
    │       result["portfolio_total_value"] = portfolio.total_value(price)
    │
    └─ [9] CandleCache.set(ts, candle_result)

After all candles:
    session_manager.finalize()
    calculate_metrics()  → MDD, Sharpe, Sortino, Win Rate, Profit Factor
    export_csv()
    deploy_gate()  → PASS / FAIL report
```