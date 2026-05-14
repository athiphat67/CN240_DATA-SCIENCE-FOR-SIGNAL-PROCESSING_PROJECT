# How to Trade

## ภาพรวม

ต้องรัน 2 อย่างพร้อมกัน โดยเปิดคนละ Terminal:

- `Src_V4/main.py` เพื่อดูสัญญาณซื้อขาย
- `Src_V4/tools/confirm_trade_ui.py` เพื่ออัปข้อมูลการเทรดลง DB

ในการรันต้องใช้ `Src_V4` จาก `Watcher_Panitan`

Flow การทำงาน:

`รัน main.py + confirm_trade_ui.py -> ซื้อขาย -> บันทึกลงเว็บ`

## ขั้นตอนเตรียมระบบ

1. Pull `Watcher_Panitan` เข้า branch ของตัวเอง จากนั้น `cd` เข้าโปรเจกต์

2. สร้างไฟล์ `.env` ใน `Src_V4` แล้วใส่ข้อมูลนี้

```env
# ─── Supabase ──────────────────────────────────────────────────────────────────
SUPABASE_URL=https://wrfatuhodumugnqktqub.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6IndyZmF0dWhvZHVtdWducWt0cXViIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3NTEzMDIxMywiZXhwIjoyMDkwNzA2MjEzfQ.9ZQRxC8UgJsh2ITKVZcXpUxK9KLKxKLQOu5OdlukfD4

# ─── Discord ───────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/1501443662771523614/TUS4Wphn56K4_sJVTMlLbVbopcEifgAgPC-Pia08AIP22Ob354H1-yZ0wf9N01bhaik-
DISCORD_MENTION_ID=

# ─── Mode ──────────────────────────────────────────────────────────────────────
DRY_RUN=false            # true = paper trading (ไม่เขียน DB)
LOG_LEVEL=INFO           # DEBUG | INFO | WARNING | ERROR
TIMEZONE=Asia/Bangkok

TRADE_LOG_API_URL=https://goldtrade-logs-api.poonnatuch.workers.dev
TRADE_LOG_API_KEY=d18c803f59daa3bc03faa3f63b9d5c411177a86d44b2066ec4443fbaac83b551
```

หมายเหตุ: สำหรับ `DISCORD_MENTION_ID` สามารถหาได้จากลิงก์ยูทูปที่การฟิวส์ส่งมา

3. แก้ไขไฟล์ `requirements.txt` ในโปรเจกต์ โดยใส่ข้อมูลนี้แทนอันเดิม

```txt
annotated-types==0.7.0
anyio==4.13.0
APScheduler==3.10.4
cachetools==6.2.6
certifi==2026.4.22
cffi==2.0.0
charset-normalizer==3.4.7
click==8.3.3
cryptography==48.0.0
deprecation==2.1.0
dotenv==0.9.9
fsspec==2026.4.0
gotrue==2.12.4
h11==0.16.0
h2==4.3.0
hpack==4.1.0
httpcore==1.0.9
httpx==0.28.1
hyperframe==6.1.0
idna==3.13
iniconfig==2.3.0
joblib==1.5.3
markdown-it-py==4.1.0
mdurl==0.1.2
mmh3==5.2.1
multidict==6.7.1
numpy
packaging==26.2
pandas
pluggy==1.6.0
postgrest==2.30.0
propcache==0.4.1
proxy==0.0.1
pycparser==3.0
pydantic==2.13.4
pydantic_core==2.46.4
Pygments==2.20.0
pyiceberg==0.11.1
PyJWT==2.12.1
pyparsing==3.3.2
pyroaring==1.1.0
pytest==8.2.0
pytest-mock==3.14.0
python-dateutil==2.9.0.post0
python-dotenv==1.0.1
pytz==2024.1
realtime==2.30.0
requests==2.33.1
rich==14.3.4
scikit-learn
scipy
six==1.17.0
sniffio==1.3.1
storage3==2.30.0
StrEnum==0.4.15
strictyaml==1.7.3
structlog==24.1.0
supabase==2.30.0
supabase-auth==2.30.0
supabase-functions==2.30.0
supafunc==0.10.2
tenacity==9.1.4
threadpoolctl==3.6.0
typing-inspection==0.4.2
typing_extensions==4.15.0
tzdata==2026.2
tzlocal==5.3.1
urllib3==2.6.3
websockets==15.0.1
xgboost
yarl==1.23.0
zstandard==0.25.0
gradio
```

4. สร้าง virtual environment (`venv`)

5. ติดตั้ง `requirements.txt` ที่แก้ไขแล้ว

## วิธีรัน

### Terminal 1: รัน `main.py`

1. `cd Src_V4`
2. รัน `main.py`

### Terminal 2: รัน `confirm_trade_ui.py`

1. `cd Src_V4`
2. `cd tools`
3. รัน `confirm_trade_ui.py`

## รายละเอียดการซื้อขาย

- จะต้องซื้อ-ขายภายใน 1 นาทีหลังสัญญาณออก ถ้าเกิน 1 นาที ให้รอสัญญาณใหม่เลย
- เราสามารถตัดสินใจเองได้ว่า สัญญาณที่ออกมาเราจะเชื่อหรือไม่ ถ้าไม่เชื่อก็รอสัญญาณครั้งถัดไป
- ซื้อครั้งละ 1000 บาท

### การเข้าแอป aomnow

- Username: `athiphatsunsit@gmail.com`
- Password: `admin12345`
- Pin: `202547`


## รายละเอียดการอัป DB

### Login หน้าเว็บ

- Username: `admin`
- Password: `admin123`

### Dashboard

Dashboard จะแบ่งเป็น 2 ฝั่ง:

#### BUY

- ใส่ราคาที่ซื้อ
- `signal ID` ไม่ต้องใส่อะไร

#### SELL

- ใส่ราคาที่ขาย
