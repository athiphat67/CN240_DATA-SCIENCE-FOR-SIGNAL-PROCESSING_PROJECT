# GoldTrader Backtest — Architecture & Method-Level Flow

> เวอร์ชัน: Phase 1–3 Complete | Phase 4 Complete  
> อัปเดต: 2026-04-03

---

## 1. ภาพรวม

**GoldTrader v3.3 Backtest** จำลอง production pipeline ทั้งหมด (ReAct + LLM) ต่อ historical candle  
เป้าหมาย: วัดว่าถ้าใช้ระบบนี้ใน production จะได้ผลอย่างไร — Win Rate, Sharpe, Drawdown, Profit Factor

```
CSV (5m OHLCV) → [csv_loader] → [session_manager] → [news_provider]
                → [build_market_state] → [ReactOrchestrator + LLM]
                → [RiskManager] → [SimPortfolio] → [metrics] → [deploy_gate]
```

---

## 2. โครงสร้างไฟล์และหน้าที่

```
Src/
├── backtest/
│   ├── data/
│   │   └── csv_loader.py          ← load CSV + คำนวณ indicators
│   ├── engine/
│   │   ├── news_provider.py       ← plug-in news sentiment
│   │   ├── portfolio.py           ← SimPortfolio v2 (bust detection, trade log)
│   │   └── session_manager.py     ← session windows + compliance
│   ├── llm/
│   │   └── provider_adapter.py    ← Phase 3: bridge to LLMClientFactory
│   ├── metrics/
│   │   ├── calculator.py          ← Phase 4: win rate, profit factor, calmar
│   │   └── deploy_gate.py         ← Phase 4: PASS/FAIL verdict
│   └── run_main_backtest.py       ← entry point หลัก (class + CLI)
│
└── agent_core/
    ├── core/
    │   ├── react.py               ← ReactOrchestrator (ใช้จาก production ตรงๆ)
    │   ├── prompt.py              ← PromptBuilder, RoleRegistry, SkillRegistry
    │   └── risk.py                ← RiskManager (validate + SL/TP)
    ├── llm/
    │   └── client.py              ← LLMClientFactory + GeminiClient, OllamaClient, ...
    └── config/
        ├── roles.json
        └── skills.json
```

---

## 3. Method-Level Flow (ครบทุก step)

### 3.1 Entry Point — `run_main_backtest()` / `main()`

```
CLI: python run_main_backtest.py --provider gemini --timeframe 5m --days 30
         │
         ▼
main()
  ├─ argparse ดึง: --provider, --model, --ollama-url, --timeframe, --days, ...
  ├─ BacktestLLMProvider.create_for_backtest(provider, model, ollama_url)
  │    └─ ตรวจ is_available() → ถ้า False: sys.exit(1)
  └─ run_main_backtest(gold_csv, provider, ...) → metrics dict
         │
         ▼
run_main_backtest()
  ├─ MainPipelineBacktest(...).__init__()
  ├─ bt.run()
  ├─ bt.calculate_metrics()
  ├─ bt.export_csv()
  ├─ deploy_gate(metrics) → gate dict
  └─ print_gate_report(gate) → ✅ DEPLOY / ❌ NOT READY
```

---

### 3.2 `MainPipelineBacktest.__init__()`

```python
def __init__(self, gold_csv, provider="ollama", ollama_model, ollama_url, ...):
```

**หน้าที่:** init components ทั้งหมด — ไม่โหลดข้อมูลยัง

```
__init__()
  ├─ BacktestLLMProvider.create_for_backtest(provider, ...)
  │    ├─ Path A: LLMClientFactory.create(provider)  ← production client (LLMResponse)
  │    └─ Path B: _FallbackOllamaClient(model, url)  ← local client (LLMResponse)
  │    ★ Bug D fix: ทั้งสอง path คืน object ที่มี .text attribute
  │
  ├─ CandleCache(cache_dir, model_slug)   ← JSON cache per candle
  ├─ TimeEstimator()                      ← ETA display
  ├─ TradingSessionManager()              ← session windows AB/C/D/E
  ├─ NewsProvider (null/csv/live)         ← plug-in news
  └─ SimPortfolio(initial_cash=1500, bust=1000, win=1500)
```

