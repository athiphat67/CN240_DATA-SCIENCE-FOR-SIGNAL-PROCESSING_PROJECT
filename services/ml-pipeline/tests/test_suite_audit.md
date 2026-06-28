# Test Suite Audit Report — HSH Gold ML Trader Post-Merge

**Date:** 2026-05-11  
**Result:** ✅ 63/63 new tests passing

---

## 1. Test Results Summary

```
tests/test_confirm_buy_ui.py      ✅ 9 passed
tests/test_e2e_mock_state_machine  ✅ 8 passed
tests/test_forced_sell_integration ✅ 3 passed
tests/test_manual_sell_ui.py       ✅ 5 passed
tests/test_model_sell_integration  ✅ 3 passed
tests/test_orchestrator_buy_pending✅ 3 passed
tests/test_startup_recovery.py     ✅ 5 passed
tests/test_state_invariants.py     ✅ 14 passed (6 invariants + 8 schema)
tests/test_state_manager.py        ✅ 7 passed
tests/test_tp_sync_integration.py  ✅ 6 passed
─────────────────────────────────────────────
TOTAL                              ✅ 63 passed in 0.08s
```

---

## 2. Jom's Existing Tests Audit

### test_tp_manager.py — 8/11 passed

| Test | Result | Issue |
|------|--------|-------|
| test_initial_state | ✅ | - |
| test_activation_sets_state | ✅ | - |
| test_reset_clears_state | ✅ | - |
| test_tp_updated_on_price_increase | ❌ | bid=30200 triggers BREAKEVEN_LOCK before TP_UPDATED |
| test_breakeven_lock_fires_once | ❌ | First tick at bid=30100 doesn't reach BE trigger correctly |
| test_trail_hit_when_price_drops | ✅ | - |
| test_score_fade_on_confidence_drop | ❌ | bid=30200 triggers BREAKEVEN_LOCK before SCORE_FADE |
| test_inactive_returns_none | ✅ | - |
| test_invalid_atr_returns_none | ✅ | - |
| test_trigger_priority_trail_vs_score | ✅ | - |
| test_sl_hit | ✅ | - |

> [!IMPORTANT]
> **These 3 failures are PRE-EXISTING test expectation issues, NOT bugs from the merge.**
> The `DynamicTPManager.py` code was NOT modified. The tests assume specific bid values
> won't trigger BREAKEVEN_LOCK, but the values exceed `entry_ask + breakeven_atr_mult × ATR`.
> These are Jom's responsibility to fix.

### test_sell_scenarios_dryrun.py

- **Status**: Not runnable in CI — sends real Discord messages
- **Category**: Integration/demo test (not unit test)
- **Recommendation**: Keep as-is for manual dry-run testing
- **No merge conflicts**: The test uses DynamicTPManager directly, doesn't touch Manual Confirm logic

---

## 3. Coverage Matrix

| Flow | Tests | Key Assertions |
|------|-------|----------------|
| **BUY Pending** | 3 tests | signal inserted as PENDING_CONFIRM, set_state NOT called, TP NOT activated |
| **Confirm BUY** | 9 tests | open_trade first, mark signal, set HOLDING, partial failure safety |
| **Model SELL** | 3 tests | insert first, check return, close trade, set EMPTY, TP reset |
| **Forced SELL** | 3 tests | unique signal ID, insert first, close trade, AUTO_EXITED, bar_log HOLDING |
| **Manual SELL** | 5 tests | manual signal record, close trade, set EMPTY, abort on fail |
| **TP Sync** | 6 tests | reset when EMPTY, activate from DB, SL calc, skip if active |
| **State Manager** | 7 tests | 3-retry, raise after 3, validation, DRY_RUN, no update_state |
| **Startup Recovery** | 5 tests | DRY_RUN skip, EMPTY skip, active skip, DB recovery, no-trade warn |
| **State Invariants** | 6 tests | EMPTY=inactive, reset clears all, SL priority, BE fires once |
| **Schema Contract** | 8 tests | All columns, indexes, unique constraint, NOTIFY |
| **E2E Lifecycle** | 8 tests | Full BUY→HOLD→SELL cycles, SL_HIT, TRAIL_HIT, SCORE_FADE |

---

## 4. Test Files Created

```
tests/
├── __init__.py
├── conftest.py                        # Stubs + fixtures
├── test_state_manager.py              # 7 tests
├── test_orchestrator_buy_pending.py    # 3 tests
├── test_confirm_buy_ui.py             # 9 tests
├── test_tp_sync_integration.py        # 6 tests
├── test_model_sell_integration.py     # 3 tests
├── test_forced_sell_integration.py    # 3 tests
├── test_manual_sell_ui.py             # 5 tests
├── test_state_invariants.py           # 14 tests
├── test_startup_recovery.py           # 5 tests
└── test_e2e_mock_state_machine.py     # 8 tests
```

---

## 5. How to Run

```bash
# Run all new tests
python3 -m pytest tests/ -v

# Run specific test file
python3 -m pytest tests/test_model_sell_integration.py -v

# Run Jom's existing TP manager tests
python3 test_tp_manager.py

# Compile check
python3 -m py_compile core/state_manager.py
python3 -m py_compile scheduler/orchestrator.py
python3 -m py_compile tools/confirm_trade_ui.py

# Verify no update_state calls
grep -rn "update_state" --include="*.py" . | grep -v "^#" | grep -v "test_" | grep -v "__pycache__"
```

---

## 6. Go/No-Go Checklist

| # | Gate | Status |
|---|------|--------|
| 1 | All 63 new tests pass | ✅ |
| 2 | BUY signal stays EMPTY (3 tests) | ✅ |
| 3 | Confirm BUY partial failure safe (9 tests) | ✅ |
| 4 | Model SELL insert-first checked (3 tests) | ✅ |
| 5 | Forced SELL insert-first checked (3 tests) | ✅ |
| 6 | Manual SELL audit record created (5 tests) | ✅ |
| 7 | TP sync resets when EMPTY (6 tests) | ✅ |
| 8 | set_state has 3-retry (3 tests) | ✅ |
| 9 | No update_state calls in orchestrator (2 tests) | ✅ |
| 10 | Schema contract validated (8 tests) | ✅ |
| 11 | Startup recovery works (5 tests) | ✅ |
| 12 | E2E lifecycle validated (8 tests) | ✅ |

**Verdict: ✅ GO for DRY_RUN=true**

---

## 7. Known Gaps (Not Critical)

| Gap | Risk | Notes |
|-----|------|-------|
| No real Supabase integration test | Low | All DB calls are mocked; verify manually in DRY_RUN=true |
| Jom's test_tp_manager 3 fails | Low | Pre-existing, Jom's responsibility |
| No timezone verification test | Medium | Requires SQL query against live DB |
| No rate-limit/Discord test | Low | Fire-and-forget, doesn't affect trading logic |
