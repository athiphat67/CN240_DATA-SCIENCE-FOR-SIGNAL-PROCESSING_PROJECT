# Backtest Data Flow — GoldTrader v3.2

> เอกสารนี้อธิบาย flow ของข้อมูลตั้งแต่ไฟล์ CSV จนกลายเป็น `market_state` dict
> และส่งต่อเข้า ReactOrchestrator เพื่อให้ LLM ตัดสินใจซื้อ/ขาย

---

## ภาพรวม (Big Picture)

```
CSV Files
    ↓
csv_loader.py          → DataFrame (indicators ครบ)
    ↓
run_main_backtest.py   → loop ทีละ candle
    ↓
MarketStateBuilder     → market_state dict
    ↓
ReactOrchestrator      → LLM decision (BUY / SELL / HOLD)
    ↓
SimPortfolio           → อัปเดต equity
    ↓
export_csv / metrics
```

---

## Step 1 — โหลดข้อมูล `csv_loader.load_gold_csv()`

### Input Files

| ไฟล์ | ข้อมูลที่ได้ |
|---|---|
| `Mock_HSH_OHLC.csv` | ราคาทองไทย OHLC (Mock HSH) |
| `Premium_Calculated_Feb_Apr.csv` | Spot USD, Forex, Premium, Spread |

### กระบวนการ

```
Mock_HSH_OHLC.csv
  → _load_and_prep_main()
      timestamp     tz_localize → Asia/Bangkok
      close         ← Mock_HSH_Sell_Close
      open          ← Mock_HSH_Sell_Open
      high          ← Mock_HSH_Sell_High
      low           ← Mock_HSH_Sell_Low
      volume        ← Mock_HSH_Sell_Volume

Premium_Calculated_Feb_Apr.csv
  → _load_and_merge_external()
      CLOSE_XAUUSD, SPREAD_XAUUSD
      CLOSE_USDTHB, SPREAD_USDTHB
      premium_buy,  premium_sell
      pred_premium_buy, pred_premium_sell

  → pd.merge(inner, on="timestamp")

  → _calculate_indicators()   ← คำนวณจาก close ทั้งหมด
      rsi, rsi_signal
      ema_20, ema_50, trend_signal
      macd_line, macd_signal, macd_hist
      bb_upper, bb_mid, bb_lower
      atr
      ↓ .shift(1)              ← ป้องกัน look-ahead bias

  → dropna(warmup rows)
```

### Output

DataFrame พร้อมใช้ ~25+ columns, tz-aware timestamp

---

## Step 2 — Prepare ใน `run_main_backtest.load_and_aggregate()`

```
DataFrame จาก csv_loader
  → rename columns (ให้ตรงชื่อที่ใช้ภายใน backtest):
      close       → close_thai
      open        → open_thai
      high        → high_thai
      low         → low_thai
      macd_signal → signal_line

  → filter ตาม --days (cutoff จาก max timestamp)

  → resample ตาม --timeframe (ถ้าไม่ใช่ 5m):
      open_thai    first
      high_thai    max
      low_thai     min
      close_thai   last
      indicators   last
      external cols (CLOSE_XAUUSD, CLOSE_USDTHB, ...)  last

→ self.agg_df  ← DataFrame ที่ backtest loop ใช้
```

---

## Step 3 — Loop ทีละ Candle `_run_candle(row)`

ทุก candle ทำตามนี้:

```
row = agg_df.iloc[i]   ← 1 แถว = 1 candle

① session_info = session_manager.process_candle(ts)
      → can_execute: True/False (อยู่ใน trading hours ไหม)
      → session_id: MORN / AFTN / EVEN / LATE / E / None

② cache.get(ts)
      → ถ้า hit → return ทันที (ข้าม LLM call)
      → ถ้า miss → ดำเนินการต่อ

③ news = news_provider.get(ts)          ⚠️ ดูหมายเหตุด้านล่าง

④ portfolio.reset_daily(date)
   portfolio_dict = portfolio.to_market_state_dict(price)

⑤ past_5 = agg_df[timestamp < ts].tail(5)
      → 5 candles ก่อนหน้า (ไม่รวม candle ปัจจุบัน)

⑥ market_state = MarketStateBuilder.build(...)
```

