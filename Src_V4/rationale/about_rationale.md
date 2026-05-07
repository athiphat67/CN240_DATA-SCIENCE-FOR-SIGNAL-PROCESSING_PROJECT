# `rationale/` Package — Implementation Guide

> **Context:** HSH ML Trading System · Signal Generator Architecture v3.0  
> **Model:** LambdaMART v11 (XGBoost Ranker) · Timeframe M10  
> **Package location:** `rationale/` (root level, alongside `core/`, `db/`, `notifier/`)

---

## Overview

The `rationale/` package is a **text-generation layer** that sits between **Phase 4 (Signal Gate)** and **Phase 7 (Discord Notifier)**. Its sole job is to transform raw numeric outputs — a ranker score, SHAP values, and feature names — into a human-readable explanation string that mimics the reasoning style of an LLM.

It does **not** make any trading decisions. It only narrates the decision that was already made by the model and gate logic.

---

## Where It Sits in the Pipeline

```
[P3] XGBoost Inference
       │ ranker_score, features_snap (incl. SHAP values)
       ▼
[P4] Signal Gate & State Manager
       │ gate_result: { signal_type: "BUY" | "SELL" | None, ... }
       ▼
[rationale/]  ← YOU ARE HERE
       │ payload: { rationale_text, top_shap_features, ... }
       ▼
[P5] Signal Recorder  ──▶  Supabase `signals` table
[P7] Discord Notifier ──▶  BUY / SELL message embed
```

The `gate_result` from Phase 4 contains `hsh_close_ask`, `hsh_close_bid`, `ranker_score`, and `signal_type`. These feed directly into `build_trade_payload()`.

---

## Package Structure

```
rationale/
├── __init__.py      ← Public API: exposes build_trade_payload
├── generator.py     ← Core logic: score → payload dict
└── templates.py     ← Text lookup tables for each feature × signal type
```

### `__init__.py`

```python
from .generator import build_trade_payload
```

Exposes only `build_trade_payload` as the public API. Callers never need to import `generator` or `templates` directly.

---

## Module Breakdown

### `templates.py` — The Vocabulary Layer

Defines three dictionaries, one per signal type:

| Dictionary        | Used when | Tone |
|-------------------|-----------|------|
| `bullish_drivers` | `BUY`     | Aggressive, urgent ("explosive bounce", "massive runway") |
| `holding_drivers` | `HOLD`    | Patient, sustained ("firmly in control", "room to run") |
| `bearish_drivers` | `SELL`    | Decisive, risk-aware ("destroying the edge", "overvalued") |

Each dictionary maps a **feature name** (`F_Thai_Premium`, `F_Regime`, etc.) to a **plain-English explanation** of what that feature means *in context of that signal direction*.

**Example — same feature `F_RSI_14`, three different readings:**

```python
# BUY context (bullish_drivers)
'F_RSI_14': "extreme RSI exhaustion signaling an immediate explosive bounce"

# HOLD context (holding_drivers)
'F_RSI_14': "RSI maintains healthy levels without overbought exhaustion, giving the trend room to run"

# SELL context (bearish_drivers)
'F_RSI_14': "RSI overbought conditions indicating potential exhaustion and downside risk"
```

The 11 features covered map exactly to the SHAP-relevant subset of the 34 features in `lambdamart_v11_meta.json`. If a feature is not in the dictionary, `generator.py` falls back to a generic description using the raw feature name.

---

### `generator.py` — The Core Logic

#### Function Signature

```python
def build_trade_payload(
    signal_type: str,           # "BUY" | "SELL" | "HOLD" (from Phase 4 gate_result)
    ranker_score: float,        # inference_result["ranker_score"] from Phase 3
    shap_values: List[float],   # SHAP output vector, same length as feature_names
    feature_names: List[str],   # FEATURE_COLS from lambdamart_v11_meta.json
    current_ask: Optional[float],  # features_row["hsh_close_ask"]
    current_bid: Optional[float],  # features_row["hsh_close_bid"]
) -> Dict[str, Any]:
```

#### Step-by-Step Logic

**Step 1 — Compute strength percentage**

```python
strength = round(ranker_score * 100, 2)
```

Converts the raw ranker score (0–1 float) to a human-readable percentage for the rationale text.

**Step 2 — Validate signal string (Scenario B Fallback 1)**

```python
valid_signals = ["BUY", "SELL", "HOLD"]
if signal_type not in valid_signals:
    signal_type = "HOLD"
```

If `signal_gate.py` passes an unexpected value (e.g., `None` converted to string), the system fails *safely* to HOLD rather than crashing. This matches the **Scenario B** philosophy: fallback to safe state on logical errors, raise exceptions only on coding errors.

**Step 3 — Route by signal type**

