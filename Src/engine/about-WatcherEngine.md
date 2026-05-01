# WatcherEngine — Version 1: Event-Driven Architecture

> เอกสารนี้อธิบาย **WatcherEngine** ซึ่งทำหน้าที่เป็น *Event-Driven gatekeeper* อยู่หน้า LLM
> เป้าหมายของเอกสารคือให้ผู้ที่ไม่ได้เขียนโค้ดเอง (เพื่อนร่วมโปรเจค, ผู้ตรวจ, ผู้ดูแลในอนาคต)
> เข้าใจ I/O contract, workflow, parameter ที่ปรับได้ และเหตุผลด้าน cost optimization โดยไม่ต้องอ่านโค้ดทุกบรรทัด



---

## 1. บทนำ — WatcherEngine คืออะไร (Overview)

`WatcherEngine` ใน `Src/engine/engine.py` คือ **background watcher ที่ทำงานแบบ Event-Driven**
มันรันใน thread แยกแบบต่อเนื่อง ดึง market state มาตรวจตามรอบ แล้วตัดสินใจว่า "ตอนนี้ควรปลุก LLM หรือไม่"

จุดสำคัญที่ทำให้ engine ตัวนี้มีค่าคือ **มันไม่ปลุก AI ในทุกรอบ**
LLM API call แต่ละครั้งมีต้นทุน (เงิน, latency, rate limit) ฉะนั้นการเรียก AI ทุก 5 นาทีตลอด 24 ชั่วโมงจะแพงโดยใช่เหตุ
WatcherEngine จึงทำหน้าที่เหมือน **Noise Filter** กรองเฉพาะช่วงตลาดที่ "น่าสนใจจริง" (RSI สุดโต่ง, hit SL, strong reversal) แล้วค่อยส่งงานวิเคราะห์ต่อให้ `AnalysisService.run_analysis()`

```text
┌─────────────────┐   poll    ┌──────────────────┐  trigger?  ┌──────────────────┐
│ Market data /   │ ───────►  │  WatcherEngine   │ ─────────► │ LLM (AnalysisSvc)│
│ Portfolio (DB)  │           │  (event filter)  │            │ run_analysis(…)  │
└─────────────────┘           └──────────────────┘            └──────────────────┘
                                       │
                                       └─► Discord / Telegram / TEAM_API_KEY log
```

WatcherEngine = ผู้เฝ้า + ผู้ป้องกันความเสี่ยง + ผู้กำหนดจังหวะให้ AI

### Design Philosophy (v3.1) — Detect ที่ Engine, Decide ที่ AI

WatcherEngine v3.1 แยก *การตรวจจับ* ออกจาก *การตัดสินใจขาย* อย่างชัดเจน:

| Layer | หน้าที่ | ใครทำ |
|---|---|---|
| **Detection** | คำนวณ trailing/hard SL, จับ RSI สุดโต่ง, สแกน fake/real swing | WatcherEngine (rule-based, deterministic) |
| **Decision** | ตัดสินขั้นสุดท้ายว่าจะ BUY / SELL / HOLD | LLM via `AnalysisService.run_analysis()` |
| **Execution** | สั่งขายจริงผ่าน broker / persistence | `_execute_emergency_sell()` ที่ถูก **AI สั่งเรียกเท่านั้น** |

ก่อนเวอร์ชัน v3.1: `_manage_trailing_stop` สั่งขายเองอัตโนมัติเมื่อ SL hit
ตั้งแต่ v3.1 เป็นต้นไป: `_manage_trailing_stop` **เพียงแค่ตั้งธง** `_sl_triggered` แล้วปล่อยให้ `_evaluate_strategy` เป็นผู้พิจารณาว่าเป็น *fake swing* (ถือต่อ) หรือ *real reversal* (ปลุก AI ให้ตัดสิน) ผลคือไม่มี auto-sell ที่ engine อีกต่อไป — **ทุก SELL ผ่านการอนุมัติของ AI ก่อนเสมอ**

---

## 2. System Inputs & Outputs

### 2.1 Inputs (รับอะไรเข้า)

