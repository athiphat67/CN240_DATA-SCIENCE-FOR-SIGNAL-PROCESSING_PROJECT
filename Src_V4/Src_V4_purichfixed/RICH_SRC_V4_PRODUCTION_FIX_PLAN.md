# RICH — Src_V4 Production Fix Plan

> เป้าหมายของรอบนี้: **ทำให้ระบบใช้จริงพรุ่งนี้ได้**  
> ไม่ใช่ทำ research v12/v13 ใหม่ และไม่ใช่ retrain model ใหม่

---

## 0) สรุปภาพรวมที่ต้องแก้

ตอนนี้ Src_V4 มี flow ประมาณนี้:

```text
M10 scheduler
→ build_candles()
→ compute_features()
→ run_inference()
→ evaluate_signal_gate()
→ build_trade_payload()
→ build_signal_record()
→ insert_signal()
→ insert_bar_log()
→ update state
→ notify Discord
```

ปัญหาหลักคือ **BUY signal ผ่านแล้วระบบถือว่า “ซื้อจริงแล้ว” ทันที**

```text
BUY passed
→ tp_manager.activate()
→ set_state(HOLDING)
→ update_state(HOLDING)
→ notify BUY
```

แต่ goal ที่เพื่อนบอกคือ:

```text
BUY signal ต้องออกจริง
→ ตอนเทรดต้องมีการกด confirm จริง
→ หลัง confirm ถึงถือว่าเข้า position
→ SELL ต้องออกและ update state ได้จริง
```

ดังนั้นรอบนี้ต้องเปลี่ยนระบบจาก:

```text
BUY signal = ซื้อแล้ว
```

เป็น:

```text
BUY signal = รอคน confirm
confirm BUY = ซื้อจริง
หลัง confirm = HOLDING + TP/SL/Trail เริ่มทำงาน
SELL / SL / Trail = ออกจริง + update state EMPTY
```

---

## 1) Scope ของรอบนี้

### ต้องทำ

```text
[ ] ทำ BUY signal ให้ไม่เปลี่ยน state เป็น HOLDING ทันที
[ ] ทำ BUY signal ให้ไม่ activate TP manager ทันที
[ ] เพิ่ม flow confirm BUY
[ ] หลัง confirm BUY ค่อย set_state(HOLDING)
[ ] หลัง confirm BUY ค่อย activate / sync TP manager
[ ] ทำ SELL ให้ update state EMPTY ได้จริง
[ ] ทำ forced SELL จาก SL_HIT / TRAIL_HIT ให้ทำงานเฉพาะหลัง confirm BUY แล้ว
[ ] เพิ่ม logging/debug เพื่อรู้ว่าทำไม BUY ไม่ออก
[ ] แก้ rationale ให้ส่ง state_before และรองรับ HOLDING
```

### ยังไม่ควรทำในรอบนี้

```text
[ ] ยังไม่เพิ่ม v13 multi-timeframe features
[ ] ยังไม่ทำ gate regressor ใหม่
[ ] ยังไม่ ensemble
[ ] ยังไม่ retrain model
[ ] ยังไม่แก้สูตร feature_engine.py ถ้าไม่ได้เจอ bug ชัดเจน
[ ] ยังไม่เอา v12/v13 feature set มาใส่ Src_V4 โดยตรง
[ ] ยังไม่รัน final holdout ซ้ำแบบมั่ว ๆ
```

เหตุผล: goal คือ production flow พรุ่งนี้ ไม่ใช่ research improvement รอบใหม่

---

## 2) ไฟล์ที่ต้องแก้จริง

## 2.1 `scheduler/orchestrator.py` — ไฟล์หลักที่สุด

### หน้าที่ปัจจุบัน

ไฟล์นี้เป็นตัวคุม pipeline ทั้งหมด:

```text
build_candles()
→ compute_features()
→ run_inference()
→ evaluate_signal_gate()
→ TP manager update
→ forced sell
→ build rationale
→ build signal record
→ insert Supabase
→ update state
→ notify Discord
```

### ปัญหาที่ต้องแก้

#### ปัญหา A — BUY signal activate TP manager ทันที

ปัจจุบันมี block ประมาณนี้:

```python
if gate_result["passed"]:
    if gate_result["signal_type"] == "BUY":
        sl_price = gate_result["hsh_ask"] - (features_row["F_ATR_48"] * 1.0)
        tp_manager.activate(
            entry_ask=gate_result["hsh_ask"],
            entry_score=gate_result["ranker_score"],
            initial_bid=gate_result["hsh_bid"],
            sl_price=sl_price,
        )
```

ต้องเปลี่ยนเป็น:

```text
ถ้า BUY signal passed:
    ห้าม tp_manager.activate()
    ให้รอ confirm BUY ก่อน

ถ้า SELL signal passed:
    reset TP manager ได้เหมือนเดิม หลัง state ถูก update EMPTY
```

#### ปัญหา B — BUY signal set_state(HOLDING) ทันที

ปัจจุบันมี block ประมาณนี้:

```python
if signal_type == "BUY":
    update_state(STATE_HOLDING)
    set_state(STATE_HOLDING)
    notify_buy_signal(gate_result, rationale_payload)
```

ต้องเปลี่ยนเป็น:

```python
if signal_type == "BUY":
    # 1) บันทึก signal ไปแล้วตามเดิม
    # 2) แจ้งเตือน BUY signal
    notify_buy_signal(gate_result, rationale_payload)

    # 3) ห้ามเปลี่ยน position state ตอนนี้
    # update_state(STATE_HOLDING)  # REMOVE / COMMENT OUT
    # set_state(STATE_HOLDING)     # REMOVE / COMMENT OUT

    trading_log.info(
        f"BUY signal sent — WAITING_CONFIRM | score={_last_score:.4f} | signal_id={gate_result['signal_id']}"
    )
```

Expected result:

```text
ก่อน BUY: state = EMPTY
BUY signal ออก: state ยังต้องเป็น EMPTY
หลัง confirm BUY: state ถึงเป็น HOLDING
```

#### ปัญหา C — TP manager update ทุก M10 ทั้งที่ยังไม่ได้ confirm

ปัจจุบัน `tp_manager.update()` ถูกเรียกทุก M10 หลัง inference

ต้อง guard เพิ่ม:

```python
current_state = get_current_state()

if current_state == STATE_HOLDING and tp_manager.is_active:
    tp_trigger, tp_price, trail_level = tp_manager.update(...)
else:
    tp_trigger, tp_price, trail_level = "NONE", None, 0.0
```

และควรมี `sync_tp_state_from_db()` ก่อน update TP manager

---

## 2.2 เพิ่ม function ใหม่ใน `scheduler/orchestrator.py`

### Function: `sync_tp_state_from_db()`

เหตุผล: ถ้า `confirm_buy.py` เป็น script แยก process มันจะ update DB state ได้ แต่ `tp_manager` ใน scheduler process ยังไม่รู้ว่าถือ position แล้ว

ให้เพิ่ม function ประมาณนี้:

```python
def sync_tp_state_from_db(features_row: dict | None = None) -> None:
    """
    Sync in-memory TP manager กับ DB state / active trade

    Rule:
    - DB state = HOLDING และ tp_manager inactive → activate จาก active trade / confirmed BUY ล่าสุด
    - DB state = EMPTY และ tp_manager active → reset
    """
    state = get_current_state()

    if state == STATE_EMPTY:
        if tp_manager.is_active:
            tp_manager.reset()
            trading_log.info("[TP Sync] Reset TP manager because DB state is EMPTY")
        return

    if state == STATE_HOLDING and not tp_manager.is_active:
        # TODO: load active trade from DB
        # Recommended source: v3_active_trade where status = 'OPEN'
        # fallback: latest confirmed BUY signal
        active_trade = load_open_active_trade()

        if not active_trade:
            trading_log.warning("[TP Sync] DB state HOLDING but no active trade found")
            return

        entry_ask = float(active_trade["entry_ask"])
        entry_score = float(active_trade["entry_score"])
        initial_bid = float(active_trade.get("entry_bid_at_signal") or entry_ask)

        atr_48 = None
        if features_row:
            atr_48 = features_row.get("F_ATR_48")

        sl_price = None
        if atr_48 and atr_48 > 0:
            sl_price = entry_ask - (float(atr_48) * 1.0)

        tp_manager.activate(
            entry_ask=entry_ask,
            entry_score=entry_score,
            initial_bid=initial_bid,
            sl_price=sl_price,
        )
        trading_log.info("[TP Sync] TP manager activated from active trade")
```

