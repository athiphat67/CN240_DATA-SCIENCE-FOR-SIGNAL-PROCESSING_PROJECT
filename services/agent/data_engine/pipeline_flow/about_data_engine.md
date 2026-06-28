# 📊 about_data_engine.md — Gold Trading Agent · Data Engineering Team
> **Version:** 2.0 (Post-Fix Final Document)
> ครอบคลุม: สถาปัตยกรรม, Data Flow, Fallback Chain, Key Mapping, Code Fixes ทุกประเด็น

---

## สารบัญ

1. [ภาพรวมสถาปัตยกรรม](#1-ภาพรวมสถาปัตยกรรม)
2. [โครงสร้างโฟลเดอร์](#2-โครงสร้างโฟลเดอร์)
3. [Data Flow ตั้งแต่ต้นจนจบ](#3-data-flow-ตั้งแต่ต้นจนจบ)
4. [แหล่งข้อมูลและ Fallback Chain](#4-แหล่งข้อมูลและ-fallback-chain)
5. [Orchestrator: โครงสร้าง market_state](#5-orchestrator-โครงสร้าง-market_state)
6. [Key Mapping: Orchestrator → Consumer](#6-key-mapping-orchestrator--consumer)
7. [slim_state: ชุดข้อมูลสำหรับ ReAct Loop](#7-slim_state-ชุดข้อมูลสำหรับ-react-loop)
8. [Analysis Tools (LLM Tools)](#8-analysis-tools-llm-tools)
9. [การแปลงข้อมูลพิเศษใน services.py](#9-การแปลงข้อมูลพิเศษใน-servicespy)
10. [Code Fixes — รายละเอียดและ Implementation](#10-code-fixes--รายละเอียดและ-implementation)
11. [Appendix: Sequence Diagram](#11-appendix-sequence-diagram)

---

## 1. ภาพรวมสถาปัตยกรรม

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        services.py  (AnalysisService)                    │
│                                                                          │
│  ①  GoldTradingOrchestrator.run()                                        │
│       ├─ fetch_price → spot USD, forex, thai gold THB, OHLCV DataFrame   │
│       ├─ fetch_indicators → RSI, MACD, BB, ATR(USD), EMA                 │
│       ├─ fetch_news → headlines + FinBERT sentiment (Smart Cache 12h)    │
│       └─ _assemble_payload() → market_state (FULL) + _raw_ohlcv          │
│                                                                          │
│  ②  services.py pre-processing                                           │
│       ├─ pop _raw_ohlcv (DataFrame แยกออกก่อนเซฟ DB)                     │
│       ├─ inject portfolio (จาก DB)                                       │
│       ├─ inject time / date (parse จาก spot timestamp)                   │
│       ├─ resolve_session_gate → attach session_gate                      │
│       └─ ATR conversion: USD/oz → THB/baht_weight (mutation + guard)     │
│                                                                          │
│  ③  market_state (FULL) ──────────────────────────────────────────────► │
│       ├─ → Database (save_run + save_llm_logs)                           │
│       └─ → RiskManager.evaluate() (FULL state, ไม่ใช่ slim)              │
│                                                                          │
│  ④  slim_state = orchestrator.pack(market_state)                         │
│       └─ → ReactOrchestrator.run(slim_state, ohlcv_df)                   │
│            ├─ PromptBuilder.build_thought() → LLM call                   │
│            ├─ LLM → CALL_TOOL | CALL_TOOLS | FINAL_DECISION              │
│            └─ Analysis Tools execute on demand (§8)                      │
│                                                                          │
│  ⑤  RiskManager.evaluate(llm_decision, market_state_FULL)               │
│  ⑥  DB.save_run → Discord / Telegram notify                             │
└──────────────────────────────────────────────────────────────────────────┘
```

**สองชุดข้อมูลหลัก:**

| ชุดข้อมูล | ปลายทาง | วัตถุประสงค์ |
|---|---|---|
| `market_state` **(FULL)** | DB · RiskManager · prompt context | ข้อมูลครบถ้วน ตัวเลขทุกอย่าง |
| `slim_state` | ReAct loop input | ตัดส่วนหนักออก บังคับ LLM ใช้ tools เพิ่มเอง |

---

## 2. โครงสร้างโฟลเดอร์

```
Src/
├── data_engine/
│   ├── analysis_tools/            # LLM-callable tools (ผ่าน TOOL_REGISTRY)
│   │   ├── __init__.py            # TOOL_REGISTRY + AVAILABLE_TOOLS_INFO
│   │   ├── fundamental_tools.py   # get_deep_news, calendar, intermarket, etf_flow
│   │   └── technical_tools.py    # htf_trend, s/r zones, swing_low, rsi_div,
│   │                             #   bb_rsi, ema_dist, spot_thb_alignment, breakout
│   ├── tools/                     # Internal pipeline tools (ไม่ expose ตรงให้ LLM)
│   │   ├── fetch_price.py         # Entry point: ราคาทอง + OHLCV
│   │   ├── fetch_indicators.py    # คำนวณ indicators จาก DataFrame
│   │   ├── fetch_news.py          # RSS + FinBERT sentiment (MERGED wrapper)
│   │   ├── tool_registry.py       # รวม INTERNAL + LLM tools ไว้ที่เดียว
│   │   ├── interceptor_manager.py # Background WebSocket daemon thread
│   │   └── schema_validator.py    # ตรวจ required fields ก่อนส่ง LLM
│   ├── fetcher.py                 # GoldDataFetcher: spot, forex, thai gold
│   ├── ohlcv_fetcher.py           # OHLCV: yfinance (primary) + TwelveData (fallback)
│   ├── indicators.py              # TechnicalIndicators: RSI, MACD, BB, ATR, EMA
│   ├── newsfetcher.py             # GoldNewsFetcher: RSS + FinBERT + Smart Cache
│   ├── orchestrator.py            # GoldTradingOrchestrator: assemble market_state
│   ├── gold_interceptor_lite.py   # WebSocket: HSH (primary) + Intergold (fallback)
│   └── thailand_timestamp.py     # Timezone utility (Asia/Bangkok)
└── agent_core/
    └── core/
        ├── prompt.py              # PromptBuilder: _format_market_state → prompt text
        ├── react.py               # ReactOrchestrator: ReAct Thought-Action-Observe loop
        ├── risk.py                # RiskManager: evaluate + adjust final_decision
        └── session_gate.py        # Session time window · quota mode · llm_mode
```

---

## 3. Data Flow ตั้งแต่ต้นจนจบ

### Step 1 — Background Threads (boot time)

```
interceptor_manager.start_interceptor_background()
  └─ เรียกอัตโนมัติตอน import fetch_price.py  (idempotent — รันครั้งเดียว)
  └─ daemon=True → ปิดเมื่อ process หลักจบ

gold_interceptor_lite.start_interceptor()  [loop ตลอดเวลา]
  ├─ Primary: fetch_huasengheng() — HSH API polling ทุก 5 วินาที
  │   GET .../getprice/   (96.5%)
  │   GET .../values      (99.99%)
  │   GET .../GetMarketStatus
  │   └─ เขียน JSON เฉพาะเมื่อ TimeUpdate เปลี่ยน (ป้องกัน write ซ้ำ)
  │   └─ [FIX C2] เรียก _fetch_usd_thb_rate() ก่อน save → usd_thb_live มีค่าจริง
  │
  └─ Fallback: run_intergold_fallback()
      wss://ws.intergold.co.th:3000/socket.io/
      └─ เขียน JSON เฉพาะเมื่อ (bid96, ask96, spot, fx) เปลี่ยน

Output: latest_gold_price.json
  { sell_price_thb, buy_price_thb, spread_thb, market_status,
    gold_spot_usd, usd_thb_live, source, timestamp }
```

### Step 2 — GoldTradingOrchestrator.run()

```
GoldTradingOrchestrator.run(history_days, interval)
│
├─ [2a] call_tool("fetch_price", history_days, interval)
│   └─ GoldDataFetcher.fetch_all()
│       ├─ fetch_gold_spot_usd()
│       │     [TwelveData] → [yfinance GC=F] → [gold-api.com]
│       │     median + deviation check (≤0.5%), confidence score
│       ├─ fetch_usd_thb_rate()
│       │     [yfinance USDTHB=X] → [TwelveData] → [interceptor JSON usd_thb_live]
│       │     → [exchangerate-api.com]  (last resort: daily update)
│       ├─ calc_thai_gold_price()
│       │     [latest_gold_price.json sell_price_thb] → [formula fallback]
│       └─ OHLCVFetcher.fetch_historical_ohlcv()
│             [yfinance GC=F] → [TwelveData]
│             Cache: Src/cache/ohlcv_XAU_USD_{interval}.csv
│   Returns: { spot_price_usd, thai_gold_thb, forex, ohlcv_df, recent_price_action[5] }
│
├─ [2b] OHLCV Timezone conversion  [FIX M1]
│         tz_localize("UTC").tz_convert("Asia/Bangkok")
│
├─ [2c] call_tool("fetch_indicators", ohlcv_df, interval)
│   └─ TechnicalIndicators(df).to_dict(interval)
│       RSI-14 · MACD(12,26,9) · Bollinger(20,2) · ATR-14[USD/oz] · EMA20/50/200
│       data_quality: warnings, quality_score
│
├─ [2d] call_tool("fetch_news", max_per_category=5)
│   └─ GoldNewsFetcher.to_dict()  [Smart Cache รอบ 12h]
│       8 categories × (yfinance news → RSS fallback) → FinBERT sentiment
│       Diet Payload: { market_bias, top_5_key_headlines[], category_summary{} }
│
├─ [2e] compute price_trend from ohlcv_df  [FIX C1]
│         current_close, prev_close, daily/5d/10d change%, 10d high/low
│
└─ [2f] _assemble_payload(price_trend=price_trend) → market_state (FULL)
    └─ inject _raw_ohlcv = ohlcv_df  (services.py จะ pop ทีหลัง)
```

### Step 3 — services.py Pre-processing

```
services.py._run_single_interval()
│
├─ ohlcv_df = market_state.pop("_raw_ohlcv")   → JSON-safe
├─ market_state["portfolio"]   = db.get_portfolio()
├─ market_state["interval"]    = interval
├─ market_state["time"/"date"] = parse(spot_timestamp)
├─ resolve_session_gate() → attach_session_gate_to_market_state()
├─ [FIX I2] ATR conversion USD→THB  (with explicit guard + unit fallback)
│
├─ slim_state = orchestrator.pack(market_state)
└─ react_orchestrator.run(slim_state, ohlcv_df)
```

### Step 4 — ReAct Loop

```
ReactOrchestrator.run(slim_state, ohlcv_df)
│
├─ [P1] StateReadinessChecker.is_ready()  — ตรวจ rsi/macd/trend ครบไหม
│        ครบ → skip tool loop ประหยัด 1 LLM call
│
├─ quota_urgent=True → fast path (max_iterations=1, max_tool_calls=0)
│
└─ while iteration < max_iterations:
    ├─ PromptBuilder.build_thought(slim_state, tool_results, iteration)
    ├─ LLMClient.call(prompt) → LLMResponse
    ├─ parse_agent_response() → AgentDecision (Pydantic validated)
    │
    ├─ CALL_TOOL   → _execute_tool(name, args, ohlcv_df)
    │                 Smart Injection: ถ้า tool รับ ohlcv_df + interval ตรงกัน
    │                 → inject DataFrame จาก memory แทนดึง API ซ้ำ
    ├─ CALL_TOOLS  → _execute_tools_parallel([...]) asyncio.gather + to_thread
    └─ FINAL_DECISION → break → RiskManager.evaluate()
```

---

## 4. แหล่งข้อมูลและ Fallback Chain

### 4.1 Gold Spot Price (USD/oz)

| ลำดับ | แหล่ง | เงื่อนไข |
|---|---|---|
| 1st | TwelveData API `XAU/USD` | ต้องมี `TWELVEDATA_API_KEY` |
| 2nd | yfinance `GC=F` | free, real-time |
| 3rd | gold-api.com | free REST |

Confidence: `1.0` (3 ตรง) · `0.6` (1 แหล่ง) · `0.0` (diverge >0.5%)

### 4.2 Thai Gold Price (THB/baht_weight 96.5%)

| ลำดับ | แหล่ง | เงื่อนไข |
|---|---|---|
| 1st | `latest_gold_price.json` → `sell_price_thb` | > 0 |
| fallback | Formula: `(spot × usd_thb / 31.1035) × 15.244 × 0.965` | — |

### 4.3 USD/THB Rate

| ลำดับ | แหล่ง | อัปเดต |
|---|---|---|
| 1st | yfinance `USDTHB=X` (1m) | real-time |
| 2nd | TwelveData `USD/THB` | real-time |
| 3rd | `latest_gold_price.json` → `usd_thb_live` | real-time **[หลัง FIX C2]** |
| 4th | exchangerate-api.com | รายวัน (last resort) |

### 4.4 OHLCV Data (XAU/USD)

| ลำดับ | แหล่ง | Max Days |
|---|---|---|
| 1st | yfinance `GC=F` | 1m→7d · 5m/15m→60d · 1h/4h→730d |
| 2nd | TwelveData (outputsize≤5000) | ตาม API credit |

Cache strategy: โหลด CSV → คำนวณ delta → ดึงเฉพาะช่วงที่หายไป → merge + sort + save

### 4.5 News Sentiment

| ขั้นตอน | Service |
|---|---|
| ดึง: yfinance news per ticker + RSS feeds | `newsfetcher.py` |
| Sentiment: FinBERT `ProsusAI/finbert` via HuggingFace API | `score_sentiment_batch()` |
| Cache: `Src/news_cache.json` รอบ 12h (00:xx / 12:xx) | `to_dict()` |

8 Categories: `gold_price` · `usd_thb` · `fed_policy` · `inflation` · `geopolitics` · `dollar_index` · `thai_economy` · `thai_gold_market`

---

## 5. Orchestrator: โครงสร้าง market_state

โครงสร้างสมบูรณ์หลัง fixes ทั้งหมด apply แล้ว:

```python
{
  "meta": {
    "agent": "gold-trading-agent", "version": "1.3.0",
    "generated_at": str,  # ISO Thai TZ
    "history_days": int, "interval": str, "data_mode": "live"
  },

  "data_quality": {
    "quality_score": "good | degraded",
    "is_weekend": bool, "llm_instruction": str, "warnings": [str]
  },

  "data_sources": { "price": str, "thai_gold": str },

  "market_data": {
    "spot_price_usd": {
      "price_usd_per_oz": float, "source": str,
      "timestamp": str, "confidence": float
    },
    "forex": { "usd_thb": float, "source": str },
    "thai_gold_thb": {
      "sell_price_thb": float, "buy_price_thb": float,
      "spread_thb": float, "mid_price_thb": float,
      "timestamp": str, "source": str
    },
    "recent_price_action": [...],  # 5 candles — ตัดออกใน slim_state

    "price_trend": {
      "current_close_usd": float,
      "prev_close_usd":    float,
      "daily_change_pct":  float,
      "5d_change_pct":     float,   # มีถ้า len(ohlcv) >= 6
      "10d_change_pct":    float,   # มีถ้า len(ohlcv) >= 11
      "10d_high":          float,
      "10d_low":           float
    }
  },

  "technical_indicators": {
    "rsi":     { "value": float, "signal": str, "period": 14 },
    "macd": {
      "macd_line": float, "signal_line": float,
      "histogram": float,
      "crossover": str,  # "bullish_cross|bearish_cross|bullish_zone|bearish_zone|neutral"
      "signal":    str   # = crossover (inject โดย orchestrator สำหรับ backward compat)
    },
    "bollinger": {
      "upper": float, "middle": float, "lower": float,
      "bandwidth": float, "pct_b": float, "signal": str
    },
    "atr": {
      # ⚠️ ค่าออกจาก indicators เป็น USD/oz
      # services.py convert เป็น THB/baht_weight ก่อนเข้า LLM
      "value":     float,  # USD/oz ก่อน → THB/baht_weight หลัง services.py
      "period":    14,
      "volatility_level": str,  # "low | normal | high"
      # หลัง services.py convert:
      # "unit":      "THB_PER_BAHT_WEIGHT"
      # "value_usd": float  (ค่าเดิมเก็บไว้)
    },
    "trend": {
      "ema_20": float, "ema_50": float,
      "trend":  str,  # "uptrend | downtrend | sideways"
      "golden_cross": bool, "death_cross": bool
      # ❌ [FIX I1] ลบ trend_signal ออกแล้ว
    },
    "latest_close": float, "calculated_at": str,
    "data_quality": { "warnings": [str], "quality_score": str }
  },

  "news": {
    "summary": {
      "total_articles": int, "overall_sentiment": float,
      "fetched_at": str, "errors": [str]
    },
    "by_category": {  # Diet format
      "market_bias": str,
      "top_5_key_headlines": [str],
      "category_summary": { cat: { "sentiment_avg": float, "article_count": int } }
    },
    "latest_news": [str],  # ≤10 headlines
    "news_count":  int
  },

  "portfolio":    { ... },   # inject โดย services.py จาก DB
  "session_gate": { ... },   # inject โดย services.py
  "interval":  str,
  "time":      str,          # "HH:MM"
  "date":      str,          # "YYYY-MM-DD"
  "timestamp": str,
  "_raw_ohlcv": DataFrame    # services.py pop() ออกก่อนเซฟ DB
}
```

---

## 6. Key Mapping: Orchestrator → Consumer

### prompt.py ← slim_state

| prompt.py อ่าน | path | สถานะ |
|---|---|---|
| `spot` | `market_data.spot_price_usd.price_usd_per_oz` | ✅ |
| `usd_thb` | `market_data.forex.usd_thb` | ✅ |
| `sell_thb / buy_thb` | `market_data.thai_gold_thb.*` | ✅ |
| `rsi.value / .signal` | `technical_indicators.rsi.*` | ✅ |
| `macd.macd_line / .signal_line / .histogram / .signal` | `technical_indicators.macd.*` | ✅ |
| `trend.ema_20 / .ema_50 / .trend` | `technical_indicators.trend.*` | ✅ |
| `bb.upper / .lower` | `technical_indicators.bollinger.*` | ✅ |
| `ti.latest_close` | `technical_indicators.latest_close` | ✅ |
| `atr.value` | `technical_indicators.atr.value` | ✅ THB หลัง services.py convert |
| `atr.unit` | `technical_indicators.atr.unit` | ✅ `"THB_PER_BAHT_WEIGHT"` |
| `atr.value_usd` | `technical_indicators.atr.value_usd` | ✅ inject โดย services.py |
| `price_trend.*` | `market_data.price_trend.*` | ✅ **[FIX C1]** |
| `news_data.latest_news / .news_count` | `news.*` | ✅ |
| `session_gate` | `session_gate` | ✅ |
| `portfolio.*` | `portfolio.*` | ✅ |

### schema_validator.py ← market_state

| Required Field | สถานะ |
|---|---|
| `market_data.spot_price_usd` | ✅ |
| `market_data.thai_gold_thb.sell_price_thb` | ✅ |
| `market_data.thai_gold_thb.buy_price_thb` | ✅ |
| `technical_indicators.rsi.value` | ✅ |

### RiskManager.evaluate() ← market_state (FULL)

รับ market_state เต็มจาก services.py — สิทธิ์อ่านทุก key รวม `portfolio`, `technical_indicators`, `market_data`, `session_gate`

---

## 7. slim_state: ชุดข้อมูลสำหรับ ReAct Loop

`orchestrator.pack(market_state)` ตัดข้อมูลหนักออก:

```python
slim_state = {
  "meta":                 ...,   # ครบ
  "interval":             ...,
  "timestamp":            ...,
  "time":                 ...,   # HH:MM
  "date":                 ...,
  "session_gate":         ...,
  "portfolio":            ...,
  "backtest_directive":   ...,
  "data_quality":         ...,   # ครบ
  "technical_indicators": ...,   # ครบทุก indicator
  "market_data": {
    "spot_price_usd":  ...,   # ✅
    "forex":           ...,   # ✅
    "thai_gold_thb":   ...,   # ✅
    "price_trend":     ...,   # ✅ 
    # ❌ recent_price_action — ตัดออก
  },
  "news": {
    "latest_news":  [...],   # ✅ headlines เท่านั้น
    "news_count":   int
    # ❌ ตัด summary + by_category ออก
    # → LLM ต้องเรียก get_deep_news_by_category เอง
  }
}
```

---

## 8. Analysis Tools (LLM Tools)

### Technical Tools

| Tool | Input Args | Output หลัก | หมายเหตุ |
|---|---|---|---|
| `get_htf_trend` | `timeframe`, `history_days` | `trend`, `ema_200`, `distance_pct` | Cache 30 นาที |
| `get_support_resistance_zones` | `interval`, `history_days` | `zones[]` | DBSCAN + ATR-adaptive |
| `detect_swing_low` | `interval`, `history_days`, `lookback_candles` | `setup_detected`, `swing_low_price` | V-shape breakout |
| `detect_rsi_divergence` | `interval`, `history_days`, `lookback_candles` | `divergence_detected` | Bullish only |
| `check_bb_rsi_combo` | `interval`, `history_days` | `combo_detected` | Price<LBB + RSI<35 + MACD flat |
| `calculate_ema_distance` | `interval`, `history_days` | `distance_atr_ratio`, `is_overextended` | >2.5 ATR = overextended |
| `check_spot_thb_alignment` | `interval`, `lookback_candles` | `alignment`, `suggestion` | XAU/USD vs USD/THB |
| `detect_breakout_confirmation` | `zone_top`, `zone_bottom`, `interval`, `history_days` | `is_confirmed_breakout` | Body strength ≥50% |

**Smart DataFrame Injection:** react.py inject `ohlcv_df` เข้า tool โดยอัตโนมัติเมื่อ interval ตรงกัน — ประหยัด API call

### Fundamental Tools

| Tool | Input Args | Output หลัก | แหล่งข้อมูล |
|---|---|---|---|
| `get_deep_news_by_category` | `category` | `articles[]`, `count` | yfinance + RSS → FinBERT |
| `check_upcoming_economic_calendar` | `hours_ahead` | `risk_level`, `events[]` | ForexFactory JSON |
| `get_intermarket_correlation` | (none) | `divergences[]`, `correlation_20d` | yfinance: GC=F, DXY, US10Y |
| `get_gold_etf_flow` | (none) | `tonnes_change_1d`, `flow_direction` | SPDR XLSX → yfinance GLD |

---

## 9. การแปลงข้อมูลพิเศษใน services.py

### 9.1 ATR Unit Conversion (Mutation)

```
[indicators.py]              [services.py หลัง convert]
atr.value = 12.34 USD/oz  → atr.value     = 189.2 THB/baht_weight
atr.unit  = "USD_PER_OZ"  → atr.unit      = "THB_PER_BAHT_WEIGHT"
                             atr.value_usd = 12.34  (เก็บไว้ debug)

สูตร: atr_thb = atr_usd × usd_thb / 31.1035 × 15.244
Guard: atr <= 0 หรือ usd_thb <= 0 → skip + log warning + set unit fallback
```

### 9.2 Time/Date Injection

```python
market_state["time"] = "HH:MM"       # parse จาก spot_price_usd.timestamp
market_state["date"] = "YYYY-MM-DD"
```

### 9.3 Session Gate

```python
gate_result = resolve_session_gate(force_bypass=bypass_session_gate)
attach_session_gate_to_market_state(market_state, gate_result)
# → market_state["session_gate"] = { apply_gate, session_id, llm_mode, ... }
```

### 9.4 DataFrame Isolation

```python
ohlcv_df = market_state.pop("_raw_ohlcv", None)
# ส่งแยกเข้า react_orchestrator.run(slim_state, ohlcv_df=ohlcv_df)
```

---

## 10. Appendix: Sequence Diagram

```
main.py / Gradio UI
    │
    └─► services.AnalysisService.run_analysis(provider, period, intervals)
            │
            │  [background daemon]
            ├─► interceptor → latest_gold_price.json
            │     HSH polling 5s + _fetch_usd_thb_rate() 60s cache  [FIX C2]
            │
            ├─► data_orchestrator.run(history_days, interval)
            │     ├─ fetch_price
            │     │    spot_usd:  TwelveData → yfinance → gold-api
            │     │    usd_thb:   yfinance → TwelveData → interceptor* → exchangerate-api
            │     │    thai_gold: interceptor JSON → formula fallback
            │     │    OHLCV:     yfinance → TwelveData → cache CSV
            │     ├─ OHLCV tz_localize(UTC).tz_convert(Bangkok)
            │     ├─ fetch_indicators (RSI, MACD, BB, ATR[USD], EMA)
            │     ├─ fetch_news (RSS + yfinance → FinBERT → Diet cache 12h)
            │     ├─ compute price_trend from ohlcv_df
            │     └─ _assemble_payload(price_trend=...) → market_state (FULL)
            │
            ├─► [services.py pre-processing]
            │     ├─ pop _raw_ohlcv
            │     ├─ inject portfolio / time / date / session_gate
            │     └─ ATR USD→THB conversion + explicit guard
            │
            ├─► slim_state = orchestrator.pack(market_state)
            │     ตัด recent_price_action · news body
            │
            ├─► react_orchestrator.run(slim_state, ohlcv_df)
            │     ├─ [iter 1] LLM → CALL_TOOL(get_htf_trend)
            │     ├─ [iter 2] LLM → CALL_TOOLS([get_support_resistance_zones,
            │     │                              check_upcoming_economic_calendar])
            │     └─ [iter 3] LLM → FINAL_DECISION {signal, confidence, rationale}
            │
            ├─► RiskManager.evaluate(final_decision, market_state_FULL)
            ├─► DB.save_run + save_llm_logs
            └─► Discord / Telegram notify

```

---

*เอกสารนี้สะท้อนสถานะโค้ดหลังจาก fixes ทั้งหมดถูก apply แล้ว*
*ทบทวนและอัปเดตทุกครั้งที่มีการเปลี่ยนแปลง pipeline หรือ data source*