**State ที่ถูก init:**
- `self._llm_client` — LLM client ที่คืน LLMResponse
- `self._react` — None (lazy load ใน `_load_main_components`)
- `self.portfolio` — SimPortfolio v2
- `self.session_manager` — TradingSessionManager
- `self.results: List[dict]` — ผลทุก candle

---

### 3.3 `run()` — Main Loop

```python
def run(self):
```

**หน้าที่:** วนทุก candle ใน agg_df

```
run()
  ├─ load_and_aggregate()  ← โหลด + resample ถ้ายังไม่โหลด
  ├─ _load_main_components()  ← init React/Prompt/Risk (lazy, ครั้งเดียว)
  │
  └─ for each candle (row) in agg_df:
       ├─ _run_candle(row) → candle_result dict
       │
       ├─ _apply_to_portfolio(candle_result, timestamp)
       │    ├─ ถ้า can_execute=False → return (outside session)
       │    ├─ BUY  → portfolio.execute_buy(price, pos_size, ts)
       │    │          → session_manager.record_trade(ts)
       │    └─ SELL → portfolio.execute_sell(price, ts)
       │               → session_manager.record_trade(ts)
       │
       ├─ [catch PortfolioBustException] → break loop
       │
       ├─ บันทึก equity snapshot:
       │    result["portfolio_total_value"] = portfolio.total_value(price)
       │    result["portfolio_cash"]        = portfolio.cash_balance
       │    result["portfolio_gold_grams"]  = portfolio.gold_grams
       │
       └─ results.append(candle_result)
  │
  ├─ session_manager.finalize()  ← ปิด session สุดท้าย
  └─ _add_validation()           ← เพิ่ม actual_direction, net_pnl_thb
```

---

### 3.4 `load_and_aggregate()` — โหลดข้อมูล

```
load_and_aggregate()
  ├─ load_gold_csv(self.gold_csv)
  │    ├─ อ่าน CSV: Datetime, Open, High, Low, Close, Volume
  │    ├─ คำนวณ RSI(14), MACD(12/26/9), EMA(20/50), BB(20,2), ATR(14)
  │    ├─ shift(1) ทุก indicator → ป้องกัน look-ahead bias
  │    └─ drop warmup bars (~40 แรก)
  │
  ├─ filter: timestamp >= max_date - days
  │
  ├─ timeframe == "5m" → ใช้ raw ตรงๆ
  └─ timeframe อื่น → df.resample(freq).agg({
         "close_thai": "last", "open_thai": "first",
         "rsi": "last", "macd_hist": "last", ... })
```

**Output columns ที่สำคัญ:**
`timestamp, open_thai, high_thai, low_thai, close_thai, volume, rsi, macd_line, signal_line, macd_hist, ema_20, ema_50, bb_upper, bb_mid, bb_lower, atr`

---

### 3.5 `_load_main_components()` — Lazy Init Production Components

```
_load_main_components()  [เรียกครั้งเดียว ก่อน loop]
  ├─ from agent_core.core.prompt import PromptBuilder, RoleRegistry, SkillRegistry
  ├─ from agent_core.core.react  import ReactOrchestrator, ReactConfig
  ├─ from agent_core.core.risk   import RiskManager
  │
  ├─ SkillRegistry.load_from_json("agent_core/config/skills.json")
  │    → register: market_analysis, risk_assessment
  │
  ├─ RoleRegistry.load_from_json("agent_core/config/roles.json")
  │    → register: AIRole.ANALYST (system prompt + available_skills)
  │
  ├─ PromptBuilder(role_registry, current_role=AIRole.ANALYST)
  │
  ├─ RiskManager(atr_multiplier=2.0, rr_ratio=1.5, min_confidence=0.5)
  │
  └─ ReactOrchestrator(
         llm_client=self._llm_client,   ← Phase 3: LLMResponse-returning client
         prompt_builder=prompt_builder,
         tool_registry={},              ← data pre-loaded, ไม่ใช้ tools
         config=ReactConfig(max_iterations=react_max_iter)
     )
```

