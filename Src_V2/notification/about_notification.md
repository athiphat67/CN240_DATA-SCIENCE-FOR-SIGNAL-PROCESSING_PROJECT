# 📣 GoldTrader — Discord Notification System

ระบบส่งการแจ้งเตือนผลการวิเคราะห์สัญญาณทองคำไปยัง Discord ผ่าน Webhook
เป็นส่วนหนึ่งของ **GoldTrader v3.3** บนแพลตฟอร์ม ออม NOW

---

## สารบัญ

- [ภาพรวม](#ภาพรวม)
- [Environment Variables](#environment-variables)
- [โครงสร้างการทำงาน](#โครงสร้างการทำงาน)
- [ฟังก์ชันหลัก](#ฟังก์ชันหลัก)
- [รูปแบบ Embed ที่ส่งไป Discord](#รูปแบบ-embed-ที่ส่งไป-discord)
- [การใช้งาน](#การใช้งาน)
- [Error Handling](#error-handling)

---

## ภาพรวม

ไฟล์ `discord_notifier.py` ทำหน้าที่สร้างและส่ง Discord Embed Message
ที่มีรายละเอียดสัญญาณซื้อขายทองคำ ประกอบด้วย 2 ส่วนหลักคือ

| ส่วน | รายละเอียด |
|---|---|
| `build_embed()` | สร้าง Discord Embed object จากข้อมูลสัญญาณ |
| `DiscordNotifier` | คลาสหลักสำหรับจัดการและส่ง notification |

---

## Environment Variables

ตั้งค่าผ่านไฟล์ `.env` หรือ environment ของระบบ

| ตัวแปร | ค่าเริ่มต้น | คำอธิบาย |
|---|---|---|
| `DISCORD_WEBHOOK_URL` | _(ว่าง)_ | URL ของ Discord Webhook (จำเป็นต้องตั้ง) |
| `DISCORD_NOTIFY_ENABLED` | `true` | เปิด/ปิดระบบ notification ทั้งหมด |
| `DISCORD_NOTIFY_HOLD` | `true` | ส่งแจ้งเตือนเมื่อสัญญาณเป็น HOLD ด้วยหรือไม่ |
| `DISCORD_NOTIFY_MIN_CONF` | `0.0` | ค่า confidence ขั้นต่ำ (0.0–1.0) ที่จะส่งแจ้งเตือน |

---

## โครงสร้างการทำงาน

```
DiscordNotifier.notify()
    │
    ├── ตรวจสอบ enabled / webhook_url / signal / confidence
    │
    ├── build_embed()
    │       ├── สร้าง fields: Signal, Confidence, Entry/SL/TP
    │       ├── ราคาทอง THB / Spot XAU-USD / USD-THB
    │       ├── Per-Interval Breakdown
    │       ├── Voting Summary
    │       ├── Rationale (ตัดที่ 900 ตัวอักษร)
    │       └── Meta (Provider / Period / Run ID)
    │
    └── ส่ง POST → Discord Webhook (timeout 10 วินาที)
```

---

## ฟังก์ชันหลัก

### `build_embed()`

สร้าง Discord Embed dictionary พร้อมข้อมูลครบชุด

**Parameters:**

| ชื่อ | ประเภท | คำอธิบาย |
|---|---|---|
| `voting_result` | `dict` | ผลสรุปการ voting รวมถึง `final_signal` และ `weighted_confidence` |
| `interval_results` | `dict` | ผลวิเคราะห์แยกตาม timeframe เช่น `1h`, `4h`, `1d` |
| `market_state` | `dict` | ข้อมูลตลาด เช่น ราคาทอง THB, Spot USD, อัตราแลกเปลี่ยน |
| `provider` | `str` | ชื่อ AI provider ที่ใช้วิเคราะห์ |
| `period` | `str` | ช่วงเวลาที่วิเคราะห์ |
| `run_id` | `int` _(optional)_ | หมายเลขรอบการรัน |

**คืนค่า:** `dict` ในรูปแบบ Discord Embed object

---

### `DiscordNotifier.notify()`

ส่ง notification ไปยัง Discord

**คืนค่า:** `True` หากส่งสำเร็จ, `False` หากถูกข้ามหรือเกิด error

**เงื่อนไขที่จะ _ไม่_ ส่ง:**
- `enabled = False`
- ไม่ได้ตั้งค่า `DISCORD_WEBHOOK_URL`
- สัญญาณเป็น `HOLD` และ `notify_hold = False`
- ค่า `confidence` ต่ำกว่า `min_conf`

---

### `DiscordNotifier.status()`

ดูสถานะปัจจุบันของ notifier

**ตัวอย่าง output:**
```python
{
    "enabled":     True,
    "notify_hold": True,
    "min_conf":    0.6,
    "webhook_set": True,
    "last_error":  None
}
```

---

## รูปแบบ Embed ที่ส่งไป Discord

Embed จะแสดงสีและ emoji ตามประเภทสัญญาณ

| สัญญาณ | Emoji | สี |
|---|---|---|
| BUY | 🟢 | Teal Green `#1D9E75` |
| SELL | 🔴 | Coral Red `#D85A30` |
| HOLD | 🟡 | Gray `#888780` |

**ข้อมูลที่แสดงในแต่ละ Embed:**

- **Signal & Confidence** — สัญญาณหลักพร้อม progress bar ระดับความมั่นใจ
- **Entry / Stop Loss / Take Profit** — ราคาจาก interval ที่มี confidence สูงสุด
- **ราคาทอง THB** — ราคาซื้อและขาย พร้อมอัตรา USD/THB
- **Spot XAU/USD** — ราคา spot ทองคำโลก พร้อม badge คุณภาพข้อมูล
- **Per-Interval Breakdown** — ผลวิเคราะห์แยกตาม timeframe (แสดงเมื่อมีมากกว่า 1 interval)
- **Voting Summary** — สรุปคะแนน BUY/SELL/HOLD
- **Rationale** — เหตุผลการวิเคราะห์ (จำกัด 900 ตัวอักษร)
- **Meta** — Provider, Period, Run ID

---

## การใช้งาน

```python
from notification.discord_notifier import DiscordNotifier

notifier = DiscordNotifier()

success = notifier.notify(
    voting_result={
        "final_signal": "BUY",
        "weighted_confidence": 0.82,
        "voting_breakdown": {
            "BUY":  {"count": 3, "weighted_score": 0.82},
            "HOLD": {"count": 1, "weighted_score": 0.18},
        }
    },
    interval_results={
        "1h": {"signal": "BUY", "confidence": 0.75, "entry_price": 48500, "stop_loss": 48000, "take_profit": 49500},
        "4h": {"signal": "BUY", "confidence": 0.90, "entry_price": 48600, "stop_loss": 47900, "take_profit": 49800, "rationale": "Uptrend confirmed"},
    },
    market_state={
        "market_data": {
            "thai_gold_thb": {"sell_price_thb": 48650, "buy_price_thb": 48150},
            "forex": {"usd_thb": 34.52},
            "spot_price_usd": {"price_usd_per_oz": 2345.10, "confidence": 0.98},
        },
        "data_quality": {"quality_score": "good"}
    },
    provider="OpenAI GPT-4o",
    period="2025-07-15 09:00",
    run_id=42,
)

if not success:
    print("Error:", notifier.last_error)
```

---

## Error Handling

ข้อผิดพลาดทั้งหมดถูก catch ภายใน `notify()` และเก็บไว้ใน `notifier.last_error`
โดยจะไม่ raise exception ออกมา

| สถานการณ์ | `last_error` |
|---|---|
| ส่งสำเร็จ | `None` |
| Webhook URL ไม่ได้ตั้งค่า | `"DISCORD_WEBHOOK_URL not set"` |
| Discord ตอบกลับ HTTP error | `"HTTP 4xx: ..."` |
| Network timeout หรือ error อื่นๆ | ข้อความ exception |

> **หมายเหตุ:** `build_embed()` จะคืน embed แจ้งเตือนแทน หาก `interval_results` ว่างเปล่า
> เพื่อป้องกัน `max()` พังเมื่อไม่มีข้อมูล interval
