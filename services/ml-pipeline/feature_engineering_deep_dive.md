# 📊 Feature Engineering Deep Dive — `02_feature_engineering.py`

## ภาพรวม

ไฟล์นี้สร้าง **feature ทั้งหมดสำหรับ Ranker Model** ที่ใช้ทำนายจังหวะ/ลำดับความสำคัญของการเทรดทองคำไทย (HSH) เทียบกับ XAU/USD และ USD/THB  
Pipeline แบ่งเป็น 4 กลุ่มหลัก:

```
compute_rolling_synthetic()   →   Synthetic Price & Thai Premium
compute_macro_features()      →   Macro & Price Features
compute_session_features()    →   Session-Aware Features
compute_technical_features()  →   Technical Indicators + Time Proxy
```

---

## 🔧 Configuration หลัก

| Parameter | ค่า | ความหมาย |
|---|---|---|
| `OLS_WINDOW` | 2016 | จำนวนแท่งสำหรับ Rolling OLS (≈ 1 สัปดาห์ใน timeframe 5 นาที) |
| `WEIGHT_TH_BAHT` | 15.244 g | น้ำหนักทองคำ 1 บาทไทย |
| `WEIGHT_TROY_OUNCE` | 31.1035 g | น้ำหนัก 1 Troy Ounce |
| `PURITY_TH_GOLD` | 0.965 | ความบริสุทธิ์ทองไทย (96.5%) |
| `PURITY_GLOBAL_GOLD` | 0.995 | ความบริสุทธิ์ทองสากล XAU (99.5%) |

**Conversion Factor** ที่ใช้แปลงราคา XAU (USD/oz) → ราคาทองไทย (THB/บาท):

```
conv_factor = (15.244 / 31.1035) × (0.965 / 0.995) ≈ 0.4744
```

---

## 🧮 Group 1 — Synthetic Price & Thai Premium

### `F_Syn_Price` — ราคาทองไทยเชิงทฤษฎี (Rolling OLS)

**วิธีคิด:**  
ใช้ Rolling OLS (Ordinary Least Squares) ขนาด 2016 แท่ง ประมาณความสัมพันธ์เชิงเส้นระหว่าง:
- `x` = XAU_Close × conv_factor × USD_Close  → ราคาทองในหน่วย THB/บาท ถ้าไม่มี premium
- `y` = HSH_Sell_Sim → ราคาขายจริงของ HSH

```
F_Syn_Price = slope × x + intercept
```

**ทำไมถึงสำคัญ:**  
- แทนที่จะแปลงราคาตรงๆ ด้วย conv_factor (ซึ่งไม่เสถียร) OLS จะปรับ slope และ intercept ให้ fit กับข้อมูลจริงใน window ที่ผ่านมา
- ช่วยจับ structural relationship ที่เปลี่ยนตามเวลา เช่น ค่าธรรมเนียม บริษัท หรือ spread นโยบาย

**ข้อควรระวัง:** Cold start 2016 แท่งแรกถูก drop ออกเพราะไม่มีข้อมูลเพียงพอ

---

### `F_Thai_Premium` — ส่วนต่างราคาจริงกับราคาทฤษฎี

```
F_Thai_Premium = HSH_Sell_Sim − F_Syn_Price
```

**ความหมาย:**  
- ค่า **บวก** → HSH ขายแพงกว่าที่ควรจะเป็นตามราคาสากล (premium สูง)
- ค่า **ลบ** → HSH ขายถูกกว่าทฤษฎี (หายาก อาจเกิดช่วง distress)
- เป็น feature หลักที่บ่งบอก **ความตึงตัวของตลาดทองไทย** ณ ขณะนั้น

---

## 📈 Group 2 — Macro Features

### `F_Corr_XAU_USD` — Correlation ระหว่าง XAU และ USD (Rolling 18 แท่ง)

```
F_Corr_XAU_USD = rolling_corr(XAU_ret, USD_ret, window=18)
```

