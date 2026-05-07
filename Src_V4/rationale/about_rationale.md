# `rationale/` Package — Implementation Guide

> **Context:** HSH ML Trading System · Signal Generator Architecture v3.1  
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
       │ gate_result: { signal_type: "BUY" | "SELL" | "HOLD", state_before, ... }
       ▼
[rationale/]  ← YOU ARE HERE
       │ payload: { rationale_text, top_shap_features, ... }
       ▼
[P5] Signal Recorder  ──▶  Supabase `signals` table
[P7] Discord Notifier ──▶  BUY / SELL / HOLD message embed
```

The `gate_result` from Phase 4 contains `hsh_close_ask`, `hsh_close_bid`, `ranker_score`, `signal_type`, and `state_before`. These feed directly into `build_trade_payload()`.

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

Defines **four** dictionaries, one per signal context:

| Dictionary        | Used when | Tone |
|-------------------|-----------|------|
| `bullish_drivers` | `BUY` | Aggressive, urgent ("explosive bounce", "massive runway") |
| `holding_drivers` | `HOLD` and `ranker_score ≥ 0` | Patient, sustained ("firmly in control", "room to run") |
| `bearish_drivers` | `SELL` | Decisive, risk-aware ("destroying the edge", "overvalued") |
| `cautious_drivers` | `HOLD` and `ranker_score < 0` | Neutral, gate-aware ("model confidence below threshold", "insufficient edge") |

Each dictionary maps a **feature name** to a **plain-English explanation** of what that feature means *in context of that signal direction*.

**Example — same feature `F_FSP`, four different readings:**

```python
# BUY context (bullish_drivers)
'F_FSP': "FSP forward price structure showing a bullish carry advantage over spot"

# HOLD, score ≥ 0 (holding_drivers)
'F_FSP': "FSP alignment continues to support the structural case for holding the position"

# SELL context (bearish_drivers)
'F_FSP': "FSP forward structure deteriorating, signaling an adverse carry cost headwind"

# HOLD, score < 0 (cautious_drivers) — the feature is a BLOCKER
'F_FSP': "FSP signal is net negative — forward carry structure does not support entry"
```

The 13 features covered map to the SHAP-relevant subset of the 34 features in `lambdamart_v11_meta.json`. If a feature is not in the dictionary, `generator.py` falls back to a generic description using the raw feature name.

---

### `generator.py` — The Core Logic

#### Function Signature

```python
def build_trade_payload(
    signal_type: str,              # "BUY" | "SELL" | "HOLD" (from Phase 4 gate_result)
    ranker_score: float,           # inference_result["ranker_score"] from Phase 3
    shap_values: List[float],      # SHAP output vector, same length as feature_names
    feature_names: List[str],      # FEATURE_COLS from lambdamart_v11_meta.json
    current_ask: Optional[float],  # features_row["hsh_close_ask"]
    current_bid: Optional[float],  # features_row["hsh_close_bid"]
    state_before: Optional[str] = None,  # "LONG" | "SHORT" | "EMPTY" | None
) -> Dict[str, Any]:
```

#### Step-by-Step Logic

**Step 1 — Compute strength percentage (sigmoid-normalised)**

```python
strength = round(1 / (1 + math.exp(-ranker_score)) * 100, 2)
```

LambdaMART outputs **unbounded** raw scores — not probabilities. A naïve `score × 100` risks displaying "196.3%" or "−214%". Sigmoid maps the full real line to `(0, 100)` and is monotone-preserving (higher score → higher %).

Reference values:

| `ranker_score` | `strength_pct` |
|---|---|
| −3.0 | 4.7% |
| −1.0 | 26.9% |
|  0.0 | 50.0% (neutral) |
| +1.0 | 73.1% |
| +3.0 | 95.3% |

**Step 2 — Validate signal string (Scenario B Fallback 1)**

```python
valid_signals = ["BUY", "SELL", "HOLD"]
if signal_type not in valid_signals:
    signal_type = "HOLD"