---

### 3.6 `_run_candle(row)` — Core Per-Candle Logic

```
_run_candle(row: pd.Series) → candle_result: dict
  │
  ├─ [1] Cache check: CandleCache.get(ts)
  │       → ถ้ามี cache → return immediately (ไม่เรียก LLM)
  │
  ├─ [2] news_provider.get(ts)
  │       → {"overall_sentiment": 0.0, "news_count": 0, ...}
  │
  ├─ [3] portfolio.reset_daily(date_str)  ← reset trades_today ถ้าวันใหม่
  │
  ├─ [4] build_market_state(row, portfolio, news, timeframe)
  │       → {
  │           "market_data": {"thai_gold_thb": {"spot_price_thb": price}, ...},
  │           "technical_indicators": {"rsi": {...}, "macd": {...}, ...},
  │           "news": {"overall_sentiment": float, ...},
  │           "portfolio": portfolio.to_market_state_dict(price),
  │           "interval": timeframe,
  │           "timestamp": str
  │         }
  │
  ├─ [5] ReactOrchestrator.run(market_state)
  │       ┌── Fast path (max_tool_calls=0):
  │       │   ├─ PromptBuilder.build_final_decision(market_state, [])
  │       │   │    → PromptPackage(system, user, step_label="THOUGHT_FINAL")
  │       │   ├─ self._llm_client.call(prompt) → LLMResponse (มี .text)
  │       │   ├─ extract_json(llm_resp.text) → parsed dict
  │       │   ├─ _build_decision(parsed) → {signal, confidence, entry_price, sl, tp, rationale}
  │       │   └─ RiskManager.evaluate(llm_decision, market_state)
  │       │        ├─ ด่าน 1: confidence >= 0.5?
  │       │        ├─ ด่าน 2: daily_loss < 500?
  │       │        ├─ ด่าน 3: BUY → position sizing + SL/TP จาก ATR
  │       │        └─ ด่าน 4: SELL → ตรวจ gold_grams > 0
  │       └── → final_decision dict + react_trace + iterations_used
  │
  ├─ [6] extract llm_signal จาก react_trace (pre-risk LLM signal)
  │
  ├─ [7] session_manager.process_candle(ts)
  │       → SessionInfo(session_id="AB"|"C"|"D"|"E"|None, can_execute=bool)
  │
  ├─ [8] สร้าง candle_result dict:
  │       {timestamp, close_thai, llm_signal, llm_confidence, llm_rationale,
  │        final_signal, final_confidence, rejection_reason,
  │        position_size_thb, stop_loss, take_profit,
  │        iterations_used, news_sentiment, from_cache,
  │        session_id, can_execute}
  │
  └─ [9] CandleCache.set(ts, candle_result) → บันทึก JSON ไว้ resume
```

---

### 3.7 `_apply_to_portfolio(candle_result, timestamp)` — Execute Trade

```
_apply_to_portfolio(candle_result, timestamp)
  │
  ├─ ดึง: signal, price, pos_size, can_execute
  │
  ├─ can_execute=False → return (outside session → skip execution)
  │
  ├─ signal == "BUY":
  │    ├─ pos_size <= 0 → fallback: pos_size = cash * 0.6  ← Bug C fix
  │    ├─ portfolio.execute_buy(price, pos_size, timestamp)
  │    │    ├─ total_cost = pos_size + SPREAD(120) + COMMISSION(3)
  │    │    ├─ cash_balance -= total_cost
  │    │    ├─ gold_grams += (pos_size / price) * 15.244
  │    │    ├─ บันทึก _open_trade
  │    │    └─ _check_bust() → raise PortfolioBustException ถ้า total_value < 1000
  │    └─ session_manager.record_trade(ts)
  │
  └─ signal == "SELL":
       ├─ portfolio.execute_sell(price, timestamp)
       │    ├─ proceeds = (gold_grams / 15.244) * price
       │    ├─ net_proceeds = proceeds - SPREAD(120) - COMMISSION(3)
       │    ├─ cash_balance += net_proceeds
       │    ├─ ปิด _open_trade → append ClosedTrade (entry, exit, pnl_thb, is_win)
       │    └─ _check_bust()
       └─ session_manager.record_trade(ts)
```

