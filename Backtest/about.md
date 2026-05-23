# Backtest Module — Walk-Forward Backtest
> **อัปเดต:** 2026-04-25

---

## 1. ภาพรวม

Walk-Forward Backtest สำหรับระบบ **Nakkhutthong Framework** — ทดสอบประสิทธิภาพของ AI Trading Signal ย้อนหลังตั้งแต่ **ม.ค. 2568 ถึงปัจจุบัน** โดยแบ่งการทดสอบออกเป็น 4 รอบตามที่อาจารย์กำหนด

```
CSV ราคาทอง (5m) → คำนวณ Indicators → Signal Engine (Rule/Mistral)
→ SimPortfolio จำลองการซื้อขาย → คำนวณ Metrics → วิเคราะห์ Variation
```

---

## 2. โครงสร้างไฟล์

```
Backtest/
├── walk_forward_backtest.py   ← Script หลัก
├── output/
│   └── walk_forward_results.json  ← ผลลัพธ์ทั้ง 4 รอบ
└── about.md                   ← เอกสารนี้
```

---

## 3. Walk-Forward Windows (Expanding Window)

| รอบ | Train | Test | ฤดูกาล |
|-----|-------|------|--------|
| 1 | ม.ค.68 – ธ.ค.68 | **ม.ค. 69** | ต้นปี นักลงทุนเปิด position ใหม่ |
| 2 | ม.ค.68 – ม.ค.69 | **ก.พ. 69** | วาเลนไทน์ / ทองคำเป็นของขวัญ |
| 3 | ม.ค.68 – ก.พ.69 | **มี.ค. 69** | ปิดเทอม / สิ้นไตรมาส |
| 4 | ม.ค.68 – มี.ค.69 | **เม.ย. 69** | สงกรานต์ / เปิดเทอม |

**วิธี Expanding Window** — Train data ขยายขึ้นทุกรอบ เพื่อลด gap ระหว่าง Train กับ Test และสอดคล้องกับระบบที่เรียนรู้สะสมไปเรื่อย ๆ

---

## 4. Data Leak Prevention

ป้องกัน Look-ahead bias ด้วยการ `shift(1)` ทุก indicator ก่อนใช้งาน

```python
# ทุก indicator ถูก shift(1) — candle ปัจจุบันรู้ได้เฉพาะข้อมูลที่ผ่านมา
indicator_cols = ["rsi", "macd_line", "macd_hist", "ema_20", "ema_50", ...]
for col in indicator_cols:
    df[col] = df[col].shift(1)
```

นอกจากนี้ยังแบ่ง Train/Test อย่างเคร่งครัด — Scaler และ Indicator ถูก fit บน Train data เท่านั้น

---

## 5. Signal Engine — 3 Modes

```bash
# Rule-based อย่างเดียว (เร็ว เหมาะทดสอบ pipeline)
python walk_forward_backtest.py --mode rule

# Rule กรองก่อน แล้วส่งให้ Mistral API ตัดสินใจ (แนะนำ)
python walk_forward_backtest.py --mode smart

# เรียก Mistral API ทุก candle (ช้า แต่ใช้ AI จริงทั้งหมด)
python walk_forward_backtest.py --mode api
```

### Rule-based Logic
| สัญญาณ | เงื่อนไข (3 ใน 4 ต้องเป็นจริง) |
|--------|-------------------------------|
| BUY | RSI < 45, MACD Hist > 0, Close > EMA20, EMA20 > EMA50 |
| SELL | RSI > 55, MACD Hist < 0, Close < EMA20, EMA20 < EMA50 |
| HOLD | ไม่ผ่านเงื่อนไขข้างต้น |

### Mistral API (Smart Mode)
- Rule-based กรอง candle ที่น่าสนใจก่อน
- เฉพาะ BUY_CANDIDATE / SELL_CANDIDATE เท่านั้นที่ส่งให้ Mistral ตัดสินใจขั้นสุดท้าย
- Fallback เป็น Rule hint อัตโนมัติถ้า API timeout

---

## 6. SimPortfolio

จำลองการซื้อขายทองตามระบบจริงของโปรเจค