**ความหมาย:**  
โดยปกติ XAU และ USD มี **negative correlation** (ดอลลาร์แข็ง → ทองอ่อน)  
- ถ้า correlation เป็นบวก → ตลาดผิดปกติ อาจมี risk-off event
- ใช้จับ **ระบบนิเวศ macro** ว่าตลาดอยู่ในสภาวะปกติหรือ stress

**หมายเหตุ:** ใช้ `safe_pct_change` เพื่อไม่ให้ return คำนวณข้าม session boundary

---

### `F_XAU_Mom_Short` / `F_XAU_Mom_Mid` — Momentum ของ XAU

| Feature | Period | ความหมาย |
|---|---|---|
| `F_XAU_Mom_Short` | 3 แท่ง | Momentum ระยะสั้น (15 นาที) |
| `F_XAU_Mom_Mid` | 12 แท่ง | Momentum ระยะกลาง (1 ชั่วโมง) |

**ทำไมถึงมีทั้ง 2 ระยะ:**  
ช่วยให้ model ตรวจจับ **divergence** ได้ เช่น Short momentum กลับทิศ แต่ Mid momentum ยังขึ้น → อาจเป็นแค่ retracement ชั่วคราว

---

### `F_USD_Mom` — Momentum ของ USD (6 แท่ง)

```
F_USD_Mom = pct_change(USD_Close, periods=6)
```

ใช้จับทิศทางดอลลาร์ในกรอบ 30 นาที เพื่อประกอบกับ `F_Corr_XAU_USD`

---

### `F_ATR_48` — Average True Range (48 แท่ง)

```
TR = max(High−Low, |High−PrevClose|, |Low−PrevClose|)
F_ATR_48 = rolling_mean(TR, 48)
```

**ความหมาย:**  
วัด **ความผันผวนของ XAU** ในกรอบ 4 ชั่วโมง (48 × 5 นาที)  
ใช้เป็น **denominator** ใน features อื่น เช่น `F_SRVR`, `F_Spread_vs_ATR`

**หมายเหตุ:** ถ้า candle แรกของ session ไม่มี PrevClose → ใช้ `High−Low` แทนเพื่อหลีกเลี่ยง look-ahead

---

### `F_Regime` — แนวโน้มตลาด (EMA Crossover)

```
F_Regime = sign(EMA_20 − EMA_50)
```

| ค่า | ความหมาย |
|---|---|
| `+1` | Uptrend — EMA เร็วอยู่เหนือ EMA ช้า |
| `-1` | Downtrend — EMA เร็วอยู่ใต้ EMA ช้า |

Feature นี้ให้ model รู้ว่า "ตลาดอยู่ใน regime ไหน" ซึ่งมีผลต่อ strategy การ rank

---

## ⏱️ Group 3 — Session-Aware Features

ทุก feature ในกลุ่มนี้คำนวณ **ภายใน Session เดียว** (groupby `Session_ID`) เพื่อสะท้อนพฤติกรรมราคาภายใน session นั้นๆ

### `F_FSP` — Fractional Session Progress ⚠️ (Anti-Lookahead Design)

```
F_FSP = Bar_In_Session / (Expected_Session_Length − 1)  [clip 0–1]
```

| Session Type | Expected Length |
|---|---|
| Morning | 18 แท่ง |
| Afternoon | 27 แท่ง |
| Night | 48 แท่ง |

**ทำไมถึงใช้ Expected แทน Actual:**  
ถ้าใช้ actual session length (นับจาก session ที่ปิดไปแล้ว) จะเกิด **look-ahead bias** เพราะ model จะรู้ว่า session จะยาวแค่ไหน ณ ตอนที่ยังเทรดอยู่  
การใช้ค่า expected ที่กำหนดล่วงหน้าตาม session type ทำให้ feature นี้ **ใช้ได้จริงใน production**

**ความหมาย:**  
- `F_FSP = 0.0` → เพิ่งเปิด session
- `F_FSP = 1.0` → ใกล้ปิด session
- ช่วยให้ model ปรับพฤติกรรมตาม "เวลาที่เหลือ" ใน session

---

### `F_SA_TWAP_Dev` — ส่วนเบี่ยงเบนจาก TWAP ภายใน Session

