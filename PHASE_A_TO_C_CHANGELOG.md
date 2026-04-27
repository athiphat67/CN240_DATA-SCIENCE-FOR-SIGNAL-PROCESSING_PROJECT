# Phase A → C Implementation Summary

เอกสารนี้สรุปการแก้ระบบตั้งแต่รอบแรกจนถึงปัจจุบัน โดยยึดเป้าหมายเดิม:
- ทุนเริ่ม 1,500 THB
- ขั้นต่ำซื้อ 1,000 THB
- ต้องบริหารให้ครบ 6 ไม้/วัน
- ลดการเข้า BUY ที่แพ้ spread ตั้งแต่ต้น

---

## Baseline Problem (ก่อนเริ่มแก้)
1. Prompt และ Risk ไม่ผูกกับ spread economics จริง
2. Tool surface กว้างและซ้ำซ้อน ทำให้ LLM รับสัญญาณตีกัน
3. Position sizing ยังไม่ sync กับขั้นต่ำซื้อ 1,000 THB
4. ไม่มี execution scheduler สำหรับโควต้า 6 ไม้/วัน
5. Decision handoff จาก ReAct ไป Risk ขาด metadata บางส่วน

---

## Phase A (วันแรก): Prompt/Skill Alignment

### สิ่งที่แก้
- ปรับ role config ให้ใช้ threshold และ size ที่เหมาะกับข้อจำกัดจริง
  - `confidence_threshold = 0.62`
  - `max_position_thb = 1000`
- ลด tools ใน `market_analysis` เหลือ core 4
  - `get_htf_trend`
  - `get_recent_indicators`
  - `check_volatility`
  - `get_deep_news_by_category`
- Prompt เปลี่ยนจาก hardcode 1250 เป็น dynamic max position จาก role
- Sync `MIN_BUY_CASH` เป็น 1000

### ผลลัพธ์
- ลดความขัดแย้งของ signal
- ลด token/tool overhead
- บังคับ execution size เข้ากับข้อจำกัดแอปจริง

---

## Phase B: Edge/Spread Integration

### สิ่งที่แก้
- Orchestrator เพิ่ม `market_data.spread_coverage`
  - `spread_thb`
  - `effective_spread`
  - `expected_move_thb`
  - `edge_score`
- Prompt แสดง spread coverage ให้ LLM เห็นใน MARKET STATE
- RiskManager เพิ่ม BUY gate:
  - reject ถ้า `edge_score < 1.0`
  - fallback คำนวณ expected move จาก trend % ถ้า payload ไม่ครบ

### ผลลัพธ์
- ปิดช่อง BUY ที่ expected move ไม่พอชนะ spread
- ลด false-positive BUY จาก setup สั้นที่ไม่คุ้มต้นทุน implicit

---

## Phase C: Daily Quota Scheduler + Safety Budget

### สิ่งที่แก้
- Orchestrator เพิ่ม `execution_quota` ใน payload
  - `daily_target_entries` (6)
  - `entries_done`
  - `entries_remaining`
  - `quota_met`
  - `current_slot` (แบ่งวันเป็น 6 ช่วง)
  - `min_entries_by_now`
  - `required_confidence_for_next_buy`
  - `recommended_next_position_thb`
- Prompt เพิ่ม section “Daily Entry Quota”
- RiskManager เพิ่ม scheduler guard
  - ห้าม BUY เกิน 6 entries/day
  - ถ้าตามโควต้าไม่ทัน ใช้ required confidence ของ slot ถัดไป
  - ใช้ `recommended_next_position_thb` เมื่อ LLM ไม่ส่ง position size

### ผลลัพธ์
- มี execution framework สำหรับ “ครบ 6 ไม้/วัน” แบบมี safety budget
- ไม่พึ่ง LLM ล้วนในการคุม pace ของการเข้าตลาด

---

## Cross-Cutting Fixes ที่ทำเพิ่ม
1. ป้องกัน tool leakage ใน prompt iteration 1
   - แสดงเฉพาะ tools ที่ role อนุญาตจริง
2. Normalize alias ของ tool args
   - รองรับ `tools_args` / `args` → `tool_args`
3. เพิ่ม field handoff จาก ReAct → Risk
   - ส่ง `position_size_thb`, `execution_check`, `analysis` ไป Risk โดยตรง
4. เพิ่ม HTF precedence ทั้ง prompt rule และ risk gate

---

## Final Architecture After Phases A–C
1. **Prompt/Role Layer**: edge-aware + HTF-first + quota-aware
2. **Orchestrator Layer**: spread/edge + quota scheduling metadata
3. **ReAct Layer**: robust parsing + structured decision handoff
4. **Risk Layer**: hard gates for spread, HTF, quota, confidence

---

## Practical Impact (Expected)
- HOLD/BUY decisions จะสอดคล้อง spread reality มากขึ้น
- Tool call ฟุ้ง/ซ้ำซ้อนลดลง
- BUY ที่ไม่คุ้ม spread ถูกตัดก่อนเข้าไม้
- การไล่ครบ 6 ไม้/วันมีกรอบ scheduler + safety budget ชัดเจน

---

## Files touched across phases
- `Src/agent_core/config/roles.json`
- `Src/agent_core/config/skills.json`
- `Src/agent_core/core/prompt.py`
- `Src/agent_core/core/react.py`
- `Src/agent_core/core/risk.py`
- `Src/data_engine/orchestrator.py`
- `STRATEGY_RESCUE_PLAN_TH.md`
