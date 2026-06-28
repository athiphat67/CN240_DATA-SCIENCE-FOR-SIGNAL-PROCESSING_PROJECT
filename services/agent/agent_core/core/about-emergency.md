# Emergency Session Modes

เอกสารนี้อธิบาย logic ปัจจุบันของ `emergency_buy_mode` และ `emergency_sell_mode`
ใน flow หลักของ `Src/agent_core/core/session_gate.py`,
`Src/ui/core/services.py`, `Src/agent_core/core/prompt.py`, และ
`Src/agent_core/core/risk.py`

## ภาพรวม

Emergency mode เป็นระบบกันปัญหา session ใกล้หมดเวลาแล้ว agent ยังไม่ได้เข้าไม้
หรือยังถือทองอยู่ก่อนจบ session

มี 2 mode หลัก:

- `emergency_buy_mode`: ใช้เมื่อ session ใกล้หมด, ยังไม่ได้เทรดเลยใน session นี้, และยังไม่ได้ถือทอง
- `emergency_sell_mode`: ใช้เมื่อ session ใกล้หมดมากและยังถือทองอยู่

`SessionGate` เป็น source of truth สำหรับการตัดสินว่าเข้า emergency หรือไม่
ส่วน `RiskManager` เป็นด่านสุดท้ายที่บังคับใช้ผลจริงก่อนส่ง final decision ออกไป

## ค่าคงที่หลัก

อยู่ใน `Src/agent_core/core/session_gate.py`

```python
EMERGENCY_BUY_RELAX_MINUTES = 60
EMERGENCY_BUY_FORCE_MINUTES = 45
EMERGENCY_BUY_MAX_TRADES_THIS_SESSION = 0
EMERGENCY_SELL_MINUTES = 8
```

ความหมาย:

- เหลือเวลาไม่เกิน 60 นาที: เริ่มพิจารณา emergency buy แบบ `relaxed`
- เหลือเวลาไม่เกิน 45 นาที: ยกระดับเป็น emergency buy แบบ `forced`
- ต้องมีจำนวน trade ใน session นี้เท่ากับ 0 เท่านั้น จึงเข้า emergency buy
- เหลือเวลาไม่เกิน 8 นาทีและยังถือทองอยู่ จะเข้า emergency sell

## ขั้นตอนที่ 1: services.py สร้าง runtime context

ไฟล์หลัก: `Src/ui/core/services.py`

ใน `_run_single_interval()` ระบบทำงานตามลำดับนี้:

1. เรียก `resolve_session_gate(force_bypass=bypass_session_gate)`
2. อ่าน portfolio ปัจจุบันจาก `market_state["portfolio"]`
3. นับจำนวน trade ของ session ปัจจุบันผ่าน `_resolve_session_trade_count()`
4. ถ้ามี database และมี `session_start_iso` จะนับจาก `trade_log` ด้วย `get_trades_count_since(session_start_iso)`
5. ถ้านับจาก `trade_log` ไม่ได้ จะ fallback ไปใช้ `portfolio["trades_this_session"]`
6. inject ค่า `trades_this_session` และ `trades_this_session_source` กลับเข้า portfolio
7. ดึง `gold_grams` ปัจจุบันจาก portfolio
8. เรียก `attach_session_gate_to_market_state(market_state, gate_res, trades_this_session, gold_grams)`

จุดสำคัญคือ emergency mode ไม่ได้ดูแค่เวลา แต่ดูสถานะ runtime จริงด้วย:

- เทรดไปแล้วกี่ครั้งใน session นี้
- ถือทองอยู่หรือไม่
- session ยังเปิดอยู่หรือไม่

## ขั้นตอนที่ 2: session_gate.py ตัดสิน emergency_sell ก่อน

ไฟล์หลัก: `Src/agent_core/core/session_gate.py`

ใน `attach_session_gate_to_market_state()` ระบบคำนวณ `is_emergency_sell` ก่อน buy:

```python
is_emergency_sell = (
    mins_left is not None
    and mins_left <= EMERGENCY_SELL_MINUTES
    and held_gold > 1e-4
)
```

แปลเป็นขั้นตอน:

1. ต้องรู้เวลาที่เหลือของ session (`mins_left`)
2. เวลาที่เหลือต้องไม่เกิน 8 นาที
3. portfolio ต้องยังถือทองมากกว่า `0.0001` gram

ถ้าเข้าเงื่อนไข:

```python
session_gate["is_emergency_sell"] = True
session_gate["is_emergency_buy"] = False
session_gate["emergency_mode"] = "forced_sell"
session_gate["emergency_reason"] = "Session ends in ... mins and portfolio holds ...g."
```

เหตุผลที่ sell มาก่อน buy:

- ถ้ายังถือทองอยู่ใกล้จบ session เป้าหมายหลักคือปิดสถานะ
- ระบบไม่ควรเปิด buy ใหม่ขณะที่ยังถือทอง
- ป้องกันการติดสถานะข้ามช่วงเวลาที่ไม่ต้องการ

## ขั้นตอนที่ 3: session_gate.py ตัดสิน emergency_buy

หลังจากตรวจ sell แล้ว ระบบจึงตรวจ buy:

```python
if (
    not is_emergency_sell
    and mins_left is not None
    and held_gold <= 1e-4
    and int(trades_this_session or 0) <= EMERGENCY_BUY_MAX_TRADES_THIS_SESSION
):
    if mins_left <= EMERGENCY_BUY_FORCE_MINUTES:
        emergency_buy_stage = "forced"
    elif mins_left <= EMERGENCY_BUY_RELAX_MINUTES:
        emergency_buy_stage = "relaxed"
```

เงื่อนไขต้องครบทั้งหมด:

1. ต้องไม่เข้า emergency sell
2. ต้องรู้เวลาที่เหลือของ session
3. ต้องไม่ได้ถือทอง (`held_gold <= 1e-4`)
4. ต้องยังไม่ได้เทรดใน session นี้ (`trades_this_session <= 0`)
5. ต้องเหลือเวลาไม่เกิน 60 นาที จึงเริ่ม emergency buy

การแบ่ง stage:

- `mins_left <= 45`: `emergency_buy_stage = "forced"`
- `45 < mins_left <= 60`: `emergency_buy_stage = "relaxed"`
- `mins_left > 60`: ไม่เข้า emergency buy

เมื่อเข้า emergency buy:

```python
session_gate["is_emergency_buy"] = True
session_gate["is_emergency_sell"] = False
session_gate["emergency_mode"] = "forced_buy"
session_gate["emergency_buy_stage"] = "relaxed" | "forced"
```

หมายเหตุ:

- `emergency_mode` เป็น `"forced_buy"` ทั้ง stage `relaxed` และ `forced`
- ตัวที่แยก stage จริงคือ `emergency_buy_stage`
- `emergency_reason` มี prefix `[RELAXED]` หรือ `[FORCED]` เพื่อให้ log/UI แยกได้ง่าย

## ขั้นตอนที่ 4: role selection ใน services.py

หลังจากแนบ `session_gate` แล้ว `services.py` ใช้ `emergency_mode` เพื่อเลือก role:

- `emergency_mode == "forced_buy"` -> ใช้ `AIRole.AGGRESSIVE_BULLISH`
- `emergency_mode == "forced_sell"` -> ใช้ `AIRole.DEFENSIVE_SCAVENGER`
- ถ้าไม่มี emergency mode -> เลือก role ตาม market regime

ผลคือทั้ง `relaxed` และ `forced` buy stage จะถูก route ไปทาง aggressive role เหมือนกัน
แต่ final behavior ยังต่างกันใน `RiskManager` ผ่าน `emergency_buy_stage`

## ขั้นตอนที่ 5: prompt.py ส่ง emergency directive ให้ LLM

ไฟล์หลัก: `Src/agent_core/core/prompt.py`

`PromptBuilder._build_emergency_directive()` อ่าน `market_state["session_gate"]`
แล้ว inject directive เข้า prompt

### Emergency Sell Directive

ถ้า `is_emergency_sell=True`:

```text
URGENT: Session ends in {mins_left} mins.
SELL ALL gold immediately. Profit/Loss is irrelevant.
Market exit is mandatory.
```

ผลคือ LLM ถูกสั่งให้ขายทันที ไม่สนกำไรขาดทุน

