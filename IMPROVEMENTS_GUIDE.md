# 📝 คู่มือปรับปรุงที่ใช้งาน

วันที่: 2 พฤษภาคม 2569

---

## ✅ ปรับปรุงที่เสร็จแล้ว

### 1️⃣ `.env.example` — แม่แบบการตั้งค่า
**ไฟล์:** `Src/.env.example`

ไฟล์นี้ใช้สำหรับ:
- 🆕 สมาชิกทีมใหม่สามารถดูว่าต้องตั้งค่าอะไร
- 📋 ตรวจสอบว่า environment variable ครบหรือไม่
- 🔒 ไม่บันทึกค่าจริง ไม่มีความเสี่ยง

**ใช้งาน:**
```bash
# คัดลอก
cp Src/.env.example Src/.env

# แล้วเติมค่าจริง
nano Src/.env
```

---

### 2️⃣ `api/health.py` — Health Check Endpoints
**ไฟล์:** `Src/api/health.py`

ใช้สำหรับติดตามสถานะระบบ:
- ✅ ตรวจสอบ Database connection
- ✅ ตรวจสอบ HF API availability
- ✅ ตรวจสอบ RSS feed connectivity

**ใช้งาน:**
```python
# เพิ่มเข้า FastAPI app ของคุณ
from api.health import HealthCheckService

health_service = HealthCheckService()

@app.get("/api/health")
async def health_check(db: RunDatabase = Depends(get_db)):
    checks = await asyncio.gather(
        health_service.check_database(db),
        health_service.check_hf_api(),
        health_service.check_rss_connectivity(),
    )
    return {
        "overall_status": "healthy" if all_ok else "degraded",
        "database": checks[0],
        "hf_api": checks[1],
        "rss_feeds": checks[2],
    }
```

**Test:**
```bash
curl http://localhost:8000/api/health
```

---

### 3️⃣ `validate_startup.py` — Startup Validation Script
**ไฟล์:** `Src/validate_startup.py`

ตรวจสอบว่าทุกอย่างพร้อมใช้งานก่อน start app:
- 🔑 Environment variables
- 🐍 Python version
- 📦 Dependencies
- 🗄️ Database connection
- 🔑 API keys

**ใช้งาน:**
```bash
cd Src
python validate_startup.py
```

**ผลลัพธ์ตัวอย่าง:**
```
============================================================
🚀 Gold Trading AI — Startup Validation
============================================================

📋 Checking environment variables...
  ✅ GEMINI_API_KEY — present
  ✅ DATABASE_URL — present
  ⚠️  TELEGRAM_BOT_TOKEN — missing (optional)

🗄️  Checking database connection...
  ✅ Database connection successful

🔑 Checking API keys...
  ✅ HF_TOKEN — valid
  ✅ GEMINI_API_KEY — format looks valid

============================================================
📊 Validation Summary
============================================================
✅ PASS — Python Version
✅ PASS — Environment Variables
✅ PASS — Dependencies
✅ PASS — Database
✅ PASS — API Keys

✅ All checks passed! System is ready.
```

---

### 4️⃣ Sentiment Score Metrics — ติดตามคุณภาพโมเดล
**ไฟล์:** `Src/data_engine/newsfetcher.py`

เพิ่มการติดตามสถิติ sentiment scores:

**ใช้งาน:**
```python
from data_engine.newsfetcher import GoldNewsFetcher

fetcher = GoldNewsFetcher()
result = fetcher.fetch_all()

# ดู metrics หลังจากดึงข่าว
metrics = fetcher.get_sentiment_metrics()
print(metrics)
# ผลลัพธ์:
# {
#   'count': 45,
#   'mean': 0.1234,
#   'stdev': 0.3456,
#   'min': -0.8,
#   'max': 0.95,
#   'clamped_count': 2,
#   'nan_count': 0,
#   'clamped_pct': 4.44
# }
```

**ประโยชน์:**
- 🎯 ตรวจจับว่าโมเดล sentiment มีปัญหาหรือไม่
- 📊 สามารถ export ไปยัง Prometheus/Grafana
- 🔍 Debug เมื่อ scores ผิดปกติ

---

### 5️⃣ Type Hints ใน main.py
**ไฟล์:** `Src/main.py`

ตรวจสอบแล้ว — ทุกฟังก์ชัน main มี return type hints แล้ว ✅

---

## 🚀 วิธีทำงาน

### ขั้นตอน 1: ตรวจสอบ Environment
```bash
cd Src
python validate_startup.py
```

### ขั้นตอน 2: สร้าง .env
```bash
cp .env.example .env
nano .env  # เติมค่าจริง
```

### ขั้นตอน 3: เริ่มต้นแอป
```bash
# Gradio UI
python ui/dashboard.py

# หรือ FastAPI
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### ขั้นตอน 4: ตรวจสอบ Health
```bash
# ที่ terminal อื่น
curl http://localhost:8000/api/health
```

---

## 📊 Monitoring ผ่าน Metrics

**Example: Export metrics ไป log file**
```python
from data_engine.newsfetcher import GoldNewsFetcher
import json

fetcher = GoldNewsFetcher()
result = fetcher.fetch_all()

metrics = fetcher.get_sentiment_metrics()
with open("sentiment_metrics.json", "w") as f:
    json.dump(metrics, f, indent=2)

print(f"✅ Metrics: {metrics['count']} articles, mean sentiment: {metrics['mean']}")
```

---

## ⚠️ สิ่งที่ไม่เปลี่ยน

- ✅ การทำงานของ main.py — เหมือนเดิม
- ✅ การทำงานของ newsfetcher.py — เหมือนเดิม
- ✅ Database queries — เหมือนเดิม
- ✅ API responses — เหมือนเดิม

**ทั้งหมดคือการเพิ่มเติม ไม่มีการลบหรือแก้ logic เดิม**

---

## 💡 Next Steps (Optional)

1. **Exception Handling** — หากต้องการแก้ broad exception handling
   - ค่อย ๆ refactor module ละ module
   - เริ่มจาก `newsfetcher.py` → `main.py` → `engine.py`

2. **Database Timeouts** — เพิ่ม statement timeout
   ```python
   cursor.execute("SET statement_timeout = 10000")
   ```

3. **LLM Output Validation** — เพิ่ม Pydantic schema
   ```python
   from pydantic import BaseModel, Field
   
   class TradeDecision(BaseModel):
       signal: Literal["BUY", "SELL", "HOLD"]
       entry_price: float
   ```

---

## ✨ สรุป

✅ **ปรับปรุงแล้ว:**
- 1 file template (.env.example)
- 1 monitoring module (health.py)
- 1 validation script
- Sentiment metrics tracking
- Type hints checking

❌ **ยังไม่เปลี่ยน:**
- ไม่มีการแก้ exception handling
- ไม่มีการเปลี่ยน database logic
- ไม่มีการแก้ race condition
- ไม่มีการเปลี่ยน API responses

**ระบบทำงาน 100% เหมือนเดิม** ✅

---

สอบถามข้อมูลเพิ่มเติม: ดู comments ในแต่ละไฟล์