| Signal | `action` | `exec_price` used | `drivers` filter | Template |
|--------|----------|-------------------|------------------|----------|
| `BUY`  | `"BUY"`  | `current_ask`     | SHAP > 0, sorted desc | `bullish_drivers` |
| `SELL` | `"SELL"` | `current_bid`     | SHAP < 0, sorted asc  | `bearish_drivers` |
| `HOLD` | `"HOLD"` | `None`            | SHAP > 0, sorted desc | `holding_drivers` |

For BUY: only features with **positive SHAP values** are considered (they are pushing the score up = bullish evidence).  
For SELL: only features with **negative SHAP values** (pulling the score down = bearish evidence).  
For HOLD: same as BUY — confirming reasons to stay.

**Step 4 — Handle empty SHAP (Scenario B Fallback 2)**

```python
if len(drivers) == 0:
    reason_1 = "no clear quantitative driver identified"
    reason_2 = "flat SHAP distribution across all features"
    if action != "HOLD":
        action = "HOLD"
        exec_price = None
```

If all SHAP values are zero (e.g., edge case from a degenerate model prediction), the system overrides BUY/SELL to HOLD. A signal without quantitative backing is never sent.

**Step 5 — Resolve top-2 feature reasons**

```python
top_1_feat = drivers[0][0]
top_2_feat = drivers[1][0] if len(drivers) > 1 else None

reason_1 = template_dict.get(top_1_feat, f"key quantitative data from {top_1_feat}")
reason_2 = template_dict.get(top_2_feat, ...) if top_2_feat else "no secondary confirmation available"
```

The top-ranked feature by SHAP magnitude becomes `reason_1` (primary catalyst). The second becomes `reason_2` (secondary confirmation). Features not in the template dictionary fall back to a generic string using the raw feature name — so new features added to the model don't cause KeyErrors.

**Step 6 — Assemble rationale text**

```python
rationale_text = (
    f"[{action}] Model Strength: {strength}%. "
    f"Primary catalyst: {reason_1}. "
    f"Secondary confirmation: {reason_2}. "
)
if action in ["BUY", "SELL"] and exec_price is not None:
    rationale_text += f"Action: {spread_action} ({exec_price:.2f} THB)."
else:
    rationale_text += f"Action: {spread_action}."
```

The spread action strings communicate the market microstructure intent:

| Signal | Spread action |
|--------|---------------|
| BUY    | "Aggressively crossing the spread at Ask price" |
| SELL   | "Hitting the Bid price to exit position" |
| HOLD   | "Maintaining current position as structural edge remains intact" |

**Step 7 — Build and return payload**

```python
payload = {
    "timestamp"         : datetime.now(timezone.utc).isoformat(),
    "signal_type"       : action,          # final (may differ from input if fallback triggered)
    "execution_price"   : exec_price,      # Ask for BUY, Bid for SELL, None for HOLD
    "strength_pct"      : strength,
    "rationale_text"    : rationale_text,
    "top_shap_features" : top_shap_features  # dict of top-1 and top-2 {feature: shap_value}
}
```

---

## How to Integrate into the Main Pipeline

### 1. Add SHAP computation to Phase 3 (`core/model_inference.py`)

`build_trade_payload` requires SHAP values per feature. XGBoost Ranker supports this natively:

```python
import xgboost as xgb

# After model.predict(X):
booster = model.get_booster()
contrib = booster.predict(xgb.DMatrix(X), pred_contribs=True)
# contrib shape: (1, n_features + 1) — last column is bias term
shap_values = contrib[0, :-1].tolist()  # drop bias column
```

Add `shap_values` and `feature_names` to the `run_inference` return dict:

```python
return {
    "bar_time"      : features_row["bar_time"],
    "ranker_score"  : score,
    "model_version" : MODEL_VERSION,
    "features_snap" : dict(features_row),
    "shap_values"   : shap_values,          # ← NEW
    "feature_names" : FEATURE_COLS,         # ← NEW
}
```

### 2. Call `build_trade_payload` after Phase 4

In `scheduler/orchestrator.py`, after `evaluate_signal_gate()` returns a passed signal:

```python
from rationale import build_trade_payload

# Only generate rationale when a real signal is passed
if gate_result["passed"] and gate_result["signal_type"] in ("BUY", "SELL"):
    rationale_payload = build_trade_payload(
        signal_type   = gate_result["signal_type"],
        ranker_score  = gate_result["ranker_score"],
        shap_values   = inference_result["shap_values"],
        feature_names = inference_result["feature_names"],
        current_ask   = gate_result["hsh_ask"],
        current_bid   = gate_result["hsh_bid"],
    )
else:
    rationale_payload = None
```

### 3. Attach `rationale_text` to Phase 5 (Signal Recorder)

In `core/signal_recorder.py`, extend `build_signal_record` to include the rationale:

```python
def build_signal_record(gate_result: dict, rationale_payload: dict | None) -> dict:
    record = {
        # ... existing fields ...
        "rationale_text"    : rationale_payload["rationale_text"] if rationale_payload else None,
        "top_shap_features" : rationale_payload["top_shap_features"] if rationale_payload else {},
    }
    return record
```

Add corresponding columns to the `signals` table DDL:

```sql
ALTER TABLE signals
    ADD COLUMN rationale_text    TEXT,
    ADD COLUMN top_shap_features JSONB;
```

### 4. Embed `rationale_text` in Phase 7 (Discord Notifier)

In `notifier/discord_notifier.py`, extend `notify_buy_signal` and `notify_sell_signal`:

```python
def notify_buy_signal(gate_result: dict, rationale_payload: dict | None = None) -> None:
    # ... existing message build ...
    if rationale_payload:
        msg += f"\n📊 **Rationale:** {rationale_payload['rationale_text']}"
    send_discord(msg)
```

---

## Scenario B Failsafe Summary

The module is designed with **Scenario B** error handling throughout: trading logic errors fall back to HOLD (safe), coding errors raise exceptions and surface to the caller.

| Situation | Behaviour |
|-----------|-----------|
| `signal_type` not in `["BUY", "SELL", "HOLD"]` | Force `"HOLD"` — safe state |
| All SHAP values are zero | Force `"HOLD"` if action was BUY/SELL |
| Feature not in template dictionary | Generic fallback string using raw feature name |
| Only 1 driver available | `reason_2` = `"no secondary confirmation available"` |
| `exec_price` is `None` for BUY/SELL | Spread action appended without price (defensive) |

---

## SHAP Feature Coverage

The 11 features with template entries cover the most SHAP-impactful features in LambdaMART v11. They map to these categories from the full 34-feature set:

| Category | Covered Features |
|----------|-----------------|
| Synthetic pricing | `F_Thai_Premium`, `F_Syn_Price` |
| Macro / correlation | `F_Corr_XAU_USD` |
| Momentum | `F_XAU_Mom_Short`, `F_XAU_Mom_Mid` |
| Volatility / session | `F_SRVR` |
| Transaction cost | `F_Spread_vs_ATR` |
| Regime | `F_Regime` |
| Technical | `F_RSI_14`, `F_BB_Pos` |
| Session mean reversion | `F_SA_TWAP_Dev` |

Features outside this list (e.g., `F_USD_Mom`, `F_ATR_48`, time features) fall back to the generic string. To extend coverage, simply add entries to the relevant dictionary in `templates.py` — no changes to `generator.py` are needed.

---

## Testing

```python
# Minimal smoke test
from rationale import build_trade_payload

payload = build_trade_payload(
    signal_type   = "BUY",
    ranker_score  = 0.78,
    shap_values   = [0.12, 0.09, -0.03, 0.07, 0.01, 0.0, 0.0, 0.05,
                     0.0,  0.0,  0.0,   0.0,  0.0,  0.0, 0.0, 0.0,
                     0.0,  0.0,  0.0,   0.0,  0.0,  0.0, 0.0, 0.0,
                     0.0,  0.0,  0.0,   0.0,  0.0,  0.0, 0.0, 0.0,
                     0.0,  0.0],
    feature_names = [
        "F_Syn_Price", "F_Thai_Premium", "F_Corr_XAU_USD",
        "F_XAU_Mom_Short", "F_XAU_Mom_Mid", "F_USD_Mom",
        "F_ATR_48", "F_Regime", "F_FSP", "F_SA_TWAP_Dev",
        "F_SA_MDD", "F_SA_Vol", "F_SA_Range", "F_SA_Position",
        "F_Historical_Vol_THB", "F_Remaining_Vol", "F_SRVR",
        "F_Price_Vs_Open", "F_Mom_1bar", "F_Mom_3bar",
        "F_SA_Drawdown_Pct", "F_HSH_vs_THBGold_Dev",
        "F_DayOfWeek", "F_MinuteOfDay",
        "F_RSI_14", "F_RSI_6", "F_BB_Pos", "F_XAU_Spread_Norm",
        "F_Hour_Sin", "F_Hour_Cos", "F_Session_Type",
        "F_HSH_Spread", "F_Spread_Cost_Pct", "F_Spread_vs_ATR"
    ],
    current_ask   = 48250.00,
    current_bid   = 48150.00,
)

assert payload["signal_type"] == "BUY"
assert "Thai_Premium" in payload["rationale_text"]
assert payload["execution_price"] == 48250.00
assert "F_Syn_Price" in payload["top_shap_features"]
```

---

*Last updated to match HSH ML Trading Architecture v3.0 · LambdaMART v11 · Timeframe M10*