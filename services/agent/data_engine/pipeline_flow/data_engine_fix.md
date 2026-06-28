---

## 10. Code Fixes — รายละเอียดและ Implementation

---
### [C1] 🔴 price_trend ว่างเปล่าเสมอ

**Root cause:** `prompt.py` บรรทัด 450–466 มี block "── Price Trend ──" แต่ `orchestrator._assemble_payload()` ไม่เคย populate key `market_data.price_trend` ทำให้ LLM ไม่เห็น context การเคลื่อนไหวราคา daily/5d/10d เลย

**แก้ไข orchestrator.py — เพิ่มใน `run()` ก่อน `_assemble_payload()`**

```python
# orchestrator.py → def run(...)
# วางหลังจาก ohlcv_df ถูก timezone-convert แล้ว

# ─── Compute price_trend ──────────────────────────────────────────────────
price_trend: dict = {}
if ohlcv_df is not None and not ohlcv_df.empty and len(ohlcv_df) >= 2:
    try:
        closes = ohlcv_df["close"].dropna()
        c_now  = float(closes.iloc[-1])
        c_prev = float(closes.iloc[-2])

        price_trend["current_close_usd"] = round(c_now, 2)
        price_trend["prev_close_usd"]    = round(c_prev, 2)
        price_trend["daily_change_pct"]  = round((c_now - c_prev) / c_prev * 100, 2)

        if len(closes) >= 6:
            c_5d = float(closes.iloc[-6])
            price_trend["5d_change_pct"] = round((c_now - c_5d) / c_5d * 100, 2)

        if len(closes) >= 11:
            c_10d    = float(closes.iloc[-11])
            window10 = closes.tail(10)
            price_trend["10d_change_pct"] = round((c_now - c_10d) / c_10d * 100, 2)
            price_trend["10d_high"]       = round(float(window10.max()), 2)
            price_trend["10d_low"]        = round(float(window10.min()), 2)

    except Exception as _pt_err:
        logger.warning(f"[Orchestrator] price_trend calc failed: {_pt_err}")
        price_trend = {}

# ─── เรียก _assemble_payload พร้อม price_trend ───────────────────────────
payload = self._assemble_payload(
    price_result, ind_result, news_result,
    effective_days, effective_interval,
    price_trend=price_trend,   # ← เพิ่ม kwarg
)
```

**แก้ไข orchestrator.py — signature และ body ของ `_assemble_payload()`**

```python
# orchestrator.py → def _assemble_payload(...)

def _assemble_payload(
    self, price, ind, news, history_days,
    interval=None,
    price_trend=None,    # ← เพิ่ม parameter
) -> dict:
    ...
    # ภายใน section "market_data"
    "market_data": {
        "spot_price_usd":      spot,
        "forex":               forex,
        "thai_gold_thb":       thai,
        "recent_price_action": price.get("recent_price_action", []),
        "price_trend":         price_trend or {},   # ← เพิ่มบรรทัดนี้
    },
```

**ผลลัพธ์:** prompt "── Price Trend ──" แสดงข้อมูลจริง LLM เห็น current close, % change 1d/5d/10d และ 10-day range ก่อนตัดสินใจ

---

### [C2] 🔴 usd_thb_live = 0.0 ใน latest_gold_price.json

**Root cause:** HSH API ไม่ส่งข้อมูล `usd_thb` มาด้วย → `latest_gold_price.json` มีค่า 0.0 เสมอเมื่อ source = `huasengheng_api` → `fetch_usd_thb_rate()` Layer 3 ตรวจ `usd_thb_live > 0` fail → ตกไป Layer 4 ที่อัปเดตวันละครั้ง

**แก้ไข gold_interceptor_lite.py — เพิ่ม helper + แก้ `fetch_huasengheng()`**

