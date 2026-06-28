# Rich × Jom Integration Audit — BUY Manual Confirm vs SELL Dynamic TP

**Date:** 2026-05-11  
**Status:** All P1 patches applied ✅

---

## 1. Executive Summary

After reading all 15 files and both reference documents, the integration between Rich's BUY Manual Confirm logic and Jom's SELL/Dynamic TP logic has **3 real conflicts** and **2 misconceptions** that aren't actually bugs. All 3 real conflicts have now been patched in this session.

**Key Verdict:** The two sides are architecturally compatible. The only true friction points were the `update_state` double-write, missing `insert_signal` return checks, and `set_state()` lacking retry. All three are now fixed.

---

## 2. Architecture Contract (Rich BUY × Jom SELL)

### 2.1 Ownership Boundaries

| Component | Owner | Rule |
|-----------|-------|------|
| `signal_gate.py` → BUY decision | Jom (model/thresholds) + Rich (gate integration) | Rich cannot change thresholds |
| `signal_gate.py` → SELL decision | Jom | Rich cannot change SELL logic |
| `orchestrator.py` → BUY signal path | Rich | Must NOT set HOLDING or activate TP |
| `orchestrator.py` → SELL/Forced path | Jom (TP logic) + Rich (DB ordering/safety) | Rich ensures insert-first, Jom owns trigger logic |
| `confirm_trade_ui.py` | Rich | Full ownership |
| `dynamic_tp_manager.py` | Jom | Rich must NOT edit |
| `state_manager.py` | Rich (single writer) | `set_state()` is the ONLY function that writes `v3_system_state` |
| `supabase_writer.py` | Rich (DB helpers) | `update_state()` is **DEPRECATED** — kept only for backward compat, never called |
| `tp_state.json` | Jom (TP persistence) | Rich reads via `sync_tp_state_from_db()` as fallback only |

### 2.2 Data Contract

| Table | Purpose | Who Writes | Who Reads |
|-------|---------|-----------|-----------|
| `v3_system_state` | EMPTY/HOLDING flag | `set_state()` only (Rich) | Both sides via `get_current_state()` |
| `v3_signals` | Audit trail for all signals | Orchestrator (both BUY/SELL) + UI (manual SELL) | UI for pending BUY |
| `v3_active_trades` | Position ledger (OPEN/CLOSED) | `open_trade_from_signal()` (Rich via UI), `close_open_trade()` (both) | Sync/recovery only, NOT for SELL calc |
| `tp_state.json` | TP manager persistence on disk | Jom's TP manager (`save_to_file`) | Jom's TP manager (`restore_from_file`) |

### 2.3 State Machine Contract

```
EMPTY ──[BUY signal]──→ EMPTY + PENDING_CONFIRM signal
EMPTY ──[Confirm BUY]──→ HOLDING + OPEN trade + TP activate
HOLDING ──[Model SELL]──→ insert signal → close trade → EMPTY + TP reset
HOLDING ──[SL/TRAIL HIT]──→ insert forced signal → close trade → mark AUTO_EXITED → EMPTY + TP reset
HOLDING ──[Manual SELL]──→ insert manual signal → close trade → EMPTY
```

### 2.4 Critical Rules

1. **BUY signal ≠ HOLDING.** Only `confirm_buy()` in UI can set HOLDING.
2. **`active_trades` = ledger only.** SELL calculation lives in `DynamicTPManager` (memory + tp_state.json).
3. **Insert signal BEFORE close_open_trade.** FK constraint requires signal record to exist first.
4. **Check return values.** If `insert_signal` fails → abort. If `close_open_trade` fails → abort. Never set_state after a failed DB operation.
5. **Single state writer.** Only `set_state()` writes to `v3_system_state`. No `update_state()` calls.

---

## 3. Conflict Analysis

### 3.1 Real Conflicts (all now fixed ✅)

| # | Conflict | Was In | Impact | Fix Applied |
|---|----------|--------|--------|-------------|
| RC-1 | `update_state()` + `set_state()` double-write | orchestrator.py L291, L390 | DB written twice; if first raises, second never runs | Removed `update_state` import and all calls |
| RC-2 | `insert_signal` return unchecked in Model SELL | orchestrator.py L348 | SELL could close trade without audit trail | Added return check + abort if False |
| RC-3 | `set_state()` had no retry while `update_state()` had 3-retry | state_manager.py | After removing `update_state`, state writes could silently fail | Added 3-retry + raise to `set_state()` |

### 3.2 Non-Conflicts (things that look wrong but aren't)

| # | Apparent Issue | Why It's OK |
|---|---------------|-------------|
| NC-1 | `sync_tp_state_from_db()` reads `active_trades` | This is recovery-only (restart bridge), not SELL calculation. `active_trades` provides `entry_ask`, `entry_score`, `entry_bid_at_signal` to re-activate TP manager. SELL logic still runs entirely from TP manager's in-memory state |
| NC-2 | `update_state()` function still exists in `supabase_writer.py` | Function definition kept for backward compatibility. No code imports or calls it. `grep` confirms only comments reference it in `confirm_trade_ui.py`. Safe to delete later |

---

## 4. 15-Point Verification Checklist (Post-Patch)