**SPREAD_THB = 120 THB** 

---

### 3.8 `_add_validation()` — Post-Loop Labeling

```
_add_validation()
  ├─ df["next_close"]     = close_thai.shift(-1)
  ├─ df["price_change"]   = next_close - close_thai
  ├─ df["actual_direction"] = "UP" | "DOWN" | "FLAT"
  ├─ df["net_pnl_thb"]   = price_change - SPREAD_THB - COMMISSION_THB
  │
  └─ for prefix in ["llm", "final"]:
       ├─ df[f"{prefix}_correct"]    = _signal_correct(signal, actual_direction)
       └─ df[f"{prefix}_profitable"] = correct & net_pnl > 0
```

---

### 3.9 `calculate_metrics()` — คำนวณ Metrics ทั้งหมด

```
calculate_metrics() → metrics dict
  │
  ├─ [1] Directional Accuracy (per prefix: "llm", "final")
  │       active = df[signal != "HOLD"]
  │       accuracy    = correct / total * 100
  │       sensitivity = total / len(df) * 100
  │       → metrics["llm"], metrics["final"]
  │
  ├─ [2] _compute_risk_metrics(df)
  │       equity = df["portfolio_total_value"]  ← equity curve ต่อ candle
  │       ├─ MDD: (equity - running_peak) / running_peak → min value
  │       ├─ Sharpe: mean(excess_return) / std * sqrt(ppy)
  │       ├─ Sortino: mean(excess_return) / downside_std * sqrt(ppy)
  │       └─ Annualized return / volatility
  │       → metrics["risk"]
  │
  ├─ [3] session_manager.compliance_report()
  │       → metrics["session_compliance"]
  │         {total_sessions, passed_sessions, compliance_pct, session_fail_flag}
  │
  ├─ [4] calculate_trade_metrics(portfolio.closed_trades)   ← Phase 4
  │       ClosedTrade = BUY→SELL cycle ที่ปิดแล้ว
  │       ├─ win_rate_pct        = wins / total * 100
  │       ├─ profit_factor       = sum(winning_pnl) / abs(sum(losing_pnl))
  │       ├─ avg_win/loss_thb    = เฉลี่ย PnL per side
  │       ├─ expectancy_thb      = (WR × avg_win) + ((1-WR) × avg_loss)
  │       ├─ max_consec_losses   = losing streak ยาวสุด
  │       └─ net_pnl_thb, total_cost_thb
  │
  ├─ [5] add_calmar(trade_metrics, risk_metrics)
  │       calmar_ratio = annualized_return_pct / abs(mdd_pct)
  │       → metrics["trade"]
  │
  └─ metrics["bust_flag"] = portfolio.bust_flag
```

---

### 3.10 `deploy_gate(metrics)` — PASS / FAIL Verdict

```
deploy_gate(metrics) → gate dict
  │
  ├─ sharpe_ratio        > 1.0
  ├─ win_rate_pct        > 50%
  ├─ abs(mdd_pct)        < 20%
  ├─ profit_factor       > 1.2
  ├─ session_compliance  > 80%
  ├─ portfolio_not_bust  = True
  └─ calmar_ratio        > 1.0
  │
  └─ verdict: "✅ DEPLOY" (ทุก check pass) | "❌ NOT READY" (มี check fail)
```

---

## 4. Data Flow สำคัญ