> หมายเหตุ: function `load_open_active_trade()` ยังไม่มี ต้องเพิ่มใน `db/supabase_writer.py` หรือทำ helper ใหม่

### จุดที่เรียก

ใน `run_signal_pipeline()` หลังได้ `features_row` และ `inference_result` แล้ว ก่อน `tp_manager.update()`:

```python
sync_tp_state_from_db(features_row)
```

---

## 2.3 Forced SELL ใน `scheduler/orchestrator.py`

### ปัจจุบัน

ถ้า `tp_trigger in ("TRAIL_HIT", "SL_HIT")` ระบบ force SELL แล้ว:

```text
update_state(EMPTY)
set_state(EMPTY)
insert forced SELL record
notify_sell_signal
reset tp_manager
return
```

### ต้องเพิ่ม guard

ก่อน forced SELL:

```python
current_state = get_current_state()

if tp_trigger in ("TRAIL_HIT", "SL_HIT"):
    if current_state != STATE_HOLDING or not tp_manager.is_active:
        trading_log.warning(
            f"[TP] Ignored {tp_trigger} because state={current_state}, tp_active={tp_manager.is_active}"
        )
        return
```

เหตุผล: forced SELL ต้องเกิดเฉพาะหลัง confirm BUY แล้วเท่านั้น

### ต้องปิด active trade

หลัง forced SELL ให้เพิ่ม:

```python
close_active_trade(
    exit_signal_id=forced_signal_id,
    exit_bid=exit_bid_price,
    exit_reason=tp_trigger,
)
```

ถ้ายังไม่มี table active trade ให้ใส่ TODO ไว้ก่อน แต่ควรทำให้เสร็จถ้าจะใช้จริง

---

## 2.4 `core/signal_gate.py`

### หน้าที่ปัจจุบัน

ตัดสิน BUY / SELL / HOLD จาก state และ gates

BUY ตอน state `EMPTY`:

```text
market_open
noise_gate
score_gate
srvr_gate
regime_gate
```

SELL ตอน state `HOLDING`:

```text
market_open
noise_gate
score_below_threshold
```

### รอบนี้ยังไม่ควรแก้ logic หลัก

ยังไม่ควรลบ `srvr_gate`, `regime_gate`, `noise_gate` ทันที

### สิ่งที่ควรแก้/เพิ่ม

#### เพิ่ม mode สำหรับ debug หรือ live relaxed แบบ config toggle

ถ้าพรุ่งนี้ BUY ไม่ออกเลย อาจต้องมี `LIVE_RELAXED` แต่ต้องเป็น config ไม่ใช่แก้ถาวร

ตัวอย่าง concept:

```python
if BUY_GATE_MODE == "STRICT":
    passed = all(buy_gates.values())

elif BUY_GATE_MODE == "LIVE_RELAXED":
    passed = (
        buy_gates["market_open"]
        and buy_gates["noise_gate"]
        and buy_gates["score_gate"]
        and (buy_gates["srvr_gate"] or buy_gates["regime_gate"])
    )
```

และต้องเพิ่มใน `gates_detail`:

```python
"buy_gate_mode": BUY_GATE_MODE
```

### ยังไม่ทำถ้าไม่จำเป็น

```text
[ ] ห้ามลด SIGNAL_THRESHOLD มั่ว ๆ
[ ] ห้ามปล่อย BUY จาก HOLD
[ ] ห้ามทำให้ BUY ออกทุกแท่งเพื่อให้ดูเหมือนระบบทำงาน
```

---

## 2.5 `core/state_manager.py`

### ปัจจุบัน

รองรับเฉพาะ:

```text
EMPTY
HOLDING
```

### ห้ามทำ

อย่าเพิ่ม `PENDING_BUY` เป็น `current_position` เพราะจะทำให้ `signal_gate.py` error จาก unknown state

### แนวทางที่ถูก

```text
position state:
- EMPTY
- HOLDING

order/signal status:
- PENDING_CONFIRM
- CONFIRMED
- CANCELLED
- CLOSED
```

ดังนั้น `PENDING_BUY` ต้องเป็นสถานะของ signal/order ไม่ใช่ position state

---

## 2.6 `core/signal_recorder.py`

