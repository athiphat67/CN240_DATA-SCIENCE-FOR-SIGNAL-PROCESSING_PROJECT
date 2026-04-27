# Strategy Rescue Plan (ข้อจำกัด: ทุนเริ่ม 1,500 / ขั้นต่ำซื้อ 1,000 / ต้องซื้อ 6 ไม้ต่อวัน)

## 1) ปรับกรอบปัญหาใหม่ (จาก Scalping เป็น Event-Driven Rotation)
- ภายใต้ spread ซื้อ-ขายทองไทยที่กว้าง การเทรด 15m แบบเก็บสั้นต่อเนื่องจะเสียเปรียบทางคณิตศาสตร์
- ให้เปลี่ยนกติกาภายในระบบเป็น: “ซื้อครบ 6 ไม้/วัน” แต่แต่ละไม้ต้องเป็น **ไม้มีเงื่อนไข (qualified entry)**
- ใช้โหมด execution แบบวงจร: `BUY (1000-1250) -> รอ TP/SL หรือ timeout -> SELL -> BUY ไม้ถัดไป`

## 2) Hierarchy ของสัญญาณ (แก้ HOLD เพราะ TF ขัดกัน)
กำหนด precedence ชัดเจน:
1. **HTF filter (4H/1D)**: อนุญาตเฉพาะฝั่งเดียว (trend-follow only)
2. **15m trigger**: ใช้หา timing เข้าออกเท่านั้น
3. **1m/5m**: ใช้ micro timing ตอน execute (optional)

กติกา:
- ถ้า HTF = Bearish -> ห้าม BUY ใหม่ ยกเว้นมี reversal regime ที่นิยามชัดเจน
- ถ้า HTF = Bullish -> อนุญาต BUY เมื่อ 15m ให้ trigger อย่างน้อย 2/3 เงื่อนไข

## 3) Tool diet (ลดเหลือ Core 4)
ให้ใช้แค่:
- `get_htf_trend`
- `get_recent_indicators`
- `check_volatility`
- `get_deep_news_by_category` (เฉพาะช่วงข่าวแรง)

ปิดหรือย้ายเป็น secondary tools:
- `detect_rsi_divergence`, `check_bb_rsi_combo`, `check_bb_squeeze`, `calculate_ema_distance`, `detect_swing_low`

เหตุผล: ลดสัญญาณซ้ำซ้อน + ลด conflict + ลด latency/token

## 4) Confidence calibration ใหม่ (ผูกกับ spread coverage)
แทนการให้ model เดา confidence ล้วน ๆ ให้ map จาก expected edge:
- สร้าง `edge_score = expected_move / effective_spread`
- map confidence ตาม edge_score:
  - edge_score < 1.0 => max confidence 0.59 (บังคับ HOLD)
  - 1.0-1.3 => 0.60-0.68
  - 1.3-1.8 => 0.69-0.78
  - >1.8 => 0.79+

RiskManager ใช้ confidence หลัง map เท่านั้น

## 5) บังคับ 6 ไม้/วันแบบไม่ฆ่าพอร์ต
นิยาม "ซื้อ 6 ไม้" ให้เป็น 6 entries ที่มี risk budget ต่อไม้คงที่:
- ไม้ 1-2: ขนาด 1,000 THB
- ไม้ 3-4: 1,000 THB เฉพาะเมื่อ cumulative PnL >= 0
- ไม้ 5-6: อนุญาตเมื่อ daily drawdown ไม่เกิน -1R

Hard rules:
- ไม้ใหม่เปิดได้ต่อเมื่อไม้ก่อนหน้า flat แล้ว (ไม่ซ้อน position)
- ถ้า daily loss ถึง limit ให้เข้าไม้ที่เหลือด้วย size ต่ำสุด + เงื่อนไขเข้มขึ้น
- ถ้าไม่ผ่านเงื่อนไขคุณภาพ entry ให้เลื่อนเวลาเข้า แต่ยังต้องครบ 6 ภายใน session

## 6) เปลี่ยนกฎออกจากตลาด (Exit first)
ใช้ 3 exit path:
1. TP/SL by ATR (dynamic)
2. Time stop (เช่น 45-90 นาที)
3. Regime flip exit (HTF/15m เปลี่ยนฝั่ง)

ยกเลิกกติกา “PnL > 0 และ 20 นาทีให้ปิด” แบบตายตัว เพราะไม่สัมพันธ์ spread จริง

## 7) ลำดับการลงมือ (ทำจริงได้ทันที)
Phase A (วันนี้):
- แก้ `roles.json` ให้มี hierarchy ชัดเจน + confidence based on edge
- ลด tools ใน `skills.json`

Phase B (ถัดไป):
- เพิ่มการคำนวณ `effective_spread` และ `expected_move` ใน orchestrator/prompt payload
- RiskManager รับ `edge_score` เพื่อ gate BUY โดยตรง

Phase C:
- เพิ่ม scheduler สำหรับภารกิจ “ต้องซื้อ 6 ไม้/วัน” พร้อม safety budget

## KPI ที่ต้องดูหลังแก้
- Hold rate (ควรลดลง)
- % entries ที่ edge_score >= 1
- Avg time-in-trade
- Net PnL/day หลังหัก spread โดยนัย
- Max drawdown ต่อวัน