### market_state dict (ส่งเข้า ReactOrchestrator)
```python
{
  "market_data": {
    "thai_gold_thb": {"spot_price_thb": 75000.0},
    "spot_price":    {"price_usd_per_oz": 0.0},    # ไม่มีใน backtest
    "forex":         {"USDTHB": 0.0},              # ไม่มีใน backtest
    "ohlcv": {"open": float, "high": float, "low": float, "close": float, "volume": float}
  },
  "technical_indicators": {
    "rsi":      {"value": 52.3, "period": 14, "signal": "neutral"},
    "macd":     {"macd_line": 12.4, "signal_line": 10.1, "histogram": 2.3, "signal": "bullish"},
    "trend":    {"ema_20": 74800.0, "ema_50": 74600.0, "trend": "uptrend"},
    "bollinger":{"upper": 76000.0, "lower": 73000.0, "mid": 74500.0},
    "atr":      {"value": 350.0}
  },
  "news": {"overall_sentiment": 0.0, "news_count": 0, "top_headlines_summary": "..."},
  "portfolio": {
    "cash_balance": 1500.0, "gold_grams": 0.0, "cost_basis_thb": 0.0,
    "current_value_thb": 0.0, "unrealized_pnl": 0.0,
    "trades_today": 0, "can_buy": "YES (cash=1500)", "can_sell": "NO (no gold held)"
  },
  "interval": "5m",
  "timestamp": "2026-01-15 10:00:00"
}
```

### candle_result dict (บันทึกทุก candle)
```python
{
  "timestamp": str, "close_thai": float,
  "llm_signal": "BUY"|"SELL"|"HOLD",  "llm_confidence": float, "llm_rationale": str,
  "final_signal": str, "final_confidence": float,
  "rejection_reason": str | None,       # ถูก RiskManager reject เพราะอะไร
  "position_size_thb": float,
  "stop_loss": float, "take_profit": float,
  "iterations_used": int, "news_sentiment": float,
  "from_cache": bool,
  "session_id": "AB"|"C"|"D"|"E"|None,
  "can_execute": bool,
  # เพิ่มใน run() หลัง _apply_to_portfolio:
  "portfolio_total_value": float,       # equity curve
  "portfolio_cash": float,
  "portfolio_gold_grams": float,
}
```

---

## 5. Constants (import จาก portfolio.py เท่านั้น — ห้าม redefine)

| Constant | ค่า | ความหมาย |
|----------|-----|----------|
| `SPREAD_THB` | **120.0** | bid/ask spread ต่อ trade |
| `COMMISSION_THB` | 3.0 | commission ต่อ trade |
| `GOLD_GRAM_PER_BAHT` | 15.244 | g ต่อ 1 บาททอง |
| `DEFAULT_CASH` | 1,500.0 | เงินเริ่มต้น |
| `BUST_THRESHOLD` | 1,000.0 | ต่ำกว่านี้ = bust → หยุดทันที |
| `WIN_THRESHOLD` | 1,500.0 | สูงกว่านี้ = winner |

---

## 6. Phase Status

| Phase | ไฟล์ | Status |
|-------|------|--------|
| Phase 1 — Data & Portfolio | `csv_loader.py`, `news_provider.py`, `portfolio.py` | ✅ Done |
| Phase 2 — Session Engine | `session_manager.py`, integration ใน `run_main_backtest.py` | ✅ Done |
| Phase 3 — LLM Provider | `provider_adapter.py`, `BacktestLLMProvider` | ✅ Done |
| Phase 4 — Metrics & Gate | `calculator.py`, `deploy_gate.py` | ✅ Done |

---

## 7. Bugs ที่ Fix แล้ว (รวมทุก session)

