# 🤖 AI Trading Agent — Gold Trading System (v2.4)

> Autonomous gold-trading agent for **Aom NOW (Hua Seng Heng)** platform.  
> Fixed capital: **฿1,500 THB** — no top-ups, no margin.

---

## Overview

The AI Trading Agent uses a Large Language Model (LLM) as its decision core, wrapped in a **ReAct (Reasoning + Acting)** loop. It analyzes real-time market data and issues trading signals: **BUY**, **SELL**, or **HOLD**.

All risk validation is handled by the `RiskManager`, which enforces **Hard Rule Overrides**: if the price hits a stored Take Profit (TP) or Stop Loss (SL) level, the system forces a SELL immediately — bypassing the LLM decision — to protect the portfolio.

---

## Architecture

```
Market Data (latest.json)
        │
        ▼
PromptBuilder  ──►  LLMClient  ──►  ReactOrchestrator
        │                                    │
        │                              Tool Registry
        │                            (CALL_TOOL path)
        └────────────────────────────────────┘
                                             │
                                        RiskManager
                                             │
                                      Final Decision
```

| Component | Role | File |
|-----------|------|------|
| `LLMClient` | Abstract base; sends `PromptPackage` to AI provider, returns `LLMResponse` | `client.py` |
| `PromptBuilder` | Builds `PromptPackage` per ReAct iteration; iteration-aware tool guidance | `prompt.py` |
| `ReactOrchestrator` | Controls Thought → Action → Observation loop; aggregates trace & tokens | `react.py` |
| `RiskManager` | Validates signal through 4 gates; enforces TP/SL overrides; sizes positions | `risk.py` |
| `RoleRegistry` | Loads agent persona & system prompt from `roles.json` | `prompt.py` |
| `SkillRegistry` | Manages available tools per role from `skills.json` | `prompt.py` |
| `LLMClientFactory` | Creates any `LLMClient` by provider name string | `client.py` |
| `FallbackChainClient` | Chains multiple providers; auto-switches on failure | `client.py` |

---

## Platform Constraints & Economics

| Item | Value | Notes |
|------|-------|-------|
| Position size | ฿1,400 THB | Adjusted for stability and fee reserve |
| Spread range | ฿100–200 / baht-weight | Varies with market volatility |
| Buy fee | ฿3.00 (fixed) | SCB Easy / Gold Wallet fee |
| Sell fee | ฿0.00 | Hua Seng Heng promotion |
| Total round-trip cost | ฿4.94–6.88 | Calculated on ฿1,400 position |
| Break-even move | ฿255–355 / baht-weight | Price must move this far in-direction to cover all costs |
| Trading hours | Mon–Fri 06:15–02:00 / Sat–Sun 09:30–17:30 | |
| Danger zone | 01:30–01:59 — SELL if holding | |
| Dead zone | 02:00–06:14 (120–374 min) — no trades at all | |

---

## Trading Rules

### 1. Capital & Risk Controls

| Rule | Value | Notes |
|------|-------|-------|
| Starting capital | ฿1,500 THB | Initial wallet balance |
| Bust threshold | ฿1,000 THB | Stop all trading if equity falls below this |
| Min cash to BUY | ฿1,408 THB | Position (฿1,400) + estimated fee (฿8) |
| Max daily loss | ฿150 THB | Preserves capital to continue trading next day |
| Max loss per trade | ฿80 THB | Logical stop-loss cut point |

### 2. Take-Profit — SELL when ANY condition triggers

> Calibrated against real gold price movements (~฿500–1,000 / baht-weight)

| Rule | Condition (PnL) | Approx. Price Move Required |
|------|-----------------|----------------------------|
| TP1 (primary target) | PnL ≥ +฿25 | ~฿1,300 / baht-weight |
| TP2 (technical) | PnL ≥ +฿12 AND RSI > 70 | ~฿620 / baht-weight + overbought |
| TP3 (momentum) | PnL ≥ +฿8 AND MACD hist < 0 | ~฿410 / baht-weight + momentum fading |
| Price-TP | Current price ≥ stored `take_profit_price` | Hard override — forces SELL at confidence 1.0 |

