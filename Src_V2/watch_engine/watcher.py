"""
engine/engine.py  — The Watcher Engine (v3.0)
Event-driven market watcher that triggers AI analysis on signal.

Changes v3.1:
  [P0] _manage_trailing_stop: ลบ _execute_emergency_sell ออก → แค่ set _sl_triggered flag
  [P0] _evaluate_strategy: รวม SL logic เข้ามาเป็น Case 1 รวมศูนย์ พร้อม fake swing check
  [P0] _execute_emergency_sell: ยังคงอยู่ แต่เรียกจาก AI decision เท่านั้น (ไม่ถูกเรียกอัตโนมัติ)
  [P1] __init__: เพิ่ม _sl_triggered: Optional[str] = None

Changes v3.0:
  [P0] แก้ Indentation ทุก method ให้ถูกต้อง
  [P0] เพิ่ม _manage_trailing_stop() กลับเข้า _watcher_loop
  [P0] ลบโค้ด floating นอก class ออก (NameError)
  [P1] _evaluate_strategy: early-exit ก่อนคำนวณ is_real ถ้าไม่จำเป็น
  [P1] sl_level: guard cost_basis = 0
  [P1] structure: อ่านจาก technical_indicators ไม่ใช่ root
  [P2] STRONG_OVERSOLD / STRONG_OVERBOUGHT รวมเข้า _evaluate_strategy แล้ว

Changes v2.0 (Full Priority Fix):
  [P0] TriggerState: ใส่ threading.Lock() ป้องกัน race condition
  [P0] _execute_emergency_sell: เรียก db.record_emergency_sell_atomic() จริง (atomic transaction)
  [P1] Defensive price reading: ไม่ใช้ silent default fallback 72000.0 อีกต่อไป
  [P1] trailing_stop_level ถูก persist ลง DB ผ่าน save_portfolio ไม่หายหลัง restart
  [P2] GOLD_BAHT_TO_GRAM เป็น module-level constant
  [P2] WatcherConfig Pydantic model — fail fast ถ้า config ขาด key
  [P3] AI decision ถูกส่งต่อ: Telegram/Discord notify + broker hook stub
"""

import threading
import time
import logging
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from .indicators import TechnicalIndicators

logger = logging.getLogger(__name__)

# ─── [P2] Module-level constant ─────────────────────────────────────────────
GOLD_BAHT_TO_GRAM: float = 15.244  # 1 บาทน้ำหนัก = 15.244 กรัม


# ─── WatcherConfig — Pydantic validation ────────────────────────────────────
class WatcherConfig(BaseModel):
    """
    Config สำหรับ WatcherEngine — validate ตอน init ทันที
    ถ้า key ขาดหรือผิด type จะ raise ValidationError ก่อน thread ขึ้น
    """

    provider: str = Field(default="gemini", description="LLM provider")
    period: str = Field(default="1d", description="Data period")
    interval: str = Field(default="5m", description="Candle interval")
    cooldown_minutes: int = Field(
        default=5, ge=1, description="Min minutes between AI triggers"
    )
    min_price_step: float = Field(
        default=1.5, gt=0.0, description="Min THB/gram move to re-trigger"
    )
    rsi_oversold: float = Field(
        default=30.0, ge=0, le=50, description="RSI oversold threshold"
    )
    rsi_overbought: float = Field(
        default=70.0, ge=50, le=100, description="RSI overbought threshold"
    )
    trailing_stop_profit_trigger: float = Field(
        default=20.0, gt=0, description="Profit/gram ที่ขยับ SL"
    )
    trailing_stop_lock_in: float = Field(
        default=5.0, gt=0, description="SL lock-in เหนือ cost"
    )
    hard_stop_loss_per_gram: float = Field(
        default=15.0, gt=0, description="Max loss/gram ก่อน cut"
    )
    loop_sleep_seconds: int = Field(
        default=30, gt=0, description="วินาทีในการพักของ Watcher loop"
    )

    @field_validator("provider")
    @classmethod
    def provider_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("provider must not be empty")
        return v.strip()

    @field_validator("period")
    @classmethod
    def valid_period(cls, v: str) -> str:
        allowed = {"1d", "3d", "5d", "7d", "14d", "1mo", "2mo", "3mo"}
        if v not in allowed:
            raise ValueError(f"period must be one of {allowed}, got '{v}'")
        return v