```python
# gold_interceptor_lite.py

# ─── เพิ่ม global cache สำหรับ usd_thb ──────────────────────────────────
_usd_thb_cache: float = 0.0
_usd_thb_last_fetch: float = 0.0
_USD_THB_CACHE_SECONDS: int = 60   # refresh ทุก 60 วินาที


def _fetch_usd_thb_rate() -> float:
    """
    ดึง USD/THB ล่าสุดจาก Yahoo Finance (lightweight — ไม่ต้อง import yfinance)
    ใช้ cache 60 วินาที เพื่อไม่ hit API ทุกรอบ 5 วินาที
    คืน 0.0 ถ้าดึงไม่ได้ (interceptor จะ keep ค่าเดิมไว้)
    """
    global _usd_thb_cache, _usd_thb_last_fetch

    now = time.time()
    if now - _usd_thb_last_fetch < _USD_THB_CACHE_SECONDS and _usd_thb_cache > 0:
        return _usd_thb_cache   # คืน cache โดยไม่ hit API

    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/USDTHB=X"
        resp = requests.get(
            url,
            params={"interval": "1m", "range": "1d"},
            timeout=5,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        data = resp.json()
        closes = (
            data["chart"]["result"][0]
            ["indicators"]["quote"][0]["close"]
        )
        valid = [c for c in closes if c is not None]
        if valid:
            _usd_thb_cache      = round(float(valid[-1]), 4)
            _usd_thb_last_fetch = now
            return _usd_thb_cache
    except Exception as e:
        print(f"[Interceptor] _fetch_usd_thb_rate failed: {e}")

    return _usd_thb_cache   # คืน cache เดิมถ้าดึงใหม่ไม่ได้


# ─── แก้ fetch_huasengheng() — เพิ่มการดึง usd_thb ก่อน save ───────────
def fetch_huasengheng(session):
    global last_hsh_update_time
    ...
    # (ใน block: if bid_96 > 0 and ask_96 > 0:)
    if bid_96 > 0 and ask_96 > 0:

        usd_thb = _fetch_usd_thb_rate()   # ← เพิ่มบรรทัดนี้

        payload = {
            "source":                    "huasengheng_api",
            "market_status":             market_status,
            "price_thb_per_baht_weight": round((bid_96 + ask_96) / 2, 2),
            "sell_price_thb":            ask_96,
            "buy_price_thb":             bid_96,
            "spread_thb":                ask_96 - bid_96,
            "gold_9999_buy":             bid_99,
            "gold_9999_sell":            ask_99,
            "gold_spot_usd":             spot,
            "usd_thb_live":              usd_thb,   # ← ไม่เป็น 0.0 แล้ว
            "timestamp":                 get_thai_time().isoformat(),
        }
        save_to_json(payload)
        ...
```

**ผลลัพธ์:** `fetch_usd_thb_rate()` Layer 3 เจอค่าจริง → ใช้ real-time rate ตลอดเวลา ไม่ต้อง fallback ไป exchangerate-api รายวันอีกต่อไป

---

### [I1] 🟠 trend_signal — Dead Code

**Root cause:** `orchestrator._assemble_payload()` inject `trend_d["trend_signal"]` แต่ไม่มีผู้บริโภคในระบบปัจจุบัน เพิ่ม payload size โดยเปล่าประโยชน์

**แก้ไข orchestrator.py — ลบบรรทัดออก**

```python
# orchestrator.py → _assemble_payload()

# ❌ ลบบรรทัดนี้:
# if trend_d and "trend_signal" not in trend_d:
#     trend_d["trend_signal"] = trend_d.get("trend", "neutral")

# ถ้าต้องการเผื่อ future ให้เปลี่ยนเป็น comment:
# TODO: trend_signal reserved for future multi-signal aggregation
```

---

### [I2] 🟠 ATR Mutation — เพิ่ม Guard ครบถ้วน

**Root cause:** ถ้า `usd_thb = 0` หรือ `atr.value = 0` การ convert จะให้ค่าผิด (0.0) แต่ไม่ crash → prompt แสดง `atr.unit = "THB_PER_BAHT_WEIGHT"` ทั้งที่ค่าจริงยังเป็น USD หรือเป็น 0 ซึ่งทำให้ LLM คำนวณ SL/TP ผิดพลาดได้

**แก้ไข services.py — แทนที่ block ATR conversion ทั้งหมด**