| ที่มา | Path / Source | ใช้ทำอะไร |
|---|---|---|
| `market_state` | `data_orchestrator.run(history_days=1, interval=...)` | snapshot ของตลาดล่าสุด |
| ↳ ราคาทอง (THB) | `market_state["market_data"]["thai_gold_thb"]["sell_price_thb"]` | คำนวณราคาต่อกรัมผ่าน `_extract_price()` |
| ↳ RSI | `market_state["technical_indicators"]["rsi"]["value"]` | ตัวกระตุ้นหลักที่ทำให้ปลุก AI |
| ↳ MACD/BB | `market_state["technical_indicators"]["macd"]`, `["bollinger"]` | ใช้ใน strong-signal check |
| ↳ Raw OHLCV | `market_state["_raw_ohlcv"]` (pandas DataFrame, ~200 bars) | คำนวณ ROC pair, MACD histogram pair, swing break |
| `portfolio` | `analysis_service.persistence.get_portfolio()` | ใช้ตัดสินใจ trailing stop / SL |
| ↳ `gold_grams` | DB column | จำนวนกรัมที่ถืออยู่ |
| ↳ `cost_basis_thb` | DB column | ทุนต่อกรัม สำหรับคำนวณ profit/loss |
| ↳ `trailing_stop_level_thb` | DB column | restore ค่า trailing SL หลัง restart |
| ENV | `DISCORD_WEBHOOK_URL`, `TELEGRAM_*`, `TEAM_API_KEY` | ปลายทางของ output ฝั่ง notification + log |

### 2.2 Outputs (ส่งอะไรออก)

| ปลายทาง | Trigger / Code path | ความหมาย |
|---|---|---|
| **AI analysis pipeline** | `_trigger_analysis()` → `analysis_service.run_analysis(provider, period, intervals=[interval], bypass_session_gate=False)` | ปลุก LLM ทำ ReAct loop เต็ม pipeline |
| **External trade log** | `main.py:send_trade_log(...)` ใช้ `TEAM_API_KEY` จาก `.env` | ส่งผลการตัดสินใจไปยัง university trade-log API |
| **Discord** | `DiscordNotifier` (`Src/notification/discord_notifier.py`) → `httpx.post(webhook_url, ...)` | embed สรุปสัญญาณ BUY/SELL/HOLD พร้อม confidence bar |
| **Telegram** | `Src/notification/telegram_notifier.py` | Bot push notification |
| **PostgreSQL writes** | `save_portfolio()`, `record_emergency_sell_atomic()`, `_persist_trailing_stop()` | persist trailing-SL level, atomic emergency sell |
| **In-memory state** | `_sl_triggered`, `_active_trailing_sl_per_gram`, `trigger_state.last_trigger_time/price`, rolling log buffer | ใช้ใน loop รอบถัดไปและ poll จาก UI |

---

## 3. Core Workflow — `_watcher_loop` step-by-step

`_watcher_loop()` (engine.py) ทำงานเป็น infinite loop ใน daemon thread จนกว่า `is_running == False`
แต่ละรอบมี 7 ขั้นตอนหลัก:

```text
┌─ STEP 1 ─ Fetch market_state ────────────────────────────────────┐
│ data_orchestrator.run(history_days=1, interval=self.config.interval)
└──────────────────────────────────────────────────────────────────┘
                             │
┌─ STEP 2 ─ Extract real-time price (defensive) ───────────────────┐
│ _extract_price(market_state) → THB/gram (None ถ้า parse ไม่ได้)
└──────────────────────────────────────────────────────────────────┘
                             │
┌─ STEP 3 ─ Risk guard (Trailing SL / Hard SL) — FLAG ONLY ────────┐
│ _manage_trailing_stop(price)
│   • คำนวณ trailing SL level + persist ลง DB
│   • ถ้าราคา hit SL → set self._sl_triggered = "..."
│   • ❗ ไม่สั่งขายเอง — ปล่อยให้ Step 5 (Strategy) + AI ตัดสิน
└──────────────────────────────────────────────────────────────────┘
                             │
┌─ STEP 4 ─ Ultimate Fallback Data Parser + indicators ────────────┐
│ closes = [...] from _raw_ohlcv  (parser handles 4 shapes)
│   • pandas.DataFrame  →  candles["close"].tolist()
│   • list[dict]        →  [c["close"] or c["Close"] for c in ...]
│   • dict-of-dict      →  candles["close"].values()
│   • list[list]        →  [c[3] for c in ...]   # OHLC[V] tuple
│ rsi  = ti["rsi"]["value"]
│ roc_now, roc_prev = _compute_roc_pair(closes)   # bar-anchored t-1, t-2
│ mad_now, mad_avg  = _compute_mad(closes)
└──────────────────────────────────────────────────────────────────┘
                             │
┌─ STEP 5 ─ Strategy evaluation ───────────────────────────────────┐
│ _evaluate_strategy(holding_gold, price, cost_basis, rsi, ...)
│   • Holding gold:
│       Case 1 — _sl_triggered != None  (จาก Step 3)
│         ├─ _is_fake_swing()    : wick ยาว + |ROC| < 0.15 +
│         │                         MAD ต่ำ + RSI 40-60
│         │                         ➜ FAKE  → ถือต่อ ไม่ปลุก AI
│         └─ _is_real_reversal() : closed bar t-1, score ≥ 4/6
│             (body ≥ 50%, vol surge, RSI extreme,
│              high MAD, ROC flip, structure break)
│             ➜ REAL → ปลุก AI ทันที (SL bypass cooldown)
│             ➜ unclear → รอรอบถัดไป
│       Case 2 — strong_overbought หรือ RSI > rsi_overbought → take profit
│   • No position:
│       Case 3 — strong_oversold หรือ RSI < rsi_oversold → ปลุก AI buy
└──────────────────────────────────────────────────────────────────┘
                             │
┌─ STEP 6 ─ TriggerState gate (anti-spam) ─────────────────────────┐
│ trigger_state.is_ready(price, bypass_cooldown=is_sl_trigger)
│   • bypass_cooldown=True → ข้ามทั้ง cooldown และ min_price_step
│   • bypass_cooldown=False → ต้องผ่านทั้งสองด่าน
└──────────────────────────────────────────────────────────────────┘
                             │
┌─ STEP 7 ─ Wake AI / log decision ────────────────────────────────┐
│ _trigger_analysis() → analysis_service.run_analysis(...)
│ → log "🎯 AI Decision: {final_signal} ({conf:.0%})"
│ → _on_ai_decision() (broker hook stub)
└──────────────────────────────────────────────────────────────────┘
                             │
                  time.sleep(loop_sleep_seconds)
```

### Ultimate Fallback Data Parser — กัน Data Crash (v3.x change)

`_raw_ohlcv` ที่ส่งจาก `data_orchestrator` อาจมาในหลายรูปแบบขึ้นอยู่กับ data source (live API vs cache vs backtest replay) Step 4 จึงมี **4-way parser** ที่ตรวจ shape ของ payload ก่อนสกัด `close` series:

```python
# กรณีที่ 0: pandas DataFrame (live & backtest หลัก)
if hasattr(candles, "columns"):
    closes = [float(x) for x in candles["close"].tolist()]

# กรณีที่ 1: list ของ dict (JSON cache)
elif isinstance(candles[0], dict):
    closes = [float(c.get("close", c.get("Close", 0))) for c in candles]

# กรณีที่ 2: dict-of-dict (legacy serialized form)
elif isinstance(candles, dict) and "close" in candles:
    closes = [float(v) for v in candles["close"].values()]

# กรณีที่ 3: list-of-list (raw OHLC tuples)
elif isinstance(candles[0], list):
    closes = [float(c[3]) for c in candles]
```

ผลคือ engine **ไม่ crash แบบเงียบ** เมื่อ data source สลับโครงสร้าง — ถ้า parser ทุก branch ล้มเหมือนกัน จะ log error แล้ว skip cycle แทนที่จะปล่อย NameError ลงไปทำลาย thread

`_normalize_candles()` ทำหน้าที่คล้ายกันสำหรับ helper อื่น ๆ (`_is_fake_swing`, `_is_real_reversal`, `_compute_macd_hist_pair`) — รับทุก shape เดียวกัน + coerce NaN → 0.0 ฝั่ง volume เพื่อกัน yfinance NaN feed

### Fake Swing Defense — กรองสัญญาณหลอกก่อนปลุก AI (v3.1 change)

