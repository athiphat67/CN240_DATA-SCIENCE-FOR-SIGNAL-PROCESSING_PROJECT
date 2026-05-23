# Technical Tools — คู่มือการใช้งาน
> ระบบ Tools สำหรับวิเคราะห์ราคาทองคำไทย 96.5 (บาททอง)  
> แต่ละ tool ถูกออกแบบให้ LLM เรียกใช้เพื่อประกอบการตัดสินใจเทรด

---

## ภาพรวมโครงสร้าง

Tools แบ่งออกเป็น 3 กลุ่มตามลักษณะการทำงาน

| กลุ่ม | ลักษณะ | Tools |
|---|---|---|
| **Group A** | ต้องการ Candle Series — วิเคราะห์ Pattern/Divergence | 5 tools |
| **Group B** | Snapshot + Threshold — เช็กสัญญาณ ณ ปัจจุบัน | 2 tools |
| **HTF** | Higher Timeframe — ดูภาพใหญ่ | 1 tool |

---

## Group A — Pattern & Divergence Tools

### 1. `check_spot_thb_alignment`

**ทำอะไร:**  
เปรียบเทียบทิศทางของ XAU/USD (ราคาทองโลก) กับ USD/THB (อัตราแลกเปลี่ยน) ในช่วงเวลาเดียวกัน โดยคำนวณ % Change ย้อนหลัง `lookback_candles` แท่ง

**Logic:**

```
ทองโลก ↑  +  บาทอ่อน (USD/THB ↑)  →  "Strong Bullish"
ทองโลก ↓  +  บาทแข็ง (USD/THB ↓)  →  "Strong Bearish"
ทองโลก ↑  +  บาทแข็ง              →  "Neutral (Spot Leading)"
ทองโลก ↓  +  บาทอ่อน              →  "Neutral (THB Leading)"
```

**ผลต่อทองไทย 96.5:**  
ราคาทองไทยเป็น **ผลคูณ** ของทั้งสองตัวแปร (`XAU/USD × USD/THB`) ดังนั้น:
- `Strong Bullish` = แรงดันขึ้นซ้อนกันทั้งสองทาง → โอกาสทะลุแนวต้านสูง
- `Strong Bearish` = แรงกดลงซ้อนกัน → โอกาสหลุดแนวรับสูง
- `Neutral` = แรงหักล้างกัน → ราคามักออกข้างหรือขึ้น/ลงช้า

**Parameters หลัก:**
- `interval` — Timeframe เช่น `"15m"`, `"1h"`
- `lookback_candles` — จำนวนแท่งย้อนหลัง (default 4 แท่ง)
- `df_spot` — รับ DataFrame ของ XAU/USD จากหน่วยความจำได้ ถ้าไม่ส่งจะดึงใหม่อัตโนมัติ
- `df_thb` — รับ DataFrame ของ USD/THB จากหน่วยความจำได้ ถ้าไม่ส่งจะดึงใหม่อัตโนมัติ

> ทั้ง `df_spot` และ `df_thb` เป็นอิสระต่อกัน ส่งแค่ตัวเดียวก็ได้ อีกตัวจะดึงเองอัตโนมัติ

---

### 2. `detect_breakout_confirmation`

**ทำอะไร:**  
รับ Zone (บน-ล่าง) แล้ววิเคราะห์แท่งเทียนล่าสุดว่าการทะลุโซนนั้น **จริง (Confirmed)** หรือ **หลอก (Fakeout)** โดยดูจากสัดส่วนของแท่งเทียน

**Logic:**

```
body_pct = (เนื้อเทียน / ความยาวทั้งแท่ง) × 100

Confirmed Breakout ขาขึ้น:
  - ราคาปิดอยู่เหนือ zone_top
  - body_pct ≥ 50%  (แท่งแรง ไม่ใช่ไส้ยาว)
  - ไส้บน ≤ เนื้อเทียน  (ไม่โดนตบลงมา)

Confirmed Breakdown ขาลง:
  - ราคาปิดอยู่ใต้ zone_bottom
  - body_pct ≥ 50%
  - ไส้ล่าง ≤ เนื้อเทียน  (ไม่โดนงัดขึ้น)
```

**ผลต่อทองไทย 96.5:**  
ใช้กรองก่อน Follow เทรนด์ เพราะทองไทยมักเกิด Fakeout บ่อยในช่วงตลาดบาง (เช้าก่อนยุโรปเปิด) การรอ Confirmed ช่วยลด Stop-out จากการเข้าเร็วเกินไป

