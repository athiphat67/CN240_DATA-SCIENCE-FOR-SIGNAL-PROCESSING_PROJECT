# Data Engine — Architecture & Flow Documentation
**Version:** v1.3.0 (Post-Refactor)  
**Updated:** April 2026  
**Author:** Team Nakkhutthong

---

## 1. ภาพรวม (Overview)

`data_engine/` คือชั้นที่รับผิดชอบ **ดึง → ตรวจสอบ → คำนวณ → ส่งมอบ** ข้อมูลตลาดทองคำทั้งหมด ก่อนที่จะถูก pack เป็น `market_state` JSON และส่งเข้า ReAct LLM loop

```
[ ข้อมูลภายนอก ]                    [ data_engine/ ]                    [ ผู้ใช้งาน ]
  HSH API          →   gold_interceptor_lite.py  →  latest_gold_price.json
  Intergold WS     ↗                                        ↓
  Yahoo Finance    →   fetcher.py + ohlcv_fetcher.py   →  tools/fetch_price.py
  TwelveData API   ↗                                        ↓
  RSS Feeds        →   newsfetcher.py              →  tools/fetch_news.py
                                                            ↓
  OHLCV DataFrame  →   indicators.py               →  tools/fetch_indicators.py
                                                            ↓
                                               [ orchestrator.py ]
                                                    market_state JSON
                                                            ↓
                                               [ services.py → ReAct Loop ]
```

---

## 2. ไฟล์และหน้าที่ (File Responsibilities)

### 2.1 `gold_interceptor_lite.py` — Real-time Price Interceptor

**หน้าที่:** ดักจับราคาทองคำไทยแบบ real-time จาก 2 แหล่ง และบันทึกลง JSON file

**แหล่งข้อมูล (Priority Order):**
| Priority | Source | Protocol | ข้อมูลที่ได้ |
|---|---|---|---|
| 1 (Primary) | ฮั่วเซ่งเฮง (HSH) | REST API Polling | ราคา 96.5%, 99.99%, สถานะตลาด |
| 2 (Fallback) | Intergold | WebSocket | ราคา 96.5%, 99.99%, Spot USD, USD/THB |

**Logic การทำงาน:**
```
loop every 5s:
    ดึง HSH API
    ├── ราคาไม่เปลี่ยน (TimeUpdate เท่าเดิม) → skip รอรอบใหม่
    └── ราคาเปลี่ยน → บันทึก latest_gold_price.json

    ถ้า HSH ล่ม:
        เปิด Intergold WebSocket
        รับ event "updateGoldRateData"
        ├── ราคาไม่เปลี่ยน → skip
        └── ราคาเปลี่ยน → บันทึก latest_gold_price.json
```

**Output:** `latest_gold_price.json`
```json
{
  "source": "huasengheng_api",
  "market_status": "ON",
  "sell_price_thb": 72300.0,
  "buy_price_thb": 72200.0,
  "spread_thb": 100.0,
  "gold_spot_usd": 0.0,
  "usd_thb_live": 0.0,
  "timestamp": "2026-04-10T16:03:28"
}
```

> ⚠️ **Known Limitation:** เมื่อ HSH เป็น primary source `gold_spot_usd` และ `usd_thb_live` จะเป็น `0.0`  
> ค่า USD/THB จะมีก็ต่อเมื่อ Intergold fallback ทำงาน

---

### 2.2 `fetcher.py` — Gold Data Fetcher (Multi-Source Aggregator)

**หน้าที่:** ดึงราคาทองโลก (USD), อัตราแลกเปลี่ยน, และคำนวณราคาทองไทย

**Class:** `GoldDataFetcher`

#### `fetch_gold_spot_usd()` — ราคาทองโลก
ดึงจาก 3 แหล่งพร้อมกัน แล้วใช้ Median + Deviation check เลือกราคาที่น่าเชื่อถือ:

```
TwelveData API  ─┐
Yahoo Finance   ─┼→ Median Filter (MAX_DEVIATION=0.5%) → final_price + confidence
Gold-API        ─┘

Priority ถ้าผ่าน filter: TwelveData > Gold-API > Yahoo Finance
Confidence: 0.0 (ขัดแย้ง) | 0.6 (แหล่งเดียว) | 0.6–1.0 (หลายแหล่ง)
```

#### `fetch_usd_thb_rate()` — อัตราแลกเปลี่ยน
```
Intergold CSV (interceptor_xauthb_fetch/gold_prices_dataset.csv)
    ↓ ถ้าไม่มี / ว่างเปล่า
ExchangeRate-API (exchangerate-api.com)
```

