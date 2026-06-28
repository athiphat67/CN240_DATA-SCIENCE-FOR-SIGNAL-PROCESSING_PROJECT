# RICH — Src_V4 Module Fix Plan

> ไฟล์นี้เป็นแผนเสริมจาก `RICH_SRC_V4_PRODUCTION_FIX_PLAN.md`  
> ให้ทำ **ไฟล์ก่อนหน้าเป็นลำดับแรก** เพื่อแก้ flow หลักใน `scheduler/orchestrator.py`  
> จากนั้นค่อยทำไฟล์นี้ เพื่อทำให้ module รอบข้าง, DB schema, UI confirm, Discord, และ Trade Log ทำงานร่วมกันได้จริง

---

## 0) สถานะไฟล์ที่ส่งมา: เพียงพอไหม

**เพียงพอสำหรับทำ MVP ให้รันจริงได้แล้ว** โดยไฟล์ที่ส่งมาครบสำหรับงาน production bridge รอบนี้:

```text
config/settings.py
db/supabase_writer.py
notifier/discord_notifier.py
notifier/trade_log_api.py
tools/confirm_trade_ui.py
logger_setup.py
requirements.txt
supabase_schema.sql
```

ยังไม่ต้องส่ง model เพิ่ม ถ้าเป้าหมายคือ “พรุ่งนี้ใช้ได้จริง” ไม่ใช่ retrain หรือเปลี่ยน feature set

สิ่งที่ยังต้องเตรียมเพิ่มตอนรันจริง:

```text
.env จริงในเครื่อง local / server
Supabase tables ที่ migrate ตาม schema ใหม่แล้ว
Discord webhook URL จริง
Trade Log API URL/KEY ถ้าต้องส่ง log อาจารย์
```

---

## 1) ลำดับการแก้ที่ถูกต้อง

ให้ทำตามลำดับนี้ ห้ามสลับมั่ว เพราะ module รอบข้างพึ่งพา flow หลักใน `orchestrator.py`

```text
Step 1: ทำตาม RICH_SRC_V4_PRODUCTION_FIX_PLAN.md ก่อน
        - BUY signal ต้องไม่ set HOLDING ทันที
        - BUY signal ต้องไม่ activate TP manager ทันที
        - SELL/forced SELL ต้องทำงานเฉพาะหลัง confirm BUY
        - build_trade_payload ต้องส่ง state_before

Step 2: ทำตามไฟล์นี้
        - แก้ Supabase schema ให้ตรงกับ record ที่ code insert จริง
        - เพิ่ม active trade table
        - เพิ่ม db helper functions
        - แก้ confirm_trade_ui ให้ไม่ใช่แค่ toggle state
        - แก้ Discord notifier ให้ไม่ crash ตอน SL_HIT
        - ต่อ Trade Log API ตอน confirm BUY/SELL
        - เพิ่ม safety/logging

Step 3: Run test แบบ manual
        EMPTY → BUY signal → Confirm BUY → HOLDING → SELL/SL/Trail → EMPTY
```

---

## 2) จุดพังสำคัญที่เจอใน module ชุดใหม่

## 2.1 `supabase_schema.sql` มี bug ชื่อ table ผิด

ปัจจุบันสร้าง table นี้:

```sql
CREATE TABLE IF NOT EXISTS v3_system_state (...);
```

แต่ insert ด้วย:

```sql
INSERT INTO system_state (id, current_position) VALUES (1, 'EMPTY') ...
```

**ผิด** เพราะ table จริงชื่อ `v3_system_state`

ต้องแก้เป็น:

```sql
INSERT INTO v3_system_state (id, current_position)
VALUES (1, 'EMPTY')
ON CONFLICT (id) DO NOTHING;
```

ถ้าไม่แก้ migration จะไม่ init state และระบบอ่าน state ไม่เจอ

---

## 2.2 `v3_signals` schema ไม่ตรงกับ `signal_recorder.py`

`core/signal_recorder.py` insert field เหล่านี้:

```text
rationale_text
top_shap_features
```

แต่ `supabase_schema.sql` ยังไม่มี 2 column นี้ใน `v3_signals`

ถ้าไม่เพิ่ม column ระบบจะ insert signal ล้ม หรือ fallback เป็น JSONL

ต้องเพิ่ม:

```sql
ALTER TABLE v3_signals
ADD COLUMN IF NOT EXISTS rationale_text TEXT,
ADD COLUMN IF NOT EXISTS top_shap_features JSONB;
```

---

## 2.3 ยังไม่มี table สำหรับ trade ที่ confirm จริง

ตอนนี้ระบบมีแค่:

```text
v3_system_state
v3_signals
v3_bar_logs
```

แต่ goal ใหม่ต้องมี:

```text
BUY signal ออก
→ คน execute จริง
→ กด confirm
→ ระบบต้องจำราคาที่ซื้อจริง
→ SELL ต้องปิด trade จริง
```

ดังนั้นต้องเพิ่ม table ใหม่ เช่น `v3_active_trades`

---

## 2.4 `confirm_trade_ui.py` ตอนนี้ยังไม่พอ

ตอนนี้ UI ทำแค่:

```text
Confirm BUY  → update_state(HOLDING) + set_state(HOLDING)
Confirm SELL → update_state(EMPTY) + set_state(EMPTY)
```

ปัญหา:

```text
[ ] ไม่ validate ว่า BUY signal ล่าสุด passed จริงหรือไม่
[ ] ไม่ผูก confirm กับ signal_id
[ ] ไม่บันทึกราคา execute จริงลง active trade
[ ] ไม่บันทึก entry_score / entry_signal_id
[ ] ไม่ปิด active trade ตอน SELL
[ ] ไม่ส่ง trade_log_api
[ ] ไม่แจ้ง Discord ว่า confirm แล้ว
[ ] ยังเรียก update_state และ set_state ซ้ำกัน
```

ดังนั้น UI นี้ควรถูกแก้เป็น **Confirm Execution UI** ไม่ใช่แค่ **State Toggle UI**

---

## 2.5 `discord_notifier.py` มี bug ตอน `SL_HIT`

`orchestrator.py` เรียก:

```python
notify_dynamic_tp(tp_trigger, ...)
```

เมื่อ `tp_trigger` เป็น:

```text
TRAIL_HIT
SL_HIT
BREAKEVEN_LOCK
SCORE_FADE
TP_UPDATED
```

แต่ `discord_notifier.py` มี message map แค่:

```text
TP_UPDATED
BREAKEVEN_LOCK
TRAIL_HIT
SCORE_FADE
```

ไม่มี `SL_HIT`

ดังนั้นถ้า SL โดน จะเกิด `KeyError: 'SL_HIT'` ก่อน forced SELL flow อาจทำงานจบไม่ครบ

ต้องเพิ่ม `SL_HIT` ใน message map

---

## 2.6 `discord_notifier.py` มี nested duplicate function

ท้ายไฟล์มี `def notify_dynamic_tp(...)` ซ้อนอยู่ข้างใน `notify_dynamic_tp()` อีกที

อันนี้อาจไม่ crash แต่รกและเสี่ยงสับสน ให้ลบทิ้ง เหลือ function เดียว

---

## 2.7 `trade_log_api.py` มีแล้ว แต่ยังไม่ได้ต่อกับ flow confirm

ไฟล์นี้พร้อมใช้สำหรับส่ง log ไป API อาจารย์:

```python
send_trade_log(action: str, price: float | str, reason: str) -> bool
```

แต่ตอนนี้ยังไม่ได้ถูกใช้ใน confirm UI หรือ orchestrator

ควรต่อใน:

```text
confirm BUY จริง → send_trade_log("BUY", executed_ask, reason)
confirm SELL จริง → send_trade_log("SELL", executed_bid, reason)
forced SELL จริง → send_trade_log("SELL", exit_bid, reason)
```

---

## 3) แก้ `supabase_schema.sql`

## 3.1 แก้ init state table name

เปลี่ยน:

```sql
INSERT INTO system_state (id, current_position) VALUES (1, 'EMPTY') ON CONFLICT (id) DO NOTHING;
```

เป็น:

```sql
INSERT INTO v3_system_state (id, current_position)
VALUES (1, 'EMPTY')
ON CONFLICT (id) DO NOTHING;
```

---

## 3.2 เพิ่ม execution fields ใน `v3_signals`

เพิ่ม column เพื่อแยก “signal” กับ “execution”

```sql
ALTER TABLE v3_signals
ADD COLUMN IF NOT EXISTS rationale_text TEXT,
ADD COLUMN IF NOT EXISTS top_shap_features JSONB,
ADD COLUMN IF NOT EXISTS execution_status TEXT DEFAULT 'SIGNAL_ONLY',
ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS confirmed_price NUMERIC(10,2),
ADD COLUMN IF NOT EXISTS confirm_note TEXT;
```

สถานะที่แนะนำ:

```text
SIGNAL_ONLY       = signal ธรรมดา เช่น HOLD หรือ rejected
PENDING_CONFIRM   = BUY/SELL signal ที่รอคน confirm
CONFIRMED         = คน confirm แล้ว
AUTO_EXITED       = forced SELL จาก SL/TRAIL
CANCELLED         = signal ถูกยกเลิก/manual skip
```

สำหรับรอบแรก:

```text
BUY passed → PENDING_CONFIRM
Confirm BUY → CONFIRMED
SELL passed → CONFIRMED หรือ AUTO_EXITED ตาม flow
HOLD → SIGNAL_ONLY
```

---