### Emergency Buy Directive: forced

ถ้า `emergency_buy_stage == "forced"`:

```text
URGENT (FORCED): Session ends in {mins_left} mins.
Zero trades completed. EXECUTE BUY IMMEDIATELY —
ignore edge score, spread coverage, and HTF trend gates.
Do not wait for further confirmation.
```

ผลคือ LLM ถูกสั่งให้เลือก BUY ทันที

### Emergency Buy Directive: relaxed

ถ้า `emergency_buy_stage == "relaxed"` หรือ legacy caller ส่งแค่
`is_emergency_buy=True` โดยไม่มี stage:

```text
URGENT: Session ends in {mins_left} mins.
Zero trades completed. RELAX all technical gates.
Find any reasonable support or momentum to ENTER now.
```

ผลคือ LLM ยังมีพื้นที่พิจารณา setup แต่ไม่ควรเข้มเหมือนโหมดปกติ

## ขั้นตอนที่ 6: risk.py บังคับ emergency_sell

ไฟล์หลัก: `Src/agent_core/core/risk.py`

`RiskManager.evaluate()` ตรวจ `is_emergency_sell` ก่อน buy:

```python
_force_sell_active = bool(session_gate.get("is_emergency_sell"))
```

ถ้าเป็น emergency sell:

```python
final_decision["signal"] = "SELL"
final_decision["confidence"] = 1.0
final_decision["entry_price"] = sell_price_thb
final_decision["position_size_thb"] = 0.0
final_decision["rationale"] = "[SESSION FORCE SELL] ..."
signal = "SELL"
```

จากนั้น flow จะลงไปที่ SELL processing:

1. ตรวจว่ามีทองพอขาย (`gold_grams > 1e-4`)
2. bypass minimum profit filter เพราะ rationale มี `[SESSION FORCE SELL]`
3. คำนวณมูลค่าทองที่จะขาย:

```python
gold_value_thb = gold_grams * (sell_price_thb / 15.244)
```

4. คืน final decision เป็น `SELL`

สรุป emergency sell เป็น hard override แบบเต็ม:

- LLM ตอบ `HOLD` ก็ถูกเปลี่ยนเป็น `SELL`
- LLM ตอบ `BUY` ก็ถูกเปลี่ยนเป็น `SELL`
- confidence ถูกตั้งเป็น `1.0`
- profit/loss ไม่ใช่ตัวตัดสินหลัก
- แต่ยังต้องมีทองจริงให้ขาย

## ขั้นตอนที่ 7: risk.py จัดการ emergency_buy แบบ relaxed

ถ้า `emergency_buy_stage == "relaxed"`:

```python
_relaxed_buy_active = signal != "SELL" and emergency_buy_stage == "relaxed"
```

ระบบจะไม่ยึดอำนาจ LLM ทันที
แปลว่า LLM ยังต้องตอบ `BUY` เอง ถ้า LLM ตอบ `HOLD` ก็ยังคง `HOLD`

ถ้า LLM ตอบ `BUY` ใน relaxed mode:

1. ลด confidence threshold ลงมาไม่เกิน `relaxed_min_conf`

```python
conf_threshold = min(effective_min_conf, self.relaxed_min_conf)
```

ค่า default:

```python
relaxed_min_conf = 0.45
```

2. bypass scheduler confidence check
3. spread coverage จาก LLM เป็น warn-only
4. bypass HTF bearish gate
5. ยังต้องผ่าน edge gate แบบ relaxed:

```python
edge_score >= relaxed_min_edge
```

ค่า default:

```python
relaxed_min_edge = 0.5
```

6. bypass capital-mode confidence cap (`critical`, `defensive`)
7. ใช้ position size ขั้นต่ำเพื่อลด exposure:

```python
investment_thb = min_trade_thb
```

ค่า default ใน `RiskManager`:

```python
min_trade_thb = 1000.0
```

สรุป relaxed buy:

- ไม่ hard override LLM
- ถ้า LLM ไม่ตอบ BUY จะไม่บังคับซื้อ
- ถ้า LLM ตอบ BUY จะผ่อน gate หลายตัว
- ยังต้องมี edge อย่างน้อย `0.5`
- ยังต้องผ่าน safety gates