| ค่าคงที่ | ค่า | ความหมาย |
|---------|-----|----------|
| `INITIAL_CASH` | 1,500 THB | เงินเริ่มต้น (ตามที่อาจารย์กำหนด) |
| `BUST_THRESHOLD` | 1,000 THB | ต่ำกว่านี้หยุดทันที |
| `SPREAD_THB` | 0 THB | ฮั่วเซ่งเฮงออกให้ |
| `COMMISSION_THB` | 0 THB | SCB EASY ฟรี |
| `GOLD_GRAM_PER_BAHT` | 15.244 g | กรัมต่อ 1 บาทน้ำหนัก |

---

## 7. Metrics ที่คำนวณ

ครอบคลุมทุก Parameter ที่อาจารย์กำหนด:

| Metric | คำอธิบาย |
|--------|---------|
| Total Closed Trade | จำนวนดีลที่ปิดแล้ว |
| Win Rate (%) | สัดส่วนดีลที่กำไร |
| Total Profit (THB) | กำไรรวมทั้งหมด |
| Average Win/Loss (THB) | เฉลี่ยกำไร/ขาดทุนต่อดีล |
| Expectancy per Trade | คาดหวังกำไรต่อดีล |
| Profit Factor | กำไรรวม / ขาดทุนรวม |
| Best/Worst/Median Annualized | ผลตอบแทนรายปีแต่ละดีล |
| XIRR | Internal Rate of Return แบบ irregular cashflow |
| Max Drawdown (%) | การขาดทุนสูงสุดจากจุดสูงสุด |
| Sharpe Ratio | ผลตอบแทนเทียบความเสี่ยง |
| Calmar Ratio | Annualized Return / MDD |

---

## 8. ผลลัพธ์ที่ได้ (Rule Mode)

| เดือน | Trades | Win Rate | กำไร/ขาดทุน | Sharpe | MDD |
|-------|--------|----------|------------|--------|-----|
| ม.ค. 69 | 131 | 35.11% | **+64.28 THB** ✅ | -1.3632 | -3.05% |
| ก.พ. 69 | 124 | 34.68% | **+24.17 THB** ✅ | -1.4260 | -3.62% |
| มี.ค. 69 | 136 | 27.21% | **-69.59 THB** ❌ | -1.9498 | -7.08% |
| เม.ย. 69 | 65 | 32.31% | **-11.03 THB** ❌ | -2.1466 | -2.28% |

### Best/Worst Annualized Trade (Compound Formula)

| เดือน | Best Annualized | Worst Annualized | Median |
|-------|----------------|-----------------|--------|
| ม.ค. 69 | 740,990.63% | -95.32% | -11.24% |
| ก.พ. 69 | 11,974.53% | -93.27% | -10.81% |
| มี.ค. 69 | 25,670.00% | -88.38% | -16.48% |
| เม.ย. 69 | 3,431.85% | -85.76% | -12.10% |

> **หมายเหตุ:** Best Annualized สูงมากเพราะ compound formula `(1+r)^(365/days)-1` ขยายผลตอบแทนของ trade ที่ถือสั้นมาก (1-2 วัน) ให้ดูใหญ่ขึ้น ซึ่งเป็นเรื่องปกติของ formula นี้

### การวิเคราะห์ Variation
- **Variation = 133.87 THB** (8.9% ของเงินต้น)
- **ม.ค.–ก.พ. กำไร** — ตลาดต้นปีมีทิศทางชัดเจน
- **มี.ค. ขาดทุนสูงสุด** — Win Rate ตกจาก 35% → 27% ช่วงปิดเทอม/สิ้นไตรมาส ตลาดผันผวน
- **เม.ย. Trade น้อยลงครึ่งนึง** — ช่วงสงกรานต์ตลาดเบาบาง

---

## 9. ข้อมูลที่ใช้

| ไฟล์ | รายละเอียด |
|------|-----------|
| `GLD965_5m_20250101_to_20260416.csv` | ราคาทอง 96.5% ระดับ 5 นาที ตั้งแต่ ม.ค.68 – เม.ย.69 |

