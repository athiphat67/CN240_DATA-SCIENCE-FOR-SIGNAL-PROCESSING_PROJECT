# HSH Gold ML Trader — Master Fix Plan UPDATED
## รวมแผนเดิม + สิ่งที่แก้เพิ่มระหว่าง Code Audit + Patch หลังรันจริง

**อัปเดตล่าสุด:** 2026-05-10  
**โปรเจกต์:** `CN240_GOLD_LLM/Src_V4`  
**เป้าหมายเอกสาร:** ใช้เป็นเอกสารกลางสำหรับบอกตัวเอง/เพื่อน/AI ตัวอื่นว่าเราแก้อะไรไปแล้ว ยังต้องแก้อะไรต่อ และต้องทดสอบอะไรหลังแก้

---

# 0. Executive Summary

ระบบเดิมมีปัญหาหลักคือ **BUY signal ถูกตีความเหมือนซื้อจริงทันที** ทั้งที่ workflow จริงต้องเป็น:

```text
BUY signal จากโมเดล
→ แจ้ง Discord ว่า WAITING CONFIRM
→ ผู้ใช้ไปซื้อจริงที่ HSH
→ กด Confirm BUY ใน UI
→ ค่อยเปิด active trade
→ ค่อยเปลี่ยน state เป็น HOLDING
```

หลังจากแก้รอบใหญ่ ระบบถูกเปลี่ยนเป็น **Manual Confirm Workflow** แล้ว แต่ระหว่าง audit เจอ bug เพิ่มเติมหลายจุด เช่น:

1. `confirm_buy()` มีโอกาสเปิด trade สำเร็จ แต่ mark signal ไม่สำเร็จ แล้ว state ค้างเป็น `EMPTY`
2. `candle_builder.py` มีความเสี่ยง timezone localize ผิด 7 ชั่วโมง
3. มี `update_state()` กับ `set_state()` เขียน state ซ้ำ
4. `signal_gate.py` มี comment/ชื่อ feature `F_XAU_Noise_Ratio` ที่ทำให้เข้าใจผิด
5. `SESSION_EXPECTED_BARS` ใน `settings.py` ไม่ตรงกับ feature จริงใน `feature_engine.py`
6. Manual SELL ผ่าน UI ไม่สร้าง signal record สำหรับ audit history
7. `supabase_schema.sql` ต้องเพิ่ม migration columns ให้รองรับ table เดิม
8. หลังลบ `update_state()` แล้ว `orchestrator.py` ยัง import `update_state` อยู่ ทำให้เกิด ImportError ตอน `python main.py`

เอกสารนี้คือฉบับ merge ที่รวมทุกอย่างแล้ว

---

# 1. Production Flow ที่ต้องการ

## 1.1 BUY Flow ที่ถูกต้อง

```text
STATE = EMPTY

M10 pipeline run
→ build candles
→ compute features
→ run inference
→ signal gate ผ่าน BUY
→ insert v3_signals:
   signal_type = BUY
   passed = true
   execution_status = PENDING_CONFIRM
→ Discord แจ้ง BUY SIGNAL / WAITING CONFIRM
→ state ยังเป็น EMPTY
→ tp_manager ยังไม่ active
```

จากนั้นผู้ใช้ซื้อจริงที่ HSH:

```text
ผู้ใช้เปิด tools/confirm_trade_ui.py
→ กรอกราคา Ask จริงที่ซื้อได้
→ กด Confirm BUY
→ validate signal
→ open_trade_from_signal()
→ insert/update v3_active_trades เป็น OPEN
→ mark_signal_execution(..., CONFIRMED)
→ set_state(HOLDING)
→ send_trade_log("BUY", ...)
→ Discord แจ้ง BUY CONFIRMED
```

## 1.2 HOLDING / TP Sync Flow

```text
M10 pipeline ถัดไป
→ get_current_state() = HOLDING
→ sync_tp_state_from_db()
→ get_open_trade()
→ tp_manager.activate(...)
→ tp_manager เริ่ม monitor SL / trailing / score fade
```

## 1.3 SELL Flow

SELL มี 3 ประเภท:

```text
1. Model SELL
   → insert SELL signal
   → close_open_trade(exit_signal_id=signal_id)
   → set_state(EMPTY)
   → tp_manager.reset()

2. Forced SELL / Auto Exit
   เช่น SL_HIT หรือ TRAIL_HIT
   → insert forced SELL signal ก่อน
   → close_open_trade(exit_signal_id=forced_signal_id)
   → mark signal เป็น AUTO_EXITED
   → set_state(EMPTY)
   → tp_manager.reset()

3. Manual SELL ผ่าน UI
   → สร้าง manual SELL signal record
   → close_open_trade(exit_signal_id=manual_sell_id)
   → set_state(EMPTY)
   → notify_sell_confirmed()
```

---

# 2. Status Board ฉบับ Update

| # | รายการ | สถานะหลัง audit/update | ความเร่งด่วน | หมายเหตุ |
|---|---|---:|---:|---|
| 1 | BUY signal ไม่เปลี่ยน state เป็น HOLDING ทันที | ✅ เสร็จแล้ว | — | orchestrator ไม่ set HOLDING ตอนเจอ BUY signal |
| 2 | BUY signal ไม่ activate TP manager ทันที | ✅ เสร็จแล้ว | — | รอ Confirm BUY ก่อน |
| 3 | Confirm BUY validate signal ก่อนเปิด trade | ✅ เสร็จแล้ว | — | validate signal_type, passed, execution_status, state_before |
| 4 | Supabase helper functions | ✅ เสร็จแล้ว | — | มี get/open/close/mark helpers |
| 5 | `sync_tp_state_from_db()` | ✅ เสร็จแล้ว | — | ใช้ recover TP manager จาก active trade |
| 6 | Forced SELL FK-safe ordering | ✅ เสร็จแล้ว | — | insert signal ก่อน close trade |
| 7 | Model SELL close trade ก่อน set EMPTY | ✅ เสร็จแล้ว | — | ถูกต้องแล้ว |
| 8 | Discord SL_HIT message | ✅ เสร็จแล้ว | — | รองรับ SL_HIT แล้ว |
| 9 | Discord confirmed messages | ✅ เสร็จแล้ว | — | notify_buy_confirmed / notify_sell_confirmed |
| 10 | `trade_log_api.py` | ✅ เสร็จแล้ว | — | รองรับ DRY_RUN / timeout / missing config |
| 11 | Supabase schema หลัก | ✅ เกือบครบ | 🟡 | ต้องเพิ่ม rationale columns ใน ALTER TABLE สำหรับ DB เก่า |
| 12 | Rationale generator state_before | ✅ เสร็จแล้ว | — | HOLD message แยก EMPTY/HOLDING |
| 13 | main.py recover_tp_state | ✅ เสร็จแล้ว | — | startup ไม่ควร crash |
| 14 | confirm_buy partial failure | ⚠️ ต้องแก้ให้ครบ | 🔴 | ต้องมี logger + set HOLDING เมื่อ trade เปิดแล้ว |
| 15 | candle_builder timezone | ⚠️ ต้องตรวจ DB ก่อน | 🟠 | ถ้า DB เป็น UTC naive ต้องแก้ code |
| 16 | Double state write | ⚠️ ต้อง clean import/call | 🟡 | ลบ update_state ออกจาก import และ function |
| 17 | F_XAU_Noise_Ratio naming mismatch | ⚠️ ต้องแก้ comment/line | 🟡 | ใช้ F_XAU_Spread_Norm อย่างเดียว |
| 18 | SESSION_EXPECTED_BARS misleading | ⚠️ ต้องใส่ warning | 🟡 | settings.py ไม่ใช่ source ของ feature |
| 19 | Manual SELL signal record | ⚠️ ควรเพิ่ม | 🟢 | เพื่อ audit history |
| 20 | ImportError จาก update_state | ❌ เพิ่งเจอจากการรันจริง | 🔴 | orchestrator import update_state ทั้งที่ลบแล้ว |

---

# 3. ไฟล์ที่เกี่ยวข้องทั้งหมด