# ─── TriggerState ────────────────────────────────────────────────────────────
class TriggerState:
    def __init__(self, cooldown_minutes: int = 0.01, min_price_step_thb: float = 1.5):
        self.cooldown_seconds = cooldown_minutes * 60
        self.min_price_step = min_price_step_thb
        self.last_trigger_time = 0.0
        self.last_trigger_price = 0.0
        self._lock = threading.Lock()

    def is_ready(
        self, current_price_per_gram: float, bypass_cooldown: bool = False
    ) -> tuple[bool, str]:
        """
        bypass_cooldown=True (e.g. SL trigger) ข้าม BOTH cooldown AND price-step
        เพื่อให้ AI ถูกปลุกทันที ไม่ว่าราคาจะขยับเล็กแค่ไหน
        """
        with self._lock:
            if bypass_cooldown:
                return True, "Ready (SL bypass — all gates skipped)"

            current_time = time.time()
            time_elapsed = current_time - self.last_trigger_time
            if time_elapsed < self.cooldown_seconds:
                remaining = self.cooldown_seconds - time_elapsed
                return False, f"Cooldown: {remaining:.0f}s left"

            if self.last_trigger_price > 0:
                price_diff = abs(current_price_per_gram - self.last_trigger_price)
                if price_diff < self.min_price_step:
                    return False, (
                        f"Price Step: Moved only {price_diff:.2f} ฿/g "
                        f"(Need {self.min_price_step})"
                    )

            return True, "Ready"

    def update_trigger(self, current_price_per_gram: float) -> None:
        with self._lock:
            self.last_trigger_time = time.time()
            self.last_trigger_price = current_price_per_gram