```
F_SA_TWAP_Dev = Price − expanding_mean(Price)
```

**ความหมาย:**  
- ค่า **บวก** → ราคาปัจจุบันสูงกว่า TWAP (ราคาเฉลี่ยตลอด session ที่ผ่านมา)
- ค่า **ลบ** → ราคาปัจจุบันต่ำกว่า TWAP
- ใช้วัด **ตำแหน่งราคาสัมพัทธ์** ภายใน session โดยไม่ look-ahead

---

### `F_SA_MDD` — Max Drawdown ภายใน Session

```
F_SA_MDD = Price − expanding_max(Price)
```

**ความหมาย:**  
วัดว่าราคาลงมาจาก high สุดของ session เท่าไหร่ (เป็น 0 หรือค่าลบเสมอ)  
ช่วยตรวจจับ "ราคากำลัง pullback" ภายใน session

---

### `F_SA_Range` / `F_SA_Position` — Range และตำแหน่งในกรอบ

```
F_SA_Range    = expanding_max − expanding_min
F_SA_Position = (Price − expanding_min) / F_SA_Range
```

| `F_SA_Position` | ความหมาย |
|---|---|
| ≈ 0.0 | ราคาอยู่ใกล้จุดต่ำสุดของ session |
| ≈ 0.5 | ราคาอยู่กลาง range |
| ≈ 1.0 | ราคาอยู่ใกล้จุดสูงสุดของ session |

---

### `F_Historical_Vol_THB` — Historical Volatility ในหน่วย THB/บาท

```
xau_ret_std = rolling_std(XAU_ret, 144)      # ≈ 12 ชั่วโมง
F_Historical_Vol_THB = xau_ret_std × XAU_Close × conv_weight × USD_Close
```

แปลง volatility ของ XAU (USD/oz) ให้อยู่ในหน่วยที่ตรงกับ P&L จริงของนักลงทุนไทย (THB/บาท)

---

### `F_Remaining_Vol` — Volatility ที่คาดว่าจะเหลือในช่วงที่เหลือของ session

```
F_Remaining_Vol = F_Historical_Vol_THB × (1 − F_FSP)
```

**ความหมาย:**  
ประมาณ **ขนาดการเคลื่อนไหวที่คาดหวัง** ในช่วงที่เหลือของ session  
ยิ่ง `F_FSP` สูง → เหลือเวลาน้อย → remaining vol น้อยลง

---

### `F_SRVR` — Session Remaining Volatility Ratio

```
F_SRVR = F_Remaining_Vol / F_ATR_48
```

**ความหมาย:**  
เปรียบเทียบ remaining vol กับ ATR ล่าสุด  
- ค่าสูง → ยังมี room เคลื่อนไหวเยอะ เทียบกับ volatility ปกติ
- ค่าต่ำ → session ใกล้หมด หรือตลาดนิ่ง

เป็น **composite feature** ที่ encode ทั้ง FSP และ volatility ไว้ในตัวเลขเดียว

---

### `F_Price_Vs_Open` — ราคาเทียบกับราคาเปิด session

```
F_Price_Vs_Open = (Price − session_open) / session_open
```

**ความหมาย:**  
วัด performance ของราคาตั้งแต่ต้น session ว่าบวกหรือลบเท่าไหร่ (เป็น %)

---

### `F_Mom_1bar` / `F_Mom_3bar` — Momentum ระยะสั้นของ HSH

| Feature | Period | ความหมาย |
|---|---|---|
| `F_Mom_1bar` | 1 แท่ง (5 นาที) | Momentum แบบ tick-by-tick |
| `F_Mom_3bar` | 3 แท่ง (15 นาที) | Micro-momentum |

ทั้งคู่ใช้ `safe_pct_change` เพื่อป้องกัน cross-session calculation

---

### `F_SA_Drawdown_Pct` — Drawdown เปอร์เซ็นต์จาก High ของ Session

```
F_SA_Drawdown_Pct = (Price − expanding_max) / expanding_max
```