#### `calc_thai_gold_price()` — ราคาทองไทย THB
```
อ่าน latest_gold_price.json (จาก interceptor)
    ↓ ถ้าไม่มีไฟล์ / ไฟล์ไม่มี sell_price_thb
Fallback Formula:
    price_thb = spot_usd × usd_thb / 31.1035 × 15.244 × 0.965
    sell = round_50(price_thb + 50)
    buy  = round_50(price_thb - 50)
```

#### `fetch_all()` — รวมทุกอย่าง
```python
{
    "spot_price": {...},   # USD/oz
    "thai_gold":  {...},   # THB/baht-weight
    "ohlcv_df":   DataFrame,
    "fetched_at": timestamp
}
```

---

### 2.3 `ohlcv_fetcher.py` — Historical OHLCV Fetcher

**หน้าที่:** ดึงข้อมูลแท่งเทียนย้อนหลัง พร้อมระบบ Cache อัตโนมัติ

**Class:** `OHLCVFetcher`

**Flow:**
```
1. โหลด Cache (CSV)
   └── คำนวณว่าต้อง fetch กี่วัน (smart delta)

2. Yahoo Finance (Primary) — มี Volume จริง
   └── ถ้าล้มเหลว → TwelveData (Fallback)

3. Merge กับ Cache + ตัด duplicate
4. Validate (high >= low, ทุกราคา > 0)
5. Save Cache
```

**Smart Cache Logic:**
```python
ถ้า cache มี < 50 rows → fetch เต็ม (days)
ถ้า cache ล่าสุด 3 วันที่แล้ว → fetch แค่ 3+1 วัน
```

**Interval Support:** `1m, 5m, 15m, 30m, 1h, 4h, 1d`

**YF Limit:** 5m/15m/30m ย้อนได้แค่ 60 วัน, 1m ย้อนได้ 7 วัน

---

### 2.4 `indicators.py` — Technical Indicators Calculator

**หน้าที่:** คำนวณ Technical Indicators ทั้งหมดจาก OHLCV DataFrame

**Class:** `TechnicalIndicators`

**Indicators ที่คำนวณ (Vectorized ทั้งหมดใน `__init__`):**

| Indicator | Parameters | Output Fields |
|---|---|---|
| RSI | Period=14, EWM | value, signal (overbought/neutral/oversold) |
| MACD | Fast=12, Slow=26, Signal=9 | macd_line, signal_line, histogram, crossover |
| Bollinger Bands | Period=20, Std=2.0 | upper, middle, lower, bandwidth, pct_b, signal |
| ATR | Period=14, EWM | value, volatility_level (low/normal/high), unit |
| EMA/Trend | EMA20, EMA50, SMA200 | ema_20, ema_50, sma_200, trend, golden_cross |

**MACD Crossover States (Hybrid):**
```
bullish_cross → เพิ่งตัดขึ้น (Action Signal — แรง)
bullish_zone  → ตัดขึ้นมาแล้ว ยังบวก (Hold Signal)
bearish_cross → เพิ่งตัดลง (Action Signal — แรง)
bearish_zone  → ตัดลงมาแล้ว ยังลบ (Hold Signal)
```

**ATR Unit Conversion:**
```
ถ้าส่ง usd_thb เข้ามา:
    ATR (USD/oz) × usd_thb / 31.1035 × 15.244 × 0.965
    → unit: THB_PER_BAHT_GOLD (ใช้กับ RiskManager)
ถ้าไม่ส่ง:
    → unit: USD_PER_OZ
```

**Data Quality Warnings:**
```
EMA20 ห่าง EMA50 < 1.0 → warn "Sideways — trend ไม่น่าเชื่อถือ"
Weekend → warn "Market closed — ข้อมูลอาจล่าช้า"
```

---

### 2.5 `newsfetcher.py` — News & Sentiment Fetcher

**หน้าที่:** ดึงข่าวทองคำจาก RSS feeds และวิเคราะห์ Sentiment ด้วย FinBERT

**Class:** `GoldNewsFetcher`

**News Categories:**
```
gold_price       → ราคาทองโดยตรง
fed_policy       → นโยบาย Fed / อัตราดอกเบี้ย
geopolitics      → ความขัดแย้งระหว่างประเทศ
dollar_index     → ดัชนีดอลลาร์ (DXY)
thai_gold_market → ตลาดทองไทย
usd_thb          → อัตราแลกเปลี่ยน
```