---

## Step 4 — ประกอบ `market_state` dict

`MarketStateBuilder.build()` รับ input และประกอบเป็น dict เดียว:

```
Input                          → field ใน market_state
─────────────────────────────────────────────────────────────
row["CLOSE_XAUUSD"]            → market_data.spot_price_usd.price_usd_per_oz
row["SPREAD_XAUUSD"]           → market_data.spot_price_usd.spread_points
row["CLOSE_USDTHB"]            → market_data.forex.usd_thb
row["SPREAD_USDTHB"]           → market_data.forex.spread_points
row["Mock_HSH_Buy_Close"]      → market_data.thai_gold_thb.broker_buy_price
row["Mock_HSH_Sell_Close"]     → market_data.thai_gold_thb.broker_sell_price
row["close_thai"]              → market_data.thai_gold_thb.mid_price_thb
row["premium_buy/sell"]        → market_data.thai_gold_thb.premium_*
row["pred_premium_buy/sell"]   → market_data.thai_gold_thb.pred_premium_*
row[open/high/low/close/vol]   → market_data.thai_gold_thb.ohlcv
past_5 rows                    → market_data.recent_price_action (5 แท่ง)
row["rsi"], ["rsi_signal"]     → technical_indicators.rsi
row["macd_line/signal_line"]   → technical_indicators.macd
row["bb_upper/mid/lower"]      → technical_indicators.bollinger
row["atr"]                     → technical_indicators.atr
row["ema_20/50/trend_signal"]  → technical_indicators.trend
news_provider.get(ts)          → news                       ⚠️
portfolio.to_market_state_dict → portfolio
self.timeframe                 → interval
ts                             → timestamp
```

### ตัวอย่าง market_state ที่ได้

```json
{
  "meta": {
    "generated_at": "2024-03-01 10:00:00+07:00",
    "data_mode": "csv_backtest"
  },
  "market_data": {
    "spot_price_usd": { "price_usd_per_oz": 2850.5, "spread_points": 0.3 },
    "forex":          { "usd_thb": 34.25, "spread_points": 0.02 },
    "thai_gold_thb": {
      "broker_buy_price": 47800.0,
      "broker_sell_price": 47900.0,
      "mid_price_thb": 47850.0,
      "premium_buy": 120.0, "premium_sell": 130.0,
      "pred_premium_buy": 115.0, "pred_premium_sell": 125.0,
      "ohlcv": { "open": 47820.0, "high": 47950.0, "low": 47780.0,
                 "close": 47850.0, "volume": 0.0 }
    },
    "recent_price_action": [
      { "datetime": "...", "open": 47700.0, "high": 47800.0,
        "low": 47650.0, "close": 47750.0 },
      "... (5 แท่งล่าสุดก่อน candle นี้)"
    ]
  },
  "technical_indicators": {
    "rsi":       { "value": 62.5, "signal": "neutral" },
    "macd":      { "macd_line": 45.2, "signal_line": 38.7,
                   "histogram": 6.5, "signal": "bullish" },
    "bollinger": { "upper": 48200.0, "middle": 47600.0, "lower": 47000.0 },
    "atr":       { "value": 180.0, "unit": "THB" },
    "trend":     { "ema_20": 47750.0, "ema_50": 47500.0, "trend": "uptrend" }
  },
  "news": {
    "overall_sentiment": 0.0,
    "news_count": 0,
    "top_headlines_summary": "No news data available."
  },
  "portfolio": {
    "cash_balance": 1000000.0, "gold_grams": 0.0,
    "unrealized_pnl": 0.0, "can_buy": "yes", "can_sell": "no"
  },
  "interval": "1h",
  "timestamp": "2024-03-01 10:00:00+07:00"
}
```