### 3. Stop-Loss — SELL when ANY condition triggers

| Rule | Condition | Notes |
|------|-----------|-------|
| SL1 (hard stop) | PnL ≤ -฿40 | Severe loss protection — no exceptions |
| SL2 (technical) | PnL ≤ -฿15 AND RSI < 30 | Loss confirmed by oversold signal |
| SL3 (time) | Holding gold AND time 01:30–01:59 | Close position before market dead zone |
| Price-SL | Current price ≤ stored `stop_loss_price` | Hard override — forces SELL at confidence 1.0 |

### 4. BUY Conditions — ALL must be true

1. Cash ≥ ฿1,408 THB
2. Gold position = 0g (not already holding)
3. Time NOT in danger zone (01:30–01:59) or dead zone (02:00–06:14)
4. At least **3 of 4** bullish signals:
   - RSI < 35 (oversold)
   - MACD histogram > 0 and increasing
   - Price > EMA20
   - Bounce from lower Bollinger Band
5. LLM confidence ≥ **0.75** (role threshold) / RiskManager gate ≥ **0.60**

---

## Risk Manager — 4-Gate Validation

```
Gate 0 — Hard Rules        (Dead zone block + Price-based TP/SL override)
Gate 1 — Confidence Filter (min 0.60; bypassed for hard-override SELLs at confidence 1.0)
Gate 2 — Daily Loss Limit  (BUY blocked if cumulative daily loss ≥ ฿150)
Gate 3 — Signal Handler    (BUY / SELL / HOLD logic + fixed ฿1,400 position sizing)
```

### Gate 0 — Hard Rules

Runs before any other checks:

1. **Dead Zone** — Rejects all signals if `120 ≤ current_minutes ≤ 374`
2. **Price-based TP/SL** — If holding gold:
   - Reads `portfolio.take_profit_price` and `portfolio.stop_loss_price` (stored at BUY time)
   - Compares against live `sell_price_thb`
   - On hit: forces `signal = SELL`, `confidence = 1.0`, prepends `[SYSTEM OVERRIDE]` to rationale

### Position Sizing Strategy

To maximize reliability and prevent insufficient-funds errors, the system uses a **fixed allocation**:

- **Fixed position**: always ฿1,400 THB per trade
- **Fee reserve**: the remaining ฿100 (from ฿1,500 capital) acts as a buffer for transaction fees and minor losses
- **Dynamic check**: if available cash < ฿1,408, the agent halts buying (HOLD) or adjusts size accordingly

### ATR-Based SL/TP (stored in portfolio at BUY time)

```
Stop Loss   = buy_price_thb − (ATR × atr_multiplier)   [default: ATR × 2.0]
Take Profit = buy_price_thb + (SL_distance × rr_ratio) [default: SL_dist × 1.5]
```

ATR unit must be `USD_PER_OZ` (validated in market data).

---

## ReAct Loop Detail

`ReactOrchestrator` runs a bounded loop (max 3 iterations per decision) using these dataclasses:

```
ReactConfig   — max_iterations (default 3), max_tool_calls (default 2)
ReactState    — market_state, tool_results, iteration, tool_call_count, react_trace
ToolResult    — tool_name, status ("success" | "error"), data, error
```

Each iteration the LLM responds with one of three actions:

| Action | Behaviour |
|--------|-----------|
| `FINAL_DECISION` | Exits loop; result passed to `RiskManager.evaluate()` |
| `CALL_TOOL` | Executes tool from registry; result appended as observation |
| `UNKNOWN` | Logs warning; falls back to HOLD immediately |

If `max_iterations` or `max_tool_calls` is reached, `build_final_decision()` is called with the full system prompt so the LLM sees all TP/SL rules.

### v2.4 Prompt Improvements