```python
# services.py → _run_single_interval()

# ─── ATR: USD/oz → THB/baht_weight ──────────────────────────────────────
try:
    _ti       = market_state.get("technical_indicators", {})
    _atr_node = _ti.get("atr", {})
    _atr_usd  = float(_atr_node.get("value", 0))
    _usd_thb  = float(
        market_state.get("market_data", {})
        .get("forex", {}).get("usd_thb", 0.0)
    )
    _spot = float(
        market_state.get("market_data", {})
        .get("spot_price_usd", {}).get("price_usd_per_oz", 0)
    )

    # Guard: ข้อมูลพร้อม?
    if _atr_usd <= 0 or _usd_thb <= 0:
        raise ValueError(
            f"ATR conversion skipped — atr_usd={_atr_usd}, usd_thb={_usd_thb}"
        )

    # Stale check: ATR < 0.1% ของราคา = ข้อมูล stale มาก
    if _spot > 0 and (_atr_usd / _spot) < 0.001:
        sys_logger.warning(
            f"[{interval}] ATR unreliable (ratio={_atr_usd/_spot:.4%}) "
            "— market likely closed or stale data"
        )

    _atr_thb = (_atr_usd * _usd_thb / 31.1035) * 15.244

    # ✅ Mutation ที่ document ชัดเจน
    _atr_node["value"]     = round(_atr_thb, 2)
    _atr_node["unit"]      = "THB_PER_BAHT_WEIGHT"
    _atr_node["value_usd"] = round(_atr_usd, 4)

    sys_logger.info(
        f"[{interval}] ATR: {_atr_usd:.4f} USD/oz "
        f"→ {_atr_thb:.2f} THB/baht_weight (usd_thb={_usd_thb:.4f})"
    )

except Exception as _atr_err:
    sys_logger.warning(
        f"[{interval}] ATR conversion failed: {_atr_err} "
        "— value remains in USD"
    )
    # ✅ Explicit fallback: set unit ให้ตรงกับความจริง
    _atr_node = market_state.get("technical_indicators", {}).get("atr", {})
    if "unit" not in _atr_node:
        _atr_node["unit"]     = "USD_PER_OZ"
    if "value_usd" not in _atr_node:
        _atr_node["value_usd"] = _atr_node.get("value", 0)
```

---

### [M1] 🟡 OHLCV Timezone — แก้ให้ proper localize

**Root cause:** `ohlcv_df.index + pd.Timedelta(hours=7)` แค่ shift ตัวเลข ไม่ได้ localize timezone → ถ้า index มี UTC tz แล้วจะ raise `TypeError`; ถ้าสำเร็จ timestamp candle ก็ยังไม่มี tz info ทำให้ debug และ plot ผิด

**แก้ไข orchestrator.py — แทนที่ block timezone ทั้งหมด**

```python
# orchestrator.py → run()

# ❌ โค้ดเดิม — ห้ามใช้
# if ohlcv_df.index.tz is None:
#     ohlcv_df.index = ohlcv_df.index + pd.Timedelta(hours=7)

# ✅ โค้ดใหม่ — proper timezone conversion
if ohlcv_df is not None and not ohlcv_df.empty:
    try:
        if ohlcv_df.index.tz is None:
            # ไม่มี tz → สมมติ UTC (yfinance ส่งมาแบบนี้) แล้ว convert
            ohlcv_df = ohlcv_df.copy()  # ป้องกัน mutation ของ cache
            ohlcv_df.index = (
                ohlcv_df.index
                .tz_localize("UTC")
                .tz_convert("Asia/Bangkok")
            )
        elif str(ohlcv_df.index.tz) != "Asia/Bangkok":
            # มี tz อื่น → convert ตรงๆ
            ohlcv_df = ohlcv_df.copy()
            ohlcv_df.index = ohlcv_df.index.tz_convert("Asia/Bangkok")
        # ถ้าเป็น Asia/Bangkok แล้ว → skip (ไม่ต้องทำอะไร)
    except Exception as _tz_err:
        logger.warning(
            f"[Orchestrator] OHLCV timezone conversion failed: {_tz_err} "
            "— using original index"
        )
```

> **Note:** เรียก `.copy()` ก่อนแก้ index เพื่อไม่ mutate DataFrame ที่ yfinance / OHLCV cache อาจถือ reference เดียวกันอยู่

---

### สรุป Fixes ทั้งหมด

| Fix ID | ไฟล์ที่แก้ | ผลลัพธ์ที่ได้ |
|---|---|---|
| **[C1]** price_trend | `orchestrator.py` | prompt แสดง price trend ครบ · LLM เห็น % change 1d/5d/10d และ range |
| **[C2]** usd_thb_live | `gold_interceptor_lite.py` | Layer 3 ทำงาน · USD/THB real-time แทน daily |
| **[I1]** trend_signal | `orchestrator.py` | ลด payload noise · โค้ดสะอาดขึ้น |
| **[I2]** ATR guard | `services.py` | ป้องกัน silent fail · unit fallback ถูกต้อง |
| **[M1]** OHLCV tz | `orchestrator.py` | timestamp candle ถูกต้อง · ป้องกัน TypeError |

---