**Output per category:**
```json
{
  "articles": [
    {
      "title": "...",
      "source": "Reuters",
      "sentiment_score": 0.72,
      "impact_level": "HIGH",
      "published_at": "..."
    }
  ],
  "category_sentiment": 0.72
}
```

**Overall Sentiment:** weighted average ทุก category (-1.0 ถึง 1.0)

---

### 2.6 `thailand_timestamp.py` — Timezone Utility

**หน้าที่:** จัดการ Timezone ทั้งโปรเจกต์ให้เป็น `Asia/Bangkok` (UTC+7)

```python
get_thai_time()              → pd.Timestamp ปัจจุบัน (Thai TZ)
convert_index_to_thai_tz()  → แปลง DatetimeIndex → Thai TZ
to_thai_time(str/int/float) → แปลง Unix/String → Thai TZ
```

> ✅ ไฟล์นี้เป็น Single Source of Truth ของ Timezone — ทุกไฟล์ต้อง import จากที่นี่เท่านั้น

---

## 3. Tools Layer — ตัวกลางระหว่าง data_engine และ Orchestrator

`tools/` คือ wrapper layer ที่ orchestrator เรียกผ่าน `call_tool()` แทนการ import โดยตรง

### การไหลของข้อมูลผ่าน tools:

```
tools/interceptor_manager.py
    └── เรียก gold_interceptor_lite.start_interceptor()
    └── รันเป็น daemon thread ตั้งแต่ orchestrator.__init__()

tools/fetch_price.py → GoldDataFetcher.fetch_all()
    Input:  history_days, interval
    Output: {
        spot_price_usd:      {price_usd_per_oz, source, confidence, timestamp}
        thai_gold_thb:       {sell_price_thb, buy_price_thb, spread_thb, source}
        recent_price_action: [{datetime, open, high, low, close, volume} × 5]
        ohlcv_df:            DataFrame (ส่งต่อ fetch_indicators โดยไม่ fetch ซ้ำ)
        data_sources:        {price: source, thai_gold: source}
    }

tools/fetch_indicators.py → TechnicalIndicators.to_dict()
    Input:  ohlcv_df (รับมาจาก fetch_price), interval
    Output: {
        indicators:   {rsi, macd, bollinger, atr, trend, latest_close}
        data_quality: {quality_score, is_weekend, warnings, llm_instruction}
        error:        None | str
    }

tools/fetch_news.py → GoldNewsFetcher.to_dict()
    Input:  max_per_category
    Output: {
        summary:     {total_articles, overall_sentiment, fetched_at}
        by_category: {category: {articles, sentiment}}
        error:       None | str
    }

tools/schema_validator.py
    Input:  market_state dict
    Output: list[str] ของ missing fields ([] = ผ่าน)
    Required fields:
        market_data.spot_price_usd
        market_data.thai_gold_thb.sell_price_thb ✅
        market_data.thai_gold_thb.buy_price_thb  ✅
        technical_indicators.rsi.value           ✅
```

---

## 4. Orchestrator — Final Assembly

`orchestrator.py` รับ output จาก 3 tools มา pack เป็น `market_state`:

```python
def run(history_days) -> market_state:

    price  = call_tool("fetch_price", ...)
    ind    = call_tool("fetch_indicators", ohlcv_df=price["ohlcv_df"], ...)
    news   = call_tool("fetch_news", ...)

    return _assemble_payload(price, ind, news)
```

### market_state Schema (Final Output):

