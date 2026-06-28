# Fundamental Tools — คำอธิบาย เหตุผล และ Flow การทำงาน

ไฟล์: `fundamental_tools.py`

รวม Tools ด้าน **ปัจจัยพื้นฐาน (Fundamental Analysis)** ที่ LLM Agent ใช้ประกอบการตัดสินใจเทรดทองคำ
ข้อมูลเหล่านี้เป็นสิ่งที่ **กราฟ (Technical Analysis) ไม่สามารถบอกได้** เช่น ข่าวเศรษฐกิจ, สถาบันซื้อ/ขาย, ความสัมพันธ์ข้ามตลาด

---

## 1. `get_deep_news_by_category(category: str)`

### คำอธิบาย
ดึงข่าวเจาะลึกตามหมวดหมู่ที่สนใจ เช่น นโยบาย Fed, เงินเฟ้อ, ภูมิรัฐศาสตร์

### เหตุผลที่ใช้
- ข่าวมหภาค (Macro News) เป็นตัวขับเคลื่อนราคาทองระยะกลาง-ยาว
- กราฟเทคนิคัลบอกไม่ได้ว่า "ทำไม" ราคาขยับ ข่าวช่วยให้ LLM เข้าใจ context
- เช่น ถ้า Fed ส่งสัญญาณ Hawkish -> ทองมักถูกกด, ถ้ามี Geopolitical risk -> ทองมัก rally

### หมวดหมู่ที่รองรับ
`gold_price`, `usd_thb`, `fed_policy`, `inflation`, `geopolitics`, `dollar_index`, `thai_economy`, `thai_gold_market`

### Flow การทำงาน
```
get_deep_news_by_category("fed_policy")
|
+-- 1. Import merged fetch_news() จาก data_engine/tools
|
+-- 2. เรียก fetch_news(category="fed_policy", deep_dive=True)
|      +-- ดึงข่าวจากหลายแหล่ง (RSS, API) แล้วกรองตาม category
|
+-- 3. Return dict
       +-- status: "success"
       +-- category: "fed_policy"
       +-- articles: [{title, summary, source, date}, ...]
       +-- count: จำนวนข่าว
```

---

## 2. `check_upcoming_economic_calendar(hours_ahead: int = 24)`

### คำอธิบาย
เช็คปฏิทินเศรษฐกิจล่วงหน้า เพื่อหา "ข่าวกล่องแดง" (High Impact)
เช่น Non-Farm Payrolls (NFP), CPI, การประชุม FOMC

### เหตุผลที่ใช้
- **ข่าว High Impact ทำให้ราคาสวิงรุนแรงภายในวินาที** กราฟเทคนิคัลไม่สามารถเตือนล่วงหน้าได้
- LLM ต้องรู้ว่า "อีกกี่ชั่วโมงจะมีข่าวอะไร" เพื่อ:
  - **ห้ามเทรด** ถ้าข่าว High USD <= 2 ชม. (risk_level = critical)
  - **ลด position** ถ้ามีข่าว High USD ใน window (risk_level = high)
  - **ระวัง volatility** ถ้ามี Medium impact (risk_level = medium)
  - **เทรดปกติ** ถ้าไม่มีข่าว (risk_level = low)

### Data Source
ForexFactory JSON Feed (public mirror, อัปเดตรายสัปดาห์)
```
URL: https://nfs.faireconomy.media/ff_calendar_thisweek.json
```
- **ข้อดีของ JSON** (เทียบกับ XML): date มาเป็น ISO-8601 พร้อม timezone offset
  เช่น `"2024-07-05T08:30:00-04:00"` ใช้ `datetime.fromisoformat()` แปลงได้ทันที

### Flow การทำงาน
```
check_upcoming_economic_calendar(hours_ahead=24)
|
+-- Step 1: FETCH JSON
|   +-- GET ff_calendar_thisweek.json -> ได้ ~100 events ทั้งสัปดาห์
|
+-- Step 2: PARSE + CONVERT TIMEZONE
|   +-- กรองสกุลเงินที่กระทบทอง: USD, EUR, GBP, JPY, CNY, CHF
|   +-- datetime.fromisoformat(date_str) -> แปลง ISO-8601+offset -> UTC
|   +-- กรอง Tentative/All Day -> เก็บเฉพาะ High USD (อาจสำคัญ)
|   +-- กรองเวลา: เฉพาะ events ภายใน hours_ahead window
|
+-- Step 3: CLASSIFY RISK
|   +-- "critical" -> High USD <= 2 ชม. -> ห้ามเทรด!
|   +-- "high"     -> High USD ใน window -> ลด position
|   +-- "medium"   -> Medium หรือ High สกุลอื่น -> ระวัง
|   +-- "low"      -> ไม่มีข่าว -> เทรดตาม technical ได้
|
+-- Step 4: INTERPRETATION
    +-- สร้างข้อความสรุปสำหรับ LLM
        เช่น "CRITICAL: NFP ออกอีก 1.5 ชม. -> ห้ามเปิดออเดอร์ใหม่!"
```