## 3.3 เพิ่ม table `v3_active_trades`

เพิ่ม table นี้ใน schema:

```sql
CREATE TABLE IF NOT EXISTS v3_active_trades (
    id                  BIGSERIAL PRIMARY KEY,
    status              TEXT NOT NULL DEFAULT 'OPEN', -- OPEN | CLOSED | CANCELLED

    entry_signal_id     TEXT REFERENCES v3_signals(id),
    entry_time          TIMESTAMPTZ DEFAULT NOW(),
    entry_bar_time      TIMESTAMPTZ,
    entry_ask           NUMERIC(10,2) NOT NULL,
    entry_bid_at_signal NUMERIC(10,2),
    entry_score         NUMERIC(10,6),
    entry_note          TEXT,

    exit_signal_id      TEXT REFERENCES v3_signals(id),
    exit_time           TIMESTAMPTZ,
    exit_bid            NUMERIC(10,2),
    exit_score          NUMERIC(10,6),
    exit_reason         TEXT,
    exit_note           TEXT,

    pnl_thb             NUMERIC(10,2),
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_active_trades_status
ON v3_active_trades(status);

CREATE INDEX IF NOT EXISTS idx_active_trades_entry_signal
ON v3_active_trades(entry_signal_id);
```

แนวคิด:

```text
v3_signals       = model พูดว่าอะไร
v3_active_trades = เรากดซื้อ/ขายจริงที่ราคาไหน
v3_system_state  = ตอนนี้ถือ position หรือไม่
```

---

## 4) แก้ `config/settings.py`

## 4.1 เพิ่ม config สำหรับ confirm flow

เพิ่มท้ายไฟล์:

```python
# ─── Execution Confirmation ──────────────────────────────────────────────────
REQUIRE_BUY_CONFIRM = os.getenv("REQUIRE_BUY_CONFIRM", "true").lower() == "true"
AUTO_CONFIRM_SELL   = os.getenv("AUTO_CONFIRM_SELL", "true").lower() == "true"

SIGNALS_TABLE       = os.getenv("SIGNALS_TABLE", "v3_signals")
BAR_LOGS_TABLE      = os.getenv("BAR_LOGS_TABLE", "v3_bar_logs")
SYSTEM_STATE_TABLE  = os.getenv("SYSTEM_STATE_TABLE", "v3_system_state")
ACTIVE_TRADES_TABLE = os.getenv("ACTIVE_TRADES_TABLE", "v3_active_trades")
```

ความหมาย:

```text
REQUIRE_BUY_CONFIRM=true
    BUY signal ออกแล้วต้องรอ confirm ก่อน HOLDING

AUTO_CONFIRM_SELL=true
    SELL signal แล้วระบบ update EMPTY ทันที เพื่อให้ทันใช้พรุ่งนี้

AUTO_CONFIRM_SELL=false
    SELL signal ต้องรอ confirm_sell เหมือน BUY
```

แนะนำสำหรับรอบพรุ่งนี้:

```env
REQUIRE_BUY_CONFIRM=true
AUTO_CONFIRM_SELL=true
```

---

## 4.2 เพิ่ม optional UI config

ตอนนี้ `confirm_trade_ui.py` อ่าน `APP_USER`, `APP_PASS`, `PORT` จาก env โดยตรง ซึ่งใช้ได้ แต่ถ้าจะรวม config ให้ชัด เพิ่มได้:

```python
CONFIRM_UI_USER = os.getenv("APP_USER", "admin")
CONFIRM_UI_PASS = os.getenv("APP_PASS", "admin123")
CONFIRM_UI_PORT = int(os.getenv("PORT", "7861"))
```

แล้วแก้ UI ให้ import จาก settings แทน

---

## 5) แก้ `db/supabase_writer.py`

ไฟล์นี้ต้องกลายเป็น helper สำหรับ DB operations ที่เกี่ยวกับ signal/trade ด้วย ไม่ใช่แค่ insert signal/log

## 5.1 ทำให้ insert functions return bool

เปลี่ยน:

```python
def insert_signal(signal: dict) -> None:
    _safe_upsert("v3_signals", signal)
```

เป็น:

```python
def insert_signal(signal: dict) -> bool:
    return _safe_upsert("v3_signals", signal)
```

และ:

```python
def insert_bar_log(log: dict) -> bool:
    return _safe_upsert("v3_bar_logs", log, conflict_col="bar_time")
```

เหตุผล: orchestrator / UI จะรู้ได้ว่า insert สำเร็จจริงไหม

---

## 5.2 เพิ่ม `get_signal_by_id()`

```python
def get_signal_by_id(signal_id: str) -> dict | None:
    if DRY_RUN:
        logger.info(f"[DRY_RUN] Would fetch signal {signal_id}")
        return None
    res = get_supabase_client().table("v3_signals").select("*").eq("id", signal_id).limit(1).execute()
    return res.data[0] if res.data else None
```