**Edge Cases:**
- แท่ง **Doji สมบูรณ์** (high == low) → return `is_confirmed_breakout: false` ทันที พร้อม message `"แท่งเทียน Doji ไม่สามารถยืนยัน Breakout ได้"` ไม่คำนวณต่อ
- ราคายังอยู่ในโซน → return `is_confirmed_breakout: false` พร้อม message

---

### 3. `get_support_resistance_zones`

**ทำอะไร:**  
ค้นหาโซนแนวรับ-แนวต้านที่ **มีนัยสำคัญทางสถิติ** โดยใช้ DBSCAN Clustering รวม Swing Highs/Lows ที่อยู่ใกล้กันเข้าเป็นโซนเดียว

**Logic (4 ขั้นตอน):**

```
1. คำนวณ ATR-14 → ได้ค่าความผันผวนปัจจุบัน
2. คำนวณ Adaptive EPS = ATR × 0.7  (clamp: 50–200 บาท)
3. หา Swing Highs/Lows ด้วย find_peaks + prominence
4. DBSCAN Clustering ด้วย EPS ที่ได้ → รวมจุดใกล้กันเป็นโซน
```

**ประเภทโซนที่ได้:**

| type | เงื่อนไข | ความหมาย |
|---|---|---|
| `Resistance` | `bottom_edge > current_price` | โซนอยู่เหนือราคาปัจจุบัน |
| `Support` | `top_edge < current_price` | โซนอยู่ใต้ราคาปัจจุบัน |
| `In-Range (Testing Zone)` | `bottom_edge ≤ price ≤ top_edge` | ราคากำลังอยู่ในโซน / กำลังทดสอบโซนนี้ |

**Strength:**
- `High` = 4+ touches
- `Medium` = 3 touches
- `Low` = 2 touches

**ผลต่อทองไทย 96.5:**  
Adaptive EPS ทำให้โซนยืดหยุ่นตามตลาด เช่น ช่วงทองผันผวนสูง (ATR = 300) จะได้ EPS = 200 → โซนกว้างขึ้น ไม่ตีกรอบแคบเกินความเป็นจริง ส่วน `In-Range (Testing Zone)` บอก LLM ว่าราคากำลัง **ตัดสินใจ** ณ จุดสำคัญ ควรรอดูทิศทางก่อนเปิดออเดอร์

---

### 4. `detect_swing_low`

**ทำอะไร:**  
สแกนย้อนหลัง `lookback_candles` แท่ง เพื่อหาโครงสร้าง **Swing Low ที่ได้รับการยืนยันแล้ว** (V-shape ที่ราคาพุ่งทะลุ High ของแท่ง Swing ไปได้)

**Logic:**

```
สแกนจากปัจจุบันย้อนไปอดีต:
  1. หาแท่ง i ที่ low[i] < low[i-1] และ low[i] < low[i+1]  → Swing Low
  2. หาแท่ง j (j > i) ที่ close[j] > high[i]              → Confirmation
  3. เจอคู่แรก → หยุดสแกน (ใช้ที่ใกล้ปัจจุบันที่สุด)
```

**ผลต่อทองไทย 96.5:**  
สัญญาณ `setup_detected: true` หมายความว่ามีโอกาส **Bullish Reversal** — ราคาทำจุดต่ำแล้วมีแรงซื้อดันขึ้นทะลุ High ก่อนหน้า เหมาะใช้ร่วมกับ `get_support_resistance_zones` เพื่อยืนยันว่า Swing Low เกิดบนแนวรับสำคัญจริงหรือไม่

---

### 5. `detect_rsi_divergence`

**ทำอะไร:**  
ตรวจหา **RSI Bullish Divergence** โดยเปรียบเทียบจุดก้นเหว (Trough) 2 จุดล่าสุดของราคา กับค่า RSI-14 ณ จุดเดียวกัน

**Logic:**

```
หา Trough ด้วย find_peaks(-low, prominence=20):
  - idx1 = ก้นเหวอดีต   (Low1, RSI1)
  - idx2 = ก้นเหวปัจจุบัน (Low2, RSI2)

Bullish Divergence = Low2 < Low1  AND  RSI2 > RSI1
(ราคาทำ Low ใหม่ แต่ RSI ยกตัวขึ้น → momentum ถดถอย)
```

**ผลต่อทองไทย 96.5:**  
Divergence บ่งชี้ว่า **แรงขายกำลังหมด** ก่อนที่ราคาจะกลับตัว เป็นสัญญาณ Early Warning ที่มักปรากฏก่อน Swing Low จะ Confirm ไม่กี่แท่ง ใช้คู่กับ `detect_swing_low` เพื่อยืนยันซ้อนกัน