### ตัวอย่าง Output
```json
{
  "status": "success",
  "risk_level": "critical",
  "high_impact_usd_count": 1,
  "events": [
    {
      "title": "Non-Farm Employment Change",
      "country": "USD",
      "impact": "High",
      "hours_until": 1.5,
      "forecast": "180K",
      "previous": "175K"
    }
  ],
  "interpretation": "CRITICAL: Non-Farm Employment Change ออกอีก 1.5 ชม. -> ห้ามเปิดออเดอร์ใหม่!"
}
```

---

## 3. `get_intermarket_correlation()`

### คำอธิบาย
ตรวจสอบความสัมพันธ์ข้ามตลาดระหว่าง Gold, DXY (Dollar Index), และ US10Y (10-Year Treasury Yield)
คำนวณ correlation 20 วัน และตรวจหา divergence ที่ผิดปกติ

### เหตุผลที่ใช้
- **ทองคำมักวิ่งสวนทาง DXY และ US10Y** (inverse correlation)
  - ดอลลาร์แข็ง -> ทองลง, ดอลลาร์อ่อน -> ทองขึ้น
  - Bond yield ขึ้น -> ทองลง (ต้นทุนค่าเสียโอกาสสูงขึ้น)
- **ถ้า correlation ผิดปกติ (positive)** = สัญญาณเตือน
  - Gold ขึ้น + DXY ขึ้น = Bearish warning -> ทองอาจกลับลง
  - Gold ลง + DXY ลง = Bullish warning -> ทองอาจกลับขึ้น
- กราฟทองอย่างเดียวบอกไม่ได้ว่าแรงขับเคลื่อนมาจาก Dollar หรือ Bond market

### Data Source
yfinance (ฟรี, real-time)
```
GC=F      -> Gold Futures (USD/oz)
DX-Y.NYB  -> Dollar Index (DXY)
^TNX      -> US 10-Year Treasury Yield
```

### Flow การทำงาน
```
get_intermarket_correlation()
|
+-- Step 1: FETCH DATA (yfinance, period="1mo")
|   +-- GC=F     -> Gold Futures price
|   +-- DX-Y.NYB -> DXY value
|   +-- ^TNX     -> US10Y yield
|
+-- Step 2: COMPUTE % CHANGE
|   +-- 1-day % change (ล่าสุด vs วันก่อน)
|   +-- 5-day % change (ล่าสุด vs 5 วันก่อน)
|
+-- Step 3: CORRELATION MATRIX (Pearson 20 วัน)
|   +-- gold_vs_dxy   -> ปกติ = -0.3 ถึง -0.8 (inverse)
|   +-- gold_vs_us10y -> ปกติ = -0.2 ถึง -0.6 (inverse)
|   (ค่าบวก = ผิดปกติ -> ระวัง reversal)
|
+-- Step 4: DETECT DIVERGENCE
|   +-- Gold + DXY ขึ้นทั้งคู่  -> "bearish_warning"
|   +-- Gold + DXY ลงทั้งคู่   -> "bullish_warning"
|   +-- Gold + Yield ขึ้นทั้งคู่ -> "bearish_warning"
|   +-- correlation > +0.3      -> "abnormal_positive" regime
|
+-- Step 5: INTERPRETATION
    +-- เช่น "Gold -0.10% + DXY -0.17% -> ผิดปกติ ทองอาจกลับขึ้น"
```

### ตัวอย่าง Output
```json
{
  "status": "success",
  "gold": { "price_usd": 4787.40, "change_1d_pct": -0.1, "change_5d_pct": 2.92 },
  "dxy": { "value": 98.65, "change_1d_pct": -0.17, "change_5d_pct": -1.38 },
  "us10y": { "yield_pct": 4.32, "change_1d_pct": 0.56, "change_5d_pct": 0.09 },
  "correlation_20d": { "gold_vs_dxy": 0.067, "gold_vs_us10y": null },
  "divergences": [
    { "pair": "gold_vs_DXY", "status": "bullish_warning",
      "note": "Gold -0.10% + DXY -0.17% -> ผิดปกติ ทองอาจกลับขึ้น" }
  ],
  "interpretation": "Gold -0.10% + DXY -0.17% -> ผิดปกติ ทองอาจกลับขึ้น"
}
```

---

## 4. `get_gold_etf_flow()`

### คำอธิบาย
ดึงข้อมูล Gold ETF Flow จาก SPDR Gold Trust (GLD) ซึ่งเป็นกองทุนทองที่ใหญ่ที่สุดในโลก
ดูการเปลี่ยนแปลง "Total Ounces of Gold in the Trust" (ทองจริงในคลัง) เพื่อวัด institutional flow