---

## 5.3 เพิ่ม `get_latest_pending_buy_signal()`

```python
def get_latest_pending_buy_signal() -> dict | None:
    if DRY_RUN:
        return None
    res = (
        get_supabase_client()
        .table("v3_signals")
        .select("*")
        .eq("signal_type", "BUY")
        .eq("passed", True)
        .in_("execution_status", ["PENDING_CONFIRM", "SIGNAL_ONLY"])
        .order("bar_time", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None
```

หมายเหตุ: ถ้าใช้ `execution_status` จริง ควรให้ orchestrator set BUY passed เป็น `PENDING_CONFIRM` ตั้งแต่แรก แล้ว query เฉพาะ `PENDING_CONFIRM`

---

## 5.4 เพิ่ม `mark_signal_execution()`

```python
def mark_signal_execution(signal_id: str, status: str, price: float | None = None, note: str | None = None) -> bool:
    if DRY_RUN:
        logger.info(f"[DRY_RUN] Would mark signal {signal_id} → {status}")
        return True

    payload = {
        "execution_status": status,
        "updated_at": "now()",
    }
    if price is not None:
        payload["confirmed_price"] = float(price)
    if note:
        payload["confirm_note"] = note
    if status in ("CONFIRMED", "AUTO_EXITED", "CANCELLED"):
        payload["confirmed_at"] = "now()"

    try:
        get_supabase_client().table("v3_signals").update(payload).eq("id", signal_id).execute()
        return True
    except Exception as e:
        logger.error(f"[DB] mark_signal_execution failed: {e}")
        return False
```

ถ้า Supabase ไม่ยอมรับ `updated_at` เพราะ `v3_signals` ยังไม่มี column นี้ ให้เพิ่ม column หรือเอา field นี้ออก

แนะนำเพิ่มใน schema:

```sql
ALTER TABLE v3_signals
ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();
```

---

## 5.5 เพิ่ม `get_open_trade()`

```python
def get_open_trade() -> dict | None:
    if DRY_RUN:
        return None
    res = (
        get_supabase_client()
        .table("v3_active_trades")
        .select("*")
        .eq("status", "OPEN")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None
```

---

## 5.6 เพิ่ม `open_trade_from_signal()`

```python
def open_trade_from_signal(signal: dict, executed_ask: float, note: str | None = None) -> bool:
    if DRY_RUN:
        logger.info(f"[DRY_RUN] Would open trade from signal {signal.get('id')} @ {executed_ask}")
        return True

    payload = {
        "status": "OPEN",
        "entry_signal_id": signal["id"],
        "entry_bar_time": signal.get("bar_time"),
        "entry_ask": float(executed_ask),
        "entry_bid_at_signal": signal.get("hsh_bid_price"),
        "entry_score": signal.get("ranker_score"),
        "entry_note": note,
    }
    try:
        get_supabase_client().table("v3_active_trades").insert(payload).execute()
        return True
    except Exception as e:
        logger.error(f"[DB] open_trade_from_signal failed: {e}")
        return False
```

---

## 5.7 เพิ่ม `close_open_trade()`

```python
def close_open_trade(exit_bid: float, exit_signal_id: str | None = None, exit_score: float | None = None, reason: str = "MANUAL_SELL", note: str | None = None) -> bool:
    if DRY_RUN:
        logger.info(f"[DRY_RUN] Would close open trade @ {exit_bid} | reason={reason}")
        return True

    trade = get_open_trade()
    if not trade:
        logger.warning("[DB] No OPEN trade to close")
        return False

    entry_ask = float(trade["entry_ask"])
    pnl = float(exit_bid) - entry_ask

    payload = {
        "status": "CLOSED",
        "exit_signal_id": exit_signal_id,
        "exit_time": "now()",
        "exit_bid": float(exit_bid),
        "exit_score": exit_score,
        "exit_reason": reason,
        "exit_note": note,
        "pnl_thb": pnl,
        "updated_at": "now()",
    }
    try:
        get_supabase_client().table("v3_active_trades").update(payload).eq("id", trade["id"]).execute()
        return True
    except Exception as e:
        logger.error(f"[DB] close_open_trade failed: {e}")
        return False
```

หมายเหตุ: `pnl_thb = exit_bid - entry_ask` เป็น PnL ต่อ 1 หน่วยราคาทอง ไม่ใช่ PnL ตาม trade size ถ้าต้องคำนวณเงินจริงตาม 1,000 บาท ต้องเพิ่ม formula ทีหลัง

---

## 5.8 เรื่อง `update_state()` กับ `set_state()`

ตอนนี้มี 2 function ที่ทำงานซ้ำกัน:

```text
db.supabase_writer.update_state()
core.state_manager.set_state()
```

แนะนำสำหรับรอบนี้:

```text
ใช้ core.state_manager.set_state() เป็นหลัก เพราะ validate STATE_EMPTY/STATE_HOLDING แล้ว
เก็บ db.supabase_writer.update_state() ไว้ backward compatibility
อย่าเรียกทั้งสองตัวซ้ำใน flow ใหม่
```

ถ้ากลัวกระทบของเดิม ให้ค่อย refactor ทีหลัง แต่ code ใหม่ใน `confirm_trade_ui.py` และ `orchestrator.py` ควรใช้ `set_state()` ตัวเดียว

---

## 6) แก้ `notifier/discord_notifier.py`

## 6.1 เพิ่ม message สำหรับ `SL_HIT`

แก้ใน `notify_dynamic_tp()`:

```python
messages = {
    "TP_UPDATED": f"📈 TP Adjusted → `{price:,.2f}` THB\nTrail Level: `{trail:,.2f}`",
    "BREAKEVEN_LOCK": f"🔒 Breakeven Locked\nTrail fixed at `{trail:,.2f}`. Downside risk removed.",
    "TRAIL_HIT": f"🔴 {mention}**DYNAMIC EXIT TRIGGERED**\nPrice hit trail at `{trail:,.2f}`. Consider closing now.\nCurrent Score: `{score:.4f}`",
    "SL_HIT": f"🛑 {mention}**STOP LOSS HIT**\nCurrent price hit SL at `{trail:,.2f}`. Exit required.\nCurrent Score: `{score:.4f}`",
    "SCORE_FADE": f"⚠️ Momentum Fading\nScore dropped significantly (`{score:.4f}`). Trail at `{trail:,.2f}`. Consider scaling out.",
}
```

และใช้ safe fallback:

```python
body = messages.get(trigger, f"ℹ️ TP Event `{trigger}` | price={price} | trail={trail} | score={score:.4f}")
send_discord(f"🤖 **HSH Dynamic TP**\n{body}\nATR(48): `{atr:,.2f}`")
```

---

## 6.2 ลบ nested duplicate function

ท้ายไฟล์มี `def notify_dynamic_tp(...)` ซ้อนอยู่ใน function เดิม ให้ลบทิ้ง เหลือ function เดียว

---

## 6.3 เพิ่ม notifier สำหรับ confirm

เพิ่ม 2 function:

```python
def notify_buy_confirmed(signal_id: str, price: float, note: str = "") -> None:
    mention = f"<@{DISCORD_MENTION_ID}> " if DISCORD_MENTION_ID else ""
    send_discord(
        f"{mention}\n✅ **BUY CONFIRMED**\n"
        f"Signal ID: `{signal_id}`\n"
        f"Executed Ask: `{price:,.2f}` THB\n"
        f"State → `HOLDING`\n"
        f"{note}"
    )


def notify_sell_confirmed(price: float, reason: str = "MANUAL_SELL", signal_id: str | None = None) -> None:
    mention = f"<@{DISCORD_MENTION_ID}> " if DISCORD_MENTION_ID else ""
    sig_line = f"Signal ID: `{signal_id}`\n" if signal_id else ""
    send_discord(
        f"{mention}\n✅ **SELL CONFIRMED**\n"
        f"{sig_line}"
        f"Executed Bid: `{price:,.2f}` THB\n"
        f"Reason: `{reason}`\n"
        f"State → `EMPTY`"
    )
```

---

## 6.4 ปรับข้อความ BUY ให้บอกว่ารอ confirm

ถ้าใช้ `REQUIRE_BUY_CONFIRM=true` ข้อความ `notify_buy_signal()` ควรมีบรรทัดนี้:

```text
⚠️ Status: WAITING CONFIRM — Execute ที่ HSH แล้วกด Confirm BUY ใน UI
```

เพื่อไม่ให้คนเข้าใจว่า bot ซื้อแล้ว

---

## 7) แก้ `tools/confirm_trade_ui.py`

ไฟล์นี้สำคัญมาก เพราะเป็น “ปุ่ม confirm จริง” สำหรับพรุ่งนี้

## 7.1 เปลี่ยน Dashboard ให้หา latest pending BUY ไม่ใช่ latest signal เฉย ๆ

ตอนนี้ `fetch_dashboard()` ดึง signal ล่าสุดทุกประเภท:

```python
.order("bar_time", desc=True).limit(1)
```

ปัญหา: ถ้า signal ล่าสุดเป็น HOLD มันจะทับ BUY pending ก่อนหน้า

ควรแสดง 2 ส่วน:

```text
Latest signal ล่าสุดทุกประเภท
Latest pending BUY ที่ยังรอ confirm
Open trade ปัจจุบัน
```

อย่างน้อยให้เพิ่ม:

```python
pending_buy_res = (
    client.table("v3_signals")
    .select("*")
    .eq("signal_type", "BUY")
    .eq("passed", True)
    .eq("execution_status", "PENDING_CONFIRM")
    .order("bar_time", desc=True)
    .limit(1)
    .execute()
)
```

---

## 7.2 เพิ่ม input `signal_id` หรือเลือก latest pending อัตโนมัติ

ทางที่ง่ายที่สุด:

```text
Confirm BUY ใช้ latest pending BUY อัตโนมัติ
```

แต่เพื่อความปลอดภัย ควรมี textbox `Signal ID` ด้วย:

```text
Signal ID ที่จะ confirm
Executed Ask
```

ถ้าค่าว่าง ให้ใช้ latest pending BUY

---

## 7.3 แก้ `confirm_buy()` ให้ validate + open trade

flow ใหม่:

```text
1. parse executed ask
2. current state ต้องเป็น EMPTY
3. หา pending BUY signal
4. signal_type ต้องเป็น BUY
5. passed ต้องเป็น True
6. execution_status ต้องเป็น PENDING_CONFIRM หรือ SIGNAL_ONLY เฉพาะ legacy
7. open_trade_from_signal(signal, executed_ask)
8. mark_signal_execution(signal_id, CONFIRMED, price)
9. set_state(HOLDING)
10. send_trade_log("BUY", price, reason)
11. notify_buy_confirmed()
```

ห้ามทำแค่ `set_state(HOLDING)`

---

## 7.4 แก้ `confirm_sell()` ให้ close trade

flow ใหม่:

```text
1. parse executed bid
2. current state ต้องเป็น HOLDING
3. ต้องมี open trade
4. close_open_trade(exit_bid, reason="MANUAL_SELL")
5. set_state(EMPTY)
6. send_trade_log("SELL", price, reason)
7. notify_sell_confirmed()
```

ถ้าไม่มี open trade แต่ state เป็น HOLDING ให้เตือนว่า DB ไม่สมบูรณ์ และให้ใช้ force reset เฉพาะกรณีฉุกเฉิน

---

## 7.5 อย่าเรียก `update_state()` และ `set_state()` ซ้ำ

ตอนนี้ UI เรียกทั้งสองตัว:

```python
update_state(STATE_HOLDING)
set_state(STATE_HOLDING)
```

ให้เหลือ:

```python
set_state(STATE_HOLDING)
```

และ SELL:

```python
set_state(STATE_EMPTY)
```

---

## 7.6 ต่อ `trade_log_api.py`

เพิ่ม import:

```python
from notifier.trade_log_api import send_trade_log
from notifier.discord_notifier import notify_buy_confirmed, notify_sell_confirmed
from db.supabase_writer import (
    get_latest_pending_buy_signal,
    mark_signal_execution,
    open_trade_from_signal,
    get_open_trade,
    close_open_trade,
)
```

ใน confirm BUY:

```python
send_trade_log("BUY", price, f"Confirmed BUY from signal {signal['id']}")
notify_buy_confirmed(signal["id"], price)
```

ใน confirm SELL:

```python
send_trade_log("SELL", price, "Manual confirmed SELL")
notify_sell_confirmed(price, reason="MANUAL_SELL")
```

---

## 8) แก้ `notifier/trade_log_api.py`

ไฟล์นี้โดยรวมใช้ได้แล้ว

สิ่งที่ควรเพิ่มเล็กน้อย:

```python
def send_trade_log(action: str, price: float | str, reason: str) -> bool:
    action = action.upper().strip()
    if action not in ("BUY", "SELL", "HOLD"):
        logger.warning(f"[TradeLog] Unsupported action: {action}")
        return False
```

และเวลา price เป็น `float` ให้ normalize:

```python
payload = {
    "action": action,
    "price": float(price) if price not in (None, "") else price,
    "reason": reason[:1000],
}
```

ไม่ใช่ critical แต่ช่วยกันข้อมูลเสีย

---

## 9) แก้ `logger_setup.py`

ไฟล์นี้ใช้ได้ แต่ถ้า `setup_logging()` ถูกเรียกมากกว่า 1 ครั้ง อาจ add handler ซ้ำ ทำให้ log ซ้ำหลายบรรทัด

เพิ่ม guard:

```python
def setup_logging():
    Path("logs").mkdir(exist_ok=True)

    sys_log = logging.getLogger("system")
    trd_log = logging.getLogger("trading")

    if sys_log.handlers or trd_log.handlers:
        return

    ... rest of setup ...
```

หรือเคลียร์ handler เดิมก่อน add ใหม่

---

## 10) `requirements.txt`

ไฟล์นี้รันได้ แต่ใหญ่มากและมี dependency จำนวนมากที่ไม่จำเป็นสำหรับ bot

สำหรับ MVP ต้องมีอย่างน้อย:

```text
python-dotenv
pandas
numpy
pytz
httpx
supabase
apscheduler
xgboost
gradio
```