### ปัจจุบัน

สร้าง record สำหรับ `signals` table รองรับ BUY / SELL / HOLD และแนบ rationale ได้

### ควรเพิ่ม field ถ้า DB รองรับ

```python
"execution_status": gate_result.get("execution_status"),
"confirmed_at": gate_result.get("confirmed_at"),
"confirmed_price": gate_result.get("confirmed_price"),
```

### ถ้ายังไม่อยาก migrate DB

ใช้ convention ไปก่อน:

```text
BUY + passed=True + state_before=EMPTY = pending buy signal
```

แต่ในระยะยาวควรเพิ่ม `execution_status` ใน signals table

---

## 2.7 `rationale/generator.py`

### ปัญหา

ระบบ state ใช้ `HOLDING` แต่ rationale แยก context ด้วย:

```text
LONG
SHORT
EMPTY
```

ถ้าส่ง `HOLDING` ไปตรง ๆ จะเข้า fallback generic ทำให้ข้อความ HOLD อาจผิด context

### ต้องแก้

เพิ่ม normalize state ตอนต้นของ `build_trade_payload()`:

```python
_state = (state_before or "").upper()
if _state == "HOLDING":
    _state = "LONG"
```

หรือเพิ่มใน block HOLD:

```python
_state = (state_before or "").upper()
if _state == "HOLDING":
    _state = "LONG"

if _state == "LONG":
    spread_action = "Maintaining current long position as structural edge remains intact"
elif _state == "SHORT":
    spread_action = "Maintaining current short position as structural edge remains intact"
elif _state == "EMPTY":
    spread_action = "No entry taken — model confidence is below the required threshold"
else:
    spread_action = "No action taken — waiting for clearer confirmation"
```

### ต้องแก้ที่ orchestrator ด้วย

ตอนเรียก `build_trade_payload()` ต้องส่ง `state_before` เข้าไปทุกครั้ง

```python
rationale_payload = build_trade_payload(
    signal_type   = gate_result["signal_type"],
    ranker_score  = inference_result["ranker_score"],
    shap_values   = inference_result.get("shap_values", []),
    feature_names = inference_result.get("feature_names", []),
    current_ask   = gate_result["hsh_ask"],
    current_bid   = gate_result["hsh_bid"],
    state_before  = gate_result["state_before"],
)
```

Forced SELL rationale ก็ให้ส่ง:

```python
state_before="HOLDING"
```

---

## 2.8 `main.py`

### ปัจจุบัน

มี `recover_tp_state()` ตอน startup เพื่อ restore TP manager จาก last BUY signal ถ้า state เป็น HOLDING

### ปัญหา

ทำเฉพาะตอน startup เท่านั้น ถ้ากด confirm BUY ระหว่าง bot running อยู่ TP manager อาจไม่ active จนกว่าจะ restart

### ต้องแก้แนวคิด

ไม่จำเป็นต้องลบ `recover_tp_state()` แต่ต้องเพิ่ม sync ใน `orchestrator.py` ด้วย

```text
main.py recover_tp_state = กันตอน startup
orchestrator.py sync_tp_state_from_db = กันระหว่าง bot running
```

---

## 2.9 `db/supabase_writer.py` — ต้องขอไฟล์เพิ่มก่อนแก้จริง

ไฟล์นี้ยังไม่ได้แนบมาในชุดที่ดูอยู่ แต่จำเป็นสำหรับ implementation จริง

### ต้องเพิ่ม function

```python
def load_open_active_trade() -> dict | None:
    ...

def open_active_trade(entry_signal_id, entry_ask, entry_bid_at_signal, entry_score, entry_time) -> None:
    ...

def close_active_trade(exit_signal_id, exit_bid, exit_reason) -> None:
    ...
```

หรือถ้าไม่อยากเพิ่ม table ใหม่ ให้เพิ่ม function สำหรับ update signals:

```python
def mark_signal_confirmed(signal_id, confirmed_price, confirmed_at) -> None:
    ...
```

---

## 2.10 `notifier/discord_notifier.py` — ต้องขอไฟล์เพิ่มก่อนแก้จริง

ไฟล์นี้ยังไม่ได้แนบมา แต่ควรแก้ข้อความ notify

### BUY signal notify

ต้องบอกชัดว่าเป็น pending confirm:

```text
BUY SIGNAL — WAITING CONFIRM
Signal ID: xxx
Ask: xxx
Score: xxx
Action: ถ้าซื้อจริงแล้วให้ run confirm_buy.py หรือกดปุ่ม Confirm
```

### BUY confirmed notify

```text
BUY CONFIRMED
Entry Ask: xxx
State: HOLDING
TP Manager: Active / Sync next bar
```

### SELL notify

```text
SELL SIGNAL / AUTO EXIT
Exit Bid: xxx
State will be updated to EMPTY
```

ถ้ามี Discord button อยู่แล้ว ต้องดูไฟล์นี้ก่อนว่า implement interaction ยังไง

---

## 3) ไฟล์ใหม่ที่ต้องเพิ่ม

## 3.1 `tools/confirm_buy.py`

### หน้าที่

หลังคนกดซื้อจริงในแอป Gold Now แล้ว ให้ระบบรู้ว่า position เปิดจริงแล้ว

### Input

```bash
python tools/confirm_buy.py --signal-id sig_YYYYMMDD_HHMMSS --price 52000
```

### Logic

```text
1. อ่าน signal_id จาก signals
2. เช็ก signal_type == BUY
3. เช็ก passed == True
4. เช็ก current_position == EMPTY
5. บันทึก active trade เป็น OPEN
6. set_state(HOLDING)
7. แจ้ง Discord ว่า BUY confirmed
```

### Pseudocode

```python
import argparse
from datetime import datetime
import pytz

from core.state_manager import get_current_state, set_state
from config.settings import STATE_EMPTY, STATE_HOLDING, DRY_RUN
from db.supabase_writer import (
    get_signal_by_id,
    open_active_trade,
    mark_signal_confirmed,
)
from notifier.discord_notifier import send_discord

TZ = pytz.timezone("Asia/Bangkok")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--signal-id", required=True)
    parser.add_argument("--price", type=float, required=True)
    args = parser.parse_args()

    signal = get_signal_by_id(args.signal_id)
    if not signal:
        raise RuntimeError(f"Signal not found: {args.signal_id}")

    if signal["signal_type"] != "BUY" or not signal["passed"]:
        raise RuntimeError("Signal is not a valid passed BUY signal")

    state = get_current_state()
    if state != STATE_EMPTY:
        raise RuntimeError(f"Cannot confirm BUY because state is {state}")

    open_active_trade(
        entry_signal_id=args.signal_id,
        entry_ask=args.price,
        entry_bid_at_signal=signal.get("hsh_bid_price"),
        entry_score=signal.get("ranker_score"),
        entry_time=datetime.now(TZ).isoformat(),
    )

    mark_signal_confirmed(
        signal_id=args.signal_id,
        confirmed_price=args.price,
        confirmed_at=datetime.now(TZ).isoformat(),
    )

    set_state(STATE_HOLDING)
    send_discord(
        f"✅ BUY CONFIRMED | signal `{args.signal_id}` | entry ask `{args.price:,.2f}` | state `HOLDING` | DRY_RUN `{DRY_RUN}`"
    )


if __name__ == "__main__":
    main()
```

---

## 3.2 `tools/confirm_sell.py` — optional แต่แนะนำ

ถ้าขายแบบ manual และต้อง confirm เหมือน BUY ให้เพิ่มไฟล์นี้

### Input

```bash
python tools/confirm_sell.py --price 52100 --reason MANUAL_SELL
```

### Logic

```text
1. เช็ก current_position == HOLDING
2. โหลด active trade ที่ OPEN
3. close active trade
4. set_state(EMPTY)
5. reset TP manager รอบถัดไปผ่าน sync
6. แจ้ง Discord ว่า SELL confirmed
```

ถ้าเพื่อนยอมให้ SELL signal = update EMPTY ทันที ยังไม่ต้องทำไฟล์นี้ใน MVP

---

## 4) DB schema ที่ควรเพิ่ม

## 4.1 Table: `v3_active_trade`

แนะนำให้มี table นี้เพื่อแยก “signal” กับ “trade จริง”

