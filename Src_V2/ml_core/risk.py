"""
agent_core/core/risk.py  — Scalping Edition (V5 WinRate Focus)
Changes from V4:
  - atr_multiplier:      1.5  → 2.5   (ให้ trade หายใจได้มากขึ้น ลด SL โดนก่อน TP)
  - risk_reward_ratio:   2.0  → 1.5   (TP ใกล้ขึ้น hit ง่ายขึ้น → win rate เพิ่ม)
  - max_trade_risk_pct:  0.30 → 0.20  (ลด exposure ต่อ trade)
  - Trailing Stop:       เริ่มทันที → เริ่มหลังราคาขึ้น 1.0x ATR จาก entry
                         (ไม่ตัดกำไรก่อนที่ trade จะได้ "วิ่ง")

[BUGFIX v5.1] แก้ __init__ default values ให้ตรงกับ V5 spec ที่ระบุใน docstring:
  - atr_multiplier:     0.5  → 2.5   (ค่าเดิมทำให้ SL แคบมาก โดนตีออกง่าย)
  - risk_reward_ratio:  1.0  → 1.5   (ค่าเดิมทำให้ TP ชิดเกิน ไม่คุ้มความเสี่ยง)
  - max_trade_risk_pct: 1.00 → 0.20  (ค่าเดิม = risk ทุนทั้งหมดได้ — อันตรายมาก)
"""

import logging
import threading
from copy import deepcopy
from datetime import datetime  # ✅ [FIX] เพิ่มเพื่อใช้ดึงวันที่ให้ trade_date

logger = logging.getLogger(__name__)

GRAMS_PER_BAHT_WEIGHT: float = 15.244
TROY_OUNCE_GRAMS: float = 31.1035
THAI_GOLD_PURITY: float = 0.965

# ── Profit/Loss Thresholds ─────────────────────────────────────────────────────
# ยอมขาดทุนได้ไม่เกินนี้ (บาท) — ถ้าขาดทุนมากกว่านี้รอให้ราคาขึ้นก่อน
ACCEPTABLE_LOSS_THB: float = 2.0

# HuaSengHeng spread ประมาณ 150-300 บาท/บาทน้ำหนัก ใช้ 200 เป็น default
SPREAD_PER_BAHT_WEIGHT: float = 200.0

# ── Force Trade Timing (นาที ก่อนหมด session) ────────────────────────────────
FORCE_SELL_THRESHOLD_MIN: int = 10   # ถ้าถือของอยู่ → force SELL
FORCE_BUY_THRESHOLD_MIN:  int = 25   # ถ้ายังไม่ได้ทำรอบ → force BUY (เหลือเวลาพอ sell ใน cycle ถัดไป)

# ── Trailing Stop Activation Threshold ────────────────────────────────────────
TRAILING_ACTIVATION_ATR_MULTIPLE: float = 1.0