เมื่อ Step 3 ตั้งธง `_sl_triggered` แล้ว Step 5 จะ **ไม่ส่งไปปลุก AI ทันที** แต่จะกรองผ่าน 2 ชั้นก่อน:

1. **`_is_fake_swing()`** — มองที่ floating bar ปัจจุบัน ถ้าครบทั้ง 4 เงื่อนไขถือว่า "หลอก":

```python
return (
    body_ratio < 0.3        # wick ยาว body เล็ก
    and abs(roc) < 0.15     # momentum อ่อนมาก
    and mad_now < mad_avg   # volatility ต่ำกว่าปกติ
    and 40 <= rsi <= 60     # RSI กลาง ๆ
)
```
ถ้าเป็น fake swing → log `🛡️ SL hit but FAKE swing — holding` และ return False (ไม่ปลุก AI)

2. **`_is_real_reversal()`** — ใช้ closed bar t-1 (ไม่ใช้ in-progress bar เพื่อกัน wick spike) ให้คะแนน 6 ข้อ:

| คะแนน | เงื่อนไข |
|---:|---|
| +1 | body ratio ≥ 0.5 (close แท่งจริง) |
| +1 | volume surge > 1.3× ค่าเฉลี่ย 14 bar |
| +1 | RSI extreme (< 30 หรือ > 70) |
| +1 | MAD now > 1.5 × MAD avg (high volatility) |
| +1 | ROC flip + |ROC| > 0.3 (momentum กลับทิศ) |
| +1 | structure break (close ทะลุ swing high/low 13 bar ก่อนหน้า) |

ต้องได้ **≥ 4/6** ถึงจะถือว่า real reversal → return `True` ปลุก AI พร้อม `bypass_cooldown=True` (ผ่านด่าน TriggerState ทันที)
ถ้าได้ < 4 → log `"SL hit but signal unclear — waiting"` รอบรอบถัดไป

ผลลัพธ์ของ defense นี้: เวลา wick spike กลางแท่งหรือ noise สั้น ๆ ยิงราคาทะลุ SL ระบบจะไม่ตื่นปลุก AI โดยไม่จำเป็น — แต่เมื่อ reversal จริงเกิดขึ้น (เช่น หลังข่าวเศรษฐกิจ) AI จะถูกปลุกในวินาทีเดียวกัน

### Strong-signal check — apples-to-apples (v3.x change)

`_evaluate_strategy()` ใช้ helper สอนตัวที่คำนวณบน `_raw_ohlcv` โดยตรง เพื่อให้การเทียบ "ค่าตอนนี้ vs ค่าก่อนหน้า" ไม่ผิดเพราะ EMA seed ต่างกัน:

```python
hist_now, hist_prev = self._compute_macd_hist_pair(market_state)
roc_now, roc_prev   = self._compute_roc_pair(closes)

strong_oversold = (
    rsi < self.config.rsi_oversold
    and roc_now > roc_prev
    and hist_now > hist_prev
    and bb.get("signal") == "below_lower"
)
```

- `_compute_macd_hist_pair`: รัน EMA 12/26/9 ครั้งเดียวบน close series ทั้ง 200 bars แล้วคืน `(hist[-1], hist[-2])` → bar t (in-progress) vs bar t-1 (closed) จาก EMA pass เดียวกัน
- `_compute_roc_pair`: คำนวณ ROC สองค่าที่ anchored บน closed bars เท่านั้น (ตัด in-progress bar ทิ้ง) → ไม่ติด mid-bar noise

### `_is_real_reversal` — ใช้เฉพาะ closed bar t-1

เพื่อไม่ให้ wick spike กลางแท่งหลอกระบบ:

```python
candles = self._normalize_candles(market_state, tail=15)
closed  = candles[:-1]            # drop floating bar t
last    = closed[-1]              # bar t-1 (most recent CLOSED)
prior   = closed[:-1]             # 13-bar swing window
```

scoring 6 ข้อ (ต้องได้ ≥ 4 ถึงเรียกว่า real reversal): strong body, vol surge, RSI extreme, high MAD, ROC flip, structure break

### `TriggerState.is_ready` — 2 ด่านกัน LLM spam

```python
if bypass_cooldown:                         # SL hit → ข้ามทุกด่าน
    return True, "Ready (SL bypass — all gates skipped)"

if elapsed < cooldown_seconds:             return False, "Cooldown ..."
if price_diff < min_price_step:            return False, "Price Step ..."
return True, "Ready"
```