---

## 10. Output Files

รันแล้วจะได้ไฟล์ใน `output/` ดังนี้:

| ไฟล์ | รายละเอียด |
|------|-----------|
| `trade_log.csv` | รายการเทรดทุกดีลตาม format อาจารย์ (Buy/Sell Price, Date, Amount, Weight, Profit, %/Year ฯลฯ) |
| `summary_metrics.csv` | Summary ครบทุก Parameter ที่อาจารย์กำหนด (Win Rate, Sharpe, XIRR, MDD ฯลฯ) |
| `walk_forward_results.json` | ผลลัพธ์ทั้งหมดในรูปแบบ JSON ครบทุกรอบ |

---

## 11. วิธีรัน

```bash
cd Backtest

# ทดสอบด้วย Rule-based (เร็ว)
python walk_forward_backtest.py --mode rule

# ทดสอบด้วย Mistral AI (แนะนำ)
python walk_forward_backtest.py --mode smart

# กำหนด CSV และ output เอง
python walk_forward_backtest.py \
  --csv ../Src/backtest/data/MarketState_data/GLD965_5m_20250101_to_20260416.csv \
  --output output/ \
  --mode rule
```

---

## 11. Trading Metrics — Formula และการคำนวณในโค้ด

| Metric | Formula | คำนวณในโค้ดอย่างไร | ผลที่ได้บอกอะไร |
|--------|---------|-------------------|----------------|
| **Total Closed Trade** | Count of closed trades | นับจาก `portfolio.closed_trades` | ยิ่งเยอะ ยิ่งเชื่อถือสถิติได้ |
| **Win Rate (%)** | (Winning trades / Total) × 100 | `len(wins) / len(trades) * 100` | อัตราชนะ (สูงไม่ได้แปลว่ากำไรเสมอ) |
| **Total Profit (THB)** | Σ profit - Σ loss | `sum(t["pnl_thb"] for t in trades)` | กำไรสุทธิทั้งหมด |
| **Unrealized P/L** | (Current price - Entry) × qty | `gold_grams / GOLD_GRAM_PER_BAHT * price - cost` | กำไร/ขาดทุนของไม้ที่ยังถืออยู่ |
| **Average Win** | Σ win_pnl / n_wins | `sum(wins) / len(wins)` | ถ้ามากกว่า Avg Loss แม้ Win Rate ต่ำก็ยังโอเค |
| **Average Loss** | Σ loss_pnl / n_losses | `sum(losses) / len(losses)` | ขนาดขาดทุนเฉลี่ยต่อดีล |
| **Expectancy per Trade** | (WR × AvgWin) - (LR × AvgLoss) | `(win_rate * avg_win) + ((1-win_rate) * avg_loss)` | ค่าคาดหวังต่อ 1 trade — เป็นบวกคือดี |
| **Best Annualized (%)** | (1 + return)^(365/days) - 1 | `pct * (365 / days_held)` บน best trade | ไม้ที่ดีที่สุดเมื่อคิดเป็นกำไรต่อปี |
| **Worst Annualized (%)** | (1 + return)^(365/days) - 1 | `pct * (365 / days_held)` บน worst trade | ไม้ที่แย่ที่สุดเมื่อคิดเป็นกำไรต่อปี |
| **Median Annualized (%)** | Median of annualized returns | `ann_sorted[n//2]` | การกระจายตัวของผลตอบแทน |
| **Top/Bottom 10%** | 90th / 10th percentile | `ann_sorted[int(n*0.9)]` / `ann_sorted[int(n*0.1)]` | ผลตอบแทนกลุ่มบน/ล่าง 10% |
| **XIRR** | Solve r where NPV=0 | Newton-Raphson จาก cashflow จริงแต่ละ trade | IRR ที่คำนวณเรื่องเวลาและการฝาก-ถอนจริง |
| **Avg Capital/Year** | Σ (BuyAmount × DaysHeld) / 365 | `sum(buy_amount * days_held / 365)` | เงินทุนเฉลี่ยที่วางในระบบต่อปี |
| **Max Drawdown (%)** | min((equity - peak) / peak × 100) | `(equity - equity.cummax()) / equity.cummax() * 100` | การขาดทุนสูงสุดจากจุดสูงสุด |
| **Sharpe Ratio** | (Rp - Rf) / σ × √252 | `(mean_return - rf/252) / std * sqrt(252)` | ผลตอบแทนเทียบความเสี่ยง — ยิ่งสูงยิ่งดี (>1 คือดี) |
| **Calmar Ratio** | Annualized Return / \|MDD\| | `ann_ret / abs(mdd)` | ผลตอบแทนต่อปีเทียบกับ Drawdown สูงสุด |