## ขั้นตอนที่ 8: risk.py จัดการ emergency_buy แบบ forced

ถ้า `emergency_buy_stage == "forced"` และไม่ได้อยู่ `forced_sell`:

```python
_force_buy_active = (not _force_sell_active) and emergency_buy_stage == "forced"
```

forced buy คือ Option B: hard override

### กรณี LLM ตอบ BUY อยู่แล้ว

ระบบยอมรับ BUY นั้นภายใต้ hard override:

```python
signal = "BUY"
final_decision["signal"] = "BUY"
final_decision["entry_price"] = buy_price_thb
```

แต่จะคง confidence เดิมของ LLM ไว้

เหตุผล:

- confidence เดิมสะท้อนความมั่นใจของ model
- ไม่ควรปั่นเป็น `1.0` ถ้า LLM เป็นคนเห็นด้วยกับ BUY อยู่แล้ว
- hard override มีหน้าที่ bypass gates ไม่ใช่ปลอม confidence ของ model

ตัวอย่าง:

```json
{
  "signal": "BUY",
  "confidence": 0.10
}
```

ผลหลัง forced stage:

```json
{
  "signal": "BUY",
  "confidence": 0.10
}
```

### กรณี LLM ตอบ HOLD หรือ SELL

ระบบจะยึดอำนาจ LLM แล้วบังคับเป็น BUY:

```python
signal = "BUY"
final_decision["signal"] = "BUY"
final_decision["confidence"] = 1.0
final_decision["entry_price"] = buy_price_thb
```

พร้อม rationale:

```text
[SESSION FORCE BUY] Emergency buy override with ... min left
and ... trades completed. LLM signal 'HOLD' was overridden.
Original rationale: ...
```

เหตุผลที่ตั้ง confidence เป็น `1.0` เฉพาะเคสนี้:

- เป็น system-forced execution
- ไม่ใช่ model confidence
- ใช้บอก downstream ว่าระบบตัดสินใจบังคับเองแล้ว

## ขั้นตอนที่ 9: forced buy bypass gate อะไรบ้าง

ใน forced buy:

- bypass confidence threshold
- bypass scheduler confidence
- bypass LLM spread coverage check
- bypass HTF bearish gate
- bypass edge gate ทั้งหมด
- bypass capital-mode confidence cap
- ใช้ position size ขั้นต่ำ (`min_trade_thb`)

ตัวอย่าง gate ที่ถูก bypass:

```python
if _force_buy_active:
    pass  # confidence check
```

```python
if _force_buy_active:
    logger.warning("Stage 2 FORCED BUY bypassed LLM spread check")
```

```python
if _force_buy_active:
    logger.warning("Stage 2 FORCED BUY bypassed edge gate")
```

## ขั้นตอนที่ 10: safety gates ที่ยังไม่ bypass

ทั้ง `relaxed` และ `forced` buy ยังต้องผ่าน safety gates เหล่านี้:

1. ห้ามซื้อถ้าถือทองอยู่แล้ว

```python
if gold_grams > 1e-4 or holding:
    return HOLD
```

2. ห้ามซื้อถ้าอยู่ dead zone

```python
if session_gate.get("is_dead_zone") and signal == "BUY":
    return HOLD
```

3. ห้ามซื้อถ้า trade วันนี้ครบ limit

```python
if trades_today >= 3:
    return HOLD
```

4. ห้ามซื้อถ้าเงินสดไม่พอขั้นต่ำ

```python
if cash_balance < min_trade_thb:
    return HOLD
```

5. ห้ามซื้อถ้า daily loss limit เต็ม

```python
if self._daily_loss_accumulated >= self.max_daily_loss_thb and signal == "BUY":
    return HOLD
```

สรุปคือ forced buy บังคับทิศทางเป็น BUY ได้ แต่ไม่ได้บังคับให้ละเมิด safety constraints

## ตัวอย่าง Flow: emergency_buy relaxed

สถานการณ์:

- เหลือเวลา 50 นาที
- ยังไม่ได้เทรดใน session นี้
- ไม่ได้ถือทอง
- LLM ตอบ BUY confidence 0.46
- edge_score 0.6

ผล:

1. `session_gate.py` ตั้ง `emergency_buy_stage = "relaxed"`
2. `prompt.py` inject directive ให้ relax technical gates
3. `RiskManager` ใช้ threshold confidence ประมาณ `0.45`
4. edge_score 0.6 ผ่าน relaxed edge gate
5. position size ใช้ขั้นต่ำ
6. final decision เป็น BUY

ถ้า edge_score เหลือ 0.4:

- relaxed mode จะ reject เป็น HOLD เพราะ `edge_score < 0.5`

## ตัวอย่าง Flow: emergency_buy forced + LLM ตอบ BUY

สถานการณ์:

- เหลือเวลา 25 นาที
- ยังไม่ได้เทรดใน session นี้
- ไม่ได้ถือทอง
- LLM ตอบ BUY confidence 0.10
- edge_score 0.1

ผล:

1. `session_gate.py` ตั้ง `emergency_buy_stage = "forced"`
2. `prompt.py` สั่ง LLM ให้ execute BUY immediately
3. `RiskManager` เห็นว่า LLM ตอบ BUY อยู่แล้ว
4. คง confidence 0.10 ไว้
5. bypass confidence, spread, HTF, edge
6. safety gates ยังตรวจอยู่
7. final decision เป็น BUY ด้วย position size ขั้นต่ำ

## ตัวอย่าง Flow: emergency_buy forced + LLM ตอบ HOLD

สถานการณ์:

- เหลือเวลา 25 นาที
- ยังไม่ได้เทรดใน session นี้
- ไม่ได้ถือทอง
- LLM ตอบ HOLD confidence 0.0

ผล:

1. `session_gate.py` ตั้ง `emergency_buy_stage = "forced"`
2. `RiskManager` hard override สัญญาณจาก HOLD เป็น BUY
3. ตั้ง confidence เป็น `1.0` เพราะเป็น system-forced execution
4. ใส่ rationale `[SESSION FORCE BUY]`
5. bypass confidence, spread, HTF, edge
6. safety gates ยังตรวจอยู่
7. final decision เป็น BUY ถ้าเงินสดพอและไม่ได้ถือทอง

## ตัวอย่าง Flow: emergency_sell

สถานการณ์:

- เหลือเวลา 5 นาที
- ยังถือทอง 0.025g
- LLM ตอบ HOLD

ผล:

1. `session_gate.py` ตั้ง `is_emergency_sell = True`
2. `emergency_mode = "forced_sell"`
3. `prompt.py` สั่ง LLM ให้ SELL ALL
4. `RiskManager` override สัญญาณเป็น SELL
5. ตั้ง confidence เป็น `1.0`
6. bypass minimum profit filter
7. คำนวณมูลค่าทองที่ขายจาก `gold_grams`
8. final decision เป็น SELL

## ตารางสรุป

| Mode | เงื่อนไขหลัก | LLM ตอบ HOLD | Confidence | Gate ที่ผ่อน |
|---|---|---|---|---|
| Normal | ไม่มี emergency | HOLD ตาม LLM | ตาม LLM | ไม่มี |
| Buy Relaxed | เหลือ 46-60 นาที, zero trade, no holding | ยัง HOLD | ตาม LLM | conf, scheduler, spread warn-only, HTF, capital caps |
| Buy Forced | เหลือ <=45 นาที, zero trade, no holding | override เป็น BUY | 1.0 ถ้า override จาก HOLD/SELL | conf, scheduler, spread, HTF, edge, capital caps |
| Sell Forced | เหลือ <=8 นาที, holding gold | override เป็น SELL | 1.0 | profit filter |

## ข้อควรระวัง

- `emergency_mode == "forced_buy"` ไม่พอสำหรับแยก relaxed/forced เพราะทั้งสอง stage ใช้ค่านี้ร่วมกัน
- ต้องดู `emergency_buy_stage` เสมอถ้าต้องการรู้ stage จริง
- forced buy ไม่ bypass safety gates
- ถ้า trade ใน session นี้มากกว่า 0 แล้ว จะไม่เข้า emergency buy
- ถ้าถือทองอยู่แล้ว จะไม่เข้า emergency buy และถ้าใกล้หมดเวลามากจะเข้า emergency sell แทน
