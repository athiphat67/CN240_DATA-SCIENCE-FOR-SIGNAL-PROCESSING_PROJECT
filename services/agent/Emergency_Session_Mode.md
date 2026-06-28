🚨 Implementation Plan: Emergency Session Mode
🎯 Objective
เพื่อแก้ไขปัญหาการ "ตกรถ" (ไม่ได้เทรดเลยตลอด Session) หรือการ "ติดดอยข้ามคืน" (ถือทองไว้จนตลาดปิดหรือหมดช่วงเวลาเทรด) โดยการเพิ่มโหมดฉุกเฉินที่จะบังคับให้ Agent ตัดสินใจขั้นเด็ดขาดเมื่อเวลาใกล้หมด
---
🛠 Phase 1: Emergency Mode Detection
เป้าหมาย: กำหนดเงื่อนไขการเข้าสู่โหมดฉุกเฉินใน `AnalysisService` หรือ `RiskManager`
Entry Emergency (Forced BUY):
เงื่อนไข: `minutes_to_session_end <= 20` นาที AND `trades_this_session == 0`
เป้าหมาย: บังคับหาจังหวะซื้อเพื่อให้ครบโควต้าขั้นต่ำ (อย่างน้อย 1 ไม้/Session)
Exit Emergency (Forced SELL):
เงื่อนไข: `minutes_to_session_end <= 5` นาที AND `gold_grams > 0`
เป้าหมาย: บังคับขายทุกกรณีเพื่อ Clear Inventory ไม่ให้ถือค้างข้าม Session
---
✍️ Phase 2: Prompt & Logic Injection
เป้าหมาย: ปรับพฤติกรรม Agent ผ่าน Prompt และข้าม Gate ของ Risk Management
Update `PromptBuilder` (`Src/agent_core/core/prompt.py`):
เพิ่ม Section "⚠️ EMERGENCY SESSION DIRECTIVE" ใน User Prompt เมื่อเข้าเงื่อนไข
Instruction (Forced BUY): "URGENT: Session ends in {N} mins. Zero trades completed. RELAX all technical gates. Find any reasonable support or momentum to ENTER now."
Instruction (Forced SELL): "URGENT: Session ends in {N} mins. SELL ALL gold immediately. Profit/Loss is irrelevant. Market exit is mandatory."
Update `RiskManager.evaluate` (`Src/agent_core/core/risk.py`):
(มีบางส่วนแล้ว) เสริม Logic ให้ข้าม `edge_score` และ `confidence_threshold` ปกติเมื่ออยู่ในโหมด Emergency Forced Buy
บังคับ `signal = SELL` และ `confidence = 1.0` ทันทีในโหมด Emergency Forced Sell
---
🛡 Phase 3: Integration into `AnalysisService`
เป้าหมาย: ควบคุมการเลือก Role และการส่งสัญญาณฉุกเฉิน
Dynamic Role Override:
หากอยู่ใน `Forced Buy Emergency` ให้เปลี่ยน Role เป็น `aggressive_bullish` อัตโนมัติ (ไม่ว่าเทรนด์จะเป็นอย่างไร) เพื่อเน้นการหาจุดเข้า
หากอยู่ใน `Forced Sell Emergency` ให้ใช้ Role `defensive_scavenger` เพื่อเน้นการหาจุดออกแบบไม่ขาดทุนมากที่สุด (หรือบังคับขายตรงๆ)
---
📅 Timeline & Tasks
[ ] Task 1: เพิ่มสถานะ `is_emergency_buy` และ `is_emergency_sell` ใน `market_state`
[ ] Task 2: ปรับปรุง `PromptBuilder` ให้แสดง Directive ฉุกเฉิน
[ ] Task 3: ปรับปรุง `RiskManager` ให้ยอมรับสัญญาณที่ต่ำกว่าเกณฑ์ปกติในโหมดฉุกเฉิน
[ ] Task 4: ทดสอบสถานการณ์จำลอง (Simulate low minutes left)
---
> [!CAUTION]
> โหมดฉุกเฉินมีความเสี่ยงสูง (High Risk) เนื่องจากเป็นการละทิ้งกฎเกณฑ์บางข้อเพื่อรักษาโควต้าหรือล้างพอร์ต ควรใช้เฉพาะในกรณีที่จำเป็นจริงๆ ตามที่กำหนดเท่านั้น