| # | Question | Status | Evidence |
|---|----------|--------|----------|
| 1 | BUY signal sets HOLDING immediately? | ✅ **No** | orchestrator.py L366: only calls `notify_buy_signal()`, no `set_state` |
| 2 | BUY signal activates TP manager? | ✅ **No** | No `tp_manager.activate()` in BUY path |
| 3 | Confirm BUY partial fail → OPEN+EMPTY? | ✅ **Fixed** | confirm_trade_ui.py L152-169: forces HOLDING if trade opened |
| 4 | Model SELL insert fail → close trade? | ✅ **Fixed** | orchestrator.py now checks `ok_signal_insert` before close |
| 5 | Forced SELL insert fail → close trade? | ✅ **Already safe** | orchestrator.py L249: checks `ok_insert`, returns if False |
| 6 | close_open_trade fail → set EMPTY? | ✅ **Safe** | All 3 SELL paths check `ok_close` and return before `set_state` |
| 7 | TP active while state EMPTY? | ✅ **Protected** | `sync_tp_state_from_db()` resets TP if state=EMPTY (L86-90) |
| 8 | State HOLDING but no OPEN trade? | ✅ **Warned** | `sync_tp_state_from_db()` logs warning at L95 |
| 9 | tp_state.json conflicts with DB state? | ✅ **Resolved** | On startup: tp_state.json restored first, then `sync_tp_state_from_db()` on every bar overrides if DB disagrees |
| 10 | Double-write update_state+set_state? | ✅ **Fixed** | `update_state` removed from orchestrator import and all calls |
| 11 | Hardcoded table names? | ✅ **None** | All use `SIGNALS_TABLE`, `ACTIVE_TRADES_TABLE`, etc. from settings |
| 12 | Missing/unused imports? | ✅ **Clean** | `update_state` removed. Minor: `_get_supabase()` unused in UI (cosmetic) |
| 13 | Manual SELL has audit record? | ✅ **Yes** | confirm_trade_ui.py L200-227: creates `manual_sell_*` signal |
| 14 | active_trades used for SELL calc? | ✅ **No** | Only used as ledger + recovery. SELL calc = DynamicTPManager.update() |
| 15 | Jom SELL logic intact? | ✅ **Yes** | `dynamic_tp_manager.py` untouched. All methods present: `update()`, `save_to_file()`, `restore_from_file()`, `reset()`, `_clear_state_file()`. Triggers: SL_HIT, TRAIL_HIT, BREAKEVEN_LOCK, SCORE_FADE, TP_UPDATED |

---

## 5. File-by-File Changes Made

### 5.1 `core/state_manager.py` — P1-1

```diff:state_manager.py
import logging
from config.settings import (
    STATE_EMPTY,
    STATE_HOLDING,
    DRY_RUN,
    SUPABASE_URL,
    SUPABASE_KEY,
    SYSTEM_STATE_TABLE,
)
from supabase import create_client, Client

logger = logging.getLogger("trading")
_client: Client | None = None
_dry_run_state = STATE_EMPTY


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def get_current_state() -> str:
    """อ่านสถานะปัจจุบันจาก DB หรือ mock เป็น EMPTY ถ้า DRY_RUN"""
    if DRY_RUN:
        return _dry_run_state
    try:
        client = _get_client()
        res = (
            client
            .table(SYSTEM_STATE_TABLE)
            .select("current_position")
            .eq("id", 1)
            .execute()
        )

        if not res.data:
            raise RuntimeError(
                f"[State] {SYSTEM_STATE_TABLE} table is empty. Run init_state() first."
            )

        current_position = res.data[0]["current_position"]

        if current_position not in (STATE_EMPTY, STATE_HOLDING):
            raise RuntimeError(f"[State] Invalid current_position in DB: {current_position}")

        return current_position

    except Exception as e:
        logger.error(f"[State] Failed to read state from {SYSTEM_STATE_TABLE}: {e}")
        raise


def set_state(new_state: str) -> None:
    """อัปเดตสถานะ → EMPTY หรือ HOLDING"""
    if new_state not in (STATE_EMPTY, STATE_HOLDING):
        raise ValueError(f"[State] Invalid state: {new_state}")

    if DRY_RUN:
        global _dry_run_state
        _dry_run_state = new_state
        logger.info(f"[DRY_RUN] Would SET state → {new_state}")
        return

    try:
        client = _get_client()
        client.table(SYSTEM_STATE_TABLE).update({
            "current_position": new_state,
            "updated_at": "now()",
        }).eq("id", 1).execute()

        logger.info(f"[State] Updated → {new_state}")

    except Exception as e:
        logger.error(f"[State] Failed to update state in {SYSTEM_STATE_TABLE}: {e}")
        raise


def init_state(initial: str = STATE_EMPTY) -> None:
    """ตั้งค่า State ครั้งแรก หรือ Reset หลัง Manual Trade"""
    if initial not in (STATE_EMPTY, STATE_HOLDING):
        raise ValueError(f"[State] Invalid initial state: {initial}")

    if DRY_RUN:
        global _dry_run_state
        _dry_run_state = initial
        logger.info(f"[DRY_RUN] Would INIT state → {initial}")
        return

    try:
        client = _get_client()
        client.table(SYSTEM_STATE_TABLE).upsert({
            "id": 1,
            "current_position": initial,
        }, on_conflict="id").execute()

        logger.info(f"[State] Initialized → {initial}")

    except Exception as e:
        logger.error(f"[State] Failed to init state in {SYSTEM_STATE_TABLE}: {e}")
        raise
===
import time
import logging
from config.settings import (
    STATE_EMPTY,
    STATE_HOLDING,
    DRY_RUN,
    SUPABASE_URL,
    SUPABASE_KEY,
    SYSTEM_STATE_TABLE,
)
from supabase import create_client, Client

logger = logging.getLogger("trading")
_client: Client | None = None
_dry_run_state = STATE_EMPTY


def _get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


def get_current_state() -> str:
    """อ่านสถานะปัจจุบันจาก DB หรือ mock เป็น EMPTY ถ้า DRY_RUN"""
    if DRY_RUN:
        return _dry_run_state
    try:
        client = _get_client()
        res = (
            client
            .table(SYSTEM_STATE_TABLE)
            .select("current_position")
            .eq("id", 1)
            .execute()
        )

        if not res.data:
            raise RuntimeError(
                f"[State] {SYSTEM_STATE_TABLE} table is empty. Run init_state() first."
            )

        current_position = res.data[0]["current_position"]

        if current_position not in (STATE_EMPTY, STATE_HOLDING):
            raise RuntimeError(f"[State] Invalid current_position in DB: {current_position}")

        return current_position

    except Exception as e:
        logger.error(f"[State] Failed to read state from {SYSTEM_STATE_TABLE}: {e}")
        raise


def set_state(new_state: str) -> None:
    """
    อัปเดตสถานะ → EMPTY หรือ HOLDING

    Single state writer for the entire system.
    Uses 3-retry + raise on final failure to prevent silent state divergence.
    """
    if new_state not in (STATE_EMPTY, STATE_HOLDING):
        raise ValueError(f"[State] Invalid state: {new_state}")

    if DRY_RUN:
        global _dry_run_state
        _dry_run_state = new_state
        logger.info(f"[DRY_RUN] Would SET state → {new_state}")
        return

    for attempt in range(3):
        try:
            client = _get_client()
            client.table(SYSTEM_STATE_TABLE).update({
                "current_position": new_state,
                "updated_at": "now()",
            }).eq("id", 1).execute()

            logger.info(f"[State] ✅ Updated → {new_state}")
            return

        except Exception as e:
            logger.warning(f"[State] ⚠️ set_state attempt {attempt + 1} failed: {e}")
            if attempt == 2:
                logger.error(f"[State] ❌ set_state failed after 3 attempts: {e}")
                raise
            time.sleep(2 ** attempt)


def init_state(initial: str = STATE_EMPTY) -> None:
    """ตั้งค่า State ครั้งแรก หรือ Reset หลัง Manual Trade"""
    if initial not in (STATE_EMPTY, STATE_HOLDING):
        raise ValueError(f"[State] Invalid initial state: {initial}")

    if DRY_RUN:
        global _dry_run_state
        _dry_run_state = initial
        logger.info(f"[DRY_RUN] Would INIT state → {initial}")
        return

    try:
        client = _get_client()
        client.table(SYSTEM_STATE_TABLE).upsert({
            "id": 1,
            "current_position": initial,
        }, on_conflict="id").execute()

        logger.info(f"[State] Initialized → {initial}")

    except Exception as e:
        logger.error(f"[State] Failed to init state in {SYSTEM_STATE_TABLE}: {e}")
        raise
```