```text
main.py
scheduler/orchestrator.py
tools/confirm_trade_ui.py
core/candle_builder.py
core/signal_gate.py
core/feature_engine.py
core/state_manager.py
db/supabase_writer.py
db/supabase_schema.sql
config/settings.py
notifier/discord_notifier.py
notifier/trade_log_api.py
rationale/generator.py
rationale/templates.py
```

ไฟล์ที่ไม่ควรแก้โดยไม่ retrain / ไม่ถามก่อน:

```text
core/feature_engine.py
core/model_inference.py
core/dynamic_tp_manager.py
models/lambdamart_v11.json
models/lambdamart_v11_meta.json
```

---

# 4. Patch 1 — แก้ ImportError จาก `update_state`

## อาการที่เกิดจริง

ตอนรัน:

```bash
python main.py
```

เจอ error:

```text
ImportError: cannot import name 'update_state' from 'db.supabase_writer'
```

## สาเหตุ

เราลบ `update_state()` ออกจาก `db/supabase_writer.py` แล้ว แต่ `scheduler/orchestrator.py` ยัง import อยู่

## วิธีแก้แบบ Copy/Paste

เปิดไฟล์:

```text
scheduler/orchestrator.py
```

หา line นี้:

```python
from db.supabase_writer import insert_signal, insert_bar_log, update_state, get_open_trade, close_open_trade, mark_signal_execution
```

แทนที่ด้วย:

```python
from db.supabase_writer import insert_signal, insert_bar_log, get_open_trade, close_open_trade, mark_signal_execution
```

## ตรวจหลังแก้

```bash
python -m py_compile scheduler/orchestrator.py
python main.py
```

---

# 5. Patch 2 — แก้ `confirm_buy()` Partial Failure / State Stuck

## ปัญหา

ใน `tools/confirm_trade_ui.py`:

```text
open_trade_from_signal() สำเร็จ
→ v3_active_trades มี OPEN trade แล้ว
→ mark_signal_execution() ล้มเหลว
→ ถ้า return error ทันทีโดยไม่ set_state(HOLDING)
→ state ยัง EMPTY
→ confirm ซ้ำไม่ได้ เพราะมี OPEN trade อยู่แล้ว
```

นี่คือ bug critical เพราะทำให้ระบบติด state ค้าง

## 5.1 เพิ่ม import logging

เปิดไฟล์:

```text
tools/confirm_trade_ui.py
```

หา:

```python
import os
import sys
```

แทนที่ด้วย:

```python
import os
import sys
import logging
```

แล้วหา:

```python
TZ_BKK = timezone(timedelta(hours=7))
```

ใส่ต่อท้าย:

```python
logger = logging.getLogger("trading")
```

## 5.2 แก้ import จาก `db.supabase_writer`

หา import เดิมที่ประมาณนี้:

```python
from db.supabase_writer import update_state, get_latest_pending_buy_signal, mark_signal_execution, open_trade_from_signal, close_open_trade, get_signal_by_id
```

แทนที่ด้วย:

```python
from db.supabase_writer import (
    get_latest_pending_buy_signal,
    mark_signal_execution,
    open_trade_from_signal,
    close_open_trade,
    get_signal_by_id,
    insert_signal,
)
```

เหตุผล:
- เอา `update_state` ออก เพราะจะใช้ `set_state()` อย่างเดียว
- เพิ่ม `insert_signal` เพื่อรองรับ manual SELL signal record

## 5.3 แก้ block `confirm_buy()`

หา block นี้:

```python
ok_trade = open_trade_from_signal(s, price)
if not ok_trade:
    return "❌ Failed to open active trade. State was NOT changed."

ok_mark = mark_signal_execution(signal_id, "CONFIRMED", price)
if not ok_mark:
    # trade เปิดแล้ว — ยังต้องอัปเดต state ให้ตรง
    logger.warning(f"[UI] mark_signal_execution failed but trade is OPEN — forcing state to HOLDING")
    # update_state(STATE_HOLDING)
    set_state(STATE_HOLDING)
    notify_buy_confirmed(signal_id, price, note="⚠️ mark_signal failed — state forced to HOLDING")
    return f"⚠️ Trade opened @ {price:,.2f} THB แต่ mark signal ไม่สำเร็จ — State → HOLDING แล้ว ตรวจ DB ด้วย"

# update_state(STATE_HOLDING)
set_state(STATE_HOLDING)
send_trade_log("BUY", price, "MANUAL_BUY_CONFIRMED")
notify_buy_confirmed(signal_id, price)
```

