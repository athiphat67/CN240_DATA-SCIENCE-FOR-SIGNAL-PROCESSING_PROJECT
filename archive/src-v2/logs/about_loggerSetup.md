# logger_setup.py — คู่มือและ Reference

ไฟล์นี้เป็น Logging Layer กลางของระบบ ทำหน้าที่สร้าง logger สองตัว (`sys_logger`, `llm_logger`) และ decorator `log_method` สำหรับ wrap function ให้ log เวลาทำงานอัตโนมัติ

---

## สารบัญ

- [โครงสร้างไฟล์ Log](#โครงสร้างไฟล์-log)
- [Loggers ที่มีในระบบ](#loggers-ที่มีในระบบ)
- [การใช้งาน](#การใช้งาน)
- [setup_logger()](#setup_logger)
- [log_method Decorator](#log_method-decorator)
- [THTimeFormatter](#thtimeformatter)
- [RotatingFileHandler](#rotatingfilehandler)
- [Bug ที่ถูกแก้ใน v1.1](#bug-ที่ถูกแก้ใน-v11)
- [Changelog](#changelog)

---

## โครงสร้างไฟล์ Log

```
logs/
├── logger_setup.py     ← ไฟล์นี้
├── system.log          ← sys_logger เขียน (rotate เมื่อ > 5 MB)
├── system.log.1        ← backup 1
├── system.log.2        ← backup 2
├── system.log.3        ← backup 3
├── llm_trace.log       ← llm_logger เขียน (rotate เมื่อ > 5 MB)
├── llm_trace.log.1
...
```

`LOG_DIR` คำนวณอัตโนมัติ — ถ้า `logger_setup.py` อยู่ใน folder ชื่อ `logs/` จะเขียน log ลงในโฟลเดอร์นั้นโดยตรง (ไม่สร้าง `logs/logs/` ซ้อน)

---

## Loggers ที่มีในระบบ

| ชื่อ | Instance | ไฟล์ Log | Level | ใช้สำหรับ |
|---|---|---|---|---|
| `system_logger` | `sys_logger` | `system.log` | DEBUG | log ทั่วไป: DB, API calls, flow |
| `llm_logger` | `llm_logger` | `llm_trace.log` | DEBUG | log เฉพาะ LLM: prompt, response, token |

ทั้งสองตัวออก log ไปพร้อมกัน **2 ที่** คือ file และ console

---

## การใช้งาน

### Import Logger

```python
from logs.logger_setup import sys_logger, llm_logger

sys_logger.info("ระบบเริ่มทำงาน")
llm_logger.debug(f"prompt sent: {prompt[:200]}")
```

### Log Levels

```python
sys_logger.debug("ข้อมูล debug ละเอียด")     # ไม่ออก console บน production ถ้าตั้ง INFO
sys_logger.info("flow ปกติ")
sys_logger.warning("เกิดบางอย่างที่ควรสังเกต")
sys_logger.error("error ที่ handle ได้")
sys_logger.critical("error ร้ายแรงมาก")
```

### ใช้ log_method Decorator

```python
from logs.logger_setup import sys_logger, log_method

@log_method(sys_logger)
def fetch_market_data(interval: str) -> dict:
    # ระบบจะ log START / END / ERROR + elapsed time อัตโนมัติ
    ...
```

ผลใน log:

```
[2025-04-07 14:32:01] [DEBUG] [market.py:fetch_market_data] - ▶️ START Action: fetch_market_data
[2025-04-07 14:32:03] [INFO]  [market.py:fetch_market_data] - ✅ END Action: fetch_market_data | Elapsed: 2.14s
```

ถ้า exception:

```
[2025-04-07 14:32:03] [ERROR] [market.py:fetch_market_data] - ❌ ERROR in fetch_market_data: ... | Elapsed: 0.43s
Traceback (most recent call last):
  ...
```

---

## setup_logger()

```python
def setup_logger(name: str, log_file: str, level=logging.INFO) -> logging.Logger
```

| Parameter | Type | คำอธิบาย |
|---|---|---|
| `name` | str | ชื่อ logger ใช้ใน `logging.getLogger(name)` — ต้อง unique ต่อ logger |
| `log_file` | str | ชื่อไฟล์ (ไม่ใช่ full path) เช่น `"system.log"` |
| `level` | int | Log level เช่น `logging.DEBUG`, `logging.INFO` |

**พฤติกรรม:**
- สร้าง logger ใหม่ถ้ายังไม่มี หรือ return อันเดิมถ้ามีอยู่แล้ว
- ตรวจ duplicate handler โดย check `baseFilename` ของ FileHandler ที่มีอยู่
- `propagate = False` เพื่อไม่ให้ log ลอยขึ้น root logger

---

## log_method Decorator

```python
def log_method(logger_instance) -> decorator
```

Decorator factory — รับ logger แล้วคืน decorator สำหรับ wrap function

**สิ่งที่ log อัตโนมัติ:**

| Event | Level | ข้อมูล |
|---|---|---|
| เริ่ม call | DEBUG | ชื่อ function |
| สำเร็จ | INFO | ชื่อ function + elapsed time (วินาที) |
| Exception | ERROR | ชื่อ function + error message + elapsed + full traceback |

**หมายเหตุ:** ถ้า function มี `@log_method` อยู่แล้ว ห้าม wrap ซ้ำใน caller — จะทำให้ log ซ้ำสองชั้น (เห็น START/END สองครั้ง) ดู `database.py` ที่ตัดสินใจลบ decorator ออกจาก `save_run()` แล้ว

---

## THTimeFormatter

Custom formatter ที่แปลง timestamp จาก UTC เป็น **UTC+7 (เวลาไทย)** ก่อนแสดงใน log

```
รูปแบบ: [YYYY-MM-DD HH:MM:SS] [LEVEL] [filename:funcName] - message
ตัวอย่าง: [2025-04-07 14:32:01] [INFO] [database.py:save_run] - save_run OK — ID=42
```

ใช้ทั้ง file handler และ console handler

---

## RotatingFileHandler

ตั้งแต่ v1.1 เปลี่ยนจาก `FileHandler` เป็น `RotatingFileHandler`

| Setting | ค่า |
|---|---|
| `maxBytes` | 5 MB (5 × 1024 × 1024) |
| `backupCount` | 3 ไฟล์ |
| encoding | UTF-8 |

เมื่อ log file ใหญ่เกิน 5 MB จะ rename เป็น `.log.1`, `.log.2`, `.log.3` แล้วสร้างไฟล์ใหม่ ไฟล์เก่าสุด (`.log.3`) จะถูกลบทิ้ง — disk usage สูงสุดประมาณ **20 MB ต่อ logger** (4 files × 5 MB)

---

## Bug ที่ถูกแก้ใน v1.1

### 🔴 `getLogger("client")` hardcode — sys_logger กับ llm_logger เป็น object เดียวกัน

**ปัญหาเดิม:**
```python
# เดิม: ไม่ว่าจะส่ง name อะไรมา ก็ได้ logger "client" ตัวเดียว
logger = logging.getLogger("client")
```

**ผล:**
- `sys_logger` และ `llm_logger` point ไปหา logger ตัวเดียวกัน
- `if not logger.handlers` ใน call แรกเพิ่ม handlers ของ `system.log`
- call ที่สองเข้า guard ไม่ผ่าน → ไม่เพิ่ม handler ของ `llm_trace.log`
- ผลสุดท้าย: `llm_trace.log` ว่างเปล่าตลอด

**แก้:**
```python
logger = logging.getLogger(name)   # ใช้ name จริงที่ส่งมา
```

---

### 🟡 `LOG_DIR` อาจสร้าง `logs/logs/` ซ้อนกัน

**ปัญหาเดิม:**
```python
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
```
ถ้า `logger_setup.py` อยู่ใน `logs/` อยู่แล้ว → path กลายเป็น `logs/logs/`

**แก้:** ตรวจชื่อโฟลเดอร์ปัจจุบันก่อน ถ้าชื่อ `logs` ให้ใช้ directory นั้นตรงๆ

---

### 🟡 Duplicate handler check ไม่ครบ

**ปัญหาเดิม:** `if not logger.handlers` — ถ้ามี handler อยู่แล้วจาก logger อื่น จะ skip ทั้งหมด

**แก้:** ตรวจ `baseFilename` ของ FileHandler แต่ละตัวแทน เพื่อให้แน่ใจว่าไฟล์ log ที่ต้องการมี handler จริง

---

### 🟢 ไม่มี Log Rotation

**ปัญหาเดิม:** `FileHandler` ธรรมดา — log file โตไม่หยุด

**แก้:** เปลี่ยนเป็น `RotatingFileHandler` (5 MB × 3 backups)

---

## Changelog

| Version | การเปลี่ยนแปลง |
|---|---|
| v1.1 | แก้ bug `getLogger("client")` hardcode, เพิ่ม RotatingFileHandler, แก้ LOG_DIR ซ้อน, แก้ duplicate handler check |
| v1.0 | Initial implementation — THTimeFormatter, sys_logger, llm_logger, log_method decorator |