**What changed:** `set_state()` now has 3-retry loop with exponential backoff + raise on final failure, matching `update_state()` safety level.

### 5.2 `scheduler/orchestrator.py` — P1-2 + P1-3

```diff:orchestrator.py
import logging
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
from config.settings import TIMEZONE, DRY_RUN, STATE_EMPTY, STATE_HOLDING
from config.settings import TP_ATR_MULTIPLIER, TP_BREAKEVEN_ATR_MULT, TP_SCORE_DROP_THRESH
from core.candle_builder import build_candles
from core.feature_engine import compute_features
from core.model_inference import run_inference
from core.signal_gate import evaluate_signal_gate
from core.signal_recorder import build_signal_record
from core.state_manager import get_current_state, set_state
from core.dynamic_tp_manager import DynamicTPManager
from db.supabase_writer import insert_signal, insert_bar_log, update_state
from notifier.discord_notifier import notify_buy_signal, notify_sell_signal, notify_heartbeat, notify_error, notify_dynamic_tp
from rationale.generator import build_trade_payload

TZ = pytz.timezone(TIMEZONE)
system_log  = logging.getLogger("system")
trading_log = logging.getLogger("trading")

_last_bar_time : str   = "N/A"
_last_score    : float = 0.0
_last_state    : str   = STATE_EMPTY

tp_manager = DynamicTPManager(
    atr_multiplier=TP_ATR_MULTIPLIER,
    breakeven_atr_mult=TP_BREAKEVEN_ATR_MULT,
    score_drop_threshold=TP_SCORE_DROP_THRESH
)

def run_signal_pipeline() -> None:
    global _last_bar_time, _last_score, _last_state
    now = datetime.now(TZ)
    system_log.info(f"[Job A] Pipeline started at {now.strftime('%H:%M:%S')}")
    try:
        candles_df = build_candles()
        features_row = compute_features(candles_df)
        if features_row["session"] == "Closed":
            system_log.info("[Job A] Market closed — skipping")
            return

        inference_result = run_inference(features_row)
        _last_bar_time = features_row["bar_time"]
        _last_score    = inference_result["ranker_score"]
        gate_result    = evaluate_signal_gate(inference_result, features_row)
        _last_state    = gate_result["state_before"]

        # ─── 🆕 TP Manager: Activate / Reset ─────────────────────────────────
        if gate_result["passed"]:
            if gate_result["signal_type"] == "BUY":
                sl_price = gate_result["hsh_ask"] - (features_row["F_ATR_48"] * 1.0)
                tp_manager.activate(
                    entry_ask=gate_result["hsh_ask"],
                    entry_score=gate_result["ranker_score"],
                    initial_bid=gate_result["hsh_bid"],
                    sl_price=sl_price
                )
            elif gate_result["signal_type"] == "SELL":
                tp_manager.reset()

        # ─── 🆕 TP Manager: Evaluate every M10 bar ───────────────────────────
        tp_trigger, tp_price, trail_level = tp_manager.update(
            current_bid=features_row["hsh_close_bid"],
            atr_48=features_row["F_ATR_48"],
            current_score=inference_result["ranker_score"]
        )
        if tp_trigger != "NONE":
            notify_dynamic_tp(tp_trigger, tp_price, trail_level, inference_result["ranker_score"], features_row["F_ATR_48"])

        # 🚨 FORCED EXIT LOGIC (SL Hit หรือ Trail Hit)
        if tp_trigger in ("TRAIL_HIT", "SL_HIT"):
            reason_text = "Trailing Stop Hit" if tp_trigger == "TRAIL_HIT" else "Stop Loss Hit"
            exit_bid_price = features_row["hsh_close_bid"]  # ✅ ใช้ Bid Price เป็นจุดออก
            system_log.info(f"[TP] {reason_text} @ {exit_bid_price:.2f}. Forcing SELL signal.")

            # 1. Override State → EMPTY
            update_state(STATE_EMPTY)
            set_state(STATE_EMPTY)

            # 2. บันทึก Forced SELL Record
            forced_signal_id = f"tp_{features_row['bar_time'][:19].replace('-','').replace(':','').replace('T','_')}"
            forced_sell_record = {
                "id"            : forced_signal_id,
                "bar_time"      : features_row["bar_time"],
                "session"       : features_row["session"],
                "signal_type"   : "SELL",
                "ranker_score"  : inference_result["ranker_score"],
                "state_before"  : "HOLDING",
                "hsh_ask_price" : features_row["hsh_close_ask"],
                "hsh_bid_price" : exit_bid_price,
                "xau_price"     : features_row["xau_close"],
                "atr_at_signal" : features_row["F_ATR_48"],
                "passed"        : True,
                "reject_reason" : f"FORCED_BY_{tp_trigger}",
                "dry_run"       : DRY_RUN,
                "features_snap" : inference_result["features_snap"],
                "created_at"    : datetime.now(TZ).isoformat(),
            }
            insert_signal(forced_sell_record)

            # 3. ✅ ใช้ Template Rationale เดิม + เติมเหตุผล Auto-Exit
            rationale_payload = build_trade_payload(
                signal_type   = "SELL",
                ranker_score  = inference_result["ranker_score"],
                shap_values   = inference_result.get("shap_values", {}),
                feature_names = inference_result.get("feature_names", []),
                current_ask   = features_row["hsh_close_ask"],
                current_bid   = exit_bid_price,
            )
            rationale_payload["rationale_text"] = (
                f"🤖 **Auto-Exit Trigger:** {reason_text} @ `{exit_bid_price:,.2f}` THB\n"
                f"{rationale_payload.get('rationale_text', '')}"
            )
            rationale_payload["execution_price"] = exit_bid_price

            # 4. แจ้ง Discord ผ่านโครงสร้างเดิม
            forced_gate_result = {
                "bar_time"      : features_row["bar_time"],
                "session"       : features_row["session"],
                "ranker_score"  : inference_result["ranker_score"],
                "hsh_bid"       : exit_bid_price,
                "xau_close"     : features_row["xau_close"]
            }
            notify_sell_signal(forced_gate_result, rationale_payload)

            # 5. Reset TP Manager & จบ Pipeline (กัน Duplicate)
            tp_manager.reset()
            trading_log.info(f"FORCED SELL executed by {tp_trigger} | Bid Price: {exit_bid_price:.2f}")
            return  # 🔚 จบรอบนี้ทันที

        # ─── P5: Build Signal Record ──────────────────────────────────────────
        rationale_payload = build_trade_payload(
            signal_type   = gate_result["signal_type"],
            ranker_score  = inference_result["ranker_score"],
            shap_values   = inference_result.get("shap_values", {}),
            feature_names = inference_result.get("feature_names", []),
            current_ask   = gate_result["hsh_ask"],
            current_bid   = gate_result["hsh_bid"],
        )
        signal_record = build_signal_record(gate_result, rationale_payload)

        # ─── P6: Write to Supabase ────────────────────────────────────────────
        insert_signal(signal_record)
        insert_bar_log({
            "bar_time"      : features_row["bar_time"],
            "session"       : features_row["session"],
            "state_at_bar"  : gate_result["state_before"],
            "ranker_score"  : inference_result["ranker_score"],
            "signal_passed" : gate_result["passed"],
            "signal_type"   : gate_result["signal_type"],
            "hsh_close_ask" : features_row["hsh_close_ask"],
            "hsh_close_bid" : features_row["hsh_close_bid"],
            "atr_48"        : features_row["F_ATR_48"],
            "features_snap" : signal_record["features_snap"],
        })

        # ─── Action & State Update ────────────────────────────────────────────
        if gate_result["passed"] and gate_result["signal_type"]:
            signal_type = gate_result["signal_type"]
            if signal_type == "BUY":
                update_state(STATE_HOLDING)
                set_state(STATE_HOLDING)
                notify_buy_signal(gate_result, rationale_payload)
                trading_log.info(f"BUY signal sent | score={_last_score:.4f}")
            elif signal_type == "SELL":
                update_state(STATE_EMPTY)
                set_state(STATE_EMPTY)
                notify_sell_signal(gate_result, rationale_payload)
                trading_log.info(f"SELL signal sent | score={_last_score:.4f}")
        else:
            trading_log.info(f"HOLD | state={_last_state} | score={_last_score:.4f} | reject={gate_result['reject_reason']}")

    except Exception as e:
        system_log.error(f"[Job A] Pipeline error: {e}", exc_info=True)
        notify_error("Job A — signal_pipeline", str(e))

def run_heartbeat() -> None:
    try:
        state = get_current_state()
        _last_state = state
        notify_heartbeat(state, _last_bar_time, _last_score)
        system_log.info(f"[Job C] Heartbeat sent | state={state}")
    except Exception as e:
        system_log.warning(f"[Job C] Heartbeat error: {e}")

def start_scheduler() -> None:
    scheduler = BlockingScheduler(timezone=TZ)
    scheduler.add_job(run_signal_pipeline, CronTrigger(minute="0,10,20,30,40,50", hour="0,1,6-23", day_of_week="mon-fri", timezone=TZ), id="signal_pipeline", name="M10 Signal Pipeline", max_instances=1, misfire_grace_time=60)
    scheduler.add_job(run_heartbeat, CronTrigger(minute=0, hour="0,1,6-23", day_of_week="mon-fri", timezone=TZ), id="heartbeat", name="System Heartbeat")
    system_log.info(f"Scheduler started | DRY_RUN={DRY_RUN} | Coverage: 06:00-01:59 BKK")
    scheduler.start()
===
import logging
import uuid
from datetime import datetime

# pyrefly: ignore [missing-import]
from apscheduler.schedulers.blocking import BlockingScheduler
# pyrefly: ignore [missing-import]
from apscheduler.triggers.cron import CronTrigger
import pytz

from config.settings import TIMEZONE, DRY_RUN, STATE_EMPTY, STATE_HOLDING
from config.settings import (
    TP_ATR_MULTIPLIER,
    TP_BREAKEVEN_ATR_MULT,
    TP_SCORE_DROP_THRESH,
    TP_SL_ATR_MULT,
)
from core.candle_builder import build_candles
from core.feature_engine import compute_features
from core.model_inference import run_inference
from core.signal_gate import evaluate_signal_gate
from core.signal_recorder import build_signal_record
from core.state_manager import get_current_state, set_state
from core.dynamic_tp_manager import DynamicTPManager
from db.supabase_writer import (
    insert_signal,
    insert_bar_log,
    get_open_trade,
    close_open_trade,
    mark_signal_execution,
)
from notifier.discord_notifier import (
    notify_buy_signal,
    notify_sell_signal,
    notify_heartbeat,
    notify_error,
    notify_dynamic_tp,
)
from rationale.generator import build_trade_payload

TZ = pytz.timezone(TIMEZONE)
system_log = logging.getLogger("system")
trading_log = logging.getLogger("trading")

_last_bar_time: str = "N/A"
_last_score: float = 0.0
_last_state: str = STATE_EMPTY

tp_manager = DynamicTPManager(
    atr_multiplier=TP_ATR_MULTIPLIER,
    breakeven_atr_mult=TP_BREAKEVEN_ATR_MULT,
    score_drop_threshold=TP_SCORE_DROP_THRESH,
)

# Jom logic: recover in-memory TP state from disk if DynamicTPManager supports it.
# Rich logic still keeps DB active_trade as the source of truth for manual-confirm entries.
try:
    if hasattr(tp_manager, "restore_from_file"):
        _tp_restored = tp_manager.restore_from_file()
        if _tp_restored:
            system_log.info("[TP] ✅ TP state recovered from disk — restart protection active.")
except Exception as e:
    system_log.warning(f"[TP] TP state restore from disk skipped: {e}")


def _save_tp_state_if_supported() -> None:
    """Persist TP state only when the current DynamicTPManager implementation supports it."""
    try:
        if hasattr(tp_manager, "save_to_file") and tp_manager.is_active:
            tp_manager.save_to_file()
    except Exception as e:
        trading_log.warning(f"[TP] save_to_file skipped: {e}")


def sync_tp_state_from_db(features_row: dict | None = None) -> None:
    """
    Rich manual-confirm bridge:
    - If DB state is EMPTY, TP manager must not remain active.
    - If DB state is HOLDING but TP manager is inactive, recover from v3_active_trades.

    This keeps manual-confirm active_trade compatible with Jom's TP manager persistence.
    """
    state = get_current_state()

    if state == STATE_EMPTY:
        if tp_manager.is_active:
            tp_manager.reset()
            trading_log.info("[TP Sync] Reset TP manager because DB state is EMPTY")
        return

    if state == STATE_HOLDING and not tp_manager.is_active:
        active_trade = get_open_trade()
        if not active_trade:
            trading_log.warning("[TP Sync] DB state HOLDING but no OPEN active trade found")
            return

        entry_ask = float(active_trade["entry_ask"])
        entry_score = float(active_trade["entry_score"])
        initial_bid = float(active_trade.get("entry_bid_at_signal") or entry_ask)

        atr_48 = None
        if features_row:
            atr_48 = features_row.get("F_ATR_48")

        sl_price = None
        if atr_48 and float(atr_48) > 0:
            sl_price = entry_ask - (float(atr_48) * TP_SL_ATR_MULT)

        tp_manager.activate(
            entry_ask=entry_ask,
            entry_score=entry_score,
            initial_bid=initial_bid,
            sl_price=sl_price,
        )
        _save_tp_state_if_supported()
        trading_log.info("[TP Sync] TP manager activated from active trade")


def run_signal_pipeline() -> None:
    global _last_bar_time, _last_score, _last_state

    now = datetime.now(TZ)
    system_log.info(f"[Job A] Pipeline started at {now.strftime('%H:%M:%S')}")

    try:
        candles_df = build_candles()
        features_row = compute_features(candles_df)

        if features_row["session"] == "Closed":
            system_log.info("[Job A] Market closed — skipping")
            return

        inference_result = run_inference(features_row)
        _last_bar_time = features_row["bar_time"]
        _last_score = inference_result["ranker_score"]

        gate_result = evaluate_signal_gate(inference_result, features_row)
        _last_state = gate_result["state_before"]

        # ─── TP Manager: sync manual-confirm DB state and evaluate only while HOLDING ───
        current_state = get_current_state()
        sync_tp_state_from_db(features_row)
        current_state = get_current_state()

        tp_trigger, tp_price, trail_level = "NONE", None, 0.0

        if current_state == STATE_HOLDING and tp_manager.is_active:
            tp_trigger, tp_price, trail_level = tp_manager.update(
                current_bid=features_row["hsh_close_bid"],
                atr_48=features_row["F_ATR_48"],
                current_score=inference_result["ranker_score"],
            )
            _save_tp_state_if_supported()

            trading_log.info(
                f"[POSITION] 🟢 ACTIVE "
                f"| Bid: {features_row['hsh_close_bid']:,.2f} "
                f"| Trail: {trail_level:,.2f} "
                f"| SL: {(tp_manager.sl_price or 0):,.2f} "
                f"| Score: {inference_result['ranker_score']:.4f}"
            )

            if tp_trigger == "BREAKEVEN_LOCK":
                trading_log.info(
                    f"[TP EVENT] 🔒 Breakeven Locked! "
                    f"Trail floored at {(tp_price or 0):,.2f} THB — downside risk removed."
                )
            elif tp_trigger == "TP_UPDATED":
                trading_log.info(
                    f"[TP EVENT] 📈 Trailing Stop ratcheted up to {trail_level:,.2f} THB"
                )
            elif tp_trigger == "SCORE_FADE":
                trading_log.warning(
                    f"[TP EVENT] ⚠️ Score Fading "
                    f"({inference_result['ranker_score']:.4f}) — "
                    f"Trail at {trail_level:,.2f} THB. Watch for organic exit."
                )

            if tp_trigger != "NONE":
                notify_dynamic_tp(
                    tp_trigger,
                    tp_price,
                    trail_level,
                    inference_result["ranker_score"],
                    features_row["F_ATR_48"],
                )

        # 🚨 FORCED EXIT LOGIC: SL Hit / Trail Hit
        if tp_trigger in ("TRAIL_HIT", "SL_HIT"):
            if current_state != STATE_HOLDING or not tp_manager.is_active:
                trading_log.warning(
                    f"[TP] Ignored {tp_trigger} because state={current_state}, "
                    f"tp_active={tp_manager.is_active}"
                )
                return

            reason_text = "Trailing Stop Hit" if tp_trigger == "TRAIL_HIT" else "Stop Loss Hit"
            exit_bid_price = features_row["hsh_close_bid"]
            forced_signal_id = (
                f"tp_{features_row['bar_time'][:19].replace('-', '').replace(':', '').replace('T', '_')}_"
                f"{uuid.uuid4().hex[:6]}"
            )

            system_log.info(
                f"[TP] {reason_text} @ {exit_bid_price:.2f}. Forcing SELL signal."
            )

            # 1. Build rationale first so DB record contains explanation.
            rationale_payload = build_trade_payload(
                signal_type="SELL",
                ranker_score=inference_result["ranker_score"],
                shap_values=inference_result.get("shap_values", []),
                feature_names=inference_result.get("feature_names", []),
                current_ask=features_row["hsh_close_ask"],
                current_bid=exit_bid_price,
                state_before=STATE_HOLDING,
            )
            rationale_payload["rationale_text"] = (
                f"🤖 **Auto-Exit Trigger:** {reason_text} @ `{exit_bid_price:,.2f}` THB\n\n"
                f"{rationale_payload.get('rationale_text', '')}"
            )
            rationale_payload["execution_price"] = exit_bid_price

            # 2. Insert forced SELL signal first.
            # Required for audit trail and for active_trade.exit_signal_id FK.
            forced_sell_record = {
                "id": forced_signal_id,
                "bar_time": features_row["bar_time"],
                "session": features_row["session"],
                "signal_type": "SELL",
                "ranker_score": inference_result["ranker_score"],
                "state_before": STATE_HOLDING,
                "hsh_ask_price": features_row["hsh_close_ask"],
                "hsh_bid_price": exit_bid_price,
                "xau_price": features_row["xau_close"],
                "atr_at_signal": features_row["F_ATR_48"],
                "passed": True,
                "reject_reason": f"FORCED_BY_{tp_trigger}",
                "dry_run": DRY_RUN,
                "features_snap": inference_result["features_snap"],
                "rationale_text": rationale_payload.get("rationale_text"),
                "top_shap_features": rationale_payload.get("top_shap_features", {}),
                "created_at": datetime.now(TZ).isoformat(),
                "execution_status": "PENDING_AUTO_EXIT",
            }

            ok_insert = insert_signal(forced_sell_record)
            if not ok_insert:
                trading_log.error(
                    f"[TP] Failed to insert forced SELL signal {forced_signal_id}. "
                    f"State was NOT changed."
                )
                notify_error(
                    "Forced SELL",
                    f"Failed to insert forced SELL signal {forced_signal_id}. State was NOT changed.",
                )
                return

            # 3. Close active trade after forced SELL signal exists.
            ok_close = close_open_trade(
                exit_signal_id=forced_signal_id,
                exit_bid=exit_bid_price,
                exit_score=inference_result["ranker_score"],
                reason=tp_trigger,
            )
            if not ok_close:
                trading_log.error(
                    f"[TP] Failed to close active trade for {tp_trigger}. "
                    f"State was NOT changed. Bid={exit_bid_price:.2f}"
                )
                notify_error(
                    "Forced SELL",
                    f"Failed to close active trade for {tp_trigger}. State was NOT changed.",
                )
                return

            ok_mark = mark_signal_execution(
                forced_signal_id,
                "AUTO_EXITED",
                exit_bid_price,
                note=tp_trigger,
            )
            if not ok_mark:
                trading_log.warning(
                    f"[TP] Forced SELL closed trade but failed to mark signal "
                    f"{forced_signal_id} as AUTO_EXITED"
                )

            # 4. Flip state after signal exists and active trade is closed.
            set_state(STATE_EMPTY)

            # 5. Forced exit bar log. Forced exit always exits from HOLDING.
            insert_bar_log({
                "bar_time": features_row["bar_time"],
                "session": features_row["session"],
                "state_at_bar": STATE_HOLDING,
                "ranker_score": inference_result["ranker_score"],
                "signal_passed": True,
                "signal_type": "SELL",
                "hsh_close_ask": features_row["hsh_close_ask"],
                "hsh_close_bid": exit_bid_price,
                "atr_48": features_row["F_ATR_48"],
                "features_snap": inference_result["features_snap"],
            })

            # 6. Notify and reset.
            forced_gate_result = {
                "bar_time": features_row["bar_time"],
                "session": features_row["session"],
                "ranker_score": inference_result["ranker_score"],
                "hsh_bid": exit_bid_price,
                "xau_close": features_row["xau_close"],
            }
            notify_sell_signal(forced_gate_result, rationale_payload)

            tp_manager.reset()
            trading_log.warning(
                f"\n{'=' * 60}\n"
                f"  🚨 [EXIT] FORCED SELL — {tp_trigger}\n"
                f"  Bid Price : {exit_bid_price:,.2f} THB\n"
                f"  Score     : {inference_result['ranker_score']:.4f}\n"
                f"  Bar Time  : {features_row['bar_time']}\n"
                f"{'=' * 60}"
            )
            return

        # ─── P5: Build Signal Record ──────────────────────────────────────────
        rationale_payload = build_trade_payload(
            signal_type=gate_result["signal_type"],
            ranker_score=inference_result["ranker_score"],
            shap_values=inference_result.get("shap_values", {}),
            feature_names=inference_result.get("feature_names", []),
            current_ask=gate_result["hsh_ask"],
            current_bid=gate_result["hsh_bid"],
            state_before=gate_result["state_before"],
        )
        signal_record = build_signal_record(gate_result, rationale_payload)

        if gate_result["passed"] and gate_result["signal_type"] == "BUY":
            # Rich manual-confirm: BUY signal does not change state yet.
            signal_record["execution_status"] = "PENDING_CONFIRM"
        elif gate_result["passed"] and gate_result["signal_type"] == "SELL":
            signal_record["execution_status"] = "CONFIRMED"

        # ─── P6: Write to Supabase ────────────────────────────────────────────
        ok_signal_insert = insert_signal(signal_record)
        insert_bar_log({
            "bar_time": features_row["bar_time"],
            "session": features_row["session"],
            "state_at_bar": gate_result["state_before"],
            "ranker_score": inference_result["ranker_score"],
            "signal_passed": gate_result["passed"],
            "signal_type": gate_result["signal_type"],
            "hsh_close_ask": features_row["hsh_close_ask"],
            "hsh_close_bid": features_row["hsh_close_bid"],
            "atr_48": features_row["F_ATR_48"],
            "features_snap": signal_record["features_snap"],
        })

        # ─── Action & State Update ────────────────────────────────────────────
        if gate_result["passed"] and gate_result["signal_type"]:
            signal_type = gate_result["signal_type"]

            if signal_type == "BUY":
                # Manual confirm mode: do not set HOLDING here.
                notify_buy_signal(gate_result, rationale_payload)
                signal_id = signal_record.get("id", gate_result.get("signal_id", "UNKNOWN"))
                trading_log.info(
                    f"BUY signal sent — WAITING_CONFIRM | score={_last_score:.4f} | signal_id={signal_id}"
                )

            elif signal_type == "SELL":
                if not ok_signal_insert:
                    trading_log.error(
                        "[SELL] insert_signal failed — aborting SELL. "
                        "State was NOT changed."
                    )
                    notify_error(
                        "Model SELL",
                        "Failed to insert SELL signal. State was NOT changed.",
                    )
                    return

                # Signal exists in DB → FK-safe to close active trade.
                ok_close = close_open_trade(
                    exit_signal_id=signal_record.get("id"),
                    exit_bid=gate_result["hsh_bid"],
                    exit_score=inference_result["ranker_score"],
                    reason="MODEL_SELL",
                )
                if not ok_close:
                    trading_log.error("[SELL] Failed to close active trade. State was NOT changed.")
                    notify_error(
                        "Model SELL",
                        "Failed to close active trade. State was NOT changed.",
                    )
                    return

                set_state(STATE_EMPTY)
                tp_manager.reset()
                notify_sell_signal(gate_result, rationale_payload)
                trading_log.info(f"SELL signal sent | score={_last_score:.4f}")

        else:
            trading_log.info(
                f"HOLD | state={_last_state} | score={_last_score:.4f} "
                f"| reject={gate_result.get('reject_reason')}"
            )

    except Exception as e:
        system_log.error(f"[Job A] Pipeline error: {e}", exc_info=True)
        notify_error("Job A — signal_pipeline", str(e))


def run_heartbeat() -> None:
    global _last_state
    try:
        state = get_current_state()
        _last_state = state
        notify_heartbeat(state, _last_bar_time, _last_score)
        system_log.info(f"[Job C] Heartbeat sent | state={state}")
    except Exception as e:
        system_log.warning(f"[Job C] Heartbeat error: {e}")


def start_scheduler() -> None:
    scheduler = BlockingScheduler(timezone=TZ)
    scheduler.add_job(
        run_signal_pipeline,
        CronTrigger(
            minute="0,10,20,30,40,50",
            hour="0,1,6-23",
            day_of_week="mon-fri",
            timezone=TZ,
        ),
        id="signal_pipeline",
        name="M10 Signal Pipeline",
        max_instances=1,
        misfire_grace_time=60,
    )
    scheduler.add_job(
        run_heartbeat,
        CronTrigger(
            minute=0,
            hour="0,1,6-23",
            day_of_week="mon-fri",
            timezone=TZ,
        ),
        id="heartbeat",
        name="System Heartbeat",
    )
    system_log.info(f"Scheduler started | DRY_RUN={DRY_RUN} | Coverage: 06:00-01:59 BKK")
    scheduler.start()
```