---

## Group B — Snapshot Tools

### 6. `check_bb_rsi_combo`

**ทำอะไร:**  
เช็กว่าเกิด **Oversold Combo** พร้อมกัน 3 เงื่อนไขหรือไม่ (Bollinger Band + RSI + MACD)

**Logic:**

```
is_price_low      = close < lower_bb
is_rsi_oversold   = rsi_14 < 35.0
is_macd_flatten   = |macd_hist| < 0.3  OR  macd_hist กำลังเพิ่มขึ้น

combo_detected = ทั้งสาม True พร้อมกัน
```

**ผลต่อทองไทย 96.5:**  
เมื่อ `combo_detected: true` หมายความว่าทองอยู่ในโซน Oversold หนัก และ Momentum กำลังชะลอตัว เป็น Setup สำหรับหาจังหวะ **Buy บริเวณล่าง** ก่อนราคาดีดกลับ ไม่ควรใช้คนเดียว ควรตรวจ `get_support_resistance_zones` ว่าราคาอยู่บนแนวรับจริงด้วย

---

### 7. `calculate_ema_distance`

**ทำอะไร:**  
วัดระยะห่างระหว่างราคาปัจจุบันกับ EMA-20 โดย **normalize ด้วย ATR** เพื่อให้ค่าเทียบกันได้ข้ามช่วงเวลา

**Logic:**

```
distance = (EMA_20 - close) / ATR_14

is_overextended = |distance| > 5.0
```

**ผลต่อทองไทย 96.5:**  
ค่า `distance_atr_ratio`:
- **บวก** = ราคาอยู่ **ต่ำกว่า** EMA (ทองถูก)
- **ลบ** = ราคาอยู่ **สูงกว่า** EMA (ทองแพง)
- **|distance| > 5** = Overextended — ราคาวิ่งห่าง EMA มากผิดปกติ สัญญาณเตือน Mean Reversion อาจเกิดขึ้น ไม่ควรเพิ่ม Position ตามทิศทางเดิม

---

## HTF — Higher Timeframe

### 8. `get_htf_trend`

**ทำอะไร:**  
ตรวจสอบ **เทรนด์หลัก** โดยเทียบราคาปิดล่าสุดกับ EMA-200 ใน Timeframe ใหญ่ (`1h`, `4h`, `1d`)

**Logic:**

```
trend = "Bullish"  if close > EMA_200
trend = "Bearish"  if close < EMA_200

distance_pct = ((close - EMA_200) / EMA_200) × 100
```

**ผลต่อทองไทย 96.5:**  
EMA-200 บน `1h` หรือ `4h` คือ **Bias หลัก** ของระบบ:
- `Bullish` → เน้นหาจังหวะ Buy เท่านั้น tools กลุ่ม A/B ใช้ยืนยัน Entry
- `Bearish` → เน้นหาจังหวะ Sell หรืองดเทรดฝั่ง Buy

ควรเรียก tool นี้เป็น **ตัวแรกเสมอ** เพื่อกำหนด Bias ก่อนใช้ tool อื่น

**Parameters หลัก:**
- `timeframe` — Timeframe ใหญ่ เช่น `"1h"`, `"4h"`, `"1d"`
- `history_days` — จำนวนวันย้อนหลัง (default 15 วัน ต้องการ 200+ แท่ง)
- `ohlcv_df` — รับ DataFrame จากหน่วยความจำได้ ถ้าไม่ส่งจะดึงใหม่อัตโนมัติ

---

## แนวทางการใช้งานร่วมกัน (Suggested Flow)

```
1. get_htf_trend               → กำหนด Bias (Bullish/Bearish)
2. check_spot_thb_alignment    → เช็ก Macro Alignment ว่าเสริมหรือหักล้าง
3. get_support_resistance_zones → หาโซนสำคัญที่ราคากำลังเข้าใกล้
4. detect_swing_low             → ยืนยันว่าเกิด Structure กลับตัวหรือยัง
   + detect_rsi_divergence      → ยืนยัน Momentum ซ้ำ
5. check_bb_rsi_combo           → เช็ก Oversold Combo สำหรับ Entry Buy
   + calculate_ema_distance     → ยืนยันว่าไม่ Overextended เกินไป
6. detect_breakout_confirmation → ใช้ตอนราคาทะลุโซน เพื่อกรอง Fakeout
```

---

## ⚠️ หมายเหตุ

**`check_volatility`** — ปัจจุบัน return ค่า hardcoded ยังไม่ได้ดึงข้อมูลจริง รอ implement

---

*อัปเดตล่าสุด: technical_tools.py (post code review v2)*