```sql
CREATE TABLE IF NOT EXISTS v3_active_trade (
    id BIGINT PRIMARY KEY DEFAULT 1,
    entry_signal_id TEXT NOT NULL,
    entry_time TIMESTAMPTZ NOT NULL,
    entry_ask DOUBLE PRECISION NOT NULL,
    entry_bid_at_signal DOUBLE PRECISION,
    entry_score DOUBLE PRECISION,
    status TEXT NOT NULL DEFAULT 'OPEN',
    exit_signal_id TEXT,
    exit_time TIMESTAMPTZ,
    exit_bid DOUBLE PRECISION,
    exit_reason TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT single_active_trade CHECK (id = 1)
);
```

แนวคิดคือมีได้ 1 active trade เท่านั้น เพราะระบบ long-only และ state มีแค่ EMPTY/HOLDING

## 4.2 เพิ่ม columns ใน `signals` table ถ้าทำได้

```sql
ALTER TABLE signals
    ADD COLUMN IF NOT EXISTS execution_status TEXT,
    ADD COLUMN IF NOT EXISTS confirmed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS confirmed_price DOUBLE PRECISION;
```

Status ที่ใช้:

```text
PENDING_CONFIRM
CONFIRMED
CANCELLED
AUTO_EXITED
CLOSED
```

ถ้าไม่อยาก migrate วันนี้ ให้ยังไม่เพิ่มก็ได้ แต่ production จริงควรมี

---

## 5) ลำดับการแก้จริงแบบไม่พัง

## Step 1 — รัน baseline เดิมก่อน

```bash
python main.py
```

หรือถ้ามีวิธี run pipeline เดี่ยว:

```bash
python -c "from scheduler.orchestrator import run_signal_pipeline; run_signal_pipeline()"
```

ต้องเช็กว่า:

```text
[ ] build_candles ผ่าน
[ ] compute_features ผ่าน
[ ] run_inference ผ่าน
[ ] ranker_score ออก
[ ] evaluate_signal_gate ออก HOLD/BUY/SELL
[ ] insert_signal ได้
[ ] insert_bar_log ได้
[ ] Discord ส่งได้
```

## Step 2 — แก้ BUY ไม่ให้ set HOLDING

แก้เฉพาะ `orchestrator.py` ก่อน

Expected:

```text
BUY signal ออก
state ยัง EMPTY
TP manager inactive
Discord แจ้ง WAITING_CONFIRM
```

## Step 3 — เพิ่ม `confirm_buy.py`

หลัง confirm:

```text
state = HOLDING
active_trade = OPEN
Discord แจ้ง BUY CONFIRMED
```

## Step 4 — เพิ่ม TP sync

หลัง confirm แล้วไม่ต้อง restart bot

Expected:

```text
รอบ M10 ถัดไป: tp_manager active จาก active_trade
```

## Step 5 — ทดสอบ SELL

Mock หรือรอสถานการณ์ที่ SELL ผ่าน

Expected:

```text
SELL signal ออก
state = EMPTY
active_trade CLOSED
tp_manager reset
```

## Step 6 — ทดสอบ forced SELL

Mock ให้ current_bid <= SL หรือ trail

Expected:

```text
forced SELL record ถูก insert
state = EMPTY
active_trade CLOSED
tp_manager reset
ไม่มี duplicate SELL
```

## Step 7 — เพิ่ม debug log

ทุก bar ควรเห็น:

```text
bar_time
session
state_before
ranker_score
signal_type
passed
reject_reason
gates_detail
hsh_ask
hsh_bid
atr_48
tp_manager_active
```

---

## 6) Test checklist ก่อนส่งงาน

## BUY pending test

```text
[ ] state เริ่มที่ EMPTY
[ ] mock หรือรอ BUY signal
[ ] signals มี BUY passed=True
[ ] state ยัง EMPTY หลัง BUY signal
[ ] TP manager ยัง inactive
[ ] Discord บอก WAITING CONFIRM
```

## Confirm BUY test

```text
[ ] run confirm_buy.py ด้วย signal_id ล่าสุด
[ ] state เปลี่ยนเป็น HOLDING
[ ] v3_active_trade status = OPEN
[ ] Discord บอก BUY CONFIRMED
[ ] รอบถัดไป TP manager active
```

## Model SELL test

```text
[ ] state = HOLDING
[ ] score ต่ำกว่า threshold
[ ] SELL signal ออก
[ ] state เปลี่ยนเป็น EMPTY
[ ] active_trade CLOSED
[ ] TP manager reset
```

