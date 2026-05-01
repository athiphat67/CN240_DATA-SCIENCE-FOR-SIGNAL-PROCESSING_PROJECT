# 📚 Gold Trading Agent — Tool Documentation

> อธิบายการทำงานของแต่ละ tool ใน `tools/` folder
> สำหรับใช้เป็น reference ตอนเขียน ReAct loop ใน `agent.py`

---

## โครงสร้างไฟล์

```
tools/
├── __init__.py
├── fetch_price.py          ← Tool: ราคาทอง, OHLCV
├── fetch_indicators.py     ← Tool: RSI, MACD, Bollinger ฯลฯ
├── fetch_news.py           ← Tool: ข่าว + FinBERT sentiment
├── tool_registry.py        ← ประตูกลาง LLM เรียก tool
├── interceptor_manager.py  ← WebSocket background thread
└── schema_validator.py     ← ตรวจสอบ payload schema
```

---

## สารบัญ

1. [fetch_price](#1-fetch_price)
2. [fetch_indicators](#2-fetch_indicators)
3. [fetch_news](#3-fetch_news)
4. [tool_registry](#4-tool_registry)
5. [interceptor_manager](#5-interceptor_manager)
6. [schema_validator](#6-schema_validator)
7. [การไหลของข้อมูลระหว่าง tools](#7-การไหลของข้อมูลระหว่าง-tools)

---

## 1. `fetch_price`

**ไฟล์:** `tools/fetch_price.py`
**หน้าที่:** ดึงข้อมูลราคาทองคำทั้งหมดจากแหล่งข้อมูลภายนอก และเรียก `start_interceptor_background()` อัตโนมัติตอน import

### Input Parameters

| Parameter | Type | Default | คำอธิบาย |
|---|---|---|---|
| `history_days` | int | 90 | จำนวนวันย้อนหลังสำหรับข้อมูล OHLCV |
| `interval` | str | `"5m"` | Timeframe ของแท่งเทียน: `1m`, `5m`, `15m`, `1h`, `1d` |

### Output (dict)

| Key | Type | คำอธิบาย |
|---|---|---|
| `spot_price_usd` | dict | ราคา spot ทองเป็น USD พร้อม source |
| `thai_gold_thb` | dict | ราคาทองไทย (sell/buy price เป็น THB) |
| `recent_price_action` | list[dict] | แท่งเทียน 5 แท่งล่าสุด (OHLCV + datetime ไทย) |
| `ohlcv_df` | DataFrame | ข้อมูลดิบสำหรับส่งต่อให้ `fetch_indicators` |
| `data_sources` | dict | แหล่งที่มาของข้อมูลแต่ละตัว |
| `error` | str \| None | `None` = สำเร็จ |

### ตัวอย่างการเรียกใช้

```python
from tools.tool_registry import call_tool

result = call_tool("fetch_price", interval="5m", history_days=30)

spot    = result["spot_price_usd"]       # {"price": 2345.6, "source": "..."}
candles = result["recent_price_action"]  # [{datetime, open, high, low, close, volume}, ...]
df      = result["ohlcv_df"]             # ส่งต่อให้ fetch_indicators
```

### หมายเหตุ

- `ohlcv_df` เป็น DataFrame ที่ **ไม่ถูก serialize เป็น JSON** — ใช้ส่งต่อระหว่าง tools ในหน่วยความจำเท่านั้น
- WebSocket จะเริ่มทำงานอัตโนมัติทันทีที่ `import` tool นี้ ไม่ต้องเรียก interceptor_manager เองแยกต่างหาก

---

## 2. `fetch_indicators`

**ไฟล์:** `tools/fetch_indicators.py`
**หน้าที่:** คำนวณ Technical Indicators จาก OHLCV DataFrame ที่ได้จาก `fetch_price`

### Input Parameters

| Parameter | Type | Required | คำอธิบาย |
|---|---|---|---|
| `ohlcv_df` | DataFrame | ✅ | DataFrame จาก `fetch_price` |
| `interval` | str | ❌ (default `"5m"`) | Timeframe เพื่อปรับพารามิเตอร์ indicator |

### Output (dict)

| Key | Type | คำอธิบาย |
|---|---|---|
| `indicators` | dict | RSI, MACD, Bollinger Bands, EMA, ATR ฯลฯ |
| `data_quality` | dict | รายงานคุณภาพข้อมูล (ดูด้านล่าง) |
| `error` | str \| None | `None` = สำเร็จ |

### โครงสร้าง `data_quality`

```json
{
  "quality_score": "good",
  "is_weekend": false,
  "llm_instruction": "Use standard technical analysis.",
  "warnings": []
}
```

> เมื่อ `is_weekend = true` ค่า `llm_instruction` จะเปลี่ยนเป็น
> `"Market is closed. Weigh news sentiment higher than short-term indicators."`

### ตัวอย่างการเรียกใช้

```python
price_result = call_tool("fetch_price", interval="5m")

ind_result = call_tool(
    "fetch_indicators",
    ohlcv_df=price_result["ohlcv_df"],
    interval="5m"
)

indicators   = ind_result["indicators"]    # {"rsi": {"value": 58.3}, "macd": {...}, ...}
data_quality = ind_result["data_quality"]  # {"quality_score": "good", ...}
```

### หมายเหตุ

- ถ้า `ohlcv_df` เป็น `None` หรือ empty จะคืน `indicators = {}` และ `quality_score = "degraded"` แทนที่จะ crash

---

## 3. `fetch_news`

**ไฟล์:** `tools/fetch_news.py`
**หน้าที่:** ดึงข่าวทองคำจาก RSS feeds และวิเคราะห์ sentiment ด้วย FinBERT

### Input Parameters

| Parameter | Type | Default | คำอธิบาย |
|---|---|---|---|
| `max_per_category` | int | 5 | จำนวนข่าวสูงสุดต่อ category |

### Output (dict)

| Key | Type | คำอธิบาย |
|---|---|---|
| `summary` | dict | ภาพรวมข่าว (ดูด้านล่าง) |
| `by_category` | dict | ข่าวแยกตาม category พร้อม sentiment รายข่าว |
| `error` | str \| None | `None` = สำเร็จ |

### โครงสร้าง `summary`

```json
{
  "total_articles": 15,
  "token_estimate": 3200,
  "overall_sentiment": 0.42,
  "fetched_at": "2025-04-11T10:30:00+07:00",
  "errors": []
}
```

> `overall_sentiment` อยู่ในช่วง `-1.0` (bearish) ถึง `1.0` (bullish)

### ตัวอย่างการเรียกใช้

```python
news_result = call_tool("fetch_news", max_per_category=5)

sentiment   = news_result["summary"]["overall_sentiment"]
by_category = news_result["by_category"]  # {"macro": [...], "gold": [...]}
```

### หมายเหตุ

- มี lazy-init cache ตาม `max_per_category` — เรียกซ้ำด้วยค่าเดิมจะไม่ init fetcher ใหม่

---

## 4. `tool_registry`

**ไฟล์:** `tools/tool_registry.py`
**หน้าที่:** ประตูกลางที่ LLM ใช้ค้นหาและเรียก tool โดยไม่ต้อง import แต่ละไฟล์เอง

### Functions

**`call_tool(tool_name, **kwargs) → dict`**

```python
result = call_tool("fetch_price", interval="5m", history_days=30)
result = call_tool("fetch_indicators", ohlcv_df=df, interval="5m")
result = call_tool("fetch_news", max_per_category=3)
```

**`list_tools() → list[dict]`**
คืน tools ทั้งหมดพร้อม description และ parameter schema — ใช้บอก LLM ว่ามี tools อะไรบ้าง

```python
tools = list_tools()
# [
#   {"name": "fetch_price", "description": "...", "parameters": {...}},
#   {"name": "fetch_indicators", ...},
#   {"name": "fetch_news", ...},
# ]
```

### การเพิ่ม Tool ใหม่

เพิ่ม entry ใน `TOOL_REGISTRY` dict เท่านั้น — `agent.py` ไม่ต้องแก้ไขใดๆ

```python
TOOL_REGISTRY["execute_order"] = {
    "fn":          execute_order,
    "description": "ส่งคำสั่งซื้อขายทองผ่าน broker API",
    "parameters": {
        "action": {"type": "str",   "description": "buy | sell | hold"},
        "amount": {"type": "float", "description": "จำนวนกรัม"},
    },
}
```

---

## 5. `interceptor_manager`

**ไฟล์:** `tools/interceptor_manager.py`
**หน้าที่:** เปิด Background Thread สำหรับ WebSocket ที่ดึงราคาทองแบบ real-time ค้างไว้ตลอดเวลา

### Functions

**`start_interceptor_background() → None`**
เปิด daemon thread — รันแค่ครั้งเดียวต่อโปรเซส ปลอดภัยถ้าเรียกซ้ำ (idempotent)

### หมายเหตุ

- **ไม่ต้องเรียกเองโดยตรง** — `fetch_price.py` เรียกให้อัตโนมัติตอน import
- ถ้า WebSocket หลุด thread จะ reconnect อัตโนมัติทุก 5 วินาที
- เป็น `daemon=True` — ปิดตัวเองเมื่อโปรแกรมหลักจบ

---

## 6. `schema_validator`

**ไฟล์:** `tools/schema_validator.py`
**หน้าที่:** ตรวจสอบว่า payload มี required fields ครบก่อนส่งให้ LLM

### Functions

**`validate_market_state(state: dict) → list[str]`**
คืน list ของ missing fields — ถ้า list ว่าง = ผ่าน

```python
from tools.schema_validator import validate_market_state

errors = validate_market_state(payload)
if errors:
    print(f"Payload ไม่สมบูรณ์: {errors}")
```

### Required Fields

```
market_data.spot_price_usd
market_data.thai_gold_thb.sell_price_thb
market_data.thai_gold_thb.buy_price_thb
technical_indicators.rsi.value
```

> แก้ไข required fields ได้ที่ค่าคงที่ `REQUIRED_FIELDS` ใน `schema_validator.py`

---

## 7. การไหลของข้อมูลระหว่าง Tools

```
[fetch_price]
    │
    ├─► spot_price_usd ──────────────────────────► agent / payload
    ├─► thai_gold_thb ──────────────────────────► agent / payload
    ├─► recent_price_action ────────────────────► agent / payload
    │
    └─► ohlcv_df (DataFrame) ──► [fetch_indicators]
                                      │
                                      ├─► indicators ─────────► agent / payload
                                      └─► data_quality ────────► agent / payload

[fetch_news]
    │
    ├─► summary ────────────────────────────────► agent / payload
    └─► by_category ────────────────────────────► agent / payload
```

> `ohlcv_df` ไหลในหน่วยความจำโดยตรง ไม่ผ่าน JSON serialization
> `agent.py` รับผิดชอบส่ง `ohlcv_df` จาก `fetch_price` ต่อไปให้ `fetch_indicators` เอง
