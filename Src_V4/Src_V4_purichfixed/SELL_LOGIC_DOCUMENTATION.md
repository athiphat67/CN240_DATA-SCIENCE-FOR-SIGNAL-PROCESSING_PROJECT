# Src_V4 — Sell Logic: How It Works & What We Fixed

> **Purpose:** Technical documentation covering the sell signal architecture, all identified bugs, the fixes applied, and the deployment verification process.
> **Last updated:** 2026-05-10

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Sell Signal Architecture](#2-sell-signal-architecture)
3. [How Each Component Works](#3-how-each-component-works)
   - 3.1 Signal Gate
   - 3.2 Dynamic TP Manager
   - 3.3 Orchestrator — Two Sell Paths
   - 3.4 Rationale Generator
   - 3.5 DB Writer
   - 3.6 Discord Notifier
4. [Sell Signal I/O — Input/Output Tables](#4-sell-signal-io--inputoutput-tables)
5. [Bugs Found & Fixes Applied](#5-bugs-found--fixes-applied)
6. [Pre-Deployment Checklist & Results](#6-pre-deployment-checklist--results)
7. [Test Scenarios](#7-test-scenarios)
8. [Remaining Low-Severity Notes](#8-remaining-low-severity-notes)

---

## 1. System Overview

Src_V4 is an automated Thai gold (HSH) trading signal bot that:
- Runs on a **M10 (10-minute) cron schedule**, Mon–Fri, 06:00–01:59 BKK
- Reads live gold price data from **Supabase**
- Computes technical features and runs a **LambdaMART (v11) model** to produce a `ranker_score`
- Evaluates gates to decide **BUY / HOLD / SELL**
- Sends alerts to **Discord** and writes all signals to Supabase

The system holds one position at a time (`STATE_EMPTY` or `STATE_HOLDING`). **Sell logic fires only when state = HOLDING.**

---

## 2. Sell Signal Architecture

There are **two completely separate sell paths**. Both ultimately result in state → EMPTY and a Discord SELL notification, but they are triggered differently.

```
M10 Bar fires
    │
    ├─ [Path A] DynamicTPManager.update() fires TRAIL_HIT or SL_HIT
    │       → FORCED EXIT (automated, price-based)
    │
    └─ [Path B] evaluate_signal_gate() → score < 0.07 while HOLDING
            → GATE SELL (model-based, organic)
```

### Full Flow Diagram

```
M10 Cron Job
    │
    ├─ build_candles() + compute_features()
    │       → If session == "Closed": skip
    │
    ├─ run_inference()          → ranker_score + shap_values
    │
    ├─ evaluate_signal_gate()   → signal_type + passed + reject_reason
    │       State = HOLDING →  SELL Gate:
    │                           ① market_open  (session ≠ Closed)
    │                           ② noise_gate   (F_XAU_Noise_Ratio < 2.5)
    │                           ③ score_gate   (ranker_score < 0.07)
    │
    ├─ DynamicTPManager.update()   ← runs every bar while HOLDING
    │       → save_to_file()       ← persists highest_bid for restart
    │       → Returns one of:
    │           TRAIL_HIT    → forced exit
    │           SL_HIT       → forced exit
    │           BREAKEVEN_LOCK → notify only
    │           SCORE_FADE    → notify only
    │           TP_UPDATED    → notify only
    │           NONE          → continue
    │
    ├─ [PATH A] if tp_trigger in (TRAIL_HIT, SL_HIT):
    │       1. notify_dynamic_tp()         → Discord alert #1
    │       2. build_trade_payload(SELL)   → SHAP bearish drivers
    │       3. Prepend Auto-Exit reason to rationale_text
    │       4. insert_signal()             → DB write FIRST ✅
    │       5. update_state(EMPTY)         → DB state AFTER insert ✅
    │       6. set_state(EMPTY)            → in-memory cache
    │       7. notify_sell_signal()        → Discord alert #2
    │       8. insert_bar_log()            → state_at_bar = "HOLDING" ✅
    │       9. tp_manager.reset()          → clears state file ✅
    │      10. return                      → end pipeline
    │
    └─ [PATH B] Normal path continues:
            build_trade_payload(signal_type)
            build_signal_record()
            insert_signal() + insert_bar_log()
            If signal_type == "SELL":
                update_state(EMPTY)
                set_state(EMPTY)
                tp_manager.reset()    ✅ I-1 fix
                notify_sell_signal()
            If signal_type == "HOLD":
                log only — no Discord, no state change
```

---

## 3. How Each Component Works

### 3.1 Signal Gate (`core/signal_gate.py`)

Evaluates whether the current bar should produce a SELL, HOLD signal based on state and market conditions.

**SELL Gate (state = HOLDING):**
```python
sell_gates = {
    "market_open":           session != "Closed",
    "noise_gate":            F_XAU_Noise_Ratio < GATE_SPREAD_NORM_MAX,  # 2.5
    "score_below_threshold": ranker_score < SIGNAL_THRESHOLD,           # 0.07
}
passed = all(sell_gates.values())
signal_type = "SELL" if passed else "HOLD"
```

**Key design decisions:**
- No regime gate or SRVR gate on SELL — those are entry-only filters
- `F_XAU_Noise_Ratio` blocks exit in chaotic markets (prevents panic-selling noise)
- `signal_type = "HOLD"` (not `None`) when gate fails — prevents `None` propagating downstream
- `reject_reason` = the first failing gate key — stored in DB for analysis

---

### 3.2 Dynamic TP Manager (`core/dynamic_tp_manager.py`)

Manages trailing stop and stop-loss for an open position. Runs every M10 bar while HOLDING.

**State variables:**
```
is_active          → True once BUY is processed
entry_ask          → Price the position was opened at (Ask)
entry_score        → Model score at entry (for SCORE_FADE detection)
sl_price           → Fixed stop loss price = entry_ask - (ATR × 1.0)
highest_bid        → Ratchets up with price (never goes down)
_breakeven_locked  → True once price moved up ≥ 1 ATR from entry
```

**Priority order in `update()`:**
```
1. SL_HIT        → bid ≤ sl_price                    (checked BEFORE updating highest_bid)
2. TRAIL_HIT     → bid ≤ highest_bid - (ATR × 1.5)
3. BREAKEVEN_LOCK → highest_bid ≥ entry_ask + max(2, ATR × 1.0)  [fires once]
4. SCORE_FADE    → entry_score - current_score ≥ 0.15            [warning only]
5. TP_UPDATED    → normal bar, trail moved up                     [info only]
```

**Breakeven lock behavior:**
- Once `highest_bid ≥ entry_ask + max(2.0, ATR)`, the trail is floored at `entry_ask + 2.0`
- This means after a sufficient rally, the position can never close below entry (+ 2 THB buffer)

**Restart persistence (new):**
```python
# On BUY signal:
tp_manager.activate(...)
tp_manager.save_to_file()   # → writes tp_state.json to Src_V4/

# Every M10 bar while active:
tp_manager.update(...)
if tp_manager.is_active:
    tp_manager.save_to_file()   # keeps highest_bid current

# On orchestrator startup:
tp_manager.restore_from_file()   # reads tp_state.json, restores all fields

# On any SELL (forced or gate):
tp_manager.reset()   # → deletes tp_state.json
```

---

### 3.3 Orchestrator — Two Sell Paths (`scheduler/orchestrator.py`)

#### PATH A — Forced Exit (TRAIL_HIT / SL_HIT)

Triggered when `DynamicTPManager.update()` returns a terminal trigger.

**Correct write order (post-fix):**
```
Step 1: build_trade_payload("SELL")           ← SHAP bearish drivers
Step 2: prepend "🤖 Auto-Exit Trigger: ..."   ← adds context to rationale
Step 3: insert_signal(forced_sell_record)     ← DB record saved FIRST
Step 4: update_state(STATE_EMPTY)             ← DB state flipped AFTER insert
Step 5: set_state(STATE_EMPTY)               ← in-memory cache updated
Step 6: notify_sell_signal()                  ← Discord "SELL SIGNAL" message
Step 7: insert_bar_log(state_at_bar="HOLDING") ← always "HOLDING" (hardcoded)
Step 8: tp_manager.reset()                    ← clears state file
Step 9: return                                ← pipeline ends, no double-write
```

The forced exit record uses a unique ID: `tp_YYYYMMDD_HHMMSS_<hex6>` and stores `reject_reason = "FORCED_BY_TRAIL_HIT"` or `"FORCED_BY_SL_HIT"` for DB traceability.

#### PATH B — Gate SELL (organic)

Triggered when `signal_gate` returns `signal_type = "SELL"`.

```
Step 1: build_trade_payload("SELL")    ← SHAP bearish drivers (no auto-exit prefix)
Step 2: build_signal_record()          ← assembles DB record
Step 3: insert_signal()                ← DB write
Step 4: insert_bar_log()               ← bar data
Step 5: update_state(STATE_EMPTY)      ← DB state
Step 6: set_state(STATE_EMPTY)         ← in-memory cache
Step 7: tp_manager.reset()             ← ✅ fixed (was missing)
Step 8: notify_sell_signal()           ← Discord "SELL SIGNAL" message
```

---

### 3.4 Rationale Generator (`rationale/generator.py`)

Generates a human-readable explanation for every signal using SHAP values.

**For SELL signals:**
- Selects features with **negative SHAP values** (features pulling score DOWN = bearish evidence)
- Sorts by most negative first (strongest bearish driver first)
- Maps feature names to the `bearish_drivers` template dictionary
- Output format: `"[SELL] Model Strength: X%. Primary catalyst: ... Secondary: ... Action: Hitting the Bid price (XXXXX.XX THB)."`

**Model Strength** is sigmoid-normalized:
```python
strength = round(1 / (1 + math.exp(-ranker_score)) * 100, 2)
# score = 0.0 → 50.0% (neutral)
# score = 1.0 → 73.1% (bullish)
# score = -1.0 → 26.9% (bearish)
```

**Fallback behavior:**
- Invalid `signal_type` → forced to `"HOLD"`
- All SHAP values = 0 → generic text, action set to HOLD

---

### 3.5 DB Writer (`db/supabase_writer.py`)

Handles all Supabase writes with retry and fallback.

**`_safe_upsert()` — used for signals and bar logs:**
```
Attempt 1 → if fail, wait 1s
Attempt 2 → if fail, wait 2s
Attempt 3 → if fail, write to fallback/pending_inserts.jsonl
```

**`update_state()` — used for state transitions:**
```
Attempt 1 → if fail, wait 1s
Attempt 2 → if fail, wait 2s
Attempt 3 → log error + RAISE  ← ensures caller knows state was not persisted
```

**`DRY_RUN=true`** — all write operations are no-ops (log only). Used for testing.

---

### 3.6 Discord Notifier (`notifier/discord_notifier.py`)

**SELL signal message format:**
```
🔴 SELL SIGNAL — `bar_time`
Session   : Open
Score     : 0.0400
HSH Bid   : 40,015.00 THB  ← exit price
XAU/USD   : 2300.00
📉 Rationale: [SELL] Model Strength: 51.0%. Primary: ...
```

**Forced exit sends two Discord messages:**
1. `notify_dynamic_tp()` → immediate `"🔴 DYNAMIC EXIT TRIGGERED"` alert
2. `notify_sell_signal()` → full SELL message with Auto-Exit rationale prepended

**All messages are prefixed with `🧪 [DRY RUN]`** when `DRY_RUN=true`.

---

## 4. Sell Signal I/O — Input/Output Tables

### Gate SELL (Path B)

| Stage | Key | Value |
|-------|-----|-------|
| **INPUT** | `ranker_score` | must be `< 0.07` |
| | `F_XAU_Noise_Ratio` | must be `< 2.5` |
| | `session` | must be `!= "Closed"` |
| | `current_state` | must be `"HOLDING"` |
| **GATE OUTPUT** | `signal_type` | `"SELL"` |
| | `passed` | `True` |
| | `hsh_bid` | `features_row["hsh_close_bid"]` |
| **RATIONALE** | `execution_price` | `current_bid` |
| | SHAP direction | negative values → `bearish_drivers` |
| **DB** | `v3_signals` | `signal_type="SELL"`, `passed=True`, `state_before="HOLDING"` |
| | `v3_bar_logs` | all market data |
| | `v3_system_state` | `current_position = "EMPTY"` |
| **DISCORD** | `notify_sell_signal()` | 🔴 SELL message |

### Forced Exit SELL (Path A)

| Stage | Key | Value |
|-------|-----|-------|
| **INPUT** | `tp_manager.update()` | returns `TRAIL_HIT` or `SL_HIT` |
| | `exit_bid_price` | `features_row["hsh_close_bid"]` |
| **DISCORD #1** | `notify_dynamic_tp()` | Immediate exit alert |
| **RATIONALE** | `rationale_text` prefix | `"🤖 Auto-Exit Trigger: {reason} @ {bid} THB"` |
| **DB** | `v3_signals` | `id=tp_*`, `reject_reason="FORCED_BY_TRAIL_HIT"` |
| | `v3_bar_logs` | `state_at_bar = "HOLDING"` (hardcoded) |
| | `v3_system_state` | `current_position = "EMPTY"` |
| **DISCORD #2** | `notify_sell_signal()` | 🔴 SELL message with Auto-Exit rationale |

### HOLD (Gate Blocked)

| Stage | Key | Value |
|-------|-----|-------|
| **INPUT** | score ≥ 0.07 while HOLDING, OR noise fails, OR market closed | |
| **GATE OUTPUT** | `signal_type` | `"HOLD"` |
| | `passed` | `False` |
| | `reject_reason` | `"score_below_threshold"` / `"noise_gate"` / `"market_open"` |
| **DB** | `v3_signals` | `signal_type="HOLD"`, `passed=False` |
| **DISCORD** | — | No notification sent |

---

## 5. Bugs Found & Fixes Applied

### I-1 🔴 Critical — Gate SELL didn't reset TP Manager

**Problem:** After an organic Gate SELL, `tp_manager.reset()` was never called. The TP manager stayed `is_active=True`. On the very next M10 bar (now in BUY context, state=EMPTY), `update()` still ran against the old entry price — potentially firing a ghost `TRAIL_HIT` or `SL_HIT` when no position was open.

**Fix (`orchestrator.py`):**
```python
# Before fix:
elif signal_type == "SELL":
    update_state(STATE_EMPTY)
    set_state(STATE_EMPTY)
    notify_sell_signal(gate_result, rationale_payload)

# After fix:
elif signal_type == "SELL":
    update_state(STATE_EMPTY)
    set_state(STATE_EMPTY)
    tp_manager.reset()  # ✅ clears state file, prevents ghost exit
    notify_sell_signal(gate_result, rationale_payload)
```

---

### I-2 🔴 Critical — TP State Lost on Restart

**Problem:** `DynamicTPManager` was a pure in-memory object. If the orchestrator crashed or was restarted while a position was open (`STATE_HOLDING`), `tp_manager` re-initialized to `is_active=False`. The trailing stop and SL would NOT fire until a new BUY was processed — meaning an open live position had zero automated protection.

**Fix (`dynamic_tp_manager.py`):** Added full file-based persistence:
```python
# New methods added to DynamicTPManager:
def to_dict(self) -> dict: ...         # snapshot all 6 state fields
def save_to_file(self) -> None: ...    # write JSON to Src_V4/tp_state.json
def restore_from_file(self) -> bool: ... # read JSON, restore all fields
def _clear_state_file(self) -> None: ... # delete file on reset

# reset() now auto-clears the file:
def reset(self) -> None:
    ...
    self._clear_state_file()  # ✅ remove persisted state on position close
```

**Fix (`orchestrator.py`):** Integrated save/restore calls:
```python
# At module load — restore on restart:
_tp_restored = tp_manager.restore_from_file()
if _tp_restored:
    system_log.info("[TP] ✅ TP state recovered from disk")

# After BUY activate — save entry state:
tp_manager.activate(...)
tp_manager.save_to_file()  # ✅ persist entry_ask, sl_price

# After every update while active — save updated highest_bid:
tp_manager.update(...)
if tp_manager.is_active:
    tp_manager.save_to_file()  # ✅ keeps trail current
```

**Fix (`dynamic_tp_manager.py`):** Used absolute path to avoid CWD dependency:
```python
# Before:
_TP_STATE_FILE = "tp_state.json"

# After:
_TP_STATE_FILE = str(Path(__file__).parent.parent / "tp_state.json")
# Always resolves to Src_V4/tp_state.json regardless of launch directory
```

---

### I-3 🟠 Medium — Dead Code in HOLD Rationale (`"LONG"` never matched)

**Problem:** The HOLD rationale branch checked `_state == "LONG"` to select the "Maintaining current long position" wording. But the system sends `state_before = "HOLDING"`, so this condition **never matched**. Every HOLD-while-HOLDING signal showed a generic fallback message instead of the correct wording.

**Fix (`rationale/generator.py`):**
```python
# Before (dead code):
if _state == "LONG":
    spread_action = "Maintaining current long position..."
elif _state == "SHORT":
    spread_action = "Maintaining current short position..."

# After (correct match):
if _state == "HOLDING":   # ✅ matches what orchestrator sends
    spread_action = "Maintaining current long position..."
# "SHORT" branch removed — system is long-only
```

---

### I-4 🟠 Medium — `update_state()` Silently Swallowed Failures

**Problem:** `update_state()` only had a bare `except → logger.error`. If the Supabase state write failed, DB state stayed `HOLDING` while in-memory state (via `set_state`) became `EMPTY`. On the next bar, the system would read `HOLDING` from DB and attempt another SELL cycle — potentially creating duplicate SELL records.

**Fix (`db/supabase_writer.py`):**
```python
# Before — single attempt, silent failure:
try:
    client.table("v3_system_state").update(...).execute()
except Exception as e:
    logger.error(f"Failed: {e}")   # ← swallowed, no raise

# After — 3 retries + raise on final failure:
for attempt in range(3):
    try:
        client.table("v3_system_state").update(...).execute()
        logger.info(f"[DB] ✅ State updated → {new_state}")
        return
    except Exception as e:
        logger.warning(f"[DB] ⚠️ update_state attempt {attempt+1} failed: {e}")
        if attempt == 2:
            logger.error(f"[DB] ❌ update_state failed after 3 attempts: {e}")
            raise   # ✅ propagate to orchestrator → logged + Discord error alert
        time.sleep(2 ** attempt)
```

---

### I-5 🟠 Medium — Forced Exit Bar Log Used Wrong State

**Problem:** The forced exit path passed `gate_result["state_before"]` to `insert_bar_log`. In a clean run this would be `"HOLDING"`. But on a restart edge case where the gate evaluated while state was somehow `"EMPTY"`, the bar log would record the wrong state, corrupting post-trade analysis.

**Fix (`orchestrator.py`):**
```python
# Before:
"state_at_bar": gate_result["state_before"],   # ← could be wrong

# After:
"state_at_bar": "HOLDING",   # ✅ forced exit ALWAYS exits from HOLDING
```

---

### I-6 🟠 Medium — State Flipped Before `insert_signal` in Forced Exit

**Problem:** The forced exit path called `update_state(STATE_EMPTY)` and `set_state(STATE_EMPTY)` *before* `insert_signal()`. If the DB insert failed for any reason, the state was already flipped to EMPTY but no signal record existed. This meant a real exit would have no audit trail in the DB.

**Fix (`orchestrator.py`):** Reordered to insert first, then flip state:
```python
# Before (wrong order):
update_state(STATE_EMPTY)       # ← state flipped first
set_state(STATE_EMPTY)
...
insert_signal(forced_sell_record)   # ← if this fails, state is wrong and no record exists

# After (correct order):
insert_signal(forced_sell_record)   # ✅ DB record saved FIRST
update_state(STATE_EMPTY)           # ✅ state flipped AFTER record exists
set_state(STATE_EMPTY)
```

---

## 6. Pre-Deployment Checklist & Results

| # | Item | Result |
|---|------|--------|
| 1 | Fix `tp_state.json` relative path → absolute | ✅ Done |
| 2 | Run all sell scenario tests (5 scenarios) | ✅ All 5 PASSED |
| 3 | Add Scenario 5: Pure Gate SELL coverage | ✅ Added & PASSED |
| 4 | `.env` credentials confirmed valid | ✅ Confirmed |
| 5 | Verify `v3_system_state` table has `id=1` row | ✅ `current_position = 'EMPTY'` |
| 6 | Full pipeline DRY_RUN flow test | ✅ Correct (no live data on Sunday) |

---

## 7. Test Scenarios

All 5 scenarios in `test_sell_scenarios_dryrun.py` passed with Discord `HTTP 204` confirmations.

| Scenario | Exit Type | What It Verifies |
|----------|-----------|-----------------|
| 1: SL Hit | `SL_HIT` forced exit | Price gaps below SL → immediate exit |
| 2: Trailing Stop | `TRAIL_HIT` profitable | Price pumps then dumps below trail |
| 3: Breakeven Lock + Trail | `BREAKEVEN_LOCK` → `TRAIL_HIT` | Trail locks at entry+2 THB after rally |
| 4: Score Fade + Model Sell | `SCORE_FADE` → `MODEL_SELL_SIGNAL` | Score warning + explicit model SELL |
| 5: Pure Gate SELL *(new)* | `GATE_SELL_SIGNAL` | Score drops below 0.07, TP active but not triggering; `tp_manager.reset()` called ✅ |

**Scenario 5 output confirming I-1 fix:**
```
🚨 [EXIT SIGNAL] Position closed due to GATE_SELL_SIGNAL!
✅ [TP Reset] tp_manager.reset() called — I-1 fix verified
```

---

## 8. Remaining Low-Severity Notes

These do **not affect trading correctness or data integrity**:

| # | File | Note |
|---|------|------|
| L-1 | `dynamic_tp_manager.py` | Breakeven floor offset `2.0` THB hardcoded in two places — could be extracted to `settings.py` as `BE_FLOOR_OFFSET` |
| L-2 | `db/supabase_writer.py` | Fallback JSONL writer uses `datetime.utcnow()` — rest of system uses Bangkok TZ |
| L-3 | `discord_notifier.py` | `SCORE_FADE` alert has no disclaimer that no automatic exit occurred — could confuse users |

---

## Deployment

```bash
# From Src_V4/ directory, with DRY_RUN=false in .env:
python -m main

# Market coverage: Mon–Fri, 06:00–01:59 BKK (Asia/Bangkok)
# Job A: Signal pipeline — every M10 bar
# Job C: Heartbeat — every hour
```