---

## Step 5 — ส่งต่อ ReactOrchestrator

```
market_state dict
  → ReactOrchestrator.run(market_state)
      → PromptBuilder.build_final_decision()
          → แปลงเป็น system + user prompt
      → OllamaClient.call(prompt)
          → ส่งไป Ollama local server (qwen3.5:9b)
      → parse LLM response
          → final_decision:
              signal:            BUY / SELL / HOLD
              confidence:        0.0 – 1.0
              rationale:         เหตุผล
              position_size_thb: จำนวน THB ที่จะใช้ซื้อ
              stop_loss:         ราคา SL
              take_profit:       ราคา TP
      → RiskManager.evaluate()
          → อาจ override เป็น HOLD ถ้า confidence ต่ำหรือ risk สูงเกิน
```

---

## Step 6 — อัปเดต Portfolio และ บันทึกผล

```
final_decision
  → _apply_to_portfolio()
      ถ้า can_execute == False (นอก session) → skip
      ถ้า BUY  → portfolio.execute_buy(price, pos_size)
      ถ้า SELL → portfolio.execute_sell(price)
      PortfolioBustException → หยุด backtest ทันที

  → บันทึก equity snapshot ต่อ candle:
      portfolio_total_value
      portfolio_cash
      portfolio_gold_grams

  → cache.set(ts, candle_result)   ← resume ได้ถ้า crash
```

---

## Step 7 — Metrics และ Export

```
หลัง loop จบ:
  → _add_validation()       ← คำนวณ actual_direction, net_pnl_thb
  → calculate_metrics()
      directional_accuracy  (llm vs final)
      _compute_risk_metrics → MDD, Sharpe, Sortino, Calmar
      calculate_trade_metrics → Win Rate, Profit Factor
      session_manager.compliance_report()
  → deploy_gate(metrics)    → PASS / FAIL
  → export_csv()            → บันทึก CSV ผล
```

---

## ⚠️ News Provider — ยังไม่พร้อมใช้งาน

ตอนนี้ `news_provider` ใช้ **`NullNewsProvider`** ซึ่งคืน sentiment = 0.0 ทุก candle

```python
# สิ่งที่เกิดขึ้นตอนนี้
news = {
    "overall_sentiment": 0.0,
    "news_count": 0,
    "top_headlines_summary": "No news data available."
}
```

**สิ่งที่ต้องทำเพิ่ม:**

| งาน | รายละเอียด |
|---|---|
| เตรียม CSV | ต้องมี `published_at`, `headline`, `sentiment_score` |
| เลือก window | แนะนำ 4h สำหรับ 1h candle — ดึงข่าวย้อนหลัง N ชั่วโมงก่อน ts |
| เปิดใช้ | `create_news_provider("csv", csv_path="news.csv", window_hours=4)` |
| ผล | LLM จะได้ข้อมูล sentiment + headline ประกอบการตัดสินใจ |

> `CSVNewsProvider` ใน `news_provider.py` รองรับ mode นี้อยู่แล้ว
> รอแค่ไฟล์ข้อมูลข่าว

---

## สรุป File Dependencies

```
run_main_backtest.py
  ├── csv_loader.py              ← โหลด + คำนวณ indicators
  ├── market_state_builder.py   ← ประกอบ market_state dict
  ├── news_provider.py          ← ⚠️ ใช้ Null ไปก่อน
  ├── engine/portfolio.py       ← SimPortfolio state
  ├── engine/session_manager.py ← ตรวจ trading hours
  ├── metrics/calculator.py     ← trade metrics
  ├── metrics/deploy_gate.py    ← PASS/FAIL verdict
  └── agent_core/               ← ReactOrchestrator, PromptBuilder, RiskManager
```