- **Iteration-aware tool guidance**: `build_thought()` now varies its instruction block per iteration number, eliminating the conflict between system prompt and user prompt that caused the LLM to skip tool calls entirely:
  - Iteration 1 — `CALL_TOOL` mandatory; `get_market_summary` required; `FINAL_DECISION` explicitly forbidden
  - Iteration 2 — choice between `get_news_sentiment` or `FINAL_DECISION`; both formats shown
  - Iteration 3+ — `FINAL_DECISION` mandatory; `CALL_TOOL` explicitly forbidden
- **Unified action format in `roles.json`**: system prompt now defines both `CALL_TOOL` and `FINAL_DECISION` actions side-by-side under `## REACT AGENT ACTIONS`, replacing the old `## OUTPUT FORMAT` block that only described `FINAL_DECISION` and caused LLM to ignore tool calls
- **Tool usage strategy in system prompt**: explicit per-iteration tool strategy (`get_market_summary` on iteration 1, `get_news_sentiment` on iteration 2) gives the LLM a clear policy without relying solely on user prompt instructions

### v2.3 Prompt Improvements

- **Break-even injection**: `_format_market_state()` now passes the break-even move (฿355 / baht-weight) directly into the prompt so the LLM can evaluate cost-effectiveness before deciding
- **PnL status tags**: e.g. `← TP1 TRIGGERED (≥+25)` or `← SL1 TRIGGERED (≤-40)` injected inline
- **Dead zone / danger zone warnings**: auto-computed from timestamp and prepended to market state

### JSON Extraction — `extract_json()`