# ─── WatcherEngine ───────────────────────────────────────────────────────────
class WatcherEngine:
    def __init__(
        self,
        analysis_service,
        data_orchestrator,
        watcher_config: dict,
    ):
        self._last_roc = 0.0
        self.analysis_service = analysis_service
        self.data_orchestrator = data_orchestrator
        self.config = WatcherConfig(**watcher_config)
        self.is_running = False
        self.lock = threading.Lock()
        self.logs: list[str] = []

        self.trigger_state = TriggerState(
            cooldown_minutes=self.config.cooldown_minutes,
            min_price_step_thb=self.config.min_price_step,
        )

        self._active_trailing_sl_per_gram: Optional[float] = None
        # [v3.1] Flag จาก _manage_trailing_stop → ให้ _evaluate_strategy ตัดสิน
        self._sl_triggered: Optional[str] = None
        self._load_trailing_stop_from_portfolio()

    # ── Logging ──────────────────────────────────────────────────────────────

    def log(self, msg: str, level: str = "INFO") -> None:
        with self.lock:
            time_str = datetime.now().strftime("%H:%M:%S")
            log_msg = f"[{time_str}] {msg}"
            self.logs.append(log_msg)
            if len(self.logs) > 50:
                self.logs.pop(0)
            if level == "ERROR":
                logger.error(log_msg)
            else:
                logger.info(log_msg)

    def get_logs(self) -> list[str]:
        """Thread-safe log snapshot สำหรับ Gradio UI"""
        with self.lock:
            return list(self.logs)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if not self.is_running:
            self.is_running = True
            self.thread = threading.Thread(target=self._watcher_loop, daemon=True)
            self.thread.start()
            self.log("🚀 Watcher Engine Started")

    def stop(self) -> None:
        self.is_running = False
        self.log("🛑 Watcher Engine Stopped")

    # ── Main Loop ─────────────────────────────────────────────────────────────

    def _watcher_loop(self) -> None:
        while self.is_running:
            try:
                # 1. ดึงข้อมูลตลาด
                market_state = self.data_orchestrator.run(
                    history_days=1,
                    interval=self.config.interval,
                )

                data_quality = market_state.get("data_quality", {})
                if (
                    data_quality.get("source") != "MTS_API"
                    or data_quality.get("fallback")
                    or data_quality.get("stale")
                    or data_quality.get("status") != "ok"
                ):
                    self.log(
                        "⚠️ MTS data not tradable — "
                        f"status={data_quality.get('status')} "
                        f"stale={data_quality.get('stale')} "
                        f"fallback={data_quality.get('fallback')}",
                        "ERROR",
                    )
                    time.sleep(3)
                    continue

                # 2. อ่านราคา: entry=ask/sell, exit=bid/buy, movement=mid
                entry_price_per_gram = self._extract_price(market_state, "entry")
                exit_price_per_gram = self._extract_price(market_state, "exit")
                movement_price_per_gram = self._extract_price(market_state, "movement")
                if (
                    entry_price_per_gram is None
                    or exit_price_per_gram is None
                    or movement_price_per_gram is None
                ):
                    self.log("⚠️ Cannot read gold price — skipping cycle", "ERROR")
                    time.sleep(3)
                    continue

                # 3. [P0] Trailing Stop ต้องรันก่อน evaluate เสมอ
                self._manage_trailing_stop(exit_price_per_gram)

                # 4. ตรวจสอบข้อมูลพื้นฐาน
                ti = market_state.get("technical_indicators", {})

                # 🎯 ชี้เป้าให้ตรงจุด! ดึงกราฟจากกล่อง _raw_ohlcv ชั้นนอกสุดโดยตรง
                candles = market_state.get("_raw_ohlcv", [])

                # ใช้ len() เช็คเพื่อป้องกัน Error ในกรณีที่ Data มาเป็น Pandas
                if len(candles) == 0 or not ti:
                    self.log("⚠️ Incomplete market data — skipping", "ERROR")
                    time.sleep(3)
                    continue

                if len(candles) < 50:
                    self.log(f"⚠️ Not enough candles ({len(candles)}/50) — skipping")
                    time.sleep(self.config.loop_sleep_seconds)
                    continue

                # 5. คำนวณ indicator (Ultimate Fallback Data Structure Parser)
                try:
                    closes = []

                    # กรณีที่ 0: ข้อมูลมาเป็น Pandas DataFrame
                    if str(
                        type(candles)
                    ) == "<class 'pandas.core.frame.DataFrame'>" or hasattr(
                        candles, "columns"
                    ):
                        closes = (
                            [float(x) for x in candles["close"].tolist()]
                            if "close" in candles
                            else []
                        )
                    # กรณีที่ 1: เป็น List ของ Dictionary
                    elif (
                        isinstance(candles, list)
                        and len(candles) > 0
                        and isinstance(candles[0], dict)
                    ):
                        closes = [
                            float(c.get("close", c.get("Close", 0))) for c in candles
                        ]
                    # กรณีที่ 2: เป็น Dictionary ที่มีคีย์ 'close' ซ้อน
                    elif isinstance(candles, dict) and "close" in candles:
                        closes = [float(v) for v in candles["close"].values()]
                    # กรณีที่ 3: เป็น List ซ้อน List
                    elif (
                        isinstance(candles, list)
                        and len(candles) > 0
                        and isinstance(candles[0], list)
                    ):
                        closes = [float(c[3]) for c in candles]

                    if not closes:
                        self.log(
                            f"⚠️ Cannot extract closes from candles structure: {type(candles)}",
                            "ERROR",
                        )
                        time.sleep(3)
                        continue

                    rsi = ti.get("rsi", {}).get("value", 50.0)
                    roc_now = self._compute_roc(closes)
                    mad_now, mad_avg = self._compute_mad(closes)

                except Exception as e:
                    self.log(f"⚠️ Error parsing indicators: {str(e)}", "ERROR")
                    time.sleep(3)
                    continue

                # 6. ดึง portfolio
                try:
                    portfolio = self.analysis_service.persistence.get_portfolio()
                    gold_grams = float(portfolio.get("gold_grams", 0.0))
                    cost_basis = float(portfolio.get("cost_basis_thb", 0.0))
                except Exception as e:
                    self.log(f"❌ Cannot read portfolio: {e}", "ERROR")
                    time.sleep(3)
                    continue

                holding_gold = gold_grams > 0

                # 7. ตัดสินใจตาม strategy
                should_trigger, trigger_reason = self._evaluate_strategy(
                    holding_gold=holding_gold,
                    current_price=exit_price_per_gram if holding_gold else entry_price_per_gram,
                    cost_basis=cost_basis,
                    rsi=rsi,
                    market_state=market_state,
                    roc_now=roc_now,
                    roc_prev=self._last_roc,
                    mad_now=mad_now,
                    mad_avg=mad_avg,
                )

                # SL bypass cooldown — ราคา hit SL ต้องปลุก AI ได้เลย
                is_sl_trigger = self._sl_triggered is not None

                if should_trigger:
                    ready, block_reason = self.trigger_state.is_ready(
                        movement_price_per_gram,
                        bypass_cooldown=is_sl_trigger,
                    )
                    if ready:
                        self.log(f"🔥 Trigger AI: {trigger_reason}")
                        self.trigger_state.update_trigger(movement_price_per_gram)
                        self._trigger_analysis()
                    else:
                        self.log(f"🔒 Blocked — {block_reason}")
                else:
                    self.log(f"😴 No trigger — {trigger_reason}")

                # reset SL flag หลังผ่าน evaluate แล้ว
                self._sl_triggered = None
                self._last_roc = roc_now

            except Exception as e:
                self.log(f"❌ Watcher Error: {e}", "ERROR")

            time.sleep(self.config.loop_sleep_seconds)

    # ── Strategy ──────────────────────────────────────────────────────────────

    def _evaluate_strategy(
        self,
        holding_gold: bool,
        current_price: float,
        cost_basis: float,
        rsi: float,
        market_state: dict,
        roc_now: float,
        roc_prev: float,
        mad_now: float,
        mad_avg: float,
    ) -> tuple[bool, str]:
        """
        กลยุทธ์หลัก 3 cases:

        ถือทองอยู่:
          Case 1 — ราคา < SL  : fake → ถือต่อ  /  real → ปลุก AI
          Case 2 — RSI overbought (เหนือ SL) → ปลุก AI (take profit)

        ไม่ถือทอง:
          Case 3 — RSI oversold → ปลุก AI (buy)
        """
        ti = market_state.get("technical_indicators", {})
        macd = ti.get("macd", {})
        bb = ti.get("bollinger", {})

        # ── STRONG signal check (อ่าน schema จริงของ orchestrator) ──────────
        # Orchestrator schema มีแค่ rsi/macd(line,signal,histogram,crossover)/bollinger/atr/trend
        # ฉะนั้นคำนวณ prev_histogram และเทียบ ROC จาก _raw_ohlcv ตรงนี้
        hist_now = float(macd.get("histogram", 0.0))
        hist_prev = self._compute_prev_macd_hist(market_state)

        strong_oversold = (
            rsi < 30
            and roc_now > roc_prev
            and hist_now > hist_prev
            and bb.get("signal") == "below_lower"
        )

        strong_overbought = (
            rsi > 70
            and roc_now < roc_prev
            and hist_now < hist_prev
            and bb.get("signal") == "above_upper"
        )

        # ── กรณีถือทองอยู่ ───────────────────────────────────────────────────
        if holding_gold:
            # [v3.1] Case 1: SL hit — ตัดสินที่นี่ ไม่ใช่ใน _manage_trailing_stop
            if self._sl_triggered is not None:
                sl_reason = self._sl_triggered

                # fake swing check ก่อน — ถ้าหลอก ไม่ต้องทำอะไร
                is_fake = self._is_fake_swing(market_state, roc_now, mad_now, mad_avg)
                if is_fake:
                    self.log(f"🛡️ SL hit ({sl_reason}) but FAKE swing — holding")
                    return False, f"SL hit ({sl_reason}) but fake swing — no action"

                # real reversal check
                is_real, real_reason = self._is_real_reversal(
                    market_state, roc_now, roc_prev, mad_now, mad_avg
                )
                if is_real:
                    return True, (
                        f"⚠️ SL hit + Real signal ({real_reason}) "
                        f"— wake AI to evaluate exit"
                    )

                return (
                    False,
                    f"SL hit ({sl_reason}) but signal unclear ({real_reason}) — waiting",
                )

            # [P1] guard cost_basis = 0
            if self._active_trailing_sl_per_gram is not None:
                sl_level = self._active_trailing_sl_per_gram
            elif cost_basis > 0:
                sl_level = cost_basis - self.config.hard_stop_loss_per_gram
            else:
                sl_level = None

            # Case 1: ราคาต่ำกว่า Stop Loss
            if sl_level is not None and current_price < sl_level:
                # early-exit ถ้า fake — ไม่ต้องคำนวณ is_real
                is_fake = self._is_fake_swing(market_state, roc_now, mad_now, mad_avg)
                if is_fake:
                    self.log(
                        f"🛡️ Below SL ({current_price:.2f} < {sl_level:.2f}) "
                        f"but FAKE signal — holding"
                    )
                    return False, "Below SL but fake swing — no action"

                is_real, real_reason = self._is_real_reversal(
                    market_state, roc_now, roc_prev, mad_now, mad_avg
                )
                if is_real:
                    return True, (
                        f"⚠️ Below SL + Real signal ({real_reason}) "
                        f"— wake AI to evaluate exit"
                    )

                return False, "Below SL but signal unclear — waiting"

            # Case 2: เหนือ SL และ overbought → take profit
            if strong_overbought:
                return True, (
                    f"📈 STRONG_OVERBOUGHT (RSI={rsi:.1f}, MACD+BB confirm) "
                    f"— wake AI for take profit"
                )

            if rsi > self.config.rsi_overbought:
                return True, (
                    f"📈 Overbought (RSI={rsi:.1f}) — wake AI for take profit decision"
                )

            # ปกติ — ถือต่อ
            profit = current_price - cost_basis if cost_basis > 0 else 0.0
            return False, (
                f"Holding — price normal (profit={profit:+.2f} ฿/g, RSI={rsi:.1f})"
            )

        # ── กรณีไม่มีทองในมือ ────────────────────────────────────────────────
        else:
            # Case 3: oversold → buy opportunity
            if strong_oversold:
                return True, (
                    f"💰 STRONG_OVERSOLD (RSI={rsi:.1f}, MACD+BB confirm) "
                    f"— wake AI for buy"
                )

            if rsi < self.config.rsi_oversold:
                return True, (f"💰 Oversold (RSI={rsi:.1f}) — wake AI for buy decision")

            return False, f"No position — waiting for oversold (RSI={rsi:.1f})"

    # ── Signal Filter ─────────────────────────────────────────────────────────

    def _is_fake_swing(
        self,
        market_state: dict,
        roc: float,
        mad_now: float,
        mad_avg: float,
    ) -> bool:
        """
        Fake swing = wick ยาว + momentum อ่อน + ตลาด sideways
        ครบทุกเงื่อนไข = หลอกแน่นอน
        """
        ti = market_state.get("technical_indicators", {})
        rsi = ti.get("rsi", {}).get("value", 50)

        candles = self._normalize_candles(market_state, tail=1)
        if not candles:
            return False

        last = candles[-1]
        body = abs(float(last["close"]) - float(last["open"]))
        full = float(last["high"]) - float(last["low"])
        body_ratio = body / full if full > 0 else 0

        return (
            body_ratio < 0.3  # wick ยาว body เล็ก
            and abs(roc) < 0.15  # momentum อ่อนมาก
            and mad_now < mad_avg  # volatility ต่ำกว่าปกติ
            and 40 <= rsi <= 60  # RSI กลางๆ
        )

    def _is_real_reversal(
        self,
        market_state: dict,
        roc: float,
        roc_prev: float,
        mad_now: float,
        mad_avg: float,
    ) -> tuple[bool, str]:
        """
        Scoring system — ต้องได้ >= 4/6 ถึงจะถือว่า reversal จริง
        """
        ti = market_state.get("technical_indicators", {})
        rsi = ti.get("rsi", {}).get("value", 50)

        candles = self._normalize_candles(market_state, tail=14)
        if not candles:
            return False, "No candle data"

        last = candles[-1]
        body = abs(float(last["close"]) - float(last["open"]))
        full = float(last["high"]) - float(last["low"])
        body_ratio = body / full if full > 0 else 0

        vol_now = float(last.get("volume", 0))
        vol_avg = sum(float(c.get("volume", 0)) for c in candles[-14:]) / 14

        # Candle-derived structure break (orchestrator schema ไม่มี structure flags)
        if len(candles) >= 2:
            prior = candles[:-1]
            swing_high = max(float(c["high"]) for c in prior)
            swing_low = min(float(c["low"]) for c in prior)
            close_last = float(last["close"])
            break_swing_high = close_last > swing_high
            break_swing_low = close_last < swing_low
        else:
            break_swing_high = False
            break_swing_low = False

        score = 0
        reasons = []

        if body_ratio >= 0.5:
            score += 1
            reasons.append(f"Strong body ({body_ratio:.0%})")

        if vol_avg > 0 and vol_now > vol_avg * 1.3:
            score += 1
            reasons.append("Vol surge")
        elif vol_avg == 0 and body_ratio >= 0.5:
            # ไม่มี volume ใช้ body แทน (ไม่ให้คะแนนซ้ำ)
            pass

        if rsi < 30 or rsi > 70:
            score += 1
            reasons.append(f"RSI extreme ({rsi:.1f})")

        if mad_now > mad_avg * 1.5:
            score += 1
            reasons.append("High volatility")

        roc_flip = (roc_prev > 0 and roc <= 0) or (roc_prev < 0 and roc >= 0)
        if roc_flip and abs(roc) > 0.3:
            score += 1
            reasons.append(f"ROC flip ({roc:.2f}%)")

        if break_swing_high or break_swing_low:
            score += 1
            reasons.append("Structure break")

        is_real = score >= 4
        return is_real, f"Score {score}/6 — {', '.join(reasons) or 'no signal'}"

    # ── Helper: Candle Normalization ──────────────────────────────────────────

    def _normalize_candles(self, market_state: dict, tail: int = 14) -> list[dict]:
        """
        Return last `tail` candles as list[dict] with keys open/high/low/close/volume.
        Sources from market_state['_raw_ohlcv'] (DataFrame | list[dict] | list[list]).
        """
        raw = market_state.get("_raw_ohlcv", [])
        if raw is None:
            return []

        # DataFrame
        if hasattr(raw, "columns"):
            if len(raw) == 0:
                return []
            sub = raw.tail(tail)
            cols = {str(c).lower(): c for c in sub.columns}

            def g(row, k: str) -> float:
                return float(row[cols[k]]) if k in cols else 0.0

            out: list[dict] = []
            for _, row in sub.iterrows():
                out.append(
                    {
                        "open": g(row, "open"),
                        "high": g(row, "high"),
                        "low": g(row, "low"),
                        "close": g(row, "close"),
                        "volume": g(row, "volume") if "volume" in cols else 0.0,
                    }
                )
            return out

        # list[dict]
        if isinstance(raw, list) and raw and isinstance(raw[0], dict):

            def pick(d: dict, *keys: str) -> float:
                for k in keys:
                    if k in d:
                        try:
                            return float(d[k])
                        except (TypeError, ValueError):
                            return 0.0
                return 0.0

            return [
                {
                    "open": pick(c, "open", "Open"),
                    "high": pick(c, "high", "High"),
                    "low": pick(c, "low", "Low"),
                    "close": pick(c, "close", "Close"),
                    "volume": pick(c, "volume", "Volume"),
                }
                for c in raw[-tail:]
            ]

        # list[list] — assume [open, high, low, close, volume]
        if isinstance(raw, list) and raw and isinstance(raw[0], (list, tuple)):
            return [
                {
                    "open": float(c[0]),
                    "high": float(c[1]),
                    "low": float(c[2]),
                    "close": float(c[3]),
                    "volume": float(c[4]) if len(c) > 4 else 0.0,
                }
                for c in raw[-tail:]
            ]

        return []

    def _compute_prev_macd_hist(self, market_state: dict) -> float:
        """
        Recompute MACD histogram for the *previous* bar from _raw_ohlcv closes.
        Returns 0.0 if not enough data.
        """
        candles = self._normalize_candles(market_state, tail=60)
        closes = [c["close"] for c in candles]
        if len(closes) < 35:
            return 0.0
        try:
            import pandas as pd

            s = pd.Series(closes[:-1])  # exclude last bar → "prev" view
            ema_fast = s.ewm(span=12, adjust=False).mean()
            ema_slow = s.ewm(span=26, adjust=False).mean()
            macd_line = ema_fast - ema_slow
            signal = macd_line.ewm(span=9, adjust=False).mean()
            return float((macd_line - signal).iloc[-1])
        except Exception:
            return 0.0

    # ── Helper: Indicators ────────────────────────────────────────────────────

    def _compute_roc(self, closes: list[float], period: int = 14) -> float:
        if len(closes) < period + 1:
            return 0.0
        return ((closes[-1] - closes[-(period + 1)]) / closes[-(period + 1)]) * 100

    def _compute_mad(
        self, closes: list[float], period: int = 14
    ) -> tuple[float, float]:
        if len(closes) < period * 2:
            return 0.0, 0.0

        def get_mad(data: list[float]) -> float:
            m = sum(data) / len(data)
            return sum(abs(x - m) for x in data) / len(data)

        return get_mad(closes[-period:]), get_mad(closes[-(period * 2) :])

    # ── Price Extraction ──────────────────────────────────────────────────────

    def _extract_price(self, market_state: dict, price_role: str = "movement") -> Optional[float]:
        """Read MTS quote by role and return THB/gram. entry=ask, exit=bid, movement=mid."""
        try:
            thai_gold_data = market_state.get("market_data", {}).get(
                "thai_gold_thb", {}
            )
            price_key_by_role = {
                "entry": "sell_price_thb",
                "buy": "sell_price_thb",
                "exit": "buy_price_thb",
                "sell": "buy_price_thb",
                "movement": "mid_price_thb",
                "mid": "mid_price_thb",
            }
            price_key = price_key_by_role.get(price_role, "mid_price_thb")
            raw_price = thai_gold_data.get(price_key)

            # ตรวจสอบว่าดึงราคามาได้หรือไม่
            if raw_price is None:
                self.log(f"⚠️ Could not find '{price_key}' in market_state", "WARNING")
                return None

            # แปลงเป็น float (เผื่อได้มาเป็น string จาก API)
            price_thb = float(raw_price)

            # ป้องกันกรณี API ส่งค่าแปลกๆ (เช่น ราคาติดลบ หรือ 0)
            if price_thb <= 0:
                self.log(f"⚠️ Invalid price received: {price_thb}", "WARNING")
                return None

            # แปลงราคาทองรูปพรรณ/แท่ง (บาททองคำ) เป็นราคาทองต่อกรัม
            price_per_gram = price_thb / GOLD_BAHT_TO_GRAM
            return price_per_gram

        except (TypeError, ValueError) as e:
            self.log(
                f"⚠️ Price parse error (invalid format): {e} | Raw value: {raw_price}",
                "ERROR",
            )
            return None
        except Exception as e:
            self.log(f"⚠️ Unexpected error in _extract_price: {e}", "ERROR")
            return None

    # ── Trailing Stop ─────────────────────────────────────────────────────────

    def _load_trailing_stop_from_portfolio(self) -> None:
        """โหลด trailing SL จาก DB ตอน init — ไม่ให้หายหลัง restart"""
        try:
            portfolio = self.analysis_service.persistence.get_portfolio()
            sl = portfolio.get("trailing_stop_level_thb")
            if sl:
                self._active_trailing_sl_per_gram = float(sl)
                self.log(
                    f"📂 Trailing SL restored: {self._active_trailing_sl_per_gram:.2f} ฿/g"
                )
        except Exception as e:
            self.log(f"⚠️ Could not load trailing SL: {e}", "ERROR")

    def _manage_trailing_stop(self, current_price_per_gram: float) -> None:
        """
        [v3.1] อัปเดต trailing SL level และ set _sl_triggered flag เท่านั้น
        ไม่สั่งขายเอง — การตัดสินใจขาย/hold อยู่ที่ _evaluate_strategy
        """
        try:
            portfolio = self.analysis_service.persistence.get_portfolio()
            gold_grams = float(portfolio.get("gold_grams", 0.0))
            cost_basis = float(portfolio.get("cost_basis_thb", 0.0))
        except Exception as e:
            self.log(f"❌ Cannot read portfolio for trailing stop: {e}", "ERROR")
            return

        if gold_grams <= 0:
            if self._active_trailing_sl_per_gram is not None:
                self._active_trailing_sl_per_gram = None
            return

        profit_per_gram = current_price_per_gram - cost_basis

        # กฎ 1: เลื่อน SL บังทุน
        if profit_per_gram >= self.config.trailing_stop_profit_trigger:
            new_sl = cost_basis + self.config.trailing_stop_lock_in

            if (
                self._active_trailing_sl_per_gram is None
                or new_sl > self._active_trailing_sl_per_gram
            ):
                self._active_trailing_sl_per_gram = new_sl
                self._persist_trailing_stop(new_sl)
                self.log(
                    f"🔼 Trailing SL raised to {new_sl:.2f} ฿/g "
                    f"(profit={profit_per_gram:.2f} ฿/g)"
                )

            # [v3.1] แค่ set flag — ไม่ execute_emergency_sell
            if current_price_per_gram <= self._active_trailing_sl_per_gram:
                self.log(
                    f"🚩 Trailing SL hit @ {self._active_trailing_sl_per_gram:.2f} ฿/g "
                    f"— flagging for strategy evaluation"
                )
                self._sl_triggered = (
                    f"Trailing Stop @ {self._active_trailing_sl_per_gram:.2f} ฿/g"
                )

        # กฎ 2: Hard Stop Loss — [v3.1] แค่ set flag เช่นกัน
        elif profit_per_gram <= -self.config.hard_stop_loss_per_gram:
            self.log(
                f"🚩 Hard SL hit (loss={profit_per_gram:.2f} ฿/g) "
                f"— flagging for strategy evaluation"
            )
            self._sl_triggered = f"Hard Stop Loss (loss={profit_per_gram:.2f} ฿/g)"

    def _persist_trailing_stop(self, new_sl_per_gram: float) -> None:
        """บันทึก trailing SL ลง DB"""
        try:
            portfolio = self.analysis_service.persistence.get_portfolio()
            portfolio["trailing_stop_level_thb"] = round(new_sl_per_gram, 4)
            self.analysis_service.persistence.save_portfolio(portfolio)
        except Exception as e:
            self.log(f"⚠️ Could not persist trailing SL: {e}", "ERROR")

    # ── Emergency Sell ────────────────────────────────────────────────────────

    def _execute_emergency_sell(
        self,
        grams_to_sell: float,
        price_thb_per_gram: float,
        reason: str,
    ) -> None:
        """
        Atomic: trade_log INSERT + portfolio UPDATE ใน transaction เดียว
        [v3.1] เรียกจาก AI decision เท่านั้น — ไม่ถูกเรียกอัตโนมัติจาก engine อีกต่อไป
        """
        self.log(
            f"🛒 Emergency SELL: {grams_to_sell:.4f}g "
            f"@ {price_thb_per_gram:.2f} ฿/g | Reason: {reason}"
        )
        try:
            # broker_api.sell(grams_to_sell, price_thb_per_gram)  # uncomment เมื่อพร้อม

            self.analysis_service.persistence.record_emergency_sell_atomic(
                grams=grams_to_sell,
                price_per_gram=price_thb_per_gram,
                reason=reason,
            )
            self._active_trailing_sl_per_gram = None
            self.log("✅ Emergency sell recorded atomically in DB")

        except Exception as e:
            self.log(
                f"🔥 CRITICAL: Emergency sell DB write failed: {e} "
                f"— Manual reconciliation required!",
                "ERROR",
            )

    # ── Trigger Analysis ──────────────────────────────────────────────────────

    def _trigger_analysis(self) -> None:
        """ปลุก AI ผ่าน AnalysisService"""
        try:
            result = self.analysis_service.run_analysis(
                provider=self.config.provider,
                period=self.config.period,
                intervals=[self.config.interval],
                bypass_session_gate=False,
            )

            if result.get("status") != "success":
                self.log(
                    f"⚠️ AI analysis error: {result.get('error', 'unknown')}",
                    "ERROR",
                )
                return

            voting = result.get("voting_result", {})
            decision = voting.get("final_signal", "UNKNOWN")
            conf = voting.get("weighted_confidence", 0.0)
            run_id = result.get("run_id")

            self.log(
                f"🎯 AI Decision: {decision} ({conf:.0%} confidence) | run_id={run_id}"
            )

            self._on_ai_decision(decision, conf, result)

        except Exception as e:
            self.log(f"❌ AI Analysis Failed: {e}", "ERROR")

    def _on_ai_decision(
        self,
        decision: str,
        confidence: float,
        full_result: dict,
    ) -> None:
        """
        Hook สำหรับ action หลัง AI ตัดสิน
        Uncomment / implement เมื่อพร้อม auto-execute:
            if decision == "BUY" and confidence >= 0.75:
                broker_api.place_order("BUY", grams=0.5)
            elif decision == "SELL" and confidence >= 0.75:
                portfolio = self.analysis_service.persistence.get_portfolio()
                self._execute_emergency_sell(
                    grams_to_sell      = float(portfolio.get("gold_grams", 0)),
                    price_thb_per_gram = ...,
                    reason             = f"AI SELL decision ({confidence:.0%})",
                )
        """
        self.log(
            f"📬 _on_ai_decision: {decision} ({confidence:.0%}) "
            f"— broker hook not yet implemented"
        )