---

## 12. วิเคราะห์ผล Model

### ภาพรวม
Model ที่ทดสอบเป็น Rule-based Signal ที่ใช้ Technical Indicators (RSI, MACD, EMA) เป็นหลัก โดยมี Mistral Ver.1 เป็น AI ช่วยตัดสินใจขั้นสุดท้าย ผลลัพธ์โดยรวมคือ **ยังไม่ผ่าน Deploy Gate** เพราะ Win Rate เฉลี่ยอยู่ที่ 32.3% ต่ำกว่าเกณฑ์ที่กำหนดไว้ที่ 50%

### ข้อดี

**ด้าน Risk Management**
- MDD ทุกเดือนต่ำกว่า 10% (สูงสุดแค่ -7.08% ในมี.ค.) ผ่านเกณฑ์ Deploy Gate ที่ 20%
- Calmar Ratio เดือน ม.ค. = 1.4 ดีกว่าเกณฑ์ที่ 1.0 แสดงว่าผลตอบแทนคุ้มกับ Drawdown

**ด้าน Consistency**
- จำนวน Trade สม่ำเสมอ 124-136 trades ต่อเดือน (ยกเว้น เม.ย. ที่ตลาดเบาบาง)
- Average Win (3-5 บาท) สูงกว่า Average Loss (1.7-2 บาท) ทุกเดือน แสดงว่า Risk/Reward ratio ดี

### ข้อเสีย

**Win Rate ต่ำเกินไป**
- Win Rate เฉลี่ย 32.3% ต่ำกว่าเกณฑ์ 50% มาก
- แม้ Average Win > Average Loss แต่ Win Rate ต่ำทำให้ยังขาดทุนในบางเดือน

**Sharpe Ratio ติดลบทุกเดือน**
- Sharpe ติดลบตั้งแต่ -1.75 ถึง -2.54 แสดงว่าผลตอบแทนไม่คุ้มกับความเสี่ยงที่รับ
- เกณฑ์ที่ดีควรมากกว่า 1.0

**Mistral Ver.1 Conservative เกินไป**
- ตอบ HOLD แทน SELL เมื่อ Signal ขัดแย้งกัน
- ทำให้พลาดโอกาส SELL ในตลาดขาลง

**ผลผันผวนตามฤดูกาล**
- มี.ค. Win Rate ตกเหลือ 27.21% ช่วงปิดเทอม/สิ้นไตรมาส
- เม.ย. Trade ลดลง 52% ช่วงสงกรานต์

### แนวทางปรับปรุง

**ระยะสั้น**
- ปรับ Threshold ของ RSI และ MACD ให้เหมาะกับแต่ละช่วงตลาด เช่น ใช้ RSI < 35 แทน < 45
- เพิ่ม Volume เป็นเงื่อนไขเพิ่มเติม เพราะตลาดเบาบาง (เม.ย.) ให้ผลต่างจากปกติมาก

**ระยะกลาง**
- เพิ่ม News Sentiment เข้าไปใน Signal เพื่อรับมือกับ Event พิเศษ
- Train Mistral Ver.2 ให้ตอบ SELL ได้ดีขึ้นในสถานการณ์ที่ชัดเจน

**ระยะยาว**
- เพิ่ม Position Sizing แบบ Dynamic ตามความผันผวน (ATR-based)
- ทดสอบ Walk-Forward กับข้อมูลมากกว่า 1 ปีเพื่อให้ Sharpe Ratio น่าเชื่อถือมากขึ้น