แทนที่ด้วย:

```python
ok_trade = open_trade_from_signal(s, price)
if not ok_trade:
    return "❌ Failed to open active trade. State was NOT changed."

ok_mark = mark_signal_execution(signal_id, "CONFIRMED", price)
if not ok_mark:
    # Trade เปิดใน v3_active_trades แล้ว
    # ดังนั้น state ต้องเป็น HOLDING ให้ตรงกับ DB จริง
    logger.warning(
        f"[UI] mark_signal_execution failed but trade is OPEN — "
        f"forcing state to HOLDING | signal_id={signal_id}"
    )

    set_state(STATE_HOLDING)
    notify_buy_confirmed(
        signal_id,
        price,
        note="⚠️ mark_signal failed — state forced to HOLDING"
    )

    now_str = datetime.now(TZ_BKK).strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"⚠️ Trade opened @ {price:,.2f} THB แต่ mark signal ไม่สำเร็จ | "
        f"State → HOLDING แล้ว | กรุณาตรวจสอบ v3_signals ใน Supabase | {now_str}"
    )

set_state(STATE_HOLDING)
send_trade_log("BUY", price, "MANUAL_BUY_CONFIRMED")
notify_buy_confirmed(signal_id, price)

now_str = datetime.now(TZ_BKK).strftime("%Y-%m-%d %H:%M:%S")
return f"✅ BUY Confirmed! | ราคา {price:,.2f} THB | State → HOLDING | {now_str}"
```

---

# 6. Patch 3 — ลบ Double State Write ให้เหลือ `set_state()`

## หลักการใหม่

หลังจากนี้ให้มี function เดียวที่เขียน state:

```python
core.state_manager.set_state()
```

ห้ามมี `update_state()` จาก `supabase_writer.py` อีก เพราะมันทำงานซ้ำกับ `set_state()`

## 6.1 `scheduler/orchestrator.py`

ในไฟล์นี้ ให้ลบ `update_state` ออกจาก import ตาม Patch 1 แล้วเช็กว่าไม่มี call เหล่านี้เหลือ:

```python
update_state(STATE_EMPTY)
update_state(STATE_HOLDING)
```

ถ้าเจอ ให้ลบออกหรือ comment ทิ้ง แล้วใช้เฉพาะ:

```python
set_state(STATE_EMPTY)
```

ตัวอย่างหลัง Forced SELL:

```python
# update_state(STATE_EMPTY)
set_state(STATE_EMPTY)
```

ให้เหลือ:

```python
set_state(STATE_EMPTY)
```

ตัวอย่างหลัง Model SELL:

```python
# update_state(STATE_EMPTY)
set_state(STATE_EMPTY)
```

ให้เหลือ:

```python
set_state(STATE_EMPTY)
```

## 6.2 `tools/confirm_trade_ui.py`

เช็กว่าไม่มี call เหล่านี้เหลือ:

```python
update_state(STATE_HOLDING)
update_state(STATE_EMPTY)
update_state(new_state)
```

ใน `force_reset_state()` ถ้าเจอ:

```python
update_state(new_state)
set_state(new_state)
```

ให้แทนที่ด้วย:

```python
set_state(new_state)
```

## 6.3 `db/supabase_writer.py`

หลังไม่มีใคร import/call แล้ว สามารถลบ function นี้ออกได้:

```python
def update_state(new_state: str) -> None:
    ...
```

## ตรวจหลังแก้

```bash
grep -R "update_state" .
```

ผลที่ดีที่สุดคือไม่เจอเลย  
ถ้าเจอเฉพาะใน comment ถือว่ายังพอได้ แต่ควรล้างให้สะอาด

---

# 7. Patch 4 — แก้ `candle_builder.py` Timezone

## ปัญหา

ใน `core/candle_builder.py` มี comment บอกว่า DB เก็บ timestamp เป็น naive UTC แต่ code localize เป็น Bangkok ตรง ๆ:

```python
df["timestamp"] = df["timestamp"].dt.tz_localize(
    TZ, ambiguous="NaT", nonexistent="NaT"
)
```

ถ้า DB เก็บ UTC จริง จะทำให้เวลาเพี้ยน 7 ชั่วโมง

## ต้องเช็ก Supabase ก่อน

รันใน Supabase SQL Editor:

```sql
SELECT timestamp, NOW() AT TIME ZONE 'UTC' AS utc_now
FROM gold_prices_hsh
ORDER BY timestamp DESC
LIMIT 3;
```

## กรณี A — DB เก็บเวลาไทย BKK naive

ถ้าตอนเวลาไทย 10:30 แล้ว row ล่าสุดเป็น `10:xx` แปลว่า DB เก็บ BKK naive

ให้แก้แค่ comment ใน `core/candle_builder.py`:

```python
# 1. Timezone: DB เก็บ timestamp เป็น BKK naive → localize เป็น Asia/Bangkok
df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
df["timestamp"] = df["timestamp"].dt.tz_localize(
    TZ, ambiguous="NaT", nonexistent="NaT"
)
```

## กรณี B — DB เก็บ UTC naive

ถ้าตอนเวลาไทย 10:30 แล้ว row ล่าสุดเป็น `03:xx` แปลว่า DB เก็บ UTC naive

ให้แทน block timezone ด้วย:

```python
# 1. Timezone: DB เก็บ timestamp เป็น UTC naive → localize UTC → convert BKK
df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
df["timestamp"] = (
    df["timestamp"]
    .dt.tz_localize("UTC", ambiguous="NaT", nonexistent="NaT")
    .dt.tz_convert(TZ)
)
```

---

# 8. Patch 5 — แก้ `signal_gate.py` เรื่อง `F_XAU_Noise_Ratio`

## ปัญหา

`feature_engine.py` ไม่มี feature ชื่อ `F_XAU_Noise_Ratio`  
feature ที่มีจริงคือ:

```text
F_XAU_Spread_Norm
```

แต่ `signal_gate.py` มี comment ทำให้เข้าใจผิด

## วิธีแก้แบบ Copy/Paste

เปิดไฟล์:

```text
core/signal_gate.py
```

หา:

```python
# 🔁 ใช้ F_XAU_Noise_Ratio แทน F_XAU_Spread_Norm ตามการอัปเดต Phase 2
F_Noise_Ratio = features_row["F_XAU_Spread_Norm"]
```

แทนที่ด้วย:

```python
# ใช้ F_XAU_Spread_Norm เป็น noise/spread gate ตาม feature ที่มีจริงใน training/live
F_Noise_Ratio = features_row["F_XAU_Spread_Norm"]
```

ถ้าเจอเวอร์ชันนี้:

```python
F_Noise_Ratio = features_row.get("F_XAU_Noise_Ratio", features_row.get("F_XAU_Spread_Norm", 0.0))
```

ให้แทนที่ด้วย:

```python
F_Noise_Ratio = features_row["F_XAU_Spread_Norm"]
```

---

# 9. Patch 6 — ใส่ Warning ใน `settings.py` เรื่อง `SESSION_EXPECTED_BARS`

## ปัญหา

ใน `settings.py`:

```python
SESSION_EXPECTED_BARS = {
    "Morning": 36,
    "Afternoon": 36,
    "Night": 48,
}
```

แต่ใน `feature_engine.py` ใช้:

```python
_SESSION_EXPECTED = {'Morning': 18, 'Afternoon': 27, 'Night': 48}
```

และ feature สำคัญอย่าง `F_FSP`, `F_Remaining_Vol`, `F_SRVR` ขึ้นกับค่าใน `feature_engine.py`

## ห้ามเปลี่ยน `feature_engine.py`

เพราะต้อง sync กับ training script และ model ที่ train มาแล้ว

## วิธีแก้ใน `settings.py`

หา block:

```python
SESSION_EXPECTED_BARS = {
    "Morning"   : 36,
    "Afternoon" : 36,
    "Night"     : 48,
}
```

แทนที่ด้วย:

```python
# ⚠️ Reference only:
# ค่านี้ไม่ได้ถูกใช้ใน core/feature_engine.py
# feature_engine.py ใช้ _SESSION_EXPECTED = {'Morning': 18, 'Afternoon': 27, 'Night': 48}
# ซึ่ง sync กับ training script และห้ามเปลี่ยนโดยไม่ retrain model
# ห้ามนำ SESSION_EXPECTED_BARS ไปใช้คำนวณ F_FSP / F_Remaining_Vol / F_SRVR โดยตรง
SESSION_EXPECTED_BARS = {
    "Morning"   : 36,
    "Afternoon" : 36,
    "Night"     : 48,
}
```

---

# 10. Patch 7 — เพิ่ม Manual SELL Signal Record

## ปัญหา

Manual SELL ผ่าน UI ปิด active trade ได้ แต่ไม่มี signal record ของการขาย ทำให้:

```text
v3_active_trades.exit_signal_id = NULL
```

ระบบไม่พัง แต่ audit history ไม่ครบ

## วิธีแก้ใน `tools/confirm_trade_ui.py`

ต้องมี import นี้ก่อน:

```python
from db.supabase_writer import (
    get_latest_pending_buy_signal,
    mark_signal_execution,
    open_trade_from_signal,
    close_open_trade,
    get_signal_by_id,
    insert_signal,
)
```

ใน function `confirm_sell()` ให้หา block ที่มี:

```python
ok_close = close_open_trade(exit_bid=price, reason="MANUAL_SELL_CONFIRMED")
if not ok_close:
    return "❌ Failed to close active trade. State was NOT changed."
```

แทนที่ด้วย:

```python
manual_sell_id = f"manual_sell_{datetime.now(TZ_BKK).strftime('%Y%m%d_%H%M%S')}"

manual_sell_record = {
    "id": manual_sell_id,
    "bar_time": datetime.now(TZ_BKK).isoformat(),
    "session": "Manual",
    "signal_type": "SELL",
    "ranker_score": 0.0,
    "state_before": STATE_HOLDING,
    "hsh_ask_price": None,
    "hsh_bid_price": price,
    "xau_price": None,
    "atr_at_signal": None,
    "passed": True,
    "reject_reason": None,
    "dry_run": False,
    "features_snap": {},
    "rationale_text": "Manual SELL confirmed from confirm_trade_ui.py",
    "top_shap_features": {},
    "execution_status": "CONFIRMED",
    "confirmed_price": price,
    "confirmed_at": datetime.now(TZ_BKK).isoformat(),
    "created_at": datetime.now(TZ_BKK).isoformat(),
}

ok_insert = insert_signal(manual_sell_record)
if not ok_insert:
    return "❌ Failed to insert manual SELL signal. State was NOT changed."

ok_close = close_open_trade(
    exit_bid=price,
    exit_signal_id=manual_sell_id,
    reason="MANUAL_SELL_CONFIRMED",
)
if not ok_close:
    return "❌ Failed to close active trade. State was NOT changed."
```

จากนั้นให้ flow เดิมทำต่อ:

```python
set_state(STATE_EMPTY)
send_trade_log("SELL", price, "MANUAL_SELL_CONFIRMED")
notify_sell_confirmed(price, "MANUAL_SELL_CONFIRMED")
```

---

# 11. Patch 8 — Supabase Schema Update

## ปัญหาที่เจอจาก schema

ถ้าใช้ `CREATE TABLE IF NOT EXISTS v3_signals (...)` กับ DB ที่มี table เดิมอยู่แล้ว PostgreSQL จะไม่เพิ่ม column ใหม่ให้อัตโนมัติ

ดังนั้นต้องมี `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` สำหรับ column ใหม่ทุกตัวที่โค้ดใช้

## Block ที่ควรมีใน `supabase_schema.sql`

ให้หา block นี้:

```sql
ALTER TABLE public.v3_signals
ADD COLUMN IF NOT EXISTS execution_status TEXT DEFAULT 'SIGNAL_ONLY',
ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS confirmed_price NUMERIC(10,2),
ADD COLUMN IF NOT EXISTS confirm_note TEXT,
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
```

แทนที่ด้วย:

```sql
ALTER TABLE public.v3_signals
ADD COLUMN IF NOT EXISTS rationale_text TEXT,
ADD COLUMN IF NOT EXISTS top_shap_features JSONB,
ADD COLUMN IF NOT EXISTS execution_status TEXT DEFAULT 'SIGNAL_ONLY',
ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS confirmed_price NUMERIC(10,2),
ADD COLUMN IF NOT EXISTS confirm_note TEXT,
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
```

จากนั้นหา:

```sql
CREATE INDEX IF NOT EXISTS idx_active_trades_entry_signal ON v3_active_trades(entry_signal_id);
```

ใส่ต่อท้าย:

```sql
CREATE INDEX IF NOT EXISTS idx_active_trades_exit_signal
ON public.v3_active_trades(exit_signal_id);
```

ตัวอย่าง block index ที่ควรได้:

```sql
CREATE INDEX IF NOT EXISTS idx_active_trades_status ON v3_active_trades(status);
CREATE INDEX IF NOT EXISTS idx_active_trades_entry_signal ON v3_active_trades(entry_signal_id);
CREATE INDEX IF NOT EXISTS idx_active_trades_exit_signal
ON public.v3_active_trades(exit_signal_id);
```

ต้องมีท้ายไฟล์:

```sql
NOTIFY pgrst, 'reload schema';
```

---

# 12. Check Commands หลังแก้โค้ด

รันจาก root ของโปรเจกต์:

```bash
python -m py_compile main.py
python -m py_compile scheduler/orchestrator.py
python -m py_compile tools/confirm_trade_ui.py
python -m py_compile core/candle_builder.py
python -m py_compile core/signal_gate.py
python -m py_compile db/supabase_writer.py
```

เช็กว่าไม่มี `update_state` เหลือ:

```bash
grep -R "update_state" .
```

เช็กว่าไม่มี import error:

```bash
python main.py
```

ถ้า `python main.py` ผ่าน ควรเห็นประมาณ:

```text
HSH ML Trader v3.0 — Signal Generator Mode
DRY_RUN = ...
Current state on startup: ...
Scheduler started
```

---

# 13. Supabase Verification SQL

หลังรัน migration ให้ตรวจ:

```sql
SELECT *
FROM public.v3_system_state;
```

Expected:

```text
id = 1
current_position = EMPTY หรือ HOLDING
```

เช็ก columns ใน `v3_signals`:

```sql
SELECT column_name
FROM information_schema.columns
WHERE table_schema = 'public'
  AND table_name = 'v3_signals'
ORDER BY ordinal_position;
```

Expected ต้องมี:

```text
rationale_text
top_shap_features
execution_status
confirmed_at
confirmed_price
confirm_note
updated_at
```

เช็ก active trade table:

```sql
SELECT *
FROM public.v3_active_trades
ORDER BY updated_at DESC
LIMIT 5;
```

เช็ก open trade ซ้อน:

```sql
SELECT status, COUNT(*)
FROM public.v3_active_trades
GROUP BY status;
```

ถ้าระบบปกติ ไม่ควรมี `OPEN` มากกว่า 1

---

# 14. Test Checklist ก่อน Go-Live

## Test A — Startup

```bash
python main.py
```

Expected:

```text
ไม่มี ImportError
อ่าน state ได้
recover_tp_state ไม่ crash
scheduler start ได้
Discord startup message ส่งได้ถ้ามี webhook
```

## Test B — BUY Signal Pending

เมื่อ pipeline เจอ BUY signal:

Expected:

```text
v3_signals:
  signal_type = BUY
  passed = true
  execution_status = PENDING_CONFIRM

v3_system_state:
  current_position = EMPTY

v3_active_trades:
  ยังไม่มี OPEN trade ใหม่

Discord:
  BUY SIGNAL / WAITING CONFIRM
```

## Test C — Confirm BUY

รัน:

```bash
python tools/confirm_trade_ui.py
```

กด Confirm BUY ด้วยราคาซื้อจริง

Expected:

```text
v3_active_trades:
  status = OPEN
  entry_ask = ราคาที่กรอก
  entry_signal_id = signal id ของ BUY

v3_signals:
  execution_status = CONFIRMED
  confirmed_price = ราคาที่กรอก

v3_system_state:
  current_position = HOLDING

Discord:
  BUY CONFIRMED

Trade Log API:
  ส่ง BUY หรือ log DRY_RUN
```