```

**Step 3 — Route by signal type**

| Signal | `ranker_score` | SHAP filter | Template |
|--------|---------------|-------------|----------|
| `BUY`  | any | positive SHAP, sorted desc | `bullish_drivers` |
| `SELL` | any | negative SHAP, sorted asc  | `bearish_drivers` |
| `HOLD` | ≥ 0 | positive SHAP, sorted desc | `holding_drivers` |
| `HOLD` | < 0 | negative SHAP, sorted asc  | `cautious_drivers` |

**Why HOLD needs two paths:** A HOLD with `ranker_score < 0` means the model sees *bearish* net evidence — entry was blocked because the signal is *not bullish enough*. Narrating the top *positive* SHAP features in that situation would falsely imply bullish support exists. The negative SHAP features are the actual gatekeepers and should be narrated using the `cautious_drivers` vocabulary.

**Step 3b — HOLD: spread action depends on `state_before`**

```python
if state_before == "LONG":
    spread_action = "Maintaining current long position as structural edge remains intact"
elif state_before == "SHORT":
    spread_action = "Maintaining current short position as structural edge remains intact"
elif state_before == "EMPTY":
    spread_action = "No entry taken — model confidence is below the required threshold"
else:
    spread_action = "Maintaining current position as structural edge remains intact"
```

**Step 4 — Handle empty SHAP (Scenario B Fallback 2)**

If all SHAP values are zero, BUY/SELL is overridden to HOLD. A signal without quantitative backing is never sent.

**Step 5 — Resolve top-2 feature reasons**

```python
reason_1 = template_dict.get(top_1_feat, f"key quantitative data from {top_1_feat}")
reason_2 = template_dict.get(top_2_feat, f"supporting data from {top_2_feat}") if top_2_feat else "..."
```

**Step 6 — Assemble rationale text**

```python
rationale_text = (
    f"[{action}] Model Strength: {strength}%. "
    f"Primary catalyst: {reason_1}. "
    f"Secondary confirmation: {reason_2}. "
    f"Action: {spread_action}."
)
```

**Step 7 — Build and return payload**

```python
payload = {
    "timestamp"         : datetime.now(timezone.utc).isoformat(),
    "signal_type"       : action,
    "execution_price"   : exec_price,
    "strength_pct"      : strength,      # sigmoid-normalised, always in (0, 100)
    "rationale_text"    : rationale_text,
    "top_shap_features" : top_shap_features  # reflects direction-correct SHAP features
}
```

---

## How to Integrate into the Main Pipeline

### 1. Add SHAP computation to Phase 3 (`core/model_inference.py`)

```python
import xgboost as xgb

booster = model.get_booster()
contrib = booster.predict(xgb.DMatrix(X), pred_contribs=True)
shap_values = contrib[0, :-1].tolist()  # drop bias column

return {
    "bar_time"      : features_row["bar_time"],
    "ranker_score"  : score,
    "model_version" : MODEL_VERSION,
    "features_snap" : dict(features_row),
    "shap_values"   : shap_values,   # ← NEW
    "feature_names" : FEATURE_COLS,  # ← NEW
}
```

### 2. Call `build_trade_payload` after Phase 4

`build_trade_payload` is called for **all** signal outcomes — `BUY`, `SELL`, and `HOLD` — because `HOLD` records are written to the `signals` table and may also be sent to Discord. Calling it only on passed `BUY`/`SELL` (as described in older doc versions) would leave `HOLD` records with null rationale fields.

```python
from rationale import build_trade_payload