```json
{
  "meta": {
    "agent": "gold-trading-agent",
    "version": "1.3.0",
    "generated_at": "2026-04-12T10:30:00+07:00",
    "history_days": 30,
    "interval": "1h"
  },

  "data_quality": {
    "quality_score": "good | degraded",
    "is_weekend": false,
    "llm_instruction": "Use standard technical analysis.",
    "warnings": []
  },

  "data_sources": {
    "price": "twelvedata | yfinance | gold-api",
    "thai_gold": "huasengheng_api | calculated_fallback",
    "news": "newsfetcher"
  },

  "market_data": {
    "spot_price_usd": {
      "price_usd_per_oz": 3150.50,
      "source": "twelvedata",
      "confidence": 0.95,
      "timestamp": "2026-04-12T10:29:55+07:00"
    },
    "forex": {
      "usd_thb": 33.45,
      "source": "intergold_live_stream | exchangerate-api.com"
    },
    "thai_gold_thb": {
      "sell_price_thb": 72300.0,
      "buy_price_thb": 72200.0,
      "spread_thb": 100.0,
      "market_status": "ON",
      "source": "huasengheng_api"
    },
    "recent_price_action": [
      {"datetime": "...", "open": 3148.0, "high": 3152.0, "low": 3147.0, "close": 3150.5, "volume": 12500}
    ]
  },

  "technical_indicators": {
    "rsi":       {"value": 58.3, "signal": "neutral", "period": 14},
    "macd":      {"macd_line": 2.14, "signal_line": 1.87, "histogram": 0.27, "crossover": "bullish_zone"},
    "bollinger": {"upper": 3165.0, "middle": 3140.0, "lower": 3115.0, "bandwidth": 0.016, "pct_b": 0.72, "signal": "inside"},
    "atr":       {"value": 18.5, "volatility_level": "normal", "unit": "USD_PER_OZ"},
    "trend":     {"ema_20": 3148.2, "ema_50": 3135.6, "sma_200": 3050.0, "trend": "uptrend", "golden_cross": true},
    "latest_close": 3150.5,
    "calculated_at": "2026-04-12T10:30:00+07:00"
  },

  "news": {
    "summary": {
      "total_articles": 18,
      "overall_sentiment": 0.32,
      "fetched_at": "2026-04-12T10:30:05+07:00"
    },
    "by_category": {
      "gold_price":   {"articles": [...], "category_sentiment": 0.45},
      "fed_policy":   {"articles": [...], "category_sentiment": 0.12},
      "geopolitics":  {"articles": [...], "category_sentiment": -0.10}
    }
  }
}
```

---

## 5. กระบวนการถัดไปหลัง market_state (Downstream)

```
market_state
    ↓
services.py → AnalysisService.run_analysis()
    ├── inject portfolio → market_state["portfolio"]
    ├── inject time/date → market_state["time"], market_state["date"]
    └── inject ATR converted → market_state["technical_indicators"]["atr"]["value"]
                               (USD/oz → THB/baht_weight สำหรับ RiskManager)
    ↓
ReactOrchestrator.run(market_state)
    ├── PromptBuilder สร้าง System Prompt จาก market_state
    ├── LLM ReAct loop (max 3 iterations, max 3 tool calls)
    └── → react_result {signal, confidence, rationale, trace}
    ↓
RiskManager.evaluate(llm_decision, market_state)
    ├── Hard Rules: Dead Zone, TP/SL hit, Daily Loss Limit
    ├── Confidence Filter (min 0.6)
    ├── Position Sizing (BUY = 1,000 THB fixed)
    └── ATR-based SL/TP calculation
    ↓
final_decision {signal, entry_price, stop_loss, take_profit}
    ↓
Database.save_run() + Discord/Telegram Notification
```

---

## 6. Known Issues & Improvement Notes

| # | ปัญหา | สถานะ | แนวทางแก้ |
|---|---|---|---|
| 1 | HSH interceptor ไม่ส่ง `usd_thb_live` (= 0.0) | ⚠️ Active | เพิ่ม `fetch_usd_thb` tool แยก หรือ fallback ใน `_assemble_payload` |
| 2 | `extract_features.py` อ่าน `market_data["forex"]` ที่อาจไม่มี | ⚠️ Active | ต้องเพิ่ม `forex` key กลับใน orchestrator หรือแก้ extract_features |
| 3 | `ohlcv_fetcher.py` มี `[DEBUG] print` หลายจุด | 🟡 Minor | เปลี่ยนเป็น `logger.debug()` |
| 4 | `indicators.py` → `TrendResult` ไม่มี `sma_200` ใน `trend()` method | 🔴 Bug | `sma_200` ถูกคำนวณแต่ไม่ return ใน `TrendResult` dataclass ให้เช็คอีกที |
| 5 | `data_quality["is_weekend"]` ถูก set ใน indicators แต่ให้ orchestrator override | ✅ Fixed | orchestrator ตรวจสอบจาก `get_thai_time().weekday()` แล้ว |

---

## 7. Dependency Map

```
thailand_timestamp.py   ← ใช้โดย: fetcher, indicators, orchestrator, ohlcv_fetcher
gold_interceptor_lite.py ← ใช้โดย: tools/interceptor_manager
fetcher.py              ← ใช้โดย: tools/fetch_price
    └── depends: ohlcv_fetcher, thailand_timestamp
ohlcv_fetcher.py        ← ใช้โดย: fetcher, tools/fetch_indicators (indirect)
indicators.py           ← ใช้โดย: tools/fetch_indicators
    └── depends: thailand_timestamp
newsfetcher.py          ← ใช้โดย: tools/fetch_news
```
