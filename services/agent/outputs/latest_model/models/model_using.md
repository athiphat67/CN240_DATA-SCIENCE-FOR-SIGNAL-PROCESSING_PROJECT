# Model Using Guide — Dual-Model Gold Signal System (Thai Physical Gold)

> คู่มือฉบับนี้อธิบายการนำ Dual-Model XGBoost ไปใช้งานจริงในระดับ Production
> สำหรับการทำนายสัญญาณซื้อขายทองคำแท่งในตลาดไทย ครอบคลุมตั้งแต่การ Config
> ไปจนถึงการ Finetune และการรวม Sentiment Score จาก News Model เข้ากับ
> Confidence Score ขั้นสุดท้ายผ่านการควบคุมด้วย LLM

---

## สารบัญ

1. [ภาพรวม Architecture](#1-ภาพรวม-architecture)
2. [หลักการ Dual-Model และการคาย Prob Score](#2-หลักการ-dual-model-และการคาย-prob-score)
3. [Config พื้นฐานที่ต้องรู้](#3-config-พื้นฐานที่ต้องรู้)
4. [การปรับ Signal ให้ถี่ขึ้นหรือเข้มงวดขึ้น](#4-การปรับ-signal-ให้ถี่ขึ้นหรือเข้มงวดขึ้น)
5. [การ Finetune โมเดลเพื่อรีดประสิทธิภาพ](#5-การ-finetune-โมเดลเพื่อรีดประสิทธิภาพ)
6. [Session-Aware Probability Weighting](#6-session-aware-probability-weighting)
7. [News Sentiment Model Integration](#7-news-sentiment-model-integration)
8. [Confidence Score รวม และการตัดสินใจขั้นสุดท้าย](#8-confidence-score-รวม-และการตัดสินใจขั้นสุดท้าย)
9. [LLM เป็น Dynamic Weight Manager](#9-llm-เป็น-dynamic-weight-manager)
10. [Production Deployment Checklist](#10-production-deployment-checklist)

---

## 1. ภาพรวม Architecture

ระบบ Dual-Model Gold Signal มีโครงสร้างการทำงานแบบ Pipeline ดังนี้

```
Raw OHLCV + Indicators
        │
        ▼
 Feature Engineering
 (26 features จาก feature_columns.json)
        │
        ├──────────────────────┐
        ▼                      ▼
  BUY Model (XGBoost)   SELL Model (XGBoost)
        │                      │
  prob_buy (0-1)         prob_sell (0-1)
        └──────────┬───────────┘
                   ▼
         Session-Aware Weighting
         (ปรับน้ำหนักตามช่วงเวลา Session)
                   │
                   ▼
         News Sentiment Score
         (FinBERT / Sentiment Model)
                   │
                   ▼
         LLM Dynamic Weight Manager
         (ปรับสัดส่วน Weighting อัตโนมัติ)
                   │
                   ▼
         Confidence Score รวม
                   │
                   ▼
         Signal Engine → BUY / SELL / HOLD
                   │
                   ▼
         Risk & Session Gate
                   │
                   ▼
         Execute Trade
```

แต่ละชั้นมีหน้าที่ชัดเจนและสามารถ Tune ได้อิสระ ทำให้ระบบมีความยืดหยุ่นสูงในการปรับตัวต่อสภาพตลาดที่เปลี่ยนแปลง

---

## 2. หลักการ Dual-Model และการคาย Prob Score

### 2.1 ทำไมต้องใช้ Dual-Model แทน Multi-Class

โมเดลเดี่ยวที่ทำนาย BUY / HOLD / SELL พร้อมกันมักเจอปัญหา Class Imbalance ที่รุนแรง เนื่องจากสัญญาณที่ดีในตลาดทองมีความถี่ต่ำมาก (ประมาณ 5-15% ของแท่งทั้งหมด) การแยกโมเดลออกเป็น 2 ตัวทำให้แต่ละโมเดลโฟกัสกับ Pattern เฉพาะทางของตัวเองได้อย่างเต็มที่

- **BUY Model** — เรียนรู้ Pattern ที่ราคามีโอกาสวิ่งขึ้น เกิน TARGET_MOVE_PCT (0.20%) ภายใน HORIZON บาร์ โดยหักต้นทุน Spread จริงแล้ว
- **SELL Model** — เรียนรู้ Pattern ที่ราคามีโอกาสวิ่งลง เกิน TARGET_MOVE_PCT (0.20%) ภายใน HORIZON บาร์ อิงจากราคา Bid ของกราฟโดยตรง

### 2.2 กระบวนการคาย Prob Score

เมื่อมีแท่งราคาใหม่เข้ามา ระบบจะทำตามลำดับนี้

```python
# ขั้นที่ 1: เตรียม Feature Vector (26 features)
feature_vector = df[feature_columns].iloc[i]

# ขั้นที่ 2: ให้โมเดลทำนายความน่าจะเป็น
prob_buy  = buy_model.predict_proba(feature_vector)[1]   # ความน่าจะเป็น Class=1 (BUY)
prob_sell = sell_model.predict_proba(feature_vector)[1]  # ความน่าจะเป็น Class=1 (SELL)

# ขั้นที่ 3: ตรวจสอบ Conflict ก่อนเสมอ
conflict_gap = 0.15  # ค่าจาก SignalConfig
if abs(prob_buy - prob_sell) < conflict_gap:
    signal = "HOLD"  # โมเดลไม่มั่นใจเพียงพอ ไม่ออกสัญญาณ
```

### 2.3 Logic การตัดสินใจของ Signal Engine

`SignalEngine.evaluate_dual_probs()` ใช้หลักการ Dynamic Threshold ที่ขึ้นอยู่กับ 2 ปัจจัย

**ปัจจัยที่ 1: session_progress (0.0 ถึง 1.0)**
แสดงว่าเวลาผ่านไปแล้วกี่ % ของ Session ปัจจุบัน

**ปัจจัยที่ 2: trades_done_in_session**
จำนวนออเดอร์ที่ปิดไปแล้วใน Session นี้

```
ถ้า trades_done_in_session == 0 (ยังไม่ได้เทรดเลยใน Session นี้):

  session_progress < 0.5   → threshold = base_threshold + 0.10  (เข้มงวดมาก)
  session_progress 0.5-0.9 → threshold ค่อยๆ ลดลงจาก base ไปหา min_threshold
  session_progress > 0.9   → threshold = 0.55  (ยืดหยุ่น เพื่อให้ได้เทรด)

ถ้า trades_done_in_session > 0 (เทรดไปแล้ว):

  threshold = base_threshold + 0.15  (เข้มงวดมากขึ้นอีก ป้องกัน Overtrading)
```

การออกสัญญาณจะเกิดขึ้นเมื่อ prob ข้ามเกณฑ์ AND ต้องชนะฝั่งตรงข้ามด้วย

```python
if prob_buy >= current_threshold and prob_buy > prob_sell:
    return "BUY"

if prob_sell >= current_threshold and prob_sell > prob_buy:
    return "SELL"

return "HOLD"
```

---

## 3. Config พื้นฐานที่ต้องรู้

Config ทั้งหมดอยู่ใน `config.py` ไฟล์เดียว แบ่งออกเป็นกลุ่มที่มีความเกี่ยวข้องกับสัญญาณดังนี้

### 3.1 SignalConfig — หัวใจของการตัดสินใจ

```python
@dataclass(slots=True)
class SignalConfig:
    base_threshold: float = 0.70   # เกณฑ์ขั้นต่ำปกติ (ช่วงกลาง Session)
    min_threshold: float  = 0.55   # เกณฑ์ต่ำสุดที่ยอมรับได้ (ท้าย Session)
    conflict_gap: float   = 0.15   # ระยะห่างขั้นต่ำระหว่าง prob_buy และ prob_sell
```

| Parameter | ค่า Default | ผลที่เกิดขึ้น |
|---|---|---|
| `base_threshold` | 0.70 | เกณฑ์หลักที่โมเดลต้องผ่าน ยิ่งสูงยิ่งน้อย Signal แต่ Quality สูง |
| `min_threshold` | 0.55 | เกณฑ์ท้าย Session ลดต่ำได้แค่นี้ ป้องกันการเข้าสัญญาณขยะ |
| `conflict_gap` | 0.15 | ถ้า prob_buy และ prob_sell ต่างกันน้อยกว่านี้ จะ HOLD เสมอ |

### 3.2 RiskConfig — กำหนดขนาด SL/TP ให้ตรงกับ Label

ค่าใน RiskConfig ต้องสอดคล้องกับค่าที่ใช้ใน `gold_data_label_v4.py` มิฉะนั้น โมเดลจะถูกเทรนด้วยเงื่อนไขหนึ่งแต่ถูก Execute ด้วยเงื่อนไขอีกแบบ

```python
@dataclass(slots=True)
class RiskConfig:
    stop_loss_pct:   float = 0.0032  # ต้องตรงกับ MAX_RISK_PCT ใน label script
    take_profit_pct: float = 0.0020  # ต้องตรงกับ TARGET_MOVE_PCT ใน label script
```

ตารางเปรียบเทียบ Label Script vs Risk Config

| ค่า | gold_data_label_v4.py | config.py (RiskConfig) |
|---|---|---|
| Target กำไร | `TARGET_MOVE_PCT = 0.0020` | `take_profit_pct = 0.0020` |
| ระยะ Stop Loss | `MAX_RISK_PCT = 0.0032` | `stop_loss_pct = 0.0032` |
| Spread | `SPREAD_PCT = 0.0014` | `spread_rate = 0.0014` |

### 3.3 ModelConfig — พารามิเตอร์ที่ได้จาก Optuna

```python
# ผลลัพธ์จาก finetune_dual_results_latest_model.json
buy_n_estimators:        270
buy_learning_rate:       0.02568
buy_max_depth:           7
buy_subsample:           0.8469
buy_colsample_bytree:    0.9963
buy_scale_pos_weight:    1.3777  # น้ำหนักชดเชย Class Imbalance ฝั่ง BUY

sell_n_estimators:       579
sell_learning_rate:      0.01012
sell_max_depth:          7
sell_subsample:          0.8973
sell_colsample_bytree:   0.9675
sell_scale_pos_weight:   1.0836  # น้ำหนักชดเชย Class Imbalance ฝั่ง SELL
```

---

## 4. การปรับ Signal ให้ถี่ขึ้นหรือเข้มงวดขึ้น

### 4.1 ต้องการ Signal ถี่ขึ้น (More Trades)

ปรับ `SignalConfig` ลดเกณฑ์ลงอย่างระมัดระวัง

```python
# config.py
@dataclass(slots=True)
class SignalConfig:
    base_threshold: float = 0.62   # ลดจาก 0.70 → สัญญาณออกบ่อยขึ้น
    min_threshold:  float = 0.50   # ลดจาก 0.55 → ท้าย Session ยืดหยุ่นมากขึ้น
    conflict_gap:   float = 0.10   # ลดจาก 0.15 → ยอมรับสัญญาณที่ "สูสี" มากขึ้น
```

**หมายเหตุ:** การลด `base_threshold` ลงทุก 0.05 จะเพิ่มจำนวน Signal ขึ้นประมาณ 20-40% แต่ Win Rate อาจลดลง ควร Backtest ก่อนนำไปใช้จริงเสมอ

### 4.2 ต้องการ Signal ที่ Quality สูงขึ้น (Fewer but Better Trades)

```python
@dataclass(slots=True)
class SignalConfig:
    base_threshold: float = 0.78   # เพิ่มจาก 0.70 → โมเดลต้องมั่นใจมากขึ้น
    min_threshold:  float = 0.62   # เพิ่มจาก 0.55 → แม้ท้าย Session ก็ยังเข้มงวด
    conflict_gap:   float = 0.20   # เพิ่มจาก 0.15 → ต้องการความชัดเจนสูง
```

### 4.3 ปรับพฤติกรรม Second Trade ใน Session

โค้ดใน `signals.py` จะเพิ่ม threshold อีก +0.15 หากเทรดไปแล้ว 1 ครั้ง ถ้าต้องการให้ออเดอร์ที่ 2 ง่ายขึ้น

```python
# signals.py — บรรทัดที่เกี่ยวข้อง
else:  # trades_done_in_session > 0
    current_threshold = self.calib_config.base_threshold + 0.05  # ลดจาก +0.15 เป็น +0.05
```

ในทางกลับกัน หากต้องการให้ระบบ One-Trade-Per-Session อย่างเคร่งครัด

```python
else:
    return "HOLD"  # ไม่ออกสัญญาณถ้าเทรดไปแล้วในรอบนี้
```

---

## 5. การ Finetune โมเดลเพื่อรีดประสิทธิภาพ

### 5.1 เมื่อไหรควร Finetune

- ข้อมูลราคาใหม่เพิ่มขึ้นมากกว่า 30 วัน
- Win Rate ลดลงต่อเนื่อง 2 สัปดาห์ขึ้นไป
- ตลาดเปลี่ยน Regime (เช่น จาก Trending เป็น Sideways หรือมีเหตุการณ์ Macro ใหญ่)
- ผลการ Backtest บน Out-of-Sample ตกต่ำกว่า In-Sample มากเกินไป

### 5.2 วิธี Finetune ด้วย Optuna

```bash
python finetune_dual.py \
    --csv  data/label/gold_data_labeled_v6.csv \
    --model xgboost \
    --trials 100 \
    --out artifacts/
```

ผลลัพธ์จะออกมาเป็น `finetune_dual_results_latest_model.json` ที่มีโครงสร้างดังนี้

```json
{
    "buy_model": {
        "best_score": 0.5569,
        "best_params": {
            "n_estimators": 270,
            "learning_rate": 0.02568,
            "max_depth": 7,
            "subsample": 0.8469,
            "colsample_bytree": 0.9963,
            "scale_pos_weight": 1.3777
        }
    },
    "sell_model": {
        "best_score": 0.5168,
        "best_params": { ... }
    }
}
```

### 5.3 อัปเดต Config หลัง Finetune

เมื่อได้ best_params แล้ว ให้อัปเดตค่าใน `config.py` ทันที

```python
# config.py → ModelConfig
buy_n_estimators:     int   = 270       # จาก best_params ของ BUY Model
buy_learning_rate:    float = 0.02568
buy_max_depth:        int   = 7
buy_subsample:        float = 0.8469
buy_colsample_bytree: float = 0.9963
buy_scale_pos_weight: float = 1.3777
```

จากนั้นรัน `train_dual.py` เพื่อ Retrain โมเดลด้วยพารามิเตอร์ใหม่บนข้อมูลทั้งหมด

```bash
python train_dual.py
```

### 5.4 Metric ที่ใช้ในการ Finetune (Custom Evaluate)

ระบบใช้ PR-AUC เป็นหลัก (70%) ผสมกับ Best F1 (30%) เพราะข้อมูลมี Imbalance สูง

```
Score = 0.7 × PR-AUC + 0.3 × Best-F1@OptimalThreshold
```

เป้าหมายที่ดี: BUY Score > 0.55, SELL Score > 0.50 เป็นจุดเริ่มต้นที่ยอมรับได้ในตลาดที่มี Noise สูง

### 5.5 เทคนิค Finetune เพิ่มเติมที่พัฒนาต่อได้

**Walk-Forward Optimization** — แทนที่จะ Finetune ครั้งเดียวทั้ง Dataset ให้แบ่งข้อมูลออกเป็น Window เช่น 60 วัน Train + 15 วัน Validate แล้วเลื่อนไปข้างหน้าทีละ 15 วัน เพื่อดูว่าพารามิเตอร์ที่ดีบน Window ใดบ้างที่ยังใช้ได้ดีบน Window ถัดไป

**Feature Importance Pruning** — หลัง Finetune ให้ตรวจ Feature Importance จาก XGBoost แล้วตัด Feature ที่ได้คะแนนน้อยกว่า 0.01 ออก จะช่วยลด Overfitting และทำให้โมเดล Generalize ได้ดีขึ้น

**scale_pos_weight Sensitivity Analysis** — รัน Optuna โดยล็อก hyperparameter อื่นๆ ไว้ แล้วกวาด scale_pos_weight ตั้งแต่ 1.0 ถึง 5.0 เพื่อดูว่าจุดไหนให้ Win Rate กับ Precision สมดุลที่สุด

---

## 6. Session-Aware Probability Weighting

### 6.1 Session ที่ระบบรู้จัก

จาก `gold_data_label_v4.py` และ `session_gate.py` ระบบแบ่ง Session ของทองคำไทยดังนี้

```
วันธรรมดา (จันทร์ - ศุกร์):
  Morning   : 06:15 → 12:00  (เปิดพร้อมตลาดเอเชีย)
  Afternoon : 12:00 → 18:00  (ช่วงกลางวัน)
  Evening   : 18:00 → 02:00  (เปิดพร้อมตลาด London + NY)

วันหยุดสุดสัปดาห์:
  Weekend   : 09:30 → 17:30  (ปริมาณซื้อขายต่ำ)
```

### 6.2 Session Progress และผลต่อ Threshold

ค่า `session_progress` (0.0-1.0) ถูกคำนวณแบบ Real-time ดังนี้

```python
# session_gate.py
def get_progress(self, local_time: time) -> float:
    elapsed       = current_seconds - start_seconds
    total_duration = end_seconds - start_seconds
    return elapsed / total_duration   # ผลลัพธ์อยู่ระหว่าง 0.0 ถึง 1.0
```

### 6.3 Session-Based Probability Weighting Layer (ขั้นต่อไป)

แทนที่จะใช้ session_progress แค่ปรับ Threshold อย่างเดียว เราสามารถสร้าง **Session Weight Layer** ที่ปรับน้ำหนักของ prob_buy และ prob_sell ตามลักษณะของแต่ละ Session ก่อนส่งเข้า Signal Engine

แนวคิดคือ แต่ละ Session มี Volatility Profile และ Pattern ที่ต่างกัน

```python
SESSION_WEIGHTS = {
    "Weekday_Morning": {
        # ตลาดเอเชียเปิด ทองมักมีทิศทางชัดเจน
        # ให้น้ำหนัก SELL มากขึ้นเล็กน้อย (ราคาทองไทยมักปรับตามราคาคืน)
        "buy_multiplier":  0.95,
        "sell_multiplier": 1.05,
        "min_prob_required": 0.65,
    },
    "Weekday_Afternoon": {
        # ช่วงกลางวัน ตลาดมักนิ่ง ใช้เกณฑ์มาตรฐาน
        "buy_multiplier":  1.00,
        "sell_multiplier": 1.00,
        "min_prob_required": 0.70,
    },
    "Weekday_Evening": {
        # London + NY เปิด Volatility สูงสุด
        # สัญญาณที่ออกมามี Edge สูง แต่ก็ Risk สูงด้วย
        "buy_multiplier":  1.10,
        "sell_multiplier": 1.10,
        "min_prob_required": 0.72,
    },
    "Weekend_Special": {
        # ปริมาณซื้อขายต่ำ ลด Multiplier ลงเพื่อความปลอดภัย
        "buy_multiplier":  0.85,
        "sell_multiplier": 0.85,
        "min_prob_required": 0.75,
    },
}

def apply_session_weight(prob_buy, prob_sell, session_name):
    weights = SESSION_WEIGHTS.get(session_name, SESSION_WEIGHTS["Weekday_Afternoon"])
    
    adj_buy  = min(prob_buy  * weights["buy_multiplier"],  1.0)
    adj_sell = min(prob_sell * weights["sell_multiplier"], 1.0)
    
    return adj_buy, adj_sell
```

**ค่า Multiplier เหล่านี้ควรถูก Calibrate จาก Historical Backtest** โดยวิเคราะห์ว่า Session ใดให้ Win Rate สูงสุดในอดีต แล้วนำมาตั้งเป็น Reference Weight

---

## 7. News Sentiment Model Integration

### 7.1 ทำไมต้องมี Sentiment Layer

โมเดล XGBoost เรียนรู้จาก Technical Pattern เท่านั้น แต่ราคาทองคำสะท้อนตัวแปรสำคัญอีกหลายตัวที่ไม่ปรากฏในกราฟ เช่น การประกาศ Fed Rate, ข้อมูล CPI, ความตึงเครียดทางภูมิรัฐศาสตร์ และข่าวเศรษฐกิจไทย Sentiment Layer ทำหน้าที่เป็น Context ที่ช่วยให้ระบบ "รู้" ว่าสภาพแวดล้อมของตลาดในขณะนั้นเอื้ออำนวยต่อสัญญาณที่โมเดลเพิ่งคายออกมาหรือไม่

### 7.2 เลือก Sentiment Model ที่เหมาะสม

| Model | ข้อดี | เหมาะกับ |
|---|---|---|
| **FinBERT** (ProsusAI/finbert) | เทรนมาจากข้อมูลการเงินโดยตรง, รู้จักคำศัพท์ตลาด | ข่าวภาษาอังกฤษ |
| **XLM-RoBERTa** (multilingual) | รองรับภาษาไทย + อังกฤษในโมเดลเดียว | ข่าวผสมภาษา |
| **WangchanBERTa** | เทรนจากข้อมูลภาษาไทย | ข่าวไทยจาก TH sources |
| **OpenAI GPT-4o / Claude API** | วิเคราะห์ Context ซับซ้อนได้ | Real-time analysis |

สำหรับระบบ Production แนะนำให้ใช้ **FinBERT เป็น Baseline** และเสริมด้วย LLM API สำหรับข่าวที่มีผลกระทบสูง (High-Impact Events)

### 7.3 Pipeline การดึง Sentiment Score

```python
from transformers import pipeline

# โหลดโมเดล (ทำครั้งเดียวตอน Startup)
sentiment_pipeline = pipeline(
    "text-classification",
    model="ProsusAI/finbert",
    return_all_scores=True
)

def get_sentiment_score(news_texts: list[str]) -> float:
    """
    รับข่าวหลายชิ้น คืนค่า Sentiment Score รวม (-1.0 ถึง +1.0)
    -1.0 = Bearish มาก
     0.0 = Neutral
    +1.0 = Bullish มาก
    """
    if not news_texts:
        return 0.0
    
    scores = []
    for text in news_texts:
        result = sentiment_pipeline(text[:512])[0]  # FinBERT จำกัด 512 tokens
        
        score_map = {item["label"]: item["score"] for item in result}
        
        # แปลงเป็น Scalar: Positive=+1, Negative=-1, Neutral=0
        net_score = (
            score_map.get("positive", 0) * 1.0
            - score_map.get("negative", 0) * 1.0
        )
        scores.append(net_score)
    
    # ค่าเฉลี่ยของข่าวทั้งหมดในช่วงเวลานั้น
    return float(sum(scores) / len(scores))
```

### 7.4 Timeframe Aggregation ของ Sentiment

เนื่องจากข่าวออกมาไม่เป็นจังหวะ ระบบต้องรวบรวม Sentiment ใน Window ที่เหมาะสมกับ Session

```python
def aggregate_sentiment_for_bar(news_df: pd.DataFrame, bar_time: datetime) -> dict:
    """
    รวม Sentiment Score ของข่าวที่ออกมาใน Window เวลาต่างๆ
    """
    # Window 1: ข่าวใน 30 นาทีที่ผ่านมา (Short-term Reaction)
    recent_30m = news_df[
        (news_df["published_at"] >= bar_time - pd.Timedelta(minutes=30)) &
        (news_df["published_at"] <= bar_time)
    ]
    
    # Window 2: ข่าวใน 4 ชั่วโมงที่ผ่านมา (Medium-term Sentiment)
    recent_4h = news_df[
        (news_df["published_at"] >= bar_time - pd.Timedelta(hours=4)) &
        (news_df["published_at"] <= bar_time)
    ]
    
    # Window 3: ข่าวใน 24 ชั่วโมงที่ผ่านมา (Daily Trend)
    recent_24h = news_df[
        (news_df["published_at"] >= bar_time - pd.Timedelta(hours=24)) &
        (news_df["published_at"] <= bar_time)
    ]
    
    return {
        "sentiment_30m": get_sentiment_score(recent_30m["text"].tolist()),
        "sentiment_4h":  get_sentiment_score(recent_4h["text"].tolist()),
        "sentiment_24h": get_sentiment_score(recent_24h["text"].tolist()),
        "news_count_30m": len(recent_30m),
        "news_count_4h":  len(recent_4h),
    }
```

### 7.5 แปลง Sentiment Score เป็น Adjustment Factor

```python
def sentiment_to_adjustment(sentiment_score: float, signal_direction: str) -> float:
    """
    คืนค่า Adjustment Factor (0.5 ถึง 1.5)
    ที่จะนำไปคูณกับ prob ของโมเดลก่อนส่งเข้า Signal Engine
    
    - ถ้า Sentiment สอดคล้องกับทิศทางสัญญาณ → เพิ่มน้ำหนัก (> 1.0)
    - ถ้า Sentiment ขัดแย้งกับสัญญาณ → ลดน้ำหนัก (< 1.0)
    """
    if signal_direction == "BUY":
        # ข่าว Bullish ช่วยเสริม BUY Signal
        if sentiment_score > 0.3:
            return 1.15
        elif sentiment_score < -0.3:
            return 0.80  # ข่าว Bearish → ลด Confidence
        else:
            return 1.00  # Neutral → ไม่ปรับ
    
    elif signal_direction == "SELL":
        # ข่าว Bearish ช่วยเสริม SELL Signal
        if sentiment_score < -0.3:
            return 1.15
        elif sentiment_score > 0.3:
            return 0.80
        else:
            return 1.00
    
    return 1.00
```

---

## 8. Confidence Score รวม และการตัดสินใจขั้นสุดท้าย

### 8.1 สูตร Confidence Score

เมื่อรวมทุก Layer เข้าด้วยกัน สูตรคำนวณ Confidence Score ขั้นสุดท้ายจะเป็น

```
Confidence Score = (
    prob_model × w_model
    + sentiment_score_normalized × w_sentiment
    + session_factor × w_session
) / (w_model + w_sentiment + w_session)
```

โดยค่าน้ำหนักเริ่มต้นที่แนะนำ

```python
WEIGHT_CONFIG = {
    "w_model":     0.65,   # XGBoost Dual-Model เป็นหลัก
    "w_sentiment": 0.20,   # News Sentiment เป็นตัวเสริม
    "w_session":   0.15,   # Session Factor เป็นตัวปรับ
}
```

### 8.2 ตัวอย่าง Walkthrough การคำนวณ

สมมติว่ามีสัญญาณ BUY ออกมาจาก Signal Engine

```
Input:
  prob_buy          = 0.74  (จาก XGBoost BUY Model)
  prob_sell         = 0.31  (จาก XGBoost SELL Model, ไม่ขัดแย้ง)
  session_name      = "Weekday_Evening"
  session_progress  = 0.35  (อยู่ช่วงต้น Evening Session)
  sentiment_score   = +0.45 (FinBERT วิเคราะห์ว่า Bullish จากข่าวล่าสุด)

การคำนวณ:
  session_factor    = 1.10 (Evening Session มี Multiplier สูง)
  adj_prob_buy      = 0.74 × 1.10 = 0.814  (หลัง Session Weighting)
  
  sentiment_normalized = (0.45 + 1.0) / 2.0 = 0.725  (แปลงจาก [-1,1] เป็น [0,1])
  
  confidence_score = (
      0.814 × 0.65
      + 0.725 × 0.20
      + 1.10  × 0.15     ← session factor normalized
  ) = 0.529 + 0.145 + 0.165 = 0.839

Output:
  confidence_score = 0.839  → สูงกว่า threshold → ออกสัญญาณ BUY
```

### 8.3 Confidence Gate ขั้นสุดท้าย

```python
CONFIDENCE_GATE = 0.75  # ต้องผ่านเกณฑ์นี้ถึงจะส่งออเดอร์จริง

def should_execute_trade(confidence_score: float, direction: str) -> bool:
    return confidence_score >= CONFIDENCE_GATE
```

---

## 9. LLM เป็น Dynamic Weight Manager

### 9.1 แนวคิด: LLM เห็นภาพรวม

ข้อจำกัดของ Static Weight Config คือ น้ำหนักที่ตั้งไว้ล่วงหน้าไม่สามารถตอบสนองต่อเหตุการณ์ผิดปกติได้ เช่น วัน FOMC Meeting, วันประกาศ Non-Farm Payroll, หรือวิกฤตการณ์ระหว่างประเทศ

**LLM เข้ามาแก้ปัญหานี้** โดยทำหน้าที่อ่านสรุปสถานการณ์ตลาดในขณะนั้น แล้วเสนอการปรับน้ำหนักที่เหมาะสมกับบริบทปัจจุบัน

### 9.2 Architecture ของ LLM Weight Manager

```
Market Context Builder
        │  (รวบรวม: ข่าวล่าสุด, ข้อมูลเศรษฐกิจ, calendar events)
        ▼
LLM Prompt (Structured JSON Request)
        │
        ▼
LLM Response (JSON: weight adjustments + reasoning)
        │
        ▼
Weight Validator (ตรวจสอบว่าค่าอยู่ในช่วงที่ปลอดภัย)
        │
        ▼
Dynamic WEIGHT_CONFIG สำหรับ Session นั้น
```

### 9.3 Prompt Template สำหรับ LLM Weight Manager

```python
WEIGHT_MANAGER_PROMPT = """
คุณคือ Market Context Analyzer สำหรับระบบซื้อขายทองคำไทย
วิเคราะห์สถานการณ์ตลาดปัจจุบันและแนะนำการปรับน้ำหนักสำหรับ Confidence Score

## สถานการณ์ตลาดปัจจุบัน
- เวลาและ Session: {session_name} | {current_time} ICT
- ข่าวล่าสุด (30 นาที): {recent_news_summary}
- Sentiment Score รวม: {sentiment_score:.2f} ({sentiment_label})
- ราคาทองล่าสุด: {gold_price} USD/oz
- ความเคลื่อนไหวราคาใน 4 ชั่วโมง: {price_change_4h:.2f}%
- Event สำคัญวันนี้: {economic_calendar}

## น้ำหนักปัจจุบันที่ระบบใช้
- w_model:     {w_model}
- w_sentiment: {w_sentiment}
- w_session:   {w_session}

## คำถาม
วิเคราะห์สถานการณ์และแนะนำการปรับน้ำหนัก ตอบในรูป JSON เท่านั้น

## รูปแบบคำตอบที่ต้องการ
{
  "w_model": <float 0.3-0.8>,
  "w_sentiment": <float 0.1-0.5>,
  "w_session": <float 0.05-0.3>,
  "confidence_gate": <float 0.65-0.90>,
  "reasoning": "<สรุปเหตุผล 1-2 ประโยค>",
  "risk_level": "LOW | MEDIUM | HIGH",
  "should_trade": true | false
}
"""
```

### 9.4 ตัวอย่างสถานการณ์และการตอบสนองของ LLM

**สถานการณ์ที่ 1: วัน FOMC ประกาศผล**
```json
{
  "w_model": 0.40,
  "w_sentiment": 0.45,
  "w_session": 0.15,
  "confidence_gate": 0.85,
  "reasoning": "FOMC เป็น Event ที่ทำให้ราคาเคลื่อนไหวรุนแรง ให้น้ำหนัก Sentiment สูงขึ้นและเพิ่ม Gate เพื่อความปลอดภัย",
  "risk_level": "HIGH",
  "should_trade": true
}
```

**สถานการณ์ที่ 2: ตลาดปกติ Evening Session**
```json
{
  "w_model": 0.65,
  "w_sentiment": 0.20,
  "w_session": 0.15,
  "confidence_gate": 0.75,
  "reasoning": "สภาวะปกติ ใช้น้ำหนักมาตรฐาน โมเดลน่าเชื่อถือ",
  "risk_level": "LOW",
  "should_trade": true
}
```

**สถานการณ์ที่ 3: เกิดวิกฤตการณ์กะทันหัน**
```json
{
  "w_model": 0.30,
  "w_sentiment": 0.20,
  "w_session": 0.10,
  "confidence_gate": 0.95,
  "reasoning": "ตลาดผิดปกติจากข่าว Black Swan เพิ่ม Gate สูงมาก หรือพิจารณาหยุดเทรดชั่วคราว",
  "risk_level": "HIGH",
  "should_trade": false
}
```

### 9.5 Weight Validator — ป้องกัน LLM ให้ค่าเกิน

```python
def validate_llm_weights(weights: dict) -> dict:
    """
    ตรวจสอบว่าน้ำหนักที่ LLM แนะนำอยู่ในช่วงที่ปลอดภัย
    """
    BOUNDS = {
        "w_model":       (0.30, 0.80),
        "w_sentiment":   (0.10, 0.50),
        "w_session":     (0.05, 0.30),
        "confidence_gate": (0.65, 0.92),
    }
    
    validated = {}
    for key, (lo, hi) in BOUNDS.items():
        if key in weights:
            validated[key] = max(lo, min(hi, float(weights[key])))
        else:
            validated[key] = (lo + hi) / 2  # ใช้ค่ากลางถ้า LLM ไม่ตอบ
    
    # ตรวจสอบ should_trade
    validated["should_trade"] = bool(weights.get("should_trade", True))
    
    return validated
```

### 9.6 Caching และ Rate Limiting สำหรับ LLM API

LLM API มีต้นทุนและ Latency ไม่ควรเรียกทุก Tick ให้ Cache ผลลัพธ์ไว้ใช้ทั้ง Session

```python
from functools import lru_cache
from datetime import datetime

_llm_cache: dict = {}
_cache_valid_until: datetime = datetime.min

def get_dynamic_weights(context: dict, session_name: str) -> dict:
    global _llm_cache, _cache_valid_until
    
    now = datetime.now()
    
    # ใช้ Cache ถ้า Session เดิมและยังไม่หมดอายุ (30 นาที)
    cache_key = f"{session_name}_{now.strftime('%Y%m%d_%H')}"
    if cache_key in _llm_cache and now < _cache_valid_until:
        return _llm_cache[cache_key]
    
    # เรียก LLM API
    raw_weights = call_llm_weight_manager(context)
    validated = validate_llm_weights(raw_weights)
    
    _llm_cache[cache_key] = validated
    _cache_valid_until = now + pd.Timedelta(minutes=30)
    
    return validated
```

---

## 10. Production Deployment Checklist

### 10.1 ก่อน Deploy

- [ ] Backtest บน Out-of-Sample Data อย่างน้อย 60 วัน ก่อน Deploy จริง
- [ ] ตรวจสอบว่า `stop_loss_pct` และ `take_profit_pct` ใน `config.py` ตรงกับ Label Script
- [ ] ตรวจสอบ Timezone ว่าตั้งเป็น `Asia/Bangkok` ถูกต้องหรือไม่
- [ ] ทดสอบ Session Gate ว่าบล็อกการเทรดนอกเวลาได้จริง
- [ ] ตรวจสอบว่าโมเดลไฟล์ `model_buy.pkl` และ `model_sell.pkl` ตรงกับ `feature_columns.json`

### 10.2 File Structure ที่ต้องมี

```
outputs/
└── latest_model/
    ├── models/
    │   ├── model_buy.pkl              ← BUY Model
    │   ├── model_sell.pkl             ← SELL Model
    │   └── feature_columns.json       ← 26 Feature Names
    ├── backtests/
    │   └── <timestamp>_summary.json   ← Backtest Report
    └── train/
        └── metrics.json               ← Training Metrics
```

### 10.3 Config Parameters ที่ต้องทบทวนทุกเดือน

| Parameter | ที่อยู่ | เหตุผลในการทบทวน |
|---|---|---|
| `scale_pos_weight` | ModelConfig | Class Ratio เปลี่ยนตามข้อมูลใหม่ |
| `base_threshold` | SignalConfig | ปรับตาม Win Rate ที่สังเกตในตลาดจริง |
| `spread_rate` | BrokerConfig | Spread ของร้านทองอาจเปลี่ยนตามช่วงเวลา |
| Session Multipliers | SESSION_WEIGHTS | Pattern ของแต่ละ Session เปลี่ยนตามฤดูกาล |

### 10.4 Monitoring Metrics ที่ต้องดูทุกวัน

```
✅ Win Rate ทุก Session แยกกัน
✅ จำนวน Signal ต่อ Session (ถ้าน้อยเกินไปอาจต้องลด Threshold)
✅ Avg Confidence Score ของ Signal ที่ออก
✅ Sentiment Score เฉลี่ยในแต่ละช่วง
✅ จำนวน HOLD ที่เกิดจาก Conflict Gap (ถ้ามากเกินไปอาจต้องปรับ conflict_gap)
```

### 10.5 Rollback Plan

หากโมเดลใหม่ทำผลงานแย่กว่าเดิมใน Live

1. สำรองโฟลเดอร์ `outputs/latest_model/` ก่อน Deploy ทุกครั้ง
2. เก็บโมเดลเก่าไว้ใน `outputs/previous_model/`
3. เปลี่ยน `ModelConfig.buy_model_path` และ `sell_model_path` ชี้กลับไปที่โมเดลเก่า
4. รีสตาร์ทระบบ ไม่จำเป็นต้อง Retrain ใหม่

---

## สรุป Flow การทำงานทั้งหมด

```
1. [Data Feed] รับ OHLCV แท่งใหม่
        ↓
2. [Feature Eng] คำนวณ 26 Features ตาม feature_columns.json
        ↓
3. [Session Gate] ตรวจว่าอยู่ใน Session ที่อนุญาตให้เทรดหรือไม่
        ↓
4. [Dual Model] คาย prob_buy และ prob_sell
        ↓
5. [Session Weighting] ปรับ prob ตาม Session Multiplier
        ↓
6. [Sentiment Layer] ดึง FinBERT Score จากข่าวล่าสุด
        ↓
7. [LLM Weight Manager] อ่านภาพรวมตลาด ปรับ w_model / w_sentiment / w_session
        ↓
8. [Confidence Score] รวมทุก Layer ด้วยสูตร Weighted Average
        ↓
9. [Confidence Gate] ตรวจว่า Score ผ่านเกณฑ์หรือไม่
        ↓
10. [Signal Engine] ตรวจ Conflict Gap แล้วออก BUY / SELL / HOLD
        ↓
11. [Risk Controller] ตรวจ Daily Loss Limit / Consecutive Loss / Blowup
        ↓
12. [Execute] ส่งออเดอร์พร้อมคำนวณ Spread + Slippage ตามจริง
```

ระบบนี้ถูกออกแบบให้แต่ละ Layer เป็น Independent Module ทำให้สามารถ Upgrade ทีละส่วนได้โดยไม่กระทบส่วนอื่น และรองรับการ A/B Test ระหว่าง Strategy ได้โดยง่าย