**What changed:**
1. Removed `update_state` from import
2. Removed `update_state(STATE_EMPTY)` from forced SELL path (L291)
3. Stored `insert_signal` return as `ok_signal_insert` (L348)
4. Added return-check for `ok_signal_insert` in Model SELL path with error log + Discord notify
5. Removed `update_state(STATE_EMPTY)` from Model SELL path (L390)

### 5.3 Files NOT changed (verified correct as-is)

| File | Status |
|------|--------|
| `tools/confirm_trade_ui.py` | ✅ Already correct — `update_state` only in comments |
| `db/supabase_writer.py` | ✅ `update_state()` function kept but no callers |
| `core/dynamic_tp_manager.py` | ✅ Untouched (Jom's area) |
| `db/supabase_schema.sql` | ✅ Complete with migration ALTERs |
| `config/settings.py` | ✅ All settings present |
| `main.py` | ✅ Two-layer recovery works |
| `core/signal_gate.py` | ✅ Correct feature names |
| `core/feature_engine.py` | ✅ Not edited |
| `core/model_inference.py` | ✅ Not edited |

---

## 6. Compilation & Grep Results

```
✅ state_manager OK
✅ orchestrator OK
✅ confirm_trade_ui OK
✅ main OK
```

`grep -rn "update_state" --include="*.py"` results:
- `confirm_trade_ui.py`: 3 hits — all **comments** (`# update_state(...)`)
- `supabase_writer.py`: 3 hits — **dead function definition** + its internal log strings
- `orchestrator.py`: **0 hits** ✅

---

## 7. Final Go/No-Go Checklist

| # | Gate | Before | After |
|---|------|--------|-------|
| 1 | `python main.py` starts without ImportError | ✅ | ✅ |
| 2 | No active `update_state` calls | ❌ 2 calls | ✅ 0 calls |
| 3 | Confirm BUY partial fail safe | ✅ | ✅ |
| 4 | Model SELL checks insert_signal return | ❌ | ✅ |
| 5 | Forced SELL checks insert_signal return | ✅ | ✅ |
| 6 | close_open_trade fail blocks set_state | ✅ | ✅ |
| 7 | `set_state()` has retry | ❌ single attempt | ✅ 3-retry |
| 8 | BUY signal doesn't set HOLDING | ✅ | ✅ |
| 9 | TP recovers on restart | ✅ | ✅ |
| 10 | Manual SELL has audit record | ✅ | ✅ |

> [!IMPORTANT]
> **Verdict: GO for DRY_RUN=true testing.**
> 
> Remaining P2 item before DRY_RUN=false:
> - Verify DB timezone (candle_builder) by running SQL query against Supabase

---

## 8. Remaining Items (not blocking)

| Priority | Item | Risk |
|----------|------|------|
| P2 | Verify `candle_builder.py` timezone with SQL query | 🟠 Could cause 7h offset if DB is UTC |
| P2 | Remove redundant `get_current_state()` at orchestrator L142 | 🟢 Performance only |
| P3 | Clean up dead `update_state()` function from `supabase_writer.py` | 🟢 Cosmetic |
| P3 | Clean up commented `# update_state(...)` in `confirm_trade_ui.py` | 🟢 Cosmetic |
| P3 | Move `TP_SL_ATR_MULT` next to other TP settings in `settings.py` | 🟢 Cosmetic |