### เหตุผลที่ใช้
- **SPDR GLD ถือทองจริง ~1,050 ตัน** เมื่อสถาบันซื้อ/ขายหุ้น GLD, ทองจริงในคลังจะเพิ่ม/ลด
- Ounces in Trust เพิ่ม = สถาบัน **สะสม (Accumulating)** -> Bullish
- Ounces in Trust ลด = สถาบัน **เทขาย (Distributing)** -> Bearish
- **Volume spike** ยิ่งยืนยันว่าเป็น institutional activity
- ข้อมูลนี้กราฟ technical ไม่มี ต้องดูจากแหล่งเฉพาะ

### Data Source (2 ชั้น)
```
Layer 1 (Primary): SPDR Historical XLSX
  URL: https://api.spdrgoldshares.com/.../historical-archive
  Sheet: 'US GLD Historical Archive'
  ข้อมูล: Total Ounces in Trust, Tonnes, Closing Price, Volume (5,500+ rows ตั้งแต่ 2004)
  Cache: .cache/spdr_gld.xlsx (max age 6 ชม.)

Layer 2 (Fallback): yfinance GLD
  ใช้เมื่อ XLSX ดาวน์โหลดไม่ได้
  ข้อมูล: Price, Volume, Volume ratio (ไม่มี Ounces in Trust)
```

### Flow การทำงาน
```
get_gold_etf_flow()
|
+-- Layer 1: SPDR XLSX (Primary)
|   +-- 1. ตรวจ cache (.cache/spdr_gld.xlsx, max age 6 ชม.)
|   +-- 2. ดาวน์โหลด XLSX ถ้าไม่มี cache
|   +-- 3. pd.read_excel(sheet_name='US GLD Historical Archive')
|   +-- 4. หา column ด้วย keyword matching:
|   |      +-- ["total", "ounces"] -> 'Total Ounces of Gold in the Trust'
|   |      +-- ["tonnes"]          -> 'Tonnes of Gold'
|   |      +-- ["closing"]         -> 'Closing Price'
|   |      +-- ["volume"]          -> 'Daily Share Volume'
|   +-- 5. เปรียบเทียบ latest vs previous day
|   |      +-- oz_change > 1000   -> "inflow" (accumulating)
|   |      +-- oz_change < -1000  -> "outflow" (distributing)
|   |      +-- else               -> "flat" (neutral)
|   +-- 6. คำนวณ 5-day net change + volume ratio
|
+-- Layer 2: yfinance GLD (Fallback)
|   +-- ดึง GLD price + volume 15 วัน
|   +-- คำนวณ volume_ratio = today / avg_10d
|   +-- volume > 2x + price ขึ้น -> "likely_inflow"
|   +-- volume > 2x + price ลง  -> "likely_outflow"
|
+-- Return: ใช้ Layer 1 ก่อน ถ้า fail ใช้ Layer 2
```

### ตัวอย่าง Output (SPDR Primary)
```json
{
  "status": "success",
  "source": "spdr_xlsx",
  "ounces_in_trust": 33836318.04,
  "ounces_change_1d": 0.0,
  "ounces_change_5d": 45929.39,
  "tonnes_in_trust": 1052.42,
  "tonnes_change_1d": 0.0,
  "tonnes_change_5d": 1.43,
  "flow_direction": "flat",
  "institutional_signal": "neutral",
  "gld_close_usd": 437.13,
  "volume_ratio": 0.59,
  "interpretation": "Holdings ไม่เปลี่ยนแปลงอย่างมีนัยสำคัญ | 5 วันย้อนหลัง: สะสม 1.43 ตัน"
}
```

---

## 5. `check_fed_speakers_schedule()` (ยังไม่ implement)

### เหตุผลที่ยังไม่ implement
- ไม่มี free API ที่ให้ตาราง Fed speakers แบบ real-time
- ข้อมูลนี้ส่วนใหญ่ฝังอยู่ในข่าวที่ `get_deep_news_by_category("fed_policy")` ดึงได้อยู่แล้ว

---

## 6. `get_institutional_positioning()` (ยังไม่ implement)

### เหตุผลที่ยังไม่ implement
- COT Report ออกรายสัปดาห์ (ทุกวันศุกร์) ไม่ใช่ real-time
- `get_gold_etf_flow()` ให้ข้อมูล institutional flow ที่อัปเดตรายวันได้แล้ว

---

## สรุปสถานะ

| Tool | Status | Data Source |
|------|--------|-------------|
| `get_deep_news_by_category` | พร้อมใช้ | merged fetch_news (RSS/API) |
| `check_upcoming_economic_calendar` | พร้อมใช้ | ForexFactory JSON |
| `get_intermarket_correlation` | พร้อมใช้ | yfinance (GC=F, DXY, ^TNX) |
| `get_gold_etf_flow` | พร้อมใช้ | SPDR XLSX + yfinance fallback |
| `check_fed_speakers_schedule` | รอพัฒนา | - |
| `get_institutional_positioning` | รอพัฒนา | - |