สิ่งที่ต้องเช็ก:

```bash
python -c "import xgboost, supabase, gradio, apscheduler, httpx, pandas, numpy; print('ok')"
```

ถ้า install ช้า/พัง ให้ทำ `requirements_mvp.txt` แยก:

```text
python-dotenv
pandas
numpy
pytz
httpx
supabase==2.28.3
apscheduler
xgboost
gradio
```

---

## 11) เชื่อมกับ `orchestrator.py` จากแผนก่อนหน้า

หลังทำ module helper แล้ว ให้กลับไปแก้ `orchestrator.py` ให้ใช้ของใหม่

## 11.1 BUY passed

ถ้า `REQUIRE_BUY_CONFIRM=true`:

```text
BUY passed
→ signal_record.execution_status = PENDING_CONFIRM
→ insert_signal
→ insert_bar_log
→ notify_buy_signal(... WAITING_CONFIRM ...)
→ state ยัง EMPTY
→ tp_manager ยัง inactive
```

ถ้า `REQUIRE_BUY_CONFIRM=false`:

```text
BUY passed
→ auto open trade
→ set_state(HOLDING)
→ tp_manager activate
```

แต่รอบนี้แนะนำให้ใช้ true

---

## 11.2 SELL passed

ถ้า `AUTO_CONFIRM_SELL=true`:

```text
SELL passed
→ close_open_trade(exit_bid=gate_result['hsh_bid'])
→ set_state(EMPTY)
→ mark signal CONFIRMED
→ send_trade_log SELL
→ notify_sell_signal
→ tp_manager.reset()
```

ถ้า `AUTO_CONFIRM_SELL=false`:

```text
SELL passed
→ execution_status = PENDING_CONFIRM
→ notify SELL waiting confirm
→ state ยัง HOLDING จนกด Confirm SELL
```

สำหรับพรุ่งนี้ให้ใช้ `AUTO_CONFIRM_SELL=true` ก่อน เพื่อให้ “sell ต้องออกและอัปเดตได้จริง”

---

## 11.3 Forced SELL จาก SL/TRAIL

เมื่อ `tp_trigger in ('TRAIL_HIT', 'SL_HIT')`:

```text
1. เช็ก current_state == HOLDING
2. เช็ก tp_manager.is_active == True
3. insert forced SELL signal
4. close_open_trade(exit_bid, reason=FORCED_BY_SL_HIT/TRAIL_HIT)
5. mark forced signal AUTO_EXITED
6. set_state(EMPTY)
7. send_trade_log SELL
8. notify_sell_signal
9. tp_manager.reset()
10. return กัน duplicate
```

---

## 12) วิธีทดสอบหลังแก้ module

## Test A — migrate schema

รัน SQL แล้วเช็ก:

```sql
SELECT * FROM v3_system_state;
SELECT column_name FROM information_schema.columns WHERE table_name = 'v3_signals';
SELECT * FROM v3_active_trades LIMIT 5;
```

Expected:

```text
v3_system_state มี id=1 current_position=EMPTY
v3_signals มี rationale_text, top_shap_features, execution_status
v3_active_trades เปิดดูได้ไม่ error
```

---

## Test B — run bot dry run

`.env`:

```env
DRY_RUN=true
REQUIRE_BUY_CONFIRM=true
AUTO_CONFIRM_SELL=true
```

รัน:

```bash
python main.py
```

Expected:

```text
ไม่มี import error
scheduler start
heartbeat ได้
pipeline ไม่พังเพราะ schema field
```

---

## Test C — BUY pending

ทำให้ BUY passed ใน dev/mock แล้วเช็ก:

```text
v3_signals.signal_type = BUY
v3_signals.passed = true
v3_signals.execution_status = PENDING_CONFIRM
v3_system_state.current_position ยังเป็น EMPTY
v3_active_trades ยังไม่มี OPEN trade
Discord ขึ้น WAITING CONFIRM
```

---

## Test D — Confirm BUY UI

รัน:

```bash
python tools/confirm_trade_ui.py
```

เปิด UI แล้วกด confirm BUY

Expected:

```text
v3_active_trades มี row status=OPEN
entry_signal_id ตรงกับ BUY signal
entry_ask = ราคาที่กรอกจริง
v3_signals.execution_status = CONFIRMED
v3_system_state.current_position = HOLDING
Discord แจ้ง BUY CONFIRMED
Trade Log API ถูกส่ง หรือ DRY_RUN log ขึ้น
```

---

## Test E — SELL auto update

ตอน state เป็น HOLDING ให้ทำให้ SELL passed หรือ forced exit

Expected:

```text
v3_signals มี SELL passed=true
v3_active_trades row เดิม status=CLOSED
exit_bid ถูกบันทึก
exit_reason ถูกบันทึก
v3_system_state.current_position = EMPTY
TP manager reset
Discord แจ้ง SELL
Trade Log API ถูกส่ง
```

