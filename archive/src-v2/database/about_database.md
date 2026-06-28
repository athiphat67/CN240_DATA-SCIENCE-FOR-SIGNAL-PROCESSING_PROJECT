# database.py — คู่มือและ Reference

ไฟล์นี้เป็น Data Access Layer หลักของระบบ ทำหน้าที่เชื่อมต่อ PostgreSQL และจัดการทุก read/write operation สำหรับโปรเจกต์วิเคราะห์ราคาทองคำด้วย LLM

---

## สารบัญ

- [โครงสร้างตาราง](#โครงสร้างตาราง)
- [Class: RunDatabase](#class-rundatabase)
- [Methods](#methods)
- [Connection Pool](#connection-pool)
- [Error Handling](#error-handling)
- [การตั้งค่า Environment](#การตั้งค่า-environment)
- [Migration System](#migration-system)
- [หมายเหตุสำคัญ (หน่วยราคา)](#หมายเหตุสำคัญ-หน่วยราคา)
- [Changelog](#changelog)

---

## โครงสร้างตาราง

ระบบมี 3 ตารางหลัก

### `runs`

เก็บผลการวิเคราะห์แต่ละครั้งที่ระบบรัน 1 run = 1 row

| Column | Type | คำอธิบาย |
|---|---|---|
| `id` | SERIAL PK | Auto-increment ID |
| `run_at` | TEXT | เวลา UTC ที่รัน (ISO 8601) |
| `provider` | TEXT | LLM provider ที่ใช้ เช่น `openai`, `anthropic` |
| `interval_tf` | TEXT | Timeframe เช่น `1h`, `4h`, `1d` |
| `period` | TEXT | ช่วงเวลาข้อมูล |
| `signal` | TEXT | ผลการวิเคราะห์: `BUY` / `SELL` / `HOLD` |
| `confidence` | REAL | ความมั่นใจ 0.0–1.0 |
| `entry_price` | REAL | ราคาเข้า **THB/gram** |
| `stop_loss` | REAL | Stop loss **THB/gram** |
| `take_profit` | REAL | Take profit **THB/gram** |
| `entry_price_thb` | REAL | Alias ของ `entry_price` (backward compat) |
| `stop_loss_thb` | REAL | Alias ของ `stop_loss` |
| `take_profit_thb` | REAL | Alias ของ `take_profit` |
| `usd_thb_rate` | REAL | อัตราแลกเปลี่ยน USD/THB ขณะนั้น |
| `gold_price` | REAL | ราคาทองโลก **USD/oz** |
| `gold_price_thb` | REAL | ราคาทองไทย **THB/gram** (sell price จาก ออมทองNOW) |
| `rsi` | REAL | RSI value |
| `macd_line` | REAL | MACD line |
| `signal_line` | REAL | MACD signal line |
| `trend` | TEXT | ทิศทาง trend เช่น `BULLISH`, `BEARISH` |
| `rationale` | TEXT | เหตุผลจาก LLM |
| `iterations_used` | INTEGER | จำนวน ReAct iterations |
| `tool_calls_used` | INTEGER | จำนวน tool calls ใน ReAct loop |
| `react_trace` | TEXT | JSON array ของ ReAct trace steps |
| `market_snapshot` | TEXT | JSON snapshot ของ market_data + indicators |

---

### `llm_logs`

เก็บ log กระบวนการคิดของ LLM แบบละเอียด ต่อ 1 run อาจมีหลาย row (1 row ต่อ interval หรือ step)

| Column | Type | คำอธิบาย |
|---|---|---|
| `id` | SERIAL PK | Auto-increment ID |
| `run_id` | INTEGER FK | อ้างอิง `runs.id` (CASCADE DELETE) |
| `logged_at` | TEXT | เวลา UTC ที่ log |
| `interval_tf` | TEXT | Timeframe ที่ log นี้เป็นของ |
| `step_type` | TEXT | `THOUGHT` / `ACTION` / `OBSERVATION` / `THOUGHT_FINAL` |
| `iteration` | INTEGER | ลำดับ iteration ใน ReAct loop |
| `provider` | TEXT | Provider จริงที่ตอบ (อาจต่างจาก runs ถ้า fallback) |
| `signal` | TEXT | ผลสุดท้าย (มีเฉพาะ `THOUGHT_FINAL`) |
| `confidence` | REAL | ความมั่นใจ |
| `rationale` | TEXT | เหตุผล |
| `entry_price` | REAL | THB/gram |
| `stop_loss` | REAL | THB/gram |
| `take_profit` | REAL | THB/gram |
| `full_prompt` | TEXT | Prompt ที่ส่ง LLM (เปิดใช้เมื่อ react.py expose) |
| `full_response` | TEXT | Response ดิบจาก LLM |
| `trace_json` | TEXT | JSON ของ trace steps ทั้งหมดในรอบนี้ |
| `token_input` | INTEGER | Input tokens |
| `token_output` | INTEGER | Output tokens |
| `token_total` | INTEGER | Total tokens |
| `elapsed_ms` | INTEGER | เวลาที่ใช้ต่อ call (milliseconds) |
| `iterations_used` | INTEGER | จำนวน iterations ทั้งหมด |
| `tool_calls_used` | INTEGER | จำนวน tool calls ทั้งหมด |
| `is_fallback` | BOOLEAN | true ถ้า run นี้ใช้ fallback provider |
| `fallback_from` | TEXT | Provider ที่ fail ก่อน fallback |

---

### `portfolio`

เก็บสถานะ portfolio ปัจจุบัน มีแค่ **1 row เสมอ** (id = 1) ใช้ UPSERT

| Column | Type | คำอธิบาย |
|---|---|---|
| `id` | SERIAL PK | Fixed = 1 |
| `cash_balance` | REAL | เงินสดคงเหลือ (THB) |
| `gold_grams` | REAL | ทองที่ถือ (gram) |
| `cost_basis_thb` | REAL | ต้นทุนเฉลี่ย (THB/gram) |
| `current_value_thb` | REAL | มูลค่าปัจจุบัน (THB) |
| `unrealized_pnl` | REAL | กำไร/ขาดทุนที่ยังไม่ realize (THB) |
| `trades_today` | INTEGER | จำนวน trades วันนี้ |
| `updated_at` | TEXT | เวลาที่ update ล่าสุด |

---

## Class: RunDatabase

```python
from database import RunDatabase

db = RunDatabase()
```

ต้องมี environment variable `DATABASE_URL` ก่อน instantiate ไม่เช่นนั้นจะ raise `ValueError`

---

## Methods

### runs

#### `save_run(provider, result, market_state, interval_tf, period) -> int`

บันทึกผล analysis 1 ครั้ง คืน `run_id` ที่ใช้อ้างอิงต่อ

```python
run_id = db.save_run(
    provider="openai",
    result={
        "signal": "BUY",
        "confidence": 0.82,
        "entry_price": 45200.0,   # THB/gram
        "stop_loss": 44800.0,
        "take_profit": 46000.0,
        "rationale": "...",
    },
    market_state={
        "market_data": { ... },
        "technical_indicators": { ... },
    },
    interval_tf="1h",
    period="90d",
)
```

> ⚠️ ราคา entry/stop/take ต้องเป็น **THB/gram** เสมอ — ไม่แปลงจาก USD อีกแล้ว (ดู [หมายเหตุสำคัญ](#หมายเหตุสำคัญ-หน่วยราคา))

---

#### `get_recent_runs(limit=50) -> list[dict]`

ดึง runs ล่าสุด เรียงจากใหม่ไปเก่า คืน fields ที่กำหนดใน `_HISTORY_COLS` (ไม่รวม react_trace และ market_snapshot เพื่อประหยัด memory)

---

#### `get_run_detail(run_id) -> dict | None`

ดึง run เต็มรูปแบบ รวม react_trace และ market_snapshot (parse เป็น dict/list ให้อัตโนมัติ) คืน `None` ถ้าไม่เจอ

---

#### `get_signal_stats() -> dict`

คืน aggregate stats ของทุก runs

```python
{
    "total": 120,
    "buy_count": 45,
    "sell_count": 30,
    "hold_count": 45,
    "avg_confidence": 0.743,
    "avg_price": 44850.25,   # THB/gram
}
```

---

#### `delete_run(run_id) -> bool`

ลบ run และ llm_logs ที่เกี่ยวข้องทั้งหมด (CASCADE) คืน `True` ถ้าลบสำเร็จ

---

### llm_logs

#### `save_llm_log(run_id, log_data) -> int`

บันทึก 1 LLM log entry คืน `log_id`

`log_data` keys ที่สำคัญ:

```python
{
    "interval_tf": "1h",            # required
    "step_type": "THOUGHT_FINAL",   # THOUGHT / ACTION / OBSERVATION / THOUGHT_FINAL
    "iteration": 3,
    "provider": "openai",
    "signal": "BUY",
    "confidence": 0.82,
    "token_input": 1200,
    "token_output": 350,
    "token_total": 1550,
    "elapsed_ms": 2300,
    "is_fallback": False,
}
```

---

#### `save_llm_logs_batch(run_id, logs) -> list[int]`

บันทึกหลาย log entries พร้อมกัน คืน list ของ `log_id` ที่ save สำเร็จ entries ที่ fail จะถูก log เป็น warning แต่ไม่หยุด batch

---

#### `get_llm_logs_for_run(run_id) -> list[dict]`

ดึง logs ทั้งหมดของ run เรียงตามเวลา (ASC) `trace_json` จะถูก parse เป็น list อัตโนมัติ

---

#### `get_recent_llm_logs(limit=20) -> list[dict]`

ดึง logs ล่าสุดข้ามทุก run สำหรับ monitoring รวม `run_at` จาก `runs` table ด้วย

---

### portfolio

#### `save_portfolio(data) -> None`

UPSERT portfolio row (id=1) เสมอ ไม่ว่าจะมีข้อมูลอยู่ก่อนหรือไม่

#### `get_portfolio() -> dict`

ดึงสถานะ portfolio ปัจจุบัน ถ้า DB fail หรือยังไม่มีข้อมูล จะคืน default values (cash=1500.0, gold=0.0) และ log warning

---

## Connection Pool

ตั้งแต่ v3.4 ใช้ `ThreadedConnectionPool` แทน direct connect ทุกครั้ง

```
min connections : 1
max connections : 5   ← เหมาะกับ Render free tier (~10 connection limit)
```

ทุก method ใช้ `get_connection()` เป็น context manager ที่ auto-return connection กลับ pool และ rollback อัตโนมัติเมื่อเกิด exception

ควรเรียก `db.close()` ตอน application shutdown เพื่อคืน connection ทั้งหมด

---

## Error Handling

| Method | พฤติกรรมเมื่อ error |
|---|---|
| `save_run` | log error พร้อม provider/interval/signal แล้ว re-raise |
| `save_llm_log` | exception ลอยขึ้น caller |
| `save_llm_logs_batch` | skip entry ที่ fail, log warning summary, ทำต่อ |
| `get_signal_stats` | log error, คืน zeros dict แทน crash |
| `get_portfolio` | log warning, คืน default dict แทน crash |
| `get_connection` | rollback อัตโนมัติ, re-raise exception |

---

## การตั้งค่า Environment

ต้องมีใน `.env` หรือ Render environment variables:

```
DATABASE_URL=postgresql://user:password@host:5432/dbname
```

ถ้าไม่มี จะ raise `ValueError` ทันทีที่ instantiate `RunDatabase()`

---

## Migration System

ระบบ migration ทำงานอัตโนมัติทุกครั้งที่ start ผ่าน `_init_db()` ใช้ `ADD COLUMN IF NOT EXISTS` ทำให้ safe รัน idempotent ได้

Columns ที่ migrate อัตโนมัติ (ทั้งหมดใน table `runs`):
- `entry_price_thb`
- `stop_loss_thb`
- `take_profit_thb`
- `usd_thb_rate`
- `gold_price_thb`

migration ผ่าน whitelist ก่อน interpolate เพื่อป้องกัน injection:
- tables ที่อนุญาต: `runs`, `portfolio`, `llm_logs`
- types ที่อนุญาต: `REAL`, `INTEGER`, `TEXT`, `BOOLEAN`

---

## หมายเหตุสำคัญ (หน่วยราคา)

> **ราคาทองในระบบนี้ใช้หน่วย THB/gram เสมอ**

LLM ส่ง `entry_price`, `stop_loss`, `take_profit` มาเป็น THB/gram โดยตรงอยู่แล้ว ไม่ต้องแปลงจาก USD ก่อนเก็บ ข้อยกเว้นเดียวคือ `gold_price` (column ใน runs) ที่เก็บเป็น **USD/oz** ตามราคาตลาดโลก

---

## Changelog

| Version | การเปลี่ยนแปลง |
|---|---|
| v3.4 | เพิ่ม ThreadedConnectionPool, migration whitelist, error handling ครบทุก method |
| v3.3 | เลิกแปลง USD→THB, ลบ `@log_method` decorator ออกจาก `save_run` |
| v3.2 | เพิ่ม `llm_logs` table, `save_llm_logs_batch` |
| v3.1 | เพิ่ม `portfolio` table, UPSERT pattern |
| v3.0 | เพิ่ม `react_trace`, `market_snapshot` columns |