1. Strip markdown fences (` ```json `)
2. Find all `{...}` candidates in response
3. Prefer objects containing `"action"` or `"signal"` key
4. Fallback to first parseable object, then full-string parse
5. If `json.loads` returns non-dict (e.g. bare `"HOLD"`) → parse error → HOLD
6. Return `{"_parse_error": True, "_raw": ...}` on failure

Ollama/Qwen3: `<think>...</think>` blocks are stripped automatically before JSON parsing (`_strip_think()`).

### Trace & Token Aggregation

Every LLM step is logged in `react_trace` with full metadata: `step`, `iteration`, `prompt_text`, `response_raw`, `token_input`, `token_output`, `token_total`, `model`, `provider`. Tokens are summed across all LLM steps (excludes `TOOL_EXECUTION`); `prompt_text` / `response_raw` are taken from the last `THOUGHT_FINAL` step.

---

## LLM Client Layer

### `LLMResponse` Dataclass

All providers return a unified object:

```python
@dataclass
class LLMResponse:
    text:         str   # Raw response text (JSON string)
    prompt_text:  str   # Full prompt sent (system + user)
    token_input:  int
    token_output: int
    token_total:  int
    model:        str   # Actual model name used
    provider:     str   # "gemini" | "claude" | "groq" | ...
```

### Provider Priority & Fallback Order

Primary chain (ใช้เมื่อ `--provider gemini`) — **7 layers with Failure Domain Awareness**:

| Layer | Provider | Class | Model | Domain | Notes |
|-------|----------|-------|-------|--------|-------|
| 1 — Primary | Gemini 3.1 Flash Lite Preview | `GeminiClient` | `gemini-3.1-flash-lite-preview` | google | เร็ว / ถูก |
| 2 | Gemini 2.5 Flash Lite | `GeminiClient` | `gemini-2.5-flash-lite` | google | auto-skip ถ้า google failed |
| 3 | GPT-5o Mini | `OpenRouterClient` | `openai/gpt-5o-mini` | openai | เปลี่ยน domain |
| 4 | Claude Haiku 3.5 | `OpenRouterClient` | `anthropic/claude-3-5-haiku-20241022` | anthropic | เปลี่ยน domain |
| 5 | Gemini 2.0 Flash Lite | `GeminiClient` | `gemini-2.0-flash-lite` | google | **auto-skipped** ถ้า google fail แล้ว |
| 6 | Nemotron Super | `OpenRouterClient` | `nvidia/llama-3.1-nemotron-ultra-253b-v1:free` | nvidia | free tier |
| 7 | Mock | `MockClient` | — | mock | ไม่เคย fail |

Other available providers (used as primary when specified):

| Provider | Class | Default Model | Notes |
|----------|-------|---------------|-------|
| `groq` | `GroqClient` | `llama-3.3-70b-versatile` | Highest speed |
| `openai` | `OpenAIClient` | `gpt-4o-mini` | Balanced |
| `claude` | `ClaudeClient` | `claude-sonnet-4-5` | High reasoning |
| `deepseek` | `DeepSeekClient` | `deepseek-chat` | Cost-efficient |
| `ollama` | `OllamaClient` | `qwen3.5:9b` (env override) | Local / offline |
| `openrouter` | `OpenRouterClient` | configurable | API gateway |

### Failure Domain Awareness

`FallbackChainClient` รองรับ **failure domain** — แต่ละ provider มี domain string กำกับ (เช่น `"google"`, `"openai"`, `"anthropic"`) เมื่อ provider ใด fail ระบบจะ **mark domain นั้นทันที** และ skip provider ที่เหลือในกลุ่มเดียวกันโดยอัตโนมัติ

```
ตัวอย่าง: Google API ล่มทั้ง data center
  Layer 1: gemini-3.1 [google] → FAIL  → mark domain "google" as failed
  Layer 2: gemini-2.5 [google] → SKIP  ← domain already failed (ประหยัด ~6s)
  Layer 3: gpt-5o-mini [openai] → ลอง  ← domain ใหม่ ไม่เกี่ยวกัน
  Layer 4: claude-haiku [anthropic] → ลอง (ถ้า openai ก็ fail)
  Layer 5: gemini-2.0 [google] → SKIP  ← domain already failed (ประหยัด ~6s)
  Layer 6: nemotron [nvidia] → ลอง
  Layer 7: mock → SUCCESS (guaranteed)
```

ประหยัดเวลาสูงสุด **~12 วินาที** เมื่อ Google API ล่ม (เทียบกับ linear chain ที่ต้อง retry ทุกตัว)

### `FallbackChainClient`

Chains multiple providers in order with **Failure Domain Awareness**. Each provider carries an optional `domain` string. On failure, the domain is marked — remaining providers in the same domain are skipped automatically without retrying. Tracks `active_provider` and a full `errors` list (including `domain_skip: True` entries) for debugging. Raises `LLMProviderError` only when all providers fail or are skipped.

```python
chain = FallbackChainClient([
    ("gemini",                     GeminiClient(),                          "google"),
    ("gemini-2.5-flash-lite",      GeminiClient(model="gemini-2.5-flash-lite"), "google"),
    ("openrouter:gpt-5o-mini",     OpenRouterClient(model="gpt-5o-mini"),   "openai"),
    ("openrouter:claude-haiku-3-5",OpenRouterClient(model="claude-haiku-3-5"),"anthropic"),
    ("gemini-2.0-flash-lite",      GeminiClient(model="gemini-2.0-flash-lite"),"google"),  # auto-skip
    ("openrouter:nemotron-super",  OpenRouterClient(model="nemotron-super"), "nvidia"),
    ("mock",                       MockClient(),                             "mock"),
])
```

### `LLMClientFactory`

```python
client = LLMClientFactory.create("gemini")
client = LLMClientFactory.create("claude", model="claude-3-5-sonnet")
client = LLMClientFactory.create("mock", response_map={...})
```

Supports `.register(name, class)` for adding new providers at runtime.

### Exception Hierarchy

```
LLMException
├── LLMProviderError    — API call failed (retryable via @with_retry)
└── LLMUnavailableError — Missing API key / no connection
```

`@with_retry(max_attempts=3, delay=2.0)` applies exponential-ish backoff between retries.

---

## Prompt System

### `PromptBuilder` Methods

| Method | Purpose |
|--------|---------|
| `build_thought(market_state, tool_results, iteration)` | ReAct iteration prompt with iteration-aware tool guidance |
| `build_final_decision(market_state, tool_results)` | Forced-final prompt; uses full system prompt so LLM sees all rules |
| `_format_market_state(state)` | Formats price, forex, indicators, portfolio, news + break-even into LLM-readable text |
| `_format_tool_results(results)` | Formats `ToolResult` list for context |

System prompt is **cached** after first build (`_cached_system`).

### `RoleRegistry` & `SkillRegistry`

- `RoleRegistry.load_from_json("roles.json")` — loads agent persona, system prompt, confidence threshold
- `SkillRegistry.load_from_json("skills.json")` — loads available tools per skill group
- `AIRole` enum: `ANALYST`, `RISK_MANAGER`, `TRADER`

---

## Configuration Files

**`roles.json`** — Agent persona (`analyst`), system prompt with BUY/SELL rules and ReAct action definitions (`CALL_TOOL` + `FINAL_DECISION`), confidence threshold (0.6), max position (฿1,400)

**`skills.json`** — Skill definitions:
- `market_analysis` — tools: `get_market_summary`, `get_news_sentiment`, `calculate_thb_conversion`
- `risk_assessment` — tools: `check_balance`, `calculate_drawdown_risk`

### Environment Variables

| Variable | Required For |
|----------|-------------|
| `GEMINI_API_KEY` | `GeminiClient` |
| `ANTHROPIC_API_KEY` | `ClaudeClient` |
| `OPENAI_API_KEY` | `OpenAIClient` |
| `GROQ_API_KEY` | `GroqClient` |
| `DEEPSEEK_API_KEY` | `DeepSeekClient` |
| `OPENROUTER_API_KEY` | `OpenRouterClient` |
| `OLLAMA_BASE_URL` | Ollama (default: `http://localhost:11434`) |
| `OLLAMA_MODEL` | Ollama (default: `qwen3.5:9b`) |

---

## Version History

| Version | Changes |
|---------|---------|
| v2.5 | **Failure Domain Awareness** — `FallbackChainClient` รองรับ 3-tuple `(name, client, domain)` · ถ้า provider fail ระบบ mark domain และ skip provider ที่เหลือใน domain นั้นทันที (ประหยัด ~12s เมื่อ Google API ล่ม) · Primary chain เปลี่ยนเป็น 7-layer: gemini-3.1-flash-lite-preview → gemini-2.5-flash-lite → GPT-5o Mini → Claude Haiku 3.5 → gemini-2.0-flash-lite* → nemotron-super (free) → mock · เพิ่ม OpenRouter shortcuts: `gpt-5o-mini`, `claude-haiku-3-5`, `nemotron-super` · `PROVIDER_DOMAIN` dict ใน config.py · `_GEMINI_VARIANTS` handling ใน services.py สำหรับ GeminiClient model override โดยตรง · Backward-compatible: 2-tuple เดิมทำงานได้ปกติ |
| v2.4 | Fix: LLM was skipping tool calls and going straight to FINAL_DECISION · `roles.json` system prompt rewritten — old `OUTPUT FORMAT` block (FINAL_DECISION only) replaced with `REACT AGENT ACTIONS` block (both CALL_TOOL + FINAL_DECISION) · `build_thought()` now injects iteration-aware mandatory/optional guidance per step · `services.py` `max_tool_calls` set to 2 |
| v2.3 | Position size → ฿1,400 · Break-even move (฿355) injected into prompt · TP/SL thresholds recalibrated to real price movements (TP1 +฿25, SL1 -฿40) · Max daily loss → ฿150 · Provider priority: Gemini → Claude → Groq |
| v2.2 | Price-based TP/SL stored at BUY, checked in Gate 0 · Hard Rule Override forces SELL with confidence 1.0 · `deepcopy` in `_reject_signal` |
| v2.1 | `build_final_decision()` uses full system prompt · PnL status tags in prompt · `extract_json` prioritizes `action`/`signal` key · Daily loss limit · ATR unit validation |
| v2.0 | `LLMResponse` dataclass · Token tracking · `FallbackChainClient` · `LLMClientFactory` · Dependency injection for `RiskManager` · `@with_retry` decorator |
| v1.0 | Initial ReAct loop · Gemini-only |