# Call for every signal outcome — BUY, SELL, and HOLD alike
rationale_payload = build_trade_payload(
    signal_type   = gate_result["signal_type"],   # "BUY" | "SELL" | "HOLD"
    ranker_score  = gate_result["ranker_score"],
    shap_values   = inference_result["shap_values"],
    feature_names = inference_result["feature_names"],
    current_ask   = gate_result["hsh_ask"],
    current_bid   = gate_result["hsh_bid"],
    state_before  = gate_result.get("state_before"),  # "LONG" | "SHORT" | "EMPTY"
)
```

> **Note:** `state_before` must be populated by the State Manager in Phase 4 and surfaced in `gate_result`. It is required for HOLD rationale to correctly distinguish "maintaining a position" from "no entry taken".

### 3. Attach `rationale_text` to Phase 5 (Signal Recorder)

```python
def build_signal_record(gate_result: dict, rationale_payload: dict) -> dict:
    record = {
        # ... existing fields ...
        "rationale_text"    : rationale_payload["rationale_text"],
        "top_shap_features" : rationale_payload["top_shap_features"],
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

```python
def notify_signal(gate_result: dict, rationale_payload: dict) -> None:
    msg = build_base_message(gate_result)
    msg += f"\n📊 **Rationale:** {rationale_payload['rationale_text']}"
    send_discord(msg)
```

---

## Scenario B Failsafe Summary

| Situation | Behaviour |
|-----------|-----------|
| `signal_type` not in `["BUY", "SELL", "HOLD"]` | Force `"HOLD"` — safe state |
| All SHAP values are zero | Force `"HOLD"` if action was BUY/SELL |
| Feature not in template dictionary | Generic fallback string using raw feature name |
| Only 1 driver available | `reason_2` = `"no secondary confirmation available"` |
| `exec_price` is `None` for BUY/SELL | Spread action appended without price (defensive) |
| `state_before` not provided | Generic "Maintaining current position" fallback |

---

## SHAP Feature Coverage

The 13 features with template entries (11 original + 2 added for v11 dominance) cover the most SHAP-impactful features in LambdaMART v11:

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
| Forward price structure | `F_FSP` ← **NEW in v3.1** |
| Session range | `F_SA_Range` ← **NEW in v3.1** |

Features outside this list fall back to the generic string. To extend coverage, add entries to the relevant dict(s) in `templates.py` — no changes to `generator.py` needed.

---

## Testing

```python
from rationale import build_trade_payload

# ── Test 1: HOLD with negative score + EMPTY state ────────────────────────────
# Should use cautious_drivers + "No entry taken" spread_action
payload = build_trade_payload(
    signal_type   = "HOLD",
    ranker_score  = -0.14,
    shap_values   = [0.01, 0.02, -0.08, 0.0, 0.0, 0.0, 0.0, 0.0,
                     -0.12, 0.0, 0.0, 0.0, -0.05, 0.0,
                     0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                     0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                     0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
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
    current_ask   = None,
    current_bid   = None,
    state_before  = "EMPTY",
)
assert payload["signal_type"] == "HOLD"
assert "No entry taken" in payload["rationale_text"]
assert "F_FSP" in payload["top_shap_features"]  # F_FSP is top negative driver
assert 0 < payload["strength_pct"] < 50  # negative score → sigmoid < 50

# ── Test 2: BUY with positive score ───────────────────────────────────────────
payload2 = build_trade_payload(
    signal_type   = "BUY",
    ranker_score  = 0.78,
    shap_values   = [0.12, 0.09, -0.03, 0.07, 0.01, 0.0, 0.0, 0.05,
                     0.0,  0.0,  0.0,   0.0,  0.0,  0.0, 0.0, 0.0,
                     0.0,  0.0,  0.0,   0.0,  0.0,  0.0, 0.0, 0.0,
                     0.0,  0.0,  0.0,   0.0,  0.0,  0.0, 0.0, 0.0,
                     0.0,  0.0],
    feature_names = [  # same feature_names list as Test 1 ],
    current_ask   = 48250.00,
    current_bid   = 48150.00,
    state_before  = "EMPTY",
)
assert payload2["signal_type"] == "BUY"
assert payload2["execution_price"] == 48250.00
assert 50 < payload2["strength_pct"] < 100  # positive score → sigmoid > 50
```

---

## Changelog

| Version | Changes |
|---------|---------|
| v3.1 | Added `state_before` param; fixed HOLD SHAP direction for negative scores; added `cautious_drivers`; sigmoid-normalised `strength_pct`; added `F_FSP` + `F_SA_Range` to all template dicts |
| v3.0 | Initial release — BUY/SELL/HOLD routing, Scenario B failsafes, 11-feature template coverage |

---

*Last updated to match HSH ML Trading Architecture v3.1 · LambdaMART v11 · Timeframe M10*