---

## Test F — SL_HIT ไม่ crash

mock ให้ `tp_trigger = SL_HIT`

Expected:

```text
notify_dynamic_tp ไม่ KeyError
forced SELL ทำงานครบ
state กลับ EMPTY
```

---

## 13) Checklist แก้ไฟล์แบบสั้น

## `supabase_schema.sql`

```text
[ ] แก้ INSERT INTO system_state → v3_system_state
[ ] เพิ่ม rationale_text ใน v3_signals
[ ] เพิ่ม top_shap_features ใน v3_signals
[ ] เพิ่ม execution_status / confirmed_at / confirmed_price / confirm_note / updated_at
[ ] เพิ่ม v3_active_trades table
```

## `config/settings.py`

```text
[ ] เพิ่ม REQUIRE_BUY_CONFIRM
[ ] เพิ่ม AUTO_CONFIRM_SELL
[ ] เพิ่ม table name configs
[ ] optional เพิ่ม CONFIRM_UI_USER/PASS/PORT
```

## `db/supabase_writer.py`

```text
[ ] insert_signal return bool
[ ] insert_bar_log return bool
[ ] get_signal_by_id
[ ] get_latest_pending_buy_signal
[ ] mark_signal_execution
[ ] get_open_trade
[ ] open_trade_from_signal
[ ] close_open_trade
[ ] code ใหม่ใช้ set_state เป็นหลัก ไม่เรียก update_state ซ้ำ
```

## `notifier/discord_notifier.py`

```text
[ ] เพิ่ม SL_HIT message
[ ] ใช้ messages.get() fallback
[ ] ลบ nested duplicate notify_dynamic_tp
[ ] เพิ่ม notify_buy_confirmed
[ ] เพิ่ม notify_sell_confirmed
[ ] BUY signal message ต้องบอก WAITING_CONFIRM
```

## `notifier/trade_log_api.py`

```text
[ ] validate action BUY/SELL/HOLD
[ ] normalize price เป็น float
[ ] limit reason length
```

## `tools/confirm_trade_ui.py`

```text
[ ] fetch latest pending BUY แยกจาก latest signal
[ ] show open trade
[ ] confirm_buy validate pending BUY
[ ] confirm_buy open active trade
[ ] confirm_buy mark signal CONFIRMED
[ ] confirm_buy set_state(HOLDING)
[ ] confirm_buy send trade log
[ ] confirm_buy notify Discord
[ ] confirm_sell close active trade
[ ] confirm_sell set_state(EMPTY)
[ ] confirm_sell send trade log
[ ] confirm_sell notify Discord
[ ] เลิกเรียก update_state + set_state ซ้ำ
```

## `logger_setup.py`

```text
[ ] เพิ่ม guard กัน duplicate handlers
```

## `requirements.txt`

```text
[ ] เช็ก import packages จำเป็น
[ ] optional ทำ requirements_mvp.txt ถ้า install ทั้งไฟล์ใหญ่เกิน
```

---

## 14) สรุปลำดับ commit ที่แนะนำ

```text
Commit 1: schema fix
- fix v3_system_state insert
- add signal execution columns
- add v3_active_trades

Commit 2: db helpers
- supabase_writer trade/signal helper functions

Commit 3: discord/trade log/logger fixes
- SL_HIT notifier
- confirm notifiers
- trade_log validation
- logger guard

Commit 4: confirm UI refactor
- confirm BUY/Sell writes active trade
- validate signal/state

Commit 5: orchestrator integration
- BUY pending confirm
- SELL closes active trade
- forced SELL closes active trade
- TP sync

Commit 6: dry-run tests and manual test notes
```

---

## 15) สรุปสุดท้าย

ไฟล์ที่ส่งมาชุดนี้ **เพียงพอแล้ว** สำหรับทำให้ project รันเป็น MVP production flow ได้

แต่ตอนนี้ module รอบข้างยังมีช่องโหว่สำคัญ:

```text
1. schema ยังไม่ตรงกับ code insert จริง
2. ไม่มี active trade table
3. confirm UI แค่ toggle state ยังไม่ใช่ confirm execution จริง
4. Discord TP notifier จะพังเมื่อ SL_HIT
5. Trade Log API ยังไม่ได้ถูกต่อกับ confirm flow
```

ให้ทำแผนก่อนหน้าเพื่อแก้ `orchestrator.py` ก่อน แล้วทำไฟล์นี้ต่อทันที ระบบถึงจะได้ flow ที่ถูกต้อง:

```text
BUY signal → pending confirm
Confirm BUY → open trade + HOLDING
SELL/SL/TRAIL → close trade + EMPTY
Discord + Supabase + Trade Log อัปเดตครบ
```