| # | Bug | ผล |
|---|-----|----|
| 1 | `run_main_backtest.py`: missing `import requests` | RuntimeError ที่ Ollama call |
| 2 | Local constants shadow imports (SPREAD 30 ทับ 120) | net_pnl_thb คำนวณผิด |
| 3 | `portfolio.py`: SPREAD_THB = **120 → 30** | cost 246 THB/trade = 16% ของ portfolio |
| 4 | Dead code `HistoricalNewsLoader` + `self.news_loader` | init 2 รอบ, code ซ้ำ |
| 5 | `backtest_main_pipeline.py`: SimPortfolio v1 inline | ไม่มี bust detection |
| 6-11 | `backtest_main_pipeline.py`: indentation, dead class, wrong __init__ | import crash |
| A | `portfolio.py`: SPREAD_THB 120 → 30 (fix ที่ source จริง) | PnL ผิดทั้งระบบ |
| B | `win_threshold=DEFAULT_CASH` → `WIN_THRESHOLD` | semantic wrong |
| C | `pos_size=0` guard → fallback 60% cash | จ่าย spread แต่ได้ทอง 0 กรัม |
| D | **Backtest `OllamaClient.call()` คืน `str` ไม่ใช่ `LLMResponse`** | `AttributeError: 'str' object has no attribute 'text'` ทุก candle → crash |

---

## 8. CLI Commands

```bash
cd Src/

# Gemini (production LLM)
python backtest/run_main_backtest.py \
  --gold-csv Src/backtest/data/latest_data/Final_Merged_HSH_M5.csv\
  --provider gemini \
  --timeframe 5m \
  --days 1

# Groq (fast, free tier)
python backtest/run_main_backtest.py \
  --gold-csv backtest/data/Cleaned_HSH965_M5_TH_Time.csv \
  --provider groq \
  --timeframe 5m \
  --days 30

# Ollama local (dev/test)
python backtest/run_main_backtest.py \
  --gold-csv backtest/data/Cleaned_HSH965_M5_TH_Time.csv \
  --provider ollama \
  --model qwen3:8b \
  --ollama-url http://localhost:11434 \
  --timeframe 5m \
  --days 7

# Mock (ไม่เรียก API — test pipeline เท่านั้น)
python backtest/run_main_backtest.py \
  --gold-csv backtest/data/Cleaned_HSH965_M5_TH_Time.csv \
  --provider mock \
  --timeframe 1h \
  --days 7
```

---

## 9. Environment Variables

```bash
GEMINI_API_KEY="..."            # required สำหรับ --provider=gemini
GROQ_API_KEY="..."              # required สำหรับ --provider=groq
ANTHROPIC_API_KEY="..."         # required สำหรับ --provider=claude
OPENAI_API_KEY="..."            # required สำหรับ --provider=openai
OLLAMA_BASE_URL="http://localhost:11434"   # ใช้เมื่อ --provider=ollama
OLLAMA_MODEL="qwen3:8b"
```

---

## 10. Deploy Gate Thresholds

| Metric | Threshold | มาจาก |
|--------|-----------|-------|
| Sharpe Ratio | > 1.0 | risk metrics |
| Win Rate | > 50% | trade metrics (closed trades) |
| Max Drawdown | < 20% | risk metrics |
| Profit Factor | > 1.2 | trade metrics |
| Session Compliance | > 80% | session_manager.compliance_report() |
| Portfolio Bust | = False | portfolio.bust_flag |
| Calmar Ratio | > 1.0 | annualized_return / abs(MDD) |

ทั้ง 7 ต้องผ่านพร้อมกันถึงจะได้ **✅ DEPLOY**

---

## 11. Known Limitations

| Issue | รายละเอียด |
|-------|-----------|
| Data ระยะสั้น | ~45 วัน → Sharpe ratio อาจไม่ reliable (ต้องการ 60–90 วัน) |
| Session E (เสาร์–อาทิตย์) | CSV ไม่มีข้อมูลช่วง 09:30–17:30 → `no_data` ไม่นับ fail |
| News data | ใช้ `NullNewsProvider` → LLM พึ่ง technical เท่านั้น |
| `backtest_main_pipeline.py` | ไฟล์เก่า ใช้ `run_main_backtest.py` แทน |
| `gold_spot_usd` / `usd_thb_rate` | ไม่มีใน CSV → ค่า 0.0 ใน market_state (LLM ไม่มีผล) |
| ATR unit warning | RiskManager ตรวจ unit field → ไม่ crash แต่ log warning |