คล้าย `F_SA_MDD` แต่ normalize เป็น % เพื่อให้เปรียบเทียบข้าม session ได้

---

### `F_HSH_vs_THBGold_Dev` — Deviation ระหว่าง HSH และ THB Gold (Rolling 6 แท่ง)

```
thb_gold_ret = pct_change(XAU × USD)
hsh_ret      = pct_change(HSH_Sell_Sim)
F_HSH_vs_THBGold_Dev = rolling_mean(hsh_ret − thb_gold_ret, 6)
```

**ความหมาย:**  
วัดว่า HSH เคลื่อนไหว **ช้ากว่าหรือเร็วกว่า** ราคาทองในหน่วย THB ที่คำนวณจากตลาดสากล  
- ค่าบวก → HSH ขึ้นเร็วกว่า XAU (premium expanding)
- ค่าลบ → HSH ขึ้นช้ากว่า หรือ lag อยู่ (อาจมีโอกาส catch-up)

---

### `F_DayOfWeek` / `F_MinuteOfDay` — Time Features ดิบ

```
F_DayOfWeek   = index.dayofweek      # 0=จันทร์ ... 4=ศุกร์
F_MinuteOfDay = hour × 60 + minute   # 0–1439
```

Feature พื้นฐานสำหรับ model ที่ต้องการ raw time reference (ก่อน encoding)

---

## 📐 Group 4 — Technical Features

### `F_RSI_14` / `F_RSI_6` — Relative Strength Index

```
RSI = 100 − (100 / (1 + avg_gain / avg_loss))
```

| Feature | Period | จุดประสงค์ |
|---|---|---|
| `F_RSI_14` | 14 แท่ง | RSI มาตรฐาน (70+ overbought, 30- oversold) |
| `F_RSI_6` | 6 แท่ง | RSI เร็ว ตอบสนองไว ใช้จับ short-term reversal |

**การ diff ข้าม session:** ใช้ `safe_diff` เพื่อให้ gain/loss ไม่ถูกคำนวณข้าม session boundary  
→ หลีกเลี่ยง RSI ที่ผิดพลาดในแท่งแรกของแต่ละ session

---

### `F_BB_Pos` — Bollinger Band Position

```
bb_mid    = rolling_mean(Price, 20)
bb_std    = rolling_std(Price, 20)
F_BB_Pos  = (Price − bb_mid) / (2 × bb_std)
```

| ค่า | ความหมาย |
|---|---|
| `> 1.0` | ราคาเหนือ Upper Band (overbought) |
| `0` | ราคาอยู่ที่ midband |
| `< -1.0` | ราคาใต้ Lower Band (oversold) |

Normalize แล้ว → ใช้เปรียบเทียบข้าม session ได้โดยตรง

---

### `F_XAU_Spread_Norm` — Normalized XAU Spread

```
F_XAU_Spread_Norm = XAU_Spread / rolling_mean(XAU_Spread, 144)
```

**ความหมาย:**  
วัดว่า spread ของ XAU กว้างกว่าค่าเฉลี่ยปกติมากแค่ไหน  
- ค่าสูง → liquidity ต่ำ / ตลาดตึง → ควรระวังในการ execute
- ใช้คู่กับ `F_Spread_vs_ATR` เพื่อประเมิน transaction cost

---

### `F_Hour_Sin` / `F_Hour_Cos` — Circular Time Encoding

```
hour         = index.hour + index.minute / 60
F_Hour_Sin   = sin(2π × hour / 24)
F_Hour_Cos   = cos(2π × hour / 24)
```

**ทำไมต้องใช้ Sin/Cos แทนชั่วโมงดิบ:**  
ชั่วโมง 23 และชั่วโมง 0 อยู่ใกล้กันในความเป็นจริง แต่ถ้าใส่เป็นตัวเลข (23 vs 0) model จะคิดว่าห่างกันมาก  
Circular encoding แก้ปัญหานี้ → **23:30 และ 00:30 จะมีค่าใกล้เคียงกัน**

---

### `F_Session_Type` — Session Type Encoding

```
F_Session_Type = {'Morning': 0, 'Afternoon': 1, 'Night': 2}
```