## Forced SELL test

```text
[ ] state = HOLDING
[ ] tp_manager active
[ ] current_bid <= SL หรือ current_bid <= trail
[ ] forced SELL ออก
[ ] state EMPTY
[ ] active_trade CLOSED
[ ] return กัน duplicate SELL
```

## Rationale test

```text
[ ] BUY ใช้ Ask price
[ ] SELL ใช้ Bid price
[ ] HOLD ตอน EMPTY บอก no entry / waiting
[ ] HOLD ตอน HOLDING บอก maintaining long position
[ ] strength_pct อยู่ใน 0-100
```

---

## 7) ถ้า BUY ไม่ออกเลย ให้ทำอย่างไร

ห้ามลด threshold มั่วทันที

ให้ดู `reject_reason` ก่อน:

```text
score_gate   → score ไม่ถึง threshold
srvr_gate    → session volatility ไม่พอ
regime_gate  → regime ไม่ตรง
noise_gate   → spread/noise สูงเกิน
market_open  → session closed
```

ถ้าจำเป็นจริง ให้เพิ่ม `BUY_GATE_MODE` ใน config:

```text
STRICT:
  market_open + noise + score + srvr + regime ต้องผ่านทั้งหมด

LIVE_RELAXED:
  market_open + noise + score ต้องผ่าน
  และ srvr หรือ regime ผ่านอย่างน้อยหนึ่งตัว
```

แต่ต้อง log ชัด ๆ ว่า signal นั้นมาจาก mode ไหน

---

## 8) ไฟล์ที่ควรขอเพิ่มจากทีมก่อนเขียน patch จริง

สำหรับแผนนี้ **ไม่ต้องใช้ model เพิ่มแล้ว** แต่ถ้าจะเขียน patch code ให้แม่น ต้องขอไฟล์เหล่านี้เพิ่ม:

```text
[ ] config/settings.py
[ ] db/supabase_writer.py
[ ] notifier/discord_notifier.py
[ ] schema ของ Supabase tables: signals, bar_logs, v3_system_state
[ ] ถ้ามีอยู่แล้ว: SQL migration scripts
[ ] ถ้ามีอยู่แล้ว: Discord interaction/button handler
[ ] ถ้ามีอยู่แล้ว: command หรือ API ที่ใช้ confirm trade
```

Model file เพิ่มจะจำเป็นเฉพาะกรณีนี้:

```text
[ ] ต้องการเปลี่ยนจาก v11 เป็น v12/v13 model จริง
[ ] ต้อง validate feature schema ของ model ใหม่
[ ] ต้อง retrain / compare model output
```

แต่สำหรับ goal “พรุ่งนี้ใช้จริง” ให้ใช้ model เดิมก่อน แล้วแก้ execution flow ก่อน

---

## 9) สรุปงานริช vs โจม

## ริช

```text
[ ] orchestrator.py: BUY pending confirm
[ ] orchestrator.py: TP sync from DB
[ ] tools/confirm_buy.py
[ ] DB active_trade flow
[ ] rationale state_before
[ ] debug log / reject_reason
[ ] model schema sanity check
```

## โจม

```text
[ ] dynamic_tp_manager.py behavior review
[ ] forced SELL guard
[ ] close active_trade on SELL
[ ] verify sell price uses Bid
[ ] decide SCORE_FADE = warning or forced sell
[ ] verify no duplicate SELL in same bar
```

---

## 10) Final expected production flow

```text
EMPTY
→ run_signal_pipeline()
→ BUY signal passed
→ insert_signal(BUY, passed=True, execution_status=PENDING_CONFIRM)
→ notify BUY WAITING_CONFIRM
→ state remains EMPTY

manual trade in Gold Now
→ run confirm_buy.py --signal-id xxx --price actual_ask
→ active_trade OPEN
→ set_state(HOLDING)
→ notify BUY CONFIRMED

next M10
→ sync_tp_state_from_db()
→ tp_manager active
→ monitor SELL / SL / TRAIL

SELL or forced SELL
→ insert_signal(SELL)
→ close active_trade
→ set_state(EMPTY)
→ tp_manager.reset()
→ notify SELL
```

นี่คือ MVP ที่ต้องเสร็จก่อนค่อยกลับไปทำ v12/v13 model improvement