## Test D — Partial Failure Confirm BUY

จำลองให้ `mark_signal_execution()` return `False`

Expected:

```text
v3_active_trades:
  status = OPEN

v3_system_state:
  current_position = HOLDING

UI:
  แจ้งว่า mark signal ไม่สำเร็จ แต่ state ถูก force เป็น HOLDING
```

ห้ามเกิด:

```text
v3_active_trades = OPEN
แต่ v3_system_state = EMPTY
```

## Test E — Model SELL

Expected:

```text
insert SELL signal
close_open_trade สำเร็จ
v3_active_trades.status = CLOSED
v3_system_state = EMPTY
tp_manager.reset()
Discord SELL signal
```

## Test F — Forced SELL / SL_HIT / TRAIL_HIT

Expected:

```text
forced SELL signal ถูก insert ก่อน
close_open_trade มี exit_signal_id
mark_signal_execution เป็น AUTO_EXITED
state = EMPTY
tp_manager.reset()
Discord แจ้ง auto-exit
```

## Test G — Manual SELL

Expected:

```text
manual_sell_xxxxx ถูก insert ใน v3_signals
v3_active_trades.exit_signal_id = manual_sell_xxxxx
status = CLOSED
pnl_thb ถูกคำนวณ
state = EMPTY
Discord SELL CONFIRMED
```

---

# 15. .env Checklist

ควรมี:

```env
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=eyJxxx

DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/xxx
DISCORD_MENTION_ID=your_discord_user_id

TRADE_LOG_API_URL=https://your-api-url
TRADE_LOG_API_KEY=your_api_key

DRY_RUN=false
LOG_LEVEL=INFO
TIMEZONE=Asia/Bangkok

SIGNALS_TABLE=v3_signals
BAR_LOGS_TABLE=v3_bar_logs
SYSTEM_STATE_TABLE=v3_system_state
ACTIVE_TRADES_TABLE=v3_active_trades
```

ถ้ายังทดสอบอยู่ให้ใช้:

```env
DRY_RUN=true
```

ก่อนเสมอ

---

# 16. Final Go-Live Gate

ห้าม go-live ถ้ายังมีข้อใดข้อหนึ่ง:

```text
[ ] python main.py ยัง ImportError
[ ] grep -R "update_state" . ยังเจอ active import/call
[ ] confirm_buy partial failure ยังทำให้ OPEN trade + EMPTY state
[ ] ยังไม่รู้ว่า DB timestamp เป็น UTC หรือ BKK
[ ] Supabase ไม่มี rationale_text / top_shap_features
[ ] BUY signal แล้วยัง set_state(HOLDING) ทันที
```

Go-live ได้เมื่อ:

```text
[x] python main.py start ได้
[x] schema migrate แล้ว
[x] BUY signal เป็น PENDING_CONFIRM
[x] Confirm BUY แล้วค่อย HOLDING
[x] SELL ปิด active trade ก่อน EMPTY
[x] TP manager recover/sync จาก active trade ได้
[x] Manual SELL มี audit record หรืออย่างน้อย close trade + state EMPTY ได้
```

---

# 17. สรุปภาษาคน

เราไม่ได้แก้ logic เทรดให้โมเดลเก่งขึ้นในรอบนี้  
เราแก้ **production workflow** ให้ตรงกับการใช้งานจริง:

```text
โมเดลแค่แนะนำ BUY
คนต้องกด confirm หลังซื้อจริง
ระบบค่อยถือว่า HOLDING
SELL ต้องปิด trade จริงก่อน state EMPTY
ทุกอย่างต้อง audit ย้อนหลังได้ใน Supabase
```

การแก้ที่สำคัญที่สุดคือ:

```text
BUY signal ≠ ซื้อจริง
Confirm BUY = ซื้อจริง
OPEN trade คือ source of truth
state ต้องตาม DB จริง
set_state() เป็นทางเดียวในการเปลี่ยน state
```

ถ้าเข้าใจ 5 บรรทัดนี้ จะเข้าใจระบบใหม่ทั้งหมด

---

*End of updated master fix plan.*
