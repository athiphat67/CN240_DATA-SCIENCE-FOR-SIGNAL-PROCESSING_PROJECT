# About Strategy — Analysis Tools Reference

**Location:** `data_engine/analysis_tools/`
**Audience:** Developers maintaining or extending the LLM agent pipeline
**Last updated:** 2025

---

## Table of Contents

1. [Overview](#1-overview)
2. [Pipeline Integration](#2-pipeline-integration)
   - 2.1 [How Tools Flow into the LLM](#21-how-tools-flow-into-the-llm)
   - 2.2 [ToolResultScorer — Scoring Mechanics](#22-toolresultscorer--scoring-mechanics)
   - 2.3 [execute_with_scoring — Retry Loop](#23-execute_with_scoring--retry-loop)
   - 2.4 [Recommendation Graph](#24-recommendation-graph)
3. [Fundamental Tools](#3-fundamental-tools)
   - 3.1 [check_upcoming_economic_calendar](#31-check_upcoming_economic_calendar)
   - 3.2 [get_deep_news_by_category](#32-get_deep_news_by_category)
   - 3.3 [get_intermarket_correlation](#33-get_intermarket_correlation)
   - 3.4 [get_gold_etf_flow](#34-get_gold_etf_flow)
4. [Technical Tools](#4-technical-tools)
   - Group A — Candle Series Tools
   - 4.1 [check_spot_thb_alignment](#41-check_spot_thb_alignment)
   - 4.2 [detect_breakout_confirmation](#42-detect_breakout_confirmation)
   - 4.3 [get_support_resistance_zones](#43-get_support_resistance_zones)
   - 4.4 [detect_swing_low](#44-detect_swing_low)
   - 4.5 [detect_rsi_divergence](#45-detect_rsi_divergence)
   - Group B — Snapshot + Threshold Tools
   - 4.6 [check_bb_rsi_combo](#46-check_bb_rsi_combo)
   - 4.7 [calculate_ema_distance](#47-calculate_ema_distance)
   - Group C — Higher Timeframe Tools
   - 4.8 [get_htf_trend](#48-get_htf_trend)
5. [Quick Reference](#5-quick-reference)

---

## 1. Overview

`data_engine/analysis_tools/` contains all tools that are explicitly exposed to the LLM agent during its ReAct loop. They are split into two categories:

**Fundamental Tools** operate on macro-level market data — economic events, news sentiment, cross-market correlations, and institutional positioning. They answer the question *"Is the macro environment safe to trade right now?"*

**Technical Tools** operate on OHLCV candle data and derived indicators. They answer the question *"What is the price structure telling us at this specific moment?"*

All tools are registered in `ANALYSIS_TOOL_REGISTRY` (imported by `tool_registry.py` as `LLM_TOOLS`) and described in `AVAILABLE_TOOLS_INFO` (injected into LLM prompts). Internal tools like `fetch_price`, `fetch_indicators`, and `fetch_news` are deliberately excluded from this registry — they are Orchestrator-only and never visible to the LLM.

---

## 2. Pipeline Integration

### 2.1 How Tools Flow into the LLM

```
Orchestrator
    │
    ├─► call_tool("fetch_price", ...)       ← Internal only
    ├─► call_tool("fetch_indicators", ...)  ← Internal only
    └─► call_tool("fetch_news", ...)        ← Internal only
            │
            ▼
     market_state (dict)  ──────────────────────────────────────►  LLM Prompt
                                                                        │
                                              ┌─────────────────────────┘
                                              │  ReAct Loop
                                              ▼
                                  execute_with_scoring([
                                      ("check_upcoming_economic_calendar", {...}),
                                      ("detect_breakout_confirmation",     {...}),
                                      ...
                                  ])
                                              │
                                              ▼
                                       ScoreReport
                                    ┌──────────────────┐
                                    │ should_proceed?  │
                                    │ avg_score ≥ 0.6? │
                                    └──────────────────┘
                                       Yes ──► LLM receives tool outputs
                                       No  ──► Retry with recommended tools
```

### 2.2 ToolResultScorer — Scoring Mechanics

Every tool output goes through `ToolResultScorer` before reaching the LLM. The scorer assigns a quality score (0.0 – 1.0) based on the *signal strength* of what the tool returned, not merely whether it succeeded.

**Key constants:**

| Constant | Value | Meaning |
|---|---|---|
| `PROCEED_THRESHOLD` | `0.6` | Minimum weighted-average score required to pass |
| `FLOOR_SCORE` | `0.2` | Minimum score for a successful-but-empty result (no signal) |

**Scoring formula:**

```
weighted_score_i  = score_i × weight_i
avg_score         = Σ(weighted_score_i) / Σ(weight_i)
hard_block        = any tool output has is_safe_to_trade == False
should_proceed    = (avg_score >= 0.6) and not hard_block
```

Weights default to `1.0` unless the caller provides a custom weight via `execute_with_scoring(weights={...})`. A weight of `1.5` for `check_upcoming_economic_calendar` means news risk has 50% more influence on the final decision.

**Hard Block mechanism:**

Before evaluating `should_proceed`, the scorer scans every tool output for the field `is_safe_to_trade`. If any tool returns `is_safe_to_trade=False`, a hard block is triggered immediately — the agent must not trade regardless of how high the data quality score is. The block captures the offending tool's `trade_action` and `trade_note` fields into `hard_block_reason` for logging.

This means `should_proceed=False` can now have two distinct causes:

| Cause | `hard_block` | `avg_score` |
|---|---|---|
| Data quality too low | `False` | `< 0.6` |
| Tool explicitly blocked trading | `True` | any value |

`ScoreReport` fields related to this feature:

| Field | Type | Description |
|---|---|---|
| `hard_block` | `bool` | `True` if any tool signaled `is_safe_to_trade=False` |
| `hard_block_reason` | `str` | `"[tool_name] trade_action=... — note"`, empty if no block |

**Score interpretation:**

| Score Range | Meaning |
|---|---|
| `0.0` | Tool returned an error |
| `0.2` | Tool succeeded but found no actionable signal (floor) |
| `0.3–0.5` | Weak or ambiguous signal |
| `0.6–0.75` | Moderate signal — passes threshold |
| `0.75–0.9` | Strong signal |
| `1.0` | Maximum signal strength (e.g. critical news risk) |

### 2.3 execute_with_scoring — Retry Loop

`execute_with_scoring()` (in `tool_registry.py`) is the main entry point for calling multiple tools as a batch. It runs the following pipeline:

**Step 0 — Deduplication:** Before any tool is called, duplicate `(tool_name, params)` pairs in `tool_calls` are removed. This prevents a repeated call from inflating the weighted average score artificially.

**Round 1:** Call all deduplicated tools via `_call_safe()`, wrap each result as `ToolResult`, score the batch.

**Retry (Rounds 2–N, up to `max_rounds=3`):** If `should_proceed=False`, inspect `report.recommendations` and call the recommended supplementary tools. Re-score all accumulated results together.

**Termination:** Loop exits when `should_proceed=True` or when `max_rounds` is exhausted. In the latter case, the agent proceeds with whatever context it has rather than blocking indefinitely.

**`_call_safe()` helper:** An internal function that wraps every tool call with error handling. If the tool raises an exception, it returns a `ToolResult` with `status=error` instead of propagating the exception — keeping the retry loop alive. `KeyError` (tool not found) is re-raised so the loop can skip it cleanly.

**`ScoreReport` fields returned:**

| Field | Type | Description |
|---|---|---|
| `tool_scores` | `list[ToolScore]` | Per-tool score and reason |
| `avg_score` | `float` | Weighted average across all tools |
| `should_proceed` | `bool` | `True` if `avg_score ≥ 0.6` AND no hard block |
| `hard_block` | `bool` | `True` if any tool returned `is_safe_to_trade=False` |
| `hard_block_reason` | `str` | Details of the blocking tool (empty if no block) |
| `recommendations` | `list[Recommendation]` | Tools to call next (empty if `should_proceed=True`) |
| `summary` | `str` | One-line log string |

```python
# Example call
report = execute_with_scoring(
    tool_calls=[
        ("check_upcoming_economic_calendar", {"hours_ahead": 24}),
        ("detect_breakout_confirmation", {"zone_top": 3250, "zone_bottom": 3200, "interval": "15m"}),
    ],
    weights={"check_upcoming_economic_calendar": 1.5},
    max_rounds=3,
)

if report.hard_block:
    print(f"Trading blocked: {report.hard_block_reason}")
elif report.should_proceed:
    llm_context = {ts.tool_name: ts for ts in report.tool_scores}
else:
    for rec in report.recommendations:
        print(rec.recommended_tool, rec.suggested_params)
```

### 2.4 Recommendation Graph

When a tool scores below `0.6`, the scorer looks it up in `_RECOMMENDATION_MAP` and suggests complementary tools to call next. Each recommendation inherits compatible params (`interval`, `history_days`, `timeframe`) from the low-scoring source tool.

```
detect_breakout_confirmation  ──►  get_support_resistance_zones
                              ──►  check_bb_rsi_combo

check_bb_rsi_combo            ──►  detect_rsi_divergence
                              ──►  calculate_ema_distance

detect_rsi_divergence         ──►  calculate_ema_distance

calculate_ema_distance        ──►  get_htf_trend
                              ──►  check_spot_thb_alignment

get_support_resistance_zones  ──►  detect_breakout_confirmation

get_htf_trend                 ──►  check_spot_thb_alignment
check_spot_thb_alignment      ──►  get_htf_trend

check_upcoming_economic_calendar ──►  get_intermarket_correlation

get_intermarket_correlation   ──►  check_upcoming_economic_calendar
                              ──►  get_deep_news_by_category

get_deep_news_by_category     ──►  (special: retry with next untried category)
```

`detect_swing_low` and `get_gold_etf_flow` are not in the recommendation graph. They are standalone tools whose low scores do not trigger follow-up calls.

---

## 3. Fundamental Tools

### 3.1 `check_upcoming_economic_calendar`

**Purpose:** Fetch the ForexFactory economic calendar for the current week and identify high-impact USD events within a configurable time window. This is the primary risk-gating tool — if critical news is imminent, the agent should refrain from opening new positions.

**Data source:** `https://nfs.faireconomy.media/ff_calendar_thisweek.json`

**Currencies monitored:** USD, EUR, GBP, JPY, CNY, CHF (gold-relevant only)

#### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `hours_ahead` | `int` | `24` | Time window (in hours) to scan for upcoming events |

#### Output Fields

| Field | Type | Description |
|---|---|---|
| `status` | `str` | `"success"` or `"error"` |
| `source` | `str` | Always `"forexfactory_json"` |
| `risk_level` | `str` | `"critical"`, `"high"`, `"medium"`, or `"low"` |
| `hours_checked` | `int` | The `hours_ahead` value used |
| `high_impact_usd_count` | `int` | Number of High-impact USD events in window |
| `high_impact_other_count` | `int` | Number of High-impact non-USD events |
| `medium_impact_count` | `int` | Number of Medium-impact events |
| `total_relevant_events` | `int` | Total events passing currency filter |
| `events` | `list[dict]` | Up to 15 events sorted by `hours_until` (ascending) |
| `interpretation` | `str` | Human-readable risk summary for the LLM |

Each item in `events`:

| Field | Type | Description |
|---|---|---|
| `title` | `str` | Event name (e.g. `"Non-Farm Employment Change"`) |
| `country` | `str` | Currency code (e.g. `"USD"`) |
| `impact` | `str` | `"High"`, `"Medium"`, or `"Low"` |
| `datetime_utc` | `str` | ISO-8601 UTC timestamp, `null` if tentative |
| `hours_until` | `float` | Hours until event from now, `null` if tentative |
| `forecast` | `str` | Analyst forecast value |
| `previous` | `str` | Previous release value |
| `is_tentative` | `bool` | True if time is not confirmed |

#### Internal Logic

**Step 1 — Fetch:** Download the ForexFactory JSON. Return error if unavailable.

**Step 2 — Parse and filter:** Convert each event's ISO-8601 timestamp to UTC. Filter to gold-relevant currencies only. Tentative events (no fixed time) are included only if they are High-impact USD — they are inserted into the list but excluded from `risk_level` calculation since their `hours_until` is `null`.

**Step 3 — Risk classification:**

| Condition | `risk_level` |
|---|---|
| Any High-impact USD event with `hours_until ≤ 2.0` | `"critical"` |
| Any High-impact USD event in window (but not imminent) | `"high"` |
| High-impact non-USD or any Medium-impact event | `"medium"` |
| None of the above | `"low"` |

**Step 4 — Interpretation:** A text message is generated based on `risk_level`, naming the nearest event and providing trading guidance.

#### Scoring (ToolResultScorer)

| `risk_level` | Score | Reason |
|---|---|---|
| `"critical"` | `1.0` | 🔴 Critical risk — imminent major news |
| `"high"` | `0.8` | 🟠 High risk — caution advised |
| `"medium"` | `0.5` | 🟡 Medium risk — minor events present |
| `"low"` | `0.2` | 🟢 Low risk — no significant events |
| error | `0.0` | Tool failed |

> **Note:** A `"low"` risk receives floor score (`0.2`) because the absence of news is still valid information, but it does not contribute meaningfully to the decision to enter a trade. A `"critical"` risk scores `1.0` because it dominates the trading decision regardless of technical signals.

#### Example

```python
result = call_tool("check_upcoming_economic_calendar", hours_ahead=12)
# result["risk_level"] → "critical"
# result["interpretation"] → "🔴 CRITICAL: Non-Farm Employment Change (USD High Impact) ออกอีก 1.5 ชม. ..."
```

---

### 3.2 `get_deep_news_by_category`

**Purpose:** Fetch in-depth news articles filtered by a specific macroeconomic category. This tool is a backward-compatible wrapper around the shared `fetch_news()` from `data_engine/tools`, called with `detail_level="deep"` and `max_per_category=5`.

**Data source:** `fetch_news()` in `data_engine/tools/fetch_news.py`

#### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `category` | `str` | (required) | News category to fetch. See supported values below. |

**Supported categories:**

| Value | Focus |
|---|---|
| `"gold_price"` | Gold price movements and analysis |
| `"usd_thb"` | USD/THB exchange rate |
| `"fed_policy"` | Federal Reserve policy and rates |
| `"inflation"` | CPI, PPI, inflation expectations |
| `"geopolitics"` | Geopolitical risks affecting safe-haven demand |
| `"dollar_index"` | DXY movements |
| `"thai_economy"` | Thai macroeconomic indicators |
| `"thai_gold_market"` | Thai domestic gold market (YLG, MTS Gold) |

#### Output Fields

| Field | Type | Description |
|---|---|---|
| `status` | `str` | `"success"` or `"error"` |
| `category` | `str` | The category requested |
| `articles` | `list[dict]` | List of article objects |
| `count` | `int` | Number of articles returned |

#### Internal Logic

Delegates entirely to `fetch_news_merged(max_per_category=5, category_filter=category, detail_level="deep")`. The wrapper then re-maps the response structure to the legacy format (`articles`, `count`) for backward compatibility with callers written before the news fetcher was unified.

If the upstream `fetch_news()` returns an error or no articles, the wrapper returns a clean `status: success` with an empty `articles` list rather than propagating an error, keeping downstream behavior predictable.

#### Scoring (ToolResultScorer)

The scorer first derives a base score from article count, then blends in `relevance_score` if the tool provides it.

**Base score (count-based):**

| `count` | Base Score | Label |
|---|---|---|
| `0` | `0.2` | No articles found (floor) |
| `1–2` | `0.5` | Few articles |
| `3–4` | `0.7` | Adequate coverage |
| `5+` | `0.85` | Full coverage |

**Relevance blending (if `relevance_score` field present in output):**

```
final_score = base × 0.6 + relevance_score × 0.4
```

`relevance_score` is a 0.0–1.0 quality signal provided by the tool itself (e.g. semantic similarity of articles to gold/forex context). Older tool versions that do not emit this field fall back to count-only scoring.

| Condition | Score |
|---|---|
| error | `0.0` |
| `count = 0` | `0.2` |
| Count-only (no `relevance_score`) | `0.5` / `0.7` / `0.85` |
| Count + `relevance_score` blended | `min(base × 0.6 + relevance × 0.4, 1.0)` |

#### Recommendation Behavior (Special Case)

Unlike other tools, when `get_deep_news_by_category` scores below `0.6`, the scorer does **not** recommend a different tool. Instead it looks through the full `results` history to find all categories that have already been tried across all rounds, then recommends the next untried one. This prevents re-calling a category that already returned few results in a previous round.

#### Example

```python
result = call_tool("get_deep_news_by_category", category="fed_policy")
# result["count"] → 4
# result["articles"] → [ {"title": "...", "url": "...", "summary": "..."}, ... ]
```

---

### 3.3 `get_intermarket_correlation`

**Purpose:** Measure the cross-market relationship between Gold, the US Dollar Index (DXY), and the 10-Year US Treasury Yield (US10Y). Gold classically moves *inverse* to both DXY and yields. When this relationship breaks down (divergence), it signals potential macro instability or an impending reversal.

**Data source:** yfinance — tickers `GC=F` (Gold Futures), `DX-Y.NYB` (DXY), `^TNX` (US10Y yield)

#### Parameters

This tool takes no parameters.

#### Output Fields

| Field | Type | Description |
|---|---|---|
| `status` | `str` | `"success"` or `"error"` |
| `gold` | `dict` | Gold price, 1d% change, 5d% change |
| `dxy` | `dict` | DXY value, 1d% change, 5d% change |
| `us10y` | `dict` | US10Y yield, 1d% change |
| `correlation_20d` | `dict` | Pearson correlation of daily returns over ~20 trading days |
| `correlation_regime` | `dict` | Regime label per pair |
| `divergences` | `list[dict]` | Per-pair divergence assessment |
| `interpretation` | `str` | Human-readable summary for the LLM |

`gold`, `dxy`, `us10y` each contain:

| Sub-field | Description |
|---|---|
| `price_usd` / `value` / `yield_pct` | Latest value |
| `change_1d_pct` | Percentage change from previous close |
| `change_5d_pct` | Percentage change from 5 sessions ago |

`correlation_20d`:

| Sub-field | Description |
|---|---|
| `gold_vs_dxy` | Pearson correlation (range -1.0 to +1.0) |
| `gold_vs_us10y` | Pearson correlation (range -1.0 to +1.0) |

`correlation_regime` labels:

| Label | Meaning |
|---|---|
| `"normal_inverse"` | Correlation is negative (expected behavior) |
| `"abnormal_positive"` | Correlation is positive (macro anomaly) |
| `"flat"` | Correlation is near zero |

Each item in `divergences`:

| Field | Description |
|---|---|
| `pair` | e.g. `"gold_vs_DXY"` |
| `status` | `"bearish_warning"`, `"bullish_warning"`, `"normal"`, or `"flat"` |
| `note` | Explanation of the divergence |

#### Internal Logic

**Step 1 — Fetch:** Pull 1 month of daily OHLCV for all three tickers. At minimum, Gold must be available. If neither DXY nor US10Y can be fetched, return error.

**Step 2 — Compute % changes:** Calculate 1-day and 5-day percentage changes for each asset using `Close` prices.

**Step 3 — Pearson correlation:** Align daily percentage returns on the intersection of trading dates (markets do not always share the same calendar). Compute Pearson correlation over the available window (minimum 10 data points required).

**Step 4 — Divergence detection:** Compare the 1-day direction of Gold vs DXY and Gold vs US10Y. Under normal conditions, Gold moves opposite to both. A same-direction move triggers a warning:
- Gold up + DXY up → `"bearish_warning"` (gold rally may be unsustainable)
- Gold down + DXY down → `"bullish_warning"` (gold may bounce)
- Opposite directions → `"normal"`
- Near-zero movement (< 0.05% threshold) → `"flat"`

**Step 5 — Interpretation:** Constructs a human-readable message surfacing any active warnings. Normal correlation is treated as confirmation of the current trend direction.

#### Scoring (ToolResultScorer)

| Condition | Score | Reason |
|---|---|---|
| 2 divergence warnings active | `1.0` | Both pairs diverging — very strong macro signal |
| 1 divergence warning active | `0.75` | One pair diverging |
| All pairs normal (inverse) | `0.3` | No anomaly — markets aligned |
| All pairs flat | `0.2` | No movement — no signal |
| No divergence data | `0.2` | Insufficient data (floor) |
| error | `0.0` | Tool failed |

#### Example

```python
result = call_tool("get_intermarket_correlation")
# result["divergences"] → [{"pair": "gold_vs_DXY", "status": "bearish_warning", "note": "Gold ↑ + DXY ↑ ..."}]
# result["interpretation"] → "⚠️ Gold ↑+0.45% + DXY ↑+0.18% → ผิดปกติ ทองอาจกลับลง"
```

---

### 3.4 `get_gold_etf_flow`

**Purpose:** Track institutional gold demand through SPDR Gold Trust (GLD) holdings changes. When large institutions buy or sell physical gold, it shows up as a change in the ounces held by GLD. This provides a cleaner signal of institutional intent than price alone.

**Data sources (with fallback):**
1. **Primary:** SPDR Historical Archive XLSX (`api.spdrgoldshares.com`) — provides actual ounces in trust
2. **Fallback:** yfinance `GLD` ticker — provides volume anomaly as a proxy

**Cache:** SPDR XLSX is cached locally for 12 hours (`_GLD_CACHE_MAX_AGE = 43200s`) to reduce API calls.

#### Parameters

This tool takes no parameters.

#### Output Fields (Primary — SPDR XLSX)

| Field | Type | Description |
|---|---|---|
| `status` | `str` | `"success"` or `"error"` |
| `source` | `str` | `"spdr_xlsx"` |
| `data_date` | `str` | Date of the latest data row |
| `ounces_in_trust` | `float` | Total troy ounces held in GLD |
| `ounces_change_1d` | `float` | Change in ounces from previous session |
| `ounces_change_5d` | `float` | Change over 5 sessions (null if insufficient data) |
| `tonnes_in_trust` | `float` | Converted to metric tonnes |
| `tonnes_change_1d` | `float` | 1-day tonnes change |
| `tonnes_change_5d` | `float` | 5-day tonnes change (null if insufficient data) |
| `flow_direction` | `str` | `"inflow"`, `"outflow"`, or `"flat"` |
| `institutional_signal` | `str` | `"accumulating"`, `"distributing"`, or `"neutral"` |
| `gld_close_usd` | `float` | GLD closing price (if available in XLSX) |
| `volume_today` | `int` | Share volume (if available) |
| `volume_avg_10d` | `int` | 10-day average volume (if available) |
| `volume_ratio` | `float` | `volume_today / volume_avg_10d` (null if unavailable) |
| `interpretation` | `str` | Human-readable summary |

#### Output Fields (Fallback — yfinance)

Same structure but `source = "yfinance_fallback"`. `ounces_in_trust` and `tonnes_change_1d` will be `null` since yfinance does not provide holdings data. `flow_direction` becomes `"likely_inflow"` / `"likely_outflow"` / `"unclear"` based on volume anomaly inference.

#### Internal Logic

**Step 1 — SPDR XLSX (Primary):** Check local cache. If stale or missing, download from the SPDR API. Parse the `"US GLD Historical Archive"` sheet using keyword-based column detection (tolerant of column name changes). Identify the latest and previous rows, compute changes.

**Flow direction thresholds:**
- `ounces_change > +1,000` → `"inflow"` / `"accumulating"`
- `ounces_change < -1,000` → `"outflow"` / `"distributing"`
- Otherwise → `"flat"` / `"neutral"`

**Step 2 — yfinance (Fallback):** If SPDR fails, fetch 15 days of GLD history. Infer flow direction from the combination of price direction and volume anomaly (`vol_ratio > 2.0`). Volume anomaly alone without consistent price direction yields `"unclear"`.

#### Scoring (ToolResultScorer)

`get_gold_etf_flow` is **not registered** in the scorer's dispatch map. It falls back to the generic scorer:

| Condition | Score |
|---|---|
| `status == "error"` | `0.0` |
| Any other result | `0.2` (floor) |

> **Developer note:** This tool is useful for LLM context enrichment but does not currently contribute to the `should_proceed` threshold in a meaningful way. If you want it to influence gate decisions, add a dedicated `_score_gold_etf_flow()` method to `ToolResultScorer` and register it in the dispatch map.

#### Example

```python
result = call_tool("get_gold_etf_flow")
# result["flow_direction"] → "inflow"
# result["tonnes_change_1d"] → 1.40
# result["institutional_signal"] → "accumulating"
# result["interpretation"] → "สถาบันเพิ่มทอง 1.40 ตัน (Bullish signal) | 5 วันย้อนหลัง: สะสม 3.20 ตัน"
```

---

## 4. Technical Tools

All technical tools use `OHLCVFetcher` (shared instance `_fetcher`) to pull candle data, and `TechnicalIndicators` to compute derived metrics (RSI, EMA, Bollinger Bands, MACD, ATR). Every tool accepts an optional `ohlcv_df` parameter — if a pre-fetched DataFrame is passed in, the tool skips the network call. This is the recommended pattern when calling multiple tools in the same pipeline iteration to avoid redundant requests.

---

### Group A — Candle Series Tools

These tools require analysis across a window of candles (not just the latest snapshot).

---

### 4.1 `check_spot_thb_alignment`

**Purpose:** Check whether XAU/USD (spot gold) and USD/THB are moving in the same direction over a short lookback window. Alignment between the two confirms that the Thai gold price is moving strongly in one direction. Divergence (one up, one down) creates a "neutral" signal — the two components partially cancel out.

#### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `interval` | `str` | `"15m"` | Candle interval |
| `lookback_candles` | `int` | `4` | Number of recent candles to measure direction |
| `df_spot` | `DataFrame` | `None` | Pre-fetched XAU/USD candles (optional) |
| `df_thb` | `DataFrame` | `None` | Pre-fetched USD/THB candles (optional) |

#### Output Fields

| Field | Type | Description |
|---|---|---|
| `status` | `str` | `"success"` or `"error"` |
| `interval` | `str` | Interval used |
| `alignment` | `str` | Alignment result (see below) |
| `details.spot_pct_change` | `float` | XAU/USD % change over lookback window |
| `details.thb_pct_change` | `float` | USD/THB % change over lookback window |

**Alignment values:**

| Value | Condition |
|---|---|
| `"Strong Bullish"` | Spot up AND THB up |
| `"Strong Bearish"` | Spot down AND THB down |
| `"Neutral (Spot Leading)"` | Spot up AND THB down |
| `"Neutral (THB Leading)"` | Spot down AND THB up |

#### Internal Logic

Computes the percentage change from the first to the last close within the lookback window for both instruments (`close[-lookback] → close[-1]`). The four possible direction combinations map to the four alignment labels above.

#### Scoring (ToolResultScorer)

| `alignment` | Score | Reason |
|---|---|---|
| `"Strong Bullish"` or `"Strong Bearish"` | `0.85` | Clear directional alignment |
| Any `"Neutral"` | `0.3` | Components opposing — ambiguous signal |
| error | `0.0` | Tool failed |

#### Example

```python
result = call_tool("check_spot_thb_alignment", interval="15m", lookback_candles=4)
# result["alignment"] → "Strong Bullish"
# result["details"] → {"spot_pct_change": 0.32, "thb_pct_change": 0.18}
```

---

### 4.2 `detect_breakout_confirmation`

**Purpose:** Verify whether the most recent candle has closed beyond a specified Support/Resistance zone with enough structural strength to count as a genuine breakout (not a false pierce). This is a confirmation tool — it expects the zone boundaries as input, typically supplied from `get_support_resistance_zones`.

#### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `zone_top` | `float` | (required) | Upper boundary of the zone |
| `zone_bottom` | `float` | (required) | Lower boundary of the zone |
| `interval` | `str` | `"15m"` | Candle interval |
| `history_days` | `int` | `3` | Days of history to fetch |
| `ohlcv_df` | `DataFrame` | `None` | Pre-fetched OHLCV data (optional) |

#### Output Fields

| Field | Type | Description |
|---|---|---|
| `status` | `str` | `"success"` or `"error"` |
| `interval` | `str` | Interval used |
| `is_confirmed_breakout` | `bool` | True if breakout is confirmed |
| `breakout_direction` | `str` | `"Upward (Resistance Breakout)"` or `"Downward (Support Breakdown)"` |
| `details.body_strength_pct` | `float` | Candle body as percentage of total range |
| `details.closed_price` | `float` | Closing price of the breakout candle |

> `breakout_direction` is only present when `is_confirmed_breakout` is True.

#### Internal Logic

**Price check:** If the latest close is between `zone_bottom` and `zone_top`, return `is_confirmed_breakout: False` immediately.

**Body strength:** `body_pct = |close - open| / (high - low) × 100`. A strong body requires `body_pct ≥ 50%`.

**Wick rejection check:**
- **Upward breakout:** If the upper wick (`high - max(open, close)`) is larger than the candle body, the price was rejected above — `confirmed = False`.
- **Downward breakout:** If the lower wick (`min(open, close) - low`) is larger than the candle body, the price was rejected below — `confirmed = False`.

A breakout is confirmed only when both conditions hold: the body is strong AND there is no significant wick rejection.

#### Scoring (ToolResultScorer)

| Condition | Score | Reason |
|---|---|---|
| Confirmed + `body_strength_pct ≥ 70%` | `0.95` | Very strong breakout candle |
| Confirmed + `body_strength_pct < 70%` | `0.85` | Valid breakout confirmation |
| Not confirmed | `0.2` | No breakout (floor) |
| error | `0.0` | Tool failed |

#### Example

```python
result = call_tool("detect_breakout_confirmation",
                   zone_top=3250.0, zone_bottom=3200.0, interval="15m")
# result["is_confirmed_breakout"] → True
# result["breakout_direction"] → "Upward (Resistance Breakout)"
# result["details"] → {"body_strength_pct": 72.5, "closed_price": 3258.40}
```

---

### 4.3 `get_support_resistance_zones`

**Purpose:** Identify Support and Resistance price zones from recent candle data using swing point detection (scipy `find_peaks`) and density clustering (DBSCAN). The output zones are adaptive — both the peak prominence and the clustering radius scale with ATR, so zones are naturally wider in volatile conditions and tighter in quiet markets.

#### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `interval` | `str` | `"15m"` | Candle interval |
| `history_days` | `int` | `5` | Days of history to fetch |
| `ohlcv_df` | `DataFrame` | `None` | Pre-fetched OHLCV data (optional) |

#### Output Fields

| Field | Type | Description |
|---|---|---|
| `status` | `str` | `"success"` or `"error"` |
| `interval` | `str` | Interval used |
| `current_price` | `float` | Latest close |
| `adaptive_metrics.atr_used` | `float` | ATR(14) used for scaling |
| `adaptive_metrics.final_eps` | `float` | DBSCAN epsilon used |
| `total_zones_found` | `int` | Number of identified zones |
| `zones` | `list[dict]` | Zones sorted top → bottom |

Each zone:

| Field | Description |
|---|---|
| `type` | `"Resistance"`, `"Support"`, or `"In-Range (Testing Zone)"` |
| `bottom` | Lower edge of zone |
| `top` | Upper edge of zone |
| `touches` | Number of swing points in the cluster |
| `strength` | `"High"` (≥4 touches), `"Medium"` (3 touches), `"Low"` (2 touches) |

#### Internal Logic

**Step 1 — Require 50+ candles.** Return error otherwise.

**Step 2 — ATR-adaptive parameters.** Compute ATR(14). Set DBSCAN `eps = clip(ATR × 0.7, ATR × 0.3, ATR × 3.0)`. Set `find_peaks` prominence threshold = `ATR × 1.5`.

**Step 3 — Swing detection.** Use `scipy.signal.find_peaks` on `high` (peaks) and `-low` (troughs) separately. Combine both into one price array.

**Step 4 — Clustering.** Run DBSCAN with the adaptive `eps` and `min_samples=2`. Clusters with label `-1` (noise) are discarded. Each surviving cluster becomes one zone, bounded by its min/max price.

**Step 5 — Zone classification.** Compare zone bounds to `current_price`:
- `bottom > current_price` → Resistance (zone is above price)
- `top < current_price` → Support (zone is below price)
- Otherwise → In-Range (price is inside or touching zone)

#### Scoring (ToolResultScorer)

The scorer checks whether price is within **1 ATR** of any zone boundary.

| Condition | Score | Reason |
|---|---|---|
| Price near High-strength zone | `0.9` | Strong zone proximity |
| Price near Medium-strength zone | `0.75` | Moderate zone proximity |
| Price near Low-strength zone | `0.6` | Weak zone proximity |
| Zones exist but none nearby | `0.4` | Zones found but price is in open space |
| No zones found | `0.2` | No structure detected (floor) |
| error | `0.0` | Tool failed |

#### Example

```python
result = call_tool("get_support_resistance_zones", interval="15m", history_days=5)
# result["zones"] → [
#   {"type": "Resistance", "bottom": 3260.0, "top": 3275.0, "touches": 4, "strength": "High"},
#   {"type": "Support",    "bottom": 3200.0, "top": 3215.0, "touches": 3, "strength": "Medium"},
# ]
```

---

### 4.4 `detect_swing_low`

**Purpose:** Detect a classic reversal setup — a swing low that has been subsequently confirmed by a close above the swing high. This is the core entry pattern: price makes a lower low (swing low), then a later candle closes above the prior swing high, signaling that buyers have taken control.

#### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `interval` | `str` | `"15m"` | Candle interval |
| `history_days` | `int` | `3` | Days of history to fetch |
| `lookback_candles` | `int` | `15` | Window size for pattern search |
| `ohlcv_df` | `DataFrame` | `None` | Pre-fetched OHLCV data (optional) |

#### Output Fields

| Field | Type | Description |
|---|---|---|
| `status` | `str` | `"success"` or `"error"` |
| `interval` | `str` | Interval used |
| `setup_detected` | `bool` | True if the pattern was found |
| `details.swing_low_price` | `float` | Price of the identified swing low (null if not found) |
| `details.confirmation_close` | `float` | Close price of the confirmation candle (null if not found) |

#### Internal Logic

Iterates backward through the last `lookback_candles` candles looking for the most recent swing low structure:

1. A candle at index `i` is a swing low if `low[i] < low[i-1]` AND `low[i] < low[i+1]`.
2. The swing high is `high[i]` of that same candle.
3. Any candle after index `i` that closes above `swing_high` is the confirmation candle.
4. The loop stops at the first complete setup found (most recent one takes priority).

#### Scoring (ToolResultScorer)

`detect_swing_low` is **not registered** in the scorer's dispatch map. It uses the generic scorer:

| Condition | Score |
|---|---|
| `status == "error"` | `0.0` |
| Any other result | `0.2` (floor) |

> **Developer note:** This is the primary entry-pattern detection tool, yet it has no dedicated scorer. Adding `_score_swing_low()` that returns `0.85` on `setup_detected=True` and `0.2` otherwise would make this tool's output actually influence the pipeline's `should_proceed` decision.

#### Example

```python
result = call_tool("detect_swing_low", interval="15m", lookback_candles=20)
# result["setup_detected"] → True
# result["details"] → {"swing_low_price": 3198.50, "confirmation_close": 3212.80}
```

---

### 4.5 `detect_rsi_divergence`

**Purpose:** Detect bullish RSI divergence — a pattern where price makes a lower low but the RSI indicator makes a higher low. This divergence signals that downward momentum is weakening even as price continues falling, often preceding a reversal.

#### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `interval` | `str` | `"15m"` | Candle interval |
| `history_days` | `int` | `5` | Days of history to fetch |
| `lookback_candles` | `int` | `30` | Window of candles to search for divergence |
| `ohlcv_df` | `DataFrame` | `None` | Pre-fetched OHLCV data (optional) |

#### Output Fields

| Field | Type | Description |
|---|---|---|
| `status` | `str` | `"success"` or `"error"` |
| `divergence_detected` | `bool` | True if bullish divergence found |
| `logic` | `str` | Human-readable explanation |
| `data.Low1` | `float` | First swing low price |
| `data.RSI1` | `float` | RSI at first swing low |
| `data.Low2` | `float` | Second swing low price (more recent) |
| `data.RSI2` | `float` | RSI at second swing low |

#### Internal Logic

1. Compute RSI(14) and ATR(14) over the lookback window.
2. Detect swing troughs in price using `scipy.signal.find_peaks(-low, prominence=ATR × 1.0)`.
3. Require at least 2 troughs. Take the two most recent as `Low1` (older) and `Low2` (newer).
4. Check: `Low2 < Low1` (price made a lower low) AND `RSI2 > RSI1` (RSI made a higher low).
5. If both conditions hold, `divergence_detected = True`.

Only **bullish** divergence (price lower, momentum higher) is currently implemented. Bearish divergence is not checked.

> **Note on recommendation graph:** In previous versions, a low score on `detect_rsi_divergence` would recommend `check_bb_rsi_combo` and `detect_breakout_confirmation` — creating a circular dependency. This has been fixed. The current map points only to `calculate_ema_distance`.

#### Scoring (ToolResultScorer)

| Condition | Score | Reason |
|---|---|---|
| `divergence_detected = True` | `0.85` | Bullish divergence confirmed |
| `divergence_detected = False` | `0.2` | No divergence (floor) |
| error | `0.0` | Tool failed |

#### Example

```python
result = call_tool("detect_rsi_divergence", interval="15m", lookback_candles=30)
# result["divergence_detected"] → True
# result["data"] → {"Low1": 3198.0, "RSI1": 28.4, "Low2": 3185.0, "RSI2": 31.7}
```

---

### Group B — Snapshot + Threshold Tools

These tools evaluate only the most recent candle state against fixed thresholds.

---

### 4.6 `check_bb_rsi_combo`

**Purpose:** Check for a multi-indicator oversold confluence: price below the lower Bollinger Band, RSI below 35, and MACD histogram flattening or turning positive. All three conditions together indicate that a short-term mean-reversion bounce is likely.

#### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `interval` | `str` | `"15m"` | Candle interval |
| `history_days` | `int` | `5` | Days of history to fetch |
| `ohlcv_df` | `DataFrame` | `None` | Pre-fetched OHLCV data (optional) |

#### Output Fields

| Field | Type | Description |
|---|---|---|
| `status` | `str` | `"success"` or `"error"` |
| `interval` | `str` | Interval used |
| `combo_detected` | `bool` | True if all three conditions are met |
| `raw_data.price` | `float` | Current close |
| `raw_data.lower_bb` | `float` | Lower Bollinger Band value |
| `raw_data.rsi` | `float` | Current RSI(14) |
| `raw_data.macd_hist` | `float` | Current MACD histogram value |
| `details` | `str` | Per-condition boolean summary |

#### Internal Logic

Compute `TechnicalIndicators` on the fetched DataFrame. Check the latest candle against three conditions simultaneously:

| Condition | Threshold | Field |
|---|---|---|
| Price below lower BB | `close < bb_low` | `is_price_low` |
| RSI oversold | `rsi_14 < 35.0` | `is_rsi_oversold` |
| MACD flattening | `|macd_hist| < (ATR × 0.05)` OR `macd_hist > macd_hist_prev` | `is_macd_flatten` |

`combo_detected = is_price_low AND is_rsi_oversold AND is_macd_flatten`

The MACD condition is intentionally loose — it passes if the histogram is very small (market energy is exhausted) or if the histogram is increasing (momentum is turning). Both interpretations suggest the downtrend is losing steam.

#### Scoring (ToolResultScorer)

| Condition | Score | Reason |
|---|---|---|
| `combo_detected = True` | `0.85` | Full oversold confluence |
| `combo_detected = False` | `0.2` | Conditions not met (floor) |
| error | `0.0` | Tool failed |

#### Example

```python
result = call_tool("check_bb_rsi_combo", interval="15m")
# result["combo_detected"] → True
# result["raw_data"] → {"price": 3195.20, "lower_bb": 3198.10, "rsi": 31.4, "macd_hist": -0.8}
# result["details"] → "Price<BB: True, RSI<35: True, MACD_Flatten: True"
```

---

### 4.7 `calculate_ema_distance`

**Purpose:** Measure how far the current price has stretched from the EMA(20), expressed in ATR units. A large distance (> 5 ATR) indicates that price is overextended and statistically likely to mean-revert back toward the moving average.

#### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `interval` | `str` | `"15m"` | Candle interval |
| `history_days` | `int` | `5` | Days of history to fetch |
| `ohlcv_df` | `DataFrame` | `None` | Pre-fetched OHLCV data (optional) |

#### Output Fields

| Field | Type | Description |
|---|---|---|
| `status` | `str` | `"success"` or `"error"` |
| `interval` | `str` | Interval used |
| `distance_atr_ratio` | `float` | `(price - EMA20) / ATR14` — positive = above EMA, negative = below |
| `is_overextended` | `bool` | True if `|distance_atr_ratio| > 5.0` |
| `metrics.current_price` | `float` | Latest close |
| `metrics.ema_20` | `float` | EMA(20) value |
| `metrics.atr` | `float` | ATR(14) value |

#### Internal Logic

Compute `TechnicalIndicators` on the fetched DataFrame. Extract `ema_20` and `atr_14` from the latest row. Calculate:

```
distance = (current_price - ema_20) / atr_14
is_overextended = |distance| > 5.0
```

The sign of `distance_atr_ratio` matters: positive means price is stretched above EMA (potential short setup), negative means stretched below (potential long setup). The `is_overextended` flag is sign-agnostic.

#### Scoring (ToolResultScorer)

| Condition | Score | Reason |
|---|---|---|
| `is_overextended = True` AND `|distance| ≥ 7.0` | `0.90` | Extremely overextended |
| `is_overextended = True` AND `|distance| < 7.0` | `0.75` | Overextended |
| `is_overextended = False` | `0.2` | Price near EMA — no mean-reversion setup (floor) |
| error | `0.0` | Tool failed |

#### Example

```python
result = call_tool("calculate_ema_distance", interval="15m")
# result["distance_atr_ratio"] → -6.3
# result["is_overextended"] → True
# result["metrics"] → {"current_price": 3188.0, "ema_20": 3220.5, "atr": 5.16}
```

---

### Group C — Higher Timeframe Tools

---

### 4.8 `get_htf_trend`

**Purpose:** Determine the macro trend direction on a higher timeframe by comparing the current price to EMA(200). The HTF trend acts as a directional filter — the LLM should ideally only take Long setups in a Bullish HTF environment and Short setups in a Bearish one.

**Cache:** Results are cached in memory for 30 minutes (`_CACHE_TTL_SECONDS = 1800`) per timeframe, since HTF trend rarely changes within a ReAct loop iteration.

#### Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `timeframe` | `str` | `"1h"` | Higher timeframe to analyze |
| `history_days` | `int` | `15` | Minimum days to fetch (automatically extended if needed — see below) |
| `ohlcv_df` | `DataFrame` | `None` | Pre-fetched OHLCV data (optional — must have ≥200 candles) |

**Automatic safe_days override:** The tool silently extends `history_days` to ensure at least 200 candles for EMA(200) computation:

| `timeframe` | Minimum `safe_days` |
|---|---|
| `"1h"` | 15 |
| `"4h"` | 45 |
| `"1d"` | 300 |

#### Output Fields

| Field | Type | Description |
|---|---|---|
| `status` | `str` | `"success"` or `"error"` |
| `timeframe` | `str` | Timeframe analyzed |
| `trend` | `str` | `"Bullish"` or `"Bearish"` |
| `current_price` | `float` | Latest close |
| `ema_200` | `float` | EMA(200) value |
| `distance_from_ema_pct` | `float` | `(price - EMA200) / EMA200 × 100` |

#### Internal Logic

1. Check in-memory cache for this `timeframe`. Return cached result if age < 30 minutes.
2. Ensure sufficient history (apply `safe_days` override).
3. Compute EMA(200) via `TechnicalIndicators`.
4. `trend = "Bullish"` if `current_price > ema_200`, else `"Bearish"`.
5. Compute `distance_from_ema_pct` — sign indicates direction, magnitude indicates clarity.
6. Write result to cache before returning.

#### Scoring (ToolResultScorer)

| Condition | Score | Reason |
|---|---|---|
| Clear trend + `|distance| ≥ 1.5%` | `0.75` | HTF trend confirmed with distance |
| Clear trend + `|distance| < 1.5%` | `0.6` | Trend direction clear but near EMA200 — may consolidate |
| Trend not `"Bullish"` or `"Bearish"` | `0.2` | Unclear trend (floor) |
| error | `0.0` | Tool failed |

> **Note:** The near-EMA200 case was raised from `0.5` to `0.6` in the latest scorer version. This means `get_htf_trend` now always passes the `PROCEED_THRESHOLD` as long as a valid trend is detected, regardless of how close price is to EMA200.

#### Example

```python
result = call_tool("get_htf_trend", timeframe="1h")
# result["trend"] → "Bullish"
# result["ema_200"] → 3145.80
# result["distance_from_ema_pct"] → 2.34
```

---

## 5. Quick Reference

### All LLM Tools

| Tool | Category | Group | Required Params | Passes Score At |
|---|---|---|---|---|
| `check_upcoming_economic_calendar` | Fundamental | — | `hours_ahead` (opt) | Any risk_level except `"low"` |
| `get_deep_news_by_category` | Fundamental | — | `category` | `count ≥ 3` |
| `get_intermarket_correlation` | Fundamental | — | none | ≥1 divergence warning |
| `get_gold_etf_flow` | Fundamental | — | none | Never (no dedicated scorer) |
| `check_spot_thb_alignment` | Technical | A | `interval` (opt) | `"Strong Bullish"` or `"Strong Bearish"` |
| `detect_breakout_confirmation` | Technical | A | `zone_top`, `zone_bottom` | Confirmed breakout |
| `get_support_resistance_zones` | Technical | A | `interval` (opt) | Price near any zone |
| `detect_swing_low` | Technical | A | `interval` (opt) | Never (no dedicated scorer) |
| `detect_rsi_divergence` | Technical | A | `interval` (opt) | Divergence detected |
| `check_bb_rsi_combo` | Technical | B | `interval` (opt) | Full combo detected |
| `calculate_ema_distance` | Technical | B | `interval` (opt) | Overextended (>5 ATR) |
| `get_htf_trend` | Technical | C | `timeframe` (opt) | Distance ≥ 1.5% |

### Score Summary

| Tool | Error | No Signal | Signal (weak) | Signal (strong) |
|---|---|---|---|---|
| `check_upcoming_economic_calendar` | 0.0 | 0.2 (low) | 0.5 (med) / 0.8 (high) | 1.0 (critical) |
| `get_deep_news_by_category` | 0.0 | 0.2 | 0.5–0.7 (count-only) or blended | 0.85 (or blended) |
| `get_intermarket_correlation` | 0.0 | 0.2 | 0.3–0.75 | 1.0 |
| `get_gold_etf_flow` | 0.0 | 0.2 | 0.2 | 0.2 |
| `check_spot_thb_alignment` | 0.0 | 0.3 | — | 0.85 |
| `detect_breakout_confirmation` | 0.0 | 0.2 | — | 0.85–0.95 |
| `get_support_resistance_zones` | 0.0 | 0.2 | 0.4–0.6 | 0.75–0.9 |
| `detect_swing_low` | 0.0 | 0.2 | 0.2 | 0.2 |
| `detect_rsi_divergence` | 0.0 | 0.2 | — | 0.85 |
| `check_bb_rsi_combo` | 0.0 | 0.2 | — | 0.85 |
| `calculate_ema_distance` | 0.0 | 0.2 | 0.75 | 0.90 |
| `get_htf_trend` | 0.0 | 0.2 | 0.6 (near EMA200) | 0.75 |

### Tools Needing Dedicated Scorers

Two tools currently fall back to the generic scorer and always receive `0.2` regardless of their output content. Adding dedicated scorers would allow them to influence the `should_proceed` gate:

| Tool | Suggested Scoring Logic |
|---|---|
| `detect_swing_low` | `0.85` if `setup_detected=True`, else `0.2` |
| `get_gold_etf_flow` | `0.85` for `"inflow"`/`"outflow"`, `0.2` for `"flat"`, scale by `vol_ratio` if available |