ผลลัพธ์ของกฎนี้คือ AI จะถูกปลุกเฉพาะตอน **(RSI สุดโต่ง หรือ SL hit) AND (cooldown หมด หรือ ราคาขยับมากพอ)**

---

## 4. Configurable Parameters

ทุก field ถูก validate ผ่าน Pydantic `WatcherConfig` (engine.py) ฉะนั้น typo / ค่าผิด range จะ raise `ValidationError` ก่อน thread เริ่ม

### 4.1 Loop cadence

| Parameter | Default | Unit | ผลกระทบเมื่อปรับ |
|---|---|---|---|
| `loop_sleep_seconds` | `30` | seconds | ความถี่ในการดึงข้อมูลและประเมิน trigger ค่าน้อย → ตอบสนองเร็วแต่กิน CPU/quota; ค่ามาก → ประหยัดทรัพยากรแต่หน่วงต่อสัญญาณ |

### 4.2 Trigger gates (anti-spam)

| Parameter | Default | Unit | ผลกระทบเมื่อปรับ |
|---|---|---|---|
| `cooldown_minutes` | `5` | minutes | ระยะห่างขั้นต่ำระหว่างการปลุก AI สองครั้ง ลดลง → AI ถูกเรียกถี่ขึ้น (cost↑); เพิ่มขึ้น → ลด LLM call แต่อาจพลาดสัญญาณติดกัน |
| `min_price_step` | `1.5` | THB/gram | ราคาต้องขยับอย่างน้อยเท่านี้จาก trigger ก่อนหน้า ค่ามาก → กรองตลาด sideways ได้ดี; ค่าน้อย → จับการเคลื่อนเล็ก ๆ ได้ แต่อาจ trigger ถี่ |

> **SL bypass:** เมื่อ `_sl_triggered` ถูก set โดย `_manage_trailing_stop`, `is_ready()` จะข้ามทั้งสองด่านนี้ทันที เพื่อให้ emergency exit ไม่ถูก block

### 4.3 AI wake-up triggers

| Parameter | Default | Range | ผลกระทบเมื่อปรับ |
|---|---|---|---|
| `rsi_oversold` | `30.0` | 0–50 | RSI ต่ำกว่าค่านี้ → ปลุก AI สำหรับ BUY ค่ามาก (เช่น 35) → ปลุกบ่อยขึ้น (false positive↑); ค่าน้อย (เช่น 25) → ปลุกเฉพาะตอน oversold หนัก |
| `rsi_overbought` | `70.0` | 50–100 | RSI สูงกว่าค่านี้ → ปลุก AI สำหรับ TAKE-PROFIT ค่าน้อย (เช่น 65) → ปลุกถี่ขึ้น; ค่ามาก (เช่น 75) → ปลุกเฉพาะ overbought หนัก |

ค่าทั้งสองนี้ถูกใช้ทั้งในกฎ RSI ธรรมดาและในเงื่อนไข `strong_oversold` / `strong_overbought` (ซึ่งต้องการ MACD histogram + ROC + BB ยืนยันเพิ่ม)

### 4.4 Risk management

| Parameter | Default | Unit | ผลกระทบเมื่อปรับ |
|---|---|---|---|
| `hard_stop_loss_per_gram` | `15.0` | THB/gram | ขาดทุน/กรัม ≥ ค่านี้ → set `_sl_triggered` เป็น "Hard Stop Loss" ค่ามาก → ทนลึกกว่า (drawdown สูง); ค่าน้อย → ตัดเร็ว (whipsaw บ่อย) |
| `trailing_stop_profit_trigger` | `20.0` | THB/gram | กำไร/กรัมต้องถึงค่านี้ก่อน trailing SL จะเปิดทำงาน เพิ่มค่า → รอให้กำไรชัดก่อนล็อก; ลดค่า → ล็อกกำไรเร็วแต่ปิดเร็ว |
| `trailing_stop_lock_in` | `5.0` | THB/gram | ตำแหน่ง SL ใหม่ = `cost_basis + trailing_stop_lock_in` (กำไรขั้นต่ำที่ล็อกไว้เมื่อ trailing เปิดแล้ว) |