class RiskManager:
    def __init__(
        self,
        atr_multiplier: float = 2.5,             # [V5] 1.5 → 2.5: SL กว้างขึ้น ลด stop-out ก่อน TP
        risk_reward_ratio: float = 1.5,           # [V5] 2.0 → 1.5: TP ใกล้ขึ้น hit rate ดีขึ้น
        min_confidence: float = 0.6,              # BUY minimum
        min_sell_confidence: float = 0.6,         # SELL minimum — sync กับ roles.json
        min_trade_thb: float = 1000.0,
        micro_port_threshold: float = 2000.0,
        max_daily_loss_thb: float = 500.0,
        max_trade_risk_pct: float = 0.20,         # [V5] 0.30 → 0.20: ลด exposure ต่อ trade
        session_end_force_sell_minutes: int = 30,
        enable_trailing_stop: bool = True,
    ):
        self.atr_multiplier                 = atr_multiplier
        self.rr_ratio                       = risk_reward_ratio
        self.min_confidence                 = min_confidence
        self.min_sell_confidence            = min_sell_confidence
        self.min_trade_thb                  = min_trade_thb
        self.micro_port_threshold           = micro_port_threshold
        self.max_daily_loss_thb             = max_daily_loss_thb
        self.max_trade_risk_pct             = max_trade_risk_pct
        self.session_end_force_sell_minutes = session_end_force_sell_minutes
        self.enable_trailing_stop           = enable_trailing_stop

        self._daily_loss_accumulated: float = 0.0
        self._loss_lock = threading.Lock()
        self._daily_loss_date: str = ""

        # ── Trailing Stop State ───────────────────────────────────────────────
        self._active_trailing_sl: float = 0.0
        self._entry_price_thb: float = 0.0
        self._entry_atr: float = 0.0

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def record_trade_result(self, pnl_thb: float, trade_date: str) -> None:
        with self._loss_lock:
            if trade_date != self._daily_loss_date:
                self._daily_loss_accumulated = 0.0
                self._daily_loss_date = trade_date
            if pnl_thb < 0:
                self._daily_loss_accumulated += abs(pnl_thb)

    def evaluate(self, llm_decision: dict, market_state: dict) -> dict:
        signal         = llm_decision.get("signal", "HOLD").upper()
        confidence     = float(llm_decision.get("confidence", 0.0))
        market_context = llm_decision.get("market_context", "")

        portfolio      = market_state.get("portfolio", {})
        cash_balance   = float(portfolio.get("cash_balance", 0.0))
        gold_grams     = float(portfolio.get("gold_grams", 0.0))
        unrealized_pnl = float(portfolio.get("unrealized_pnl", 0.0))
        trades_today   = int(portfolio.get("trades_today", 0) or 0)

        summary = market_state.get("portfolio_summary", {})

        capital_mode = summary.get("mode", "normal")
        can_trade = summary.get("can_trade", True)
        holding = summary.get("holding", gold_grams > 0)
        profiting = summary.get("profit", unrealized_pnl > 0)

        try:
            thai_gold      = market_state["market_data"]["thai_gold_thb"]
            buy_price_thb  = float(thai_gold["sell_price_thb"])
            sell_price_thb = float(thai_gold["buy_price_thb"])
            atr_data       = market_state.get("technical_indicators", {}).get("atr", {}) or {}
            atr_value      = self._atr_to_thb_per_baht_gold(
                float(atr_data.get("value", 0) or 0),
                str(atr_data.get("unit", "") or ""),
                market_state,
            )
        except (KeyError, ValueError):
            return self._reject_signal({"rationale": market_context}, "Data Error")

        final_decision = {
            "signal": signal,
            "confidence": confidence,
            "entry_price": buy_price_thb if signal == "BUY" else (
                sell_price_thb if signal == "SELL" else None
            ),
            "position_size_thb": 0.0,
            "rationale": market_context,
            "rejection_reason": None,
        }

        # ================================================================
        # Gate 0a — Session Guard
        # ================================================================
        session_gate = market_state.get("session_gate", {})
        if session_gate.get("is_dead_zone") and signal == "BUY":
            return self._reject_signal(final_decision, "Dead Zone")

        # ================================================================
        # Gate 0b — Trailing Stop & TP/SL Hard Override [V5]
        # ================================================================
        if gold_grams <= 0:
            self._reset_trailing_state()
        else:
            tp_price    = float(portfolio.get("take_profit_price", 0.0) or 0.0)
            base_sl     = float(portfolio.get("stop_loss_price",   0.0) or 0.0)
            check_price = sell_price_thb if sell_price_thb > 0 else buy_price_thb

            if self._active_trailing_sl == 0.0:
                self._active_trailing_sl = base_sl

            if self.enable_trailing_stop and atr_value > 0 and self._entry_price_thb > 0:
                activation_price = (
                    self._entry_price_thb
                    + (self._entry_atr * TRAILING_ACTIVATION_ATR_MULTIPLE)
                )
                if check_price >= activation_price:
                    sl_distance  = max(
                        atr_value * self.atr_multiplier,
                        check_price * 0.0007,
                    )
                    potential_sl = check_price - sl_distance
                    if potential_sl > self._active_trailing_sl:
                        self._active_trailing_sl = potential_sl
                        final_decision["stop_loss"] = round(self._active_trailing_sl, 2)
                        logger.debug(f"[TrailingSL] Activated & moved to ฿{self._active_trailing_sl:,.2f}")
                else:
                    logger.debug(f"[TrailingSL] Waiting: price ฿{check_price:,.0f} < activation ฿{activation_price:,.0f}")

            override_reason = None
            if tp_price > 0 and check_price >= tp_price:
                override_reason = f"TP hit: ฿{check_price:,.0f}"
            elif self._active_trailing_sl > 0 and check_price <= self._active_trailing_sl:
                override_reason = f"Trailing SL hit: ฿{check_price:,.0f} (SL=฿{self._active_trailing_sl:,.0f})"

            if override_reason:
                final_decision["signal"]     = "SELL"
                final_decision["confidence"] = 1.0
                final_decision["rationale"]  = f"[SYSTEM OVERRIDE] {override_reason}"
                signal = "SELL"
                self._reset_trailing_state()

        # ================================================================
        # Gate 1 & 1.5 — Confidence Filter & Capital Protection
        # ================================================================
        if signal == "BUY":
            if final_decision["confidence"] < self.min_confidence:
                return self._reject_signal(final_decision, f"BUY conf ({final_decision['confidence']:.2f}) < {self.min_confidence}")

            quota = market_state.get("execution_quota", {}) or {}
            min_entries_by_now = int(quota.get("min_entries_by_now", 0) or 0)
            required_conf_next = float(quota.get("required_confidence_for_next_buy", self.min_confidence) or self.min_confidence)

            if trades_today < min_entries_by_now and confidence < required_conf_next:
                return self._reject_signal(final_decision, f"ตาม scheduler ยังไม่ทัน และ conf ({confidence:.2f}) < {required_conf_next:.2f}")

            execution_check = llm_decision.get("execution_check", {}) or {}
            if execution_check.get("is_spread_covered") is False:
                return self._reject_signal(final_decision, "LLM ระบุว่ายังไม่ครอบคลุม spread")

            htf = market_state.get("pre_fetched_tools", {}).get("get_htf_trend", {})
            htf_trend = str(htf.get("trend", "")).lower() if isinstance(htf, dict) else ""
            if "bear" in htf_trend and confidence < 0.75:
                return self._reject_signal(final_decision, f"HTF bearish ({htf.get('trend')}) — BUY ต้อง conf >= 0.75")

            spread_thb = max(0.0, buy_price_thb - sell_price_thb)
            market_data = market_state.get("market_data", {})
            spread_cov = market_data.get("spread_coverage", {}) if isinstance(market_data, dict) else {}
            expected_move_thb = float(spread_cov.get("expected_move_thb", 0.0) or 0.0)
            effective_spread = float(spread_cov.get("effective_spread", spread_thb) or spread_thb)
            used_spread_fallback = False
            if effective_spread <= 0:
                effective_spread = spread_thb
                used_spread_fallback = True
            edge_score = float(spread_cov.get("edge_score", 0.0) or 0.0)
            if used_spread_fallback and effective_spread > 0 and expected_move_thb > 0:
                edge_score = expected_move_thb / effective_spread

            if effective_spread > 0 and expected_move_thb <= 0:
                # [BUG 1 FIX] ใช้ ATR เป็น expected move หลัก (น่าเชื่อถือกว่า trend_pct)
                # ATR ทองไทยทั่วไป ~300-500 THB สะท้อน volatility จริง
                # trend_pct 0.1% × 42000 = 42 THB < spread 200 THB เสมอ → edge_score < 1.0 ทุกครั้ง
                if atr_value > 0:
                    expected_move_thb = atr_value
                else:
                    trend_pct = abs(float((market_data.get("price_trend", {}) or {}).get("change_pct", 0.0) or 0.0))
                    expected_move_thb = buy_price_thb * (trend_pct / 100.0)
                edge_score = expected_move_thb / effective_spread if effective_spread > 0 else 0.0

            if effective_spread > 0 and edge_score < 1.0:
                return self._reject_signal(final_decision, f"Edge ไม่พอชนะ spread (edge={edge_score:.2f})")

            if not can_trade:
                return self._reject_signal(final_decision, "เงินคงเหลือต่ำกว่าเกณฑ์ขั้นต่ำ")

            if capital_mode == "critical" and confidence < 0.76:
                return self._reject_signal(final_decision, "ทุน critical ต้อง BUY conf >= 0.76")
            if capital_mode == "defensive" and confidence < 0.68:
                return self._reject_signal(final_decision, "ทุน defensive ต้อง BUY conf >= 0.68")
            
            if holding and profiting and confidence < 0.74:
                return self._reject_signal(final_decision, "มีกำไรอยู่แล้ว BUY เพิ่มต้อง conf >= 0.74")
            if holding and not profiting and confidence < 0.80:
                return self._reject_signal(final_decision, "มีของขาดทุนอยู่ ไม่ถัวเพิ่มถ้า conf < 0.80")

        elif signal == "SELL":
            if final_decision["confidence"] < self.min_sell_confidence:
                return self._reject_signal(final_decision, f"SELL conf ({final_decision['confidence']:.2f}) < {self.min_sell_confidence}")

        # ================================================================
        # Gate 2 — Daily Loss Limit
        # ================================================================
        # ✅[FIX] กำหนดวันที่ปัจจุบันก่อนส่งเข้าฟังก์ชันเพื่อแก้ปัญหา NameError
        trade_date = datetime.now().strftime("%Y-%m-%d")
        
        if signal != "HOLD":
            self._reset_daily_loss_if_new_day(trade_date)
            if self._daily_loss_accumulated >= self.max_daily_loss_thb and signal == "BUY":
                return self._reject_signal(final_decision, "Loss limit")

        # ================================================================
        # Gate 3 — Signal Processing & Dynamic Sizing
        # ================================================================
        if signal == "BUY":
            if cash_balance < self.min_trade_thb:
                return self._reject_signal(final_decision, "Low Cash")

            # [BUG 2 FIX] session_gate ใช้ key "quota_urgent" ไม่ใช่ "near_session_end"
            near_end    = session_gate.get("quota_urgent", False)
            # [BUG 3 FIX] session_gate ไม่ได้ set "trades_this_session"
            # ใช้ trades_today จาก portfolio ซึ่งมีค่าจริงเสมอ
            trades_done = trades_today

            # ── [v4.0] Force BUY near session end ───────────────────────────
            # ถ้าเหลือเวลาน้อย + ยังไม่ได้ทำรอบ → บังคับซื้อ ข้าม confidence check
            mins_left_buy = int(session_gate.get("minutes_to_session_end", 999) or 999)
            session_quota_buy = session_gate.get("session_quota", {}) or {}
            session_rounds_buy = int(session_quota_buy.get("rounds_done", 0) or 0)
            is_force_buy = (
                mins_left_buy <= FORCE_BUY_THRESHOLD_MIN
                and session_rounds_buy == 0
                and not (session_quota_buy.get("has_open_position", False))
            )
            if is_force_buy:
                logger.warning(
                    "[RiskManager] FORCE BUY — %d min left, rounds_done=%d",
                    mins_left_buy, session_rounds_buy,
                )
                final_decision["rationale"] = (
                    f"[SESSION FORCE BUY] เหลือ {mins_left_buy} นาที ยังไม่ได้ทำรอบ → บังคับซื้อ"
                )
                # ข้าม confidence check ทั้งหมด ไปที่ sizing โดยตรง
                is_forced = True
            else:
                is_forced = near_end and (trades_done < 2)

            # ✅[FIX] นำ Logic การดึง Position Size ของ LLM ที่เคยเป็น Dead Code มารวมไว้ตรงนี้
            llm_suggested_size = float(llm_decision.get("position_size_thb") or 0.0)
            quota = market_state.get("execution_quota", {}) or {}
            recommended_size = float(quota.get("recommended_next_position_thb", self.min_trade_thb) or self.min_trade_thb)

            if is_forced:
                investment_thb = self.min_trade_thb
                logger.warning("Forced Trade for quota - using min size.")
            else:
                base_investment = llm_suggested_size if llm_suggested_size > 0 else recommended_size
                
                # คำนวณ size ตามความเสี่ยงและ confidence
                calculated_size = min(
                    base_investment,
                    (cash_balance * self.max_trade_risk_pct) * confidence
                )
                
                # [FIX] บังคับให้ size ไม่ต่ำกว่าขั้นต่ำของออม NOW (1000 บาท)
                investment_thb = max(self.min_trade_thb, calculated_size)

            # เช็คเงินสดอีกรอบเพื่อความชัวร์
            if cash_balance < investment_thb:
                # ถ้าคำนวณแล้วเกินเงินสดที่มี ให้เทหมดหน้าตัก (เรารู้ว่า cash >= 1000 แน่นอนจากด่านบน)
                investment_thb = cash_balance

            if investment_thb < self.min_trade_thb:
                return self._reject_signal(
                    final_decision,
                    f"Position size ต่ำเกินไป ({investment_thb:.2f} THB < min {self.min_trade_thb:.0f} THB)"
                )

            if cash_balance < investment_thb:
                return self._reject_signal(final_decision, f"เงินสดไม่พอ ({cash_balance:.2f} < {investment_thb:.2f})")

            if atr_value <= 0:
                atr_value = buy_price_thb * 0.003
                logger.warning(f"[RiskManager] ATR=0 → fallback atr={atr_value:.0f} (0.3% of price)")

            # คำนวณ TP / SL
            min_move = buy_price_thb * 0.0007
            sl_distance = max(atr_value * self.atr_multiplier, min_move)
            tp_distance = max(sl_distance * self.rr_ratio, min_move)

            final_decision["entry_price"]        = buy_price_thb
            final_decision["position_size_thb"]  = round(investment_thb, 2)
            final_decision["stop_loss"]          = round(buy_price_thb - sl_distance, 2)
            final_decision["take_profit"]        = round(buy_price_thb + tp_distance, 2)
            
            pass

            # [V5] บันทึก entry state สำหรับ trailing stop activation
            self._active_trailing_sl = 0.0
            self._entry_price_thb    = buy_price_thb
            self._entry_atr          = atr_value

            logger.info(
                "[RiskManager] → BUY entry=%.0f SL=%.0f TP=%.0f (ATR×%.1f / RR×%.1f)",
                buy_price_thb, final_decision["stop_loss"], final_decision["take_profit"],
                self.atr_multiplier, self.rr_ratio,
            )
            return final_decision

        elif signal == "SELL":
            if holding and profiting:
                logger.info("[RiskManager] SELL while profitable position → prioritize profit protection")

            if gold_grams <= 1e-4:
                return self._reject_signal(final_decision, "ไม่มีทองเพียงพอสำหรับการขาย")

            # ── [v4.0] Dynamic MIN_PROFIT_FILTER ─────────────────────────────
            # ยอมขาดทุนได้ไม่เกิน ACCEPTABLE_LOSS_THB (2 บาท)
            # ยอมกำไรได้ทุกกรณี (pnl >= 0 หรือมากกว่า)
            # คิด spread cost จริงเพื่อรู้ว่า breakeven อยู่ที่ไหน
            spread_cost_thb = gold_grams * (SPREAD_PER_BAHT_WEIGHT / GRAMS_PER_BAHT_WEIGHT)
            # min_sell_pnl = จุดที่ยอมรับได้ = -(spread_cost + ACCEPTABLE_LOSS)
            # แปลว่า: ยอมให้ขาดทุนได้ถึง spread + 2 บาท (รวมค่า spread ที่หลีกเลี่ยงไม่ได้)
            min_sell_pnl = -(spread_cost_thb + ACCEPTABLE_LOSS_THB)

            # ── [v4.0] Force SELL near session end ───────────────────────────
            # ถ้าเหลือเวลาน้อย + ยังไม่ได้ทำรอบ → บังคับปิด ข้าม profit filter
            mins_left = int(session_gate.get("minutes_to_session_end", 999) or 999)
            session_quota = session_gate.get("session_quota", {}) or {}
            session_rounds_done = int(session_quota.get("rounds_done", 0) or 0)
            is_force_close = (
                mins_left <= FORCE_SELL_THRESHOLD_MIN
                and session_rounds_done == 0
            )

            current_rationale = final_decision.get("rationale", "")
            is_override = any(msg in current_rationale for msg in ["[SYSTEM OVERRIDE]", "[SESSION FORCE SELL]"])

            if is_force_close and not is_override:
                # บังคับปิด — ติด tag ให้รู้ว่า force
                final_decision["rationale"] = (
                    f"[SESSION FORCE SELL] เหลือ {mins_left} นาที ยังไม่ครบรอบ session"
                )
                logger.warning(
                    "[RiskManager] FORCE SELL — %d min left, rounds_done=%d",
                    mins_left, session_rounds_done,
                )
            elif not is_override:
                # ตรวจ pnl ปกติ
                if unrealized_pnl < min_sell_pnl:
                    return self._reject_signal(
                        final_decision,
                        f"ขาดทุน {unrealized_pnl:.2f} THB เกินเกณฑ์ยอมรับ {min_sell_pnl:.2f} THB "
                        f"(spread={spread_cost_thb:.2f} + tolerance={ACCEPTABLE_LOSS_THB:.0f})"
                    )

            gold_value_thb = gold_grams * (sell_price_thb / 15.244)
            
            final_decision["entry_price"]       = sell_price_thb
            final_decision["position_size_thb"] = round(gold_value_thb, 2)

            pass

            logger.info(f"RiskManager Approved SELL: {gold_value_thb:.2f} THB")
            return final_decision

        return final_decision

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _atr_to_thb_per_baht_gold(self, atr_value: float, atr_unit: str, market_state: dict) -> float:
        if atr_value <= 0:
            return atr_value

        if atr_unit == "USD_PER_OZ":
            usd_thb = float(
                market_state.get("market_data", {})
                            .get("forex", {})
                            .get("usd_thb", 0.0) or 0.0
            )
            if usd_thb <= 0:
                logger.warning("[RiskManager] ATR unit is USD_PER_OZ but usd_thb is missing; using raw ATR")
                return atr_value
            return atr_value * usd_thb / TROY_OUNCE_GRAMS * GRAMS_PER_BAHT_WEIGHT * THAI_GOLD_PURITY

        if atr_unit and atr_unit != "THB_PER_BAHT_GOLD":
            logger.warning("[RiskManager] Unknown ATR unit '%s'; using raw ATR", atr_unit)

        return atr_value

    def _reset_trailing_state(self) -> None:
        self._active_trailing_sl = 0.0
        self._entry_price_thb    = 0.0
        self._entry_atr          = 0.0

    def _reset_daily_loss_if_new_day(self, trade_date: str) -> None:
        with self._loss_lock:
            if trade_date and trade_date != self._daily_loss_date:
                self._daily_loss_accumulated = 0.0
                self._daily_loss_date = trade_date

    def _reject_signal(self, decision: dict, reason: str) -> dict:
        safe = deepcopy(decision)
        safe["signal"]            = "HOLD"
        safe["stop_loss"]         = None
        safe["take_profit"]       = None
        safe["entry_price"]       = None
        safe["position_size_thb"] = 0.0
        safe["rejection_reason"]  = reason
        safe["rationale"]         = f"REJECTED: {reason} | เดิม: {safe.get('rationale', '')}"
        logger.info("[RiskManager] REJECTED: %s", reason)
        return safe