Label encoding สำหรับประเภท session ให้ model รู้ว่าอยู่ใน session ไหน

---

### `F_HSH_Spread` / `F_Spread_Cost_Pct` / `F_Spread_vs_ATR` — Spread Features

| Feature | สูตร | ความหมาย |
|---|---|---|
| `F_HSH_Spread` | `HSH_Spread_Sim` | Spread ดิบของ HSH |
| `F_Spread_Cost_Pct` | `Spread / Price` | ต้นทุน spread เป็น % ของราคา |
| `F_Spread_vs_ATR` | `Spread / ATR_48` | Spread เทียบกับ volatility |

**`F_Spread_vs_ATR`** เป็น feature ที่สำคัญสำหรับ Ranker:  
ถ้า spread สูงเทียบกับ ATR → โอกาสทำกำไรยาก → ควร rank ต่ำ

---

## 🛡️ Anti-Lookahead Mechanisms

ไฟล์นี้ออกแบบมาอย่างระมัดระวังเพื่อป้องกัน look-ahead bias:

| กลไก | ใช้ใน |
|---|---|
| `safe_pct_change()` — ตั้งค่า return = 0 ที่ session boundary | Momentum, Corr, Vol |
| `safe_diff()` — ตั้งค่า diff = 0 ที่ session boundary | RSI |
| `expanding()` แทน `rolling()` ใน session features | TWAP, MDD, Range, Position |
| `Expected_Session_Length` แทน Actual Length | `F_FSP`, `F_Remaining_Vol`, `F_SRVR` |
| OLS ใช้เฉพาะข้อมูลในอดีต (sliding window) | `F_Syn_Price` |

---

## 📋 สรุป Feature ทั้งหมด

| Feature | กลุ่ม | ประเภท |
|---|---|---|
| `F_Syn_Price` | Synthetic | Continuous |
| `F_Thai_Premium` | Synthetic | Continuous |
| `F_Corr_XAU_USD` | Macro | Continuous [-1, 1] |
| `F_XAU_Mom_Short` | Macro | Continuous (%) |
| `F_XAU_Mom_Mid` | Macro | Continuous (%) |
| `F_USD_Mom` | Macro | Continuous (%) |
| `F_ATR_48` | Macro | Continuous (THB) |
| `F_Regime` | Macro | Categorical {-1, +1} |
| `F_FSP` | Session | Continuous [0, 1] |
| `F_SA_TWAP_Dev` | Session | Continuous |
| `F_SA_MDD` | Session | Continuous (≤ 0) |
| `F_SA_Vol` | Session | Continuous |
| `F_SA_Range` | Session | Continuous |
| `F_SA_Position` | Session | Continuous [0, 1] |
| `F_Historical_Vol_THB` | Session | Continuous |
| `F_Remaining_Vol` | Session | Continuous |
| `F_SRVR` | Session | Continuous |
| `F_Price_Vs_Open` | Session | Continuous (%) |
| `F_Mom_1bar` | Session | Continuous (%) |
| `F_Mom_3bar` | Session | Continuous (%) |
| `F_SA_Drawdown_Pct` | Session | Continuous (%) |
| `F_HSH_vs_THBGold_Dev` | Session | Continuous |
| `F_DayOfWeek` | Time | Ordinal [0, 4] |
| `F_MinuteOfDay` | Time | Ordinal [0, 1439] |
| `F_RSI_14` | Technical | Continuous [0, 100] |
| `F_RSI_6` | Technical | Continuous [0, 100] |
| `F_BB_Pos` | Technical | Continuous |
| `F_XAU_Spread_Norm` | Technical | Continuous |
| `F_Hour_Sin` | Technical | Continuous [-1, 1] |
| `F_Hour_Cos` | Technical | Continuous [-1, 1] |
| `F_Session_Type` | Technical | Categorical {0, 1, 2} |
| `F_HSH_Spread` | Technical | Continuous |
| `F_Spread_Cost_Pct` | Technical | Continuous (%) |
| `F_Spread_vs_ATR` | Technical | Continuous |