ตรรกะเต็มของ trailing stop:

```text
profit_per_gram = current_price - cost_basis

if profit_per_gram >= trailing_stop_profit_trigger:
    new_sl = cost_basis + trailing_stop_lock_in
    if new_sl > current SL: ขยับ SL ขึ้น + persist ลง DB
    if price <= active SL:  set _sl_triggered = "Trailing Stop @ ..."

elif profit_per_gram <= -hard_stop_loss_per_gram:
    set _sl_triggered = "Hard Stop Loss (loss=...)"
```

### 4.5 Provider/period/interval

| Parameter | Default | Note |
|---|---|---|
| `provider` | `"gemini"` | LLM provider name (gemini/groq/openrouter/...) ส่งต่อให้ `AnalysisService.run_analysis()` |
| `period` | `"1d"` | data period ที่ส่งให้ orchestrator (allowed: 1d/3d/5d/7d/14d/1mo/2mo/3mo) |
| `interval` | `"5m"` | candle interval ที่ใช้ดึงและประเมิน |

---

## 5. Related Files

| ไฟล์ | บทบาท |
|---|---|
| `Src/engine/engine.py` | สมองและ loop ของ WatcherEngine — ประกาศ `WatcherConfig` (Pydantic), `TriggerState` (cooldown + price-step lock + SL bypass), `WatcherEngine` (loop + strategy + trailing-stop **flagging** + `_execute_emergency_sell()` hook ที่ AI สั่งเรียกเท่านั้น) |
| `Src/engine/indicators.py` | Vectorized pandas EWM สำหรับ RSI, MACD, Bollinger, ATR, EMA trend, momentum, structure — ส่งออกเป็น dataclass ผ่าน `TechnicalIndicators.to_dict()` |
| `Src/notification/discord_notifier.py` | `DiscordNotifier` (line 182) — อ่าน `DISCORD_WEBHOOK_URL` จาก env, สร้าง embed ผ่าน `build_embed(...)` ด้วย defensive numeric formatters (`_fmt_price`, `_fmt_usd`, `_confidence_bar`), POST ผ่าน `httpx` |
| `Src/main.py` | CLI entry point — สร้าง `_watcher = WatcherEngine(...)` ที่ line 292, เรียก `.start()` เพื่อ spin daemon thread (line 301), และ log การตัดสินใจไปยัง university server ผ่าน `send_trade_log(api_key=os.getenv("TEAM_API_KEY"), ...)` (line 180–197) |

```text
main.py
  └─► WatcherEngine.start()           # daemon thread
        └─► _watcher_loop()
              ├─► data_orchestrator.run()           # market_state
              ├─► analysis_service.persistence      # portfolio R/W
              ├─► _evaluate_strategy()              # uses indicators.py outputs
              ├─► _trigger_analysis()
              │     └─► AnalysisService.run_analysis()
              │           ├─► DiscordNotifier.send(...)
              │           └─► TelegramNotifier.send(...)
              └─► (post-decision) send_trade_log(TEAM_API_KEY, ...)
```

---

## 6. Cost Optimization & Value

WatcherEngine ทำหน้าที่เป็น **Noise Filter 3 ชั้น** เพื่อลดจำนวน LLM API call โดยไม่เสียคุณภาพการตัดสินใจ

### 6.1 Sanity math — ก่อน vs หลัง WatcherEngine

สมมติ market interval = 5m, ใช้งานต่อเนื่อง 24 ชม.:

| สถานการณ์ | LLM calls / วัน | หมายเหตุ |
|---|---:|---|
| **ไม่มี filter** (เรียก AI ทุกแท่ง 5m) | `24 × 60 / 5 = 288` | ทุกแท่งเรียก AI ทั้งหมด ไม่ว่าจะ sideways หรือไม่ |
| **มี WatcherEngine** (RSI band + cooldown 5m + price step 1.5 ฿/g) | `~ 5–20` (ขึ้นกับวันที่ตลาดผันผวน) | เรียกเฉพาะตอน RSI สุดโต่งหรือ SL hit |

ลดลงประมาณ **93–98%** บนวันตลาดปกติ
ในวันที่ตลาด sideways (RSI 40–60 ตลอด) อาจไม่มี LLM call เลยทั้งวัน — ซึ่งถูกต้องเพราะ LLM ที่ถูกถามจะตอบ HOLD อยู่ดี

### 6.2 Filter ทั้ง 3 ชั้น

```text
Layer 1: RSI band gate
  rsi >= rsi_oversold AND rsi <= rsi_overbought  →  ❌ no trigger
                                                     (ตลาดอยู่ใน neutral zone)

Layer 2: TriggerState (cooldown + price step)
  elapsed < cooldown_seconds                     →  ❌ blocked: "Cooldown"
  |price - last_trigger_price| < min_price_step  →  ❌ blocked: "Price Step"

Layer 3: SL bypass (override layer 2 only)
  _sl_triggered != None                          →  ✅ skip layers 2's gates
                                                     (emergency exit ต้องผ่านเสมอ)
```

แต่ละ layer ออกแบบให้ **fail-safe ฝั่ง cost** (default คือไม่ปลุก AI) ยกเว้น emergency exit ที่ **fail-safe ฝั่ง risk** (ปลุก AI ทันที)

### 6.3 ทำไมต้องเป็น Event-Driven แทน Polling

**Polling-based** (เรียก AI ทุก ๆ N นาที):
- จ่ายเงินทุก call ไม่ว่าตลาดจะมีอะไรเกิดขึ้นหรือไม่
- ใน sideways market: 95% ของ output คือ HOLD → จ่ายเงินเปล่า
- Rate limit หมดได้ในวันเดียว

**Event-Driven** (WatcherEngine v1):
- จ่ายเงินเฉพาะตอนตลาดส่งสัญญาณจริง (RSI breakout, hit SL, strong reversal)
- Sideways market = ไม่มี cost เพิ่ม
- เก็บ "งบ LLM" ไว้ใช้ตอนสำคัญจริง ๆ (เช่น Fed announcement, gold price spike)

### 6.4 มูลค่าที่เพิ่มขึ้นนอกเหนือจาก cost

| ด้าน | ผลของ WatcherEngine |
|---|---|
| **Risk** | Trailing/Hard SL ทำงานต่อเนื่องโดยไม่ต้องรอ AI cycle ใหม่ → ปกป้องทุนได้ทันที |
| **Latency** | ไม่ต้องรอ LLM ตอบช่วง emergency exit (SL bypass ส่งตรงไป AI โดยไม่ผ่าน gate) |
| **Observability** | rolling log buffer (50 entries) + Discord/Telegram + DB transaction log → debug ได้แม้ headless |
| **Testability** | กฎทุกข้อ deterministic + คอนฟิกเปลี่ยนได้ → ทดสอบได้ทั้งใน unit test และ live |

### 6.5 สรุป

WatcherEngine เปลี่ยนระบบจาก *"AI ทำงานตลอดเวลา จ่ายเงินตลอด"* ไปเป็น *"AI ทำงานเฉพาะตอนที่ตลาดมีสัญญาณจริง"*
ผลคือต้นทุน LLM ลดลง 90%+ ในขณะที่คุณภาพการตัดสินใจคงเดิมหรือดีขึ้น (เพราะ AI ไม่ถูกถามคำถามที่ไม่จำเป็น)

นี่คือเหตุผลหลักที่เราออกแบบ engine ตัวนี้ก่อนจะปล่อยให้ LLM เป็นคนตัดสินใจเองทั้งหมด

---

## 7. Quick reference

```python
from engine.engine import WatcherEngine

watcher = WatcherEngine(
    analysis_service  = analysis_svc,
    data_orchestrator = orchestrator,
    watcher_config    = {
        "provider":               "gemini",
        "period":                 "1d",
        "interval":               "5m",
        "cooldown_minutes":       5,
        "min_price_step":         1.5,
        "rsi_oversold":           30.0,
        "rsi_overbought":         70.0,
        "hard_stop_loss_per_gram":      15.0,
        "trailing_stop_profit_trigger": 20.0,
        "trailing_stop_lock_in":         5.0,
        "loop_sleep_seconds":     30,
    },
)
watcher.start()        # spin background thread
# ... later ...
watcher.stop()         # graceful shutdown
print(watcher.get_logs())  # last 50 log lines, thread-safe snapshot
```

