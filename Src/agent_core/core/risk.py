"""
agent_core/core/risk.py  — Scalping Edition (V5 WinRate Focus)
Changes from V4:
  - atr_multiplier:      1.5  → 2.5   (ให้ trade หายใจได้มากขึ้น ลด SL โดนก่อน TP)
  - risk_reward_ratio:   2.0  → 1.5   (TP ใกล้ขึ้น hit ง่ายขึ้น → win rate เพิ่ม)
  - max_trade_risk_pct:  0.30 → 0.20  (ลด exposure ต่อ trade)
  - Trailing Stop:       เริ่มทันที → เริ่มหลังราคาขึ้น 1.0x ATR จาก entry
                         (ไม่ตัดกำไรก่อนที่ trade จะได้ "วิ่ง")
"""

import logging
import threading
from copy import deepcopy
from datetime import datetime  # ✅ [FIX] เพิ่มเพื่อใช้ดึงวันที่ให้ trade_date

logger = logging.getLogger(__name__)

GRAMS_PER_BAHT_WEIGHT: float = 15.244

# ── Trailing Stop Activation Threshold ────────────────────────────────────────
TRAILING_ACTIVATION_ATR_MULTIPLE: float = 1.0


class RiskManager:
    def __init__(
        self,
        atr_multiplier: float = 2.5,             # [V5] 0.5 → 2.5 (SL หายใจได้มากขึ้น)
        risk_reward_ratio: float = 1.5,           # [V5] 1.0 → 1.5 (TP ใกล้ขึ้น win rate เพิ่ม)
        min_confidence: float = 0.52,              # [V6] 0.55→0.52 ซื้อง่ายขึ้น ~5%
        min_sell_confidence: float = 0.52,         # [V6] sync กับ min_confidence
        min_trade_thb: float = 1000.0,
        micro_port_threshold: float = 2000.0,
        max_daily_loss_thb: float = 500.0,
        max_trade_risk_pct: float = 0.20,         # [V5] 1.00 → 0.20 (ลด exposure ต่อ trade)
        session_end_force_sell_minutes: int = 5,  # Emergency Session Mode: clear inventory in final 5 minutes
        session_end_force_buy_minutes: int = 20,  # [NEW] ถ้า trades ยังไม่ครบ → บังคับหา entry ก่อนหมด session
        min_trades_per_session: int = 3,          # [NEW] ขั้นต่ำต่อ session — ถ้าไม่ถึงจะ trigger force buy
        enable_trailing_stop: bool = True,
    ):
        self.atr_multiplier                  = atr_multiplier
        self.rr_ratio                        = risk_reward_ratio
        self.min_confidence                  = min_confidence
        self.min_sell_confidence             = min_sell_confidence
        self.min_trade_thb                   = min_trade_thb
        self.micro_port_threshold            = micro_port_threshold
        self.max_daily_loss_thb              = max_daily_loss_thb
        self.max_trade_risk_pct              = max_trade_risk_pct
        self.session_end_force_sell_minutes  = session_end_force_sell_minutes
        self.session_end_force_buy_minutes   = session_end_force_buy_minutes
        self.min_trades_per_session          = min_trades_per_session
        self.enable_trailing_stop            = enable_trailing_stop

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
            atr_value      = float(
                market_state.get("technical_indicators", {})
                            .get("atr", {})
                            .get("value", 0)
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
        # Gate 0c — Session End Force Sell [FIX Bug 2]
        # ================================================================
        session_gate = market_state.get("session_gate", {})
        mins_left = session_gate.get("minutes_to_session_end")
        trades_this_session = int(session_gate.get("trades_this_session", 0) or 0)
        _force_sell_active = bool(session_gate.get("is_emergency_sell")) or (
            gold_grams > 1e-4
            and mins_left is not None
            and mins_left <= self.session_end_force_sell_minutes
        )

        logger.debug(
            "[SessionGate keys] %s", list(session_gate.keys())
        )
        logger.debug(
            "[SessionGate] near_session_end=%s quota_urgent=%s trades_this_session=%s mins_left=%s",
            session_gate.get("near_session_end"),
            session_gate.get("quota_urgent"),
            trades_this_session,
            mins_left,
        )

        if _force_sell_active:
            final_decision["signal"]     = "SELL"
            final_decision["confidence"] = 1.0
            final_decision["entry_price"] = sell_price_thb
            final_decision["position_size_thb"] = 0.0
            final_decision["rationale"]  = (
                f"[SESSION FORCE SELL] Emergency exit with {mins_left} min left. "
                "SELL ALL before session end."
            )
            signal = "SELL"
            self._reset_trailing_state()
            logger.warning(
                "[RiskManager] Gate 0c SESSION FORCE SELL — %d min left (threshold=%d)",
                mins_left, self.session_end_force_sell_minutes,
            )

        # ================================================================
        # Gate 0d — Session End Force BUY hint [NEW]
        # ถ้ายังไม่มีทอง + trades ยังไม่ครบ quota + เวลาใกล้หมด → ลด threshold
        # ================================================================
        _force_buy_active = signal != "SELL" and (
            bool(session_gate.get("is_emergency_buy")) or (
                gold_grams <= 1e-4
                and mins_left is not None
                and mins_left <= self.session_end_force_buy_minutes
                and trades_this_session == 0
            )
        )
        if _force_buy_active:
            logger.warning(
                "[RiskManager] Gate 0d EMERGENCY FORCE BUY MODE — %s min left, trades=%d",
                mins_left, trades_this_session,
            )

        # ================================================================
        # Gate 0a — Session Guard
        # ================================================================
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
        # [FIX Bug 3] คำนวณ effective threshold ก่อนเช็คทุก gate
        session_suggested_conf = float(
            session_gate.get("suggested_min_confidence") or self.min_confidence
        )
        effective_min_conf = min(self.min_confidence, session_suggested_conf)
        is_quota_urgent = bool(session_gate.get("quota_urgent", False)) or _force_buy_active

        # ── [MTF Phase 4] Dynamic Regime-Based Risk Tuning ──────────────────────
        market_regime = str(market_state.get("market_regime", "UNKNOWN")).upper()
        _regime_rr_ratio = self.rr_ratio            # default
        _regime_atr_mult = self.atr_multiplier      # default

        if market_regime == "UPTREND":
            # ขาขึ้น: ลด threshold เพื่อตาม momentum ได้ทัน + TP กว้างขึ้นรันเทรนด์
            _regime_conf_adj = -0.04          # ลด 4% (เช่น 0.52 → 0.48)
            _regime_rr_ratio = 2.0            # TP ไกลขึ้น (RR 1:2)
            _regime_atr_mult = 2.5            # SL กว้างพอหายใจ
            effective_min_conf = max(0.45, effective_min_conf + _regime_conf_adj)
            logger.info(
                "[MTF Phase 4] UPTREND regime — relaxed conf=%.2f RR=%.1f ATR×%.1f",
                effective_min_conf, _regime_rr_ratio, _regime_atr_mult,
            )
        elif market_regime == "DOWNTREND":
            # ขาลง: เพิ่ม threshold กรองสัญญาณหลอก + SL/TP แคบสำหรับ rebound
            _regime_conf_adj = +0.13          # เพิ่ม 13% (เช่น 0.52 → 0.65)
            _regime_rr_ratio = 1.0            # TP สั้น (RR 1:1 พอ)
            _regime_atr_mult = 1.5            # SL แคบ ตัดเร็ว
            effective_min_conf = min(0.90, effective_min_conf + _regime_conf_adj)
            logger.info(
                "[MTF Phase 4] DOWNTREND regime — strict conf=%.2f RR=%.1f ATR×%.1f",
                effective_min_conf, _regime_rr_ratio, _regime_atr_mult,
            )
        elif market_regime == "SIDEWAYS":
            # ไซด์เวย์: threshold ปกติ + TP สั้น hit-and-run
            _regime_rr_ratio = 1.0            # เน้นรัด TP ให้โดนง่าย
            _regime_atr_mult = 2.0
            logger.info(
                "[MTF Phase 4] SIDEWAYS regime — normal conf=%.2f RR=%.1f ATR×%.1f",
                effective_min_conf, _regime_rr_ratio, _regime_atr_mult,
            )
        # UNKNOWN → ใช้ค่า default ไม่ปรับ

        if signal == "BUY":
            if gold_grams > 1e-4 or holding:
                return self._reject_signal(final_decision, "Already holding gold")
            if not _force_buy_active and final_decision["confidence"] < effective_min_conf:
                return self._reject_signal(
                    final_decision,
                    f"BUY conf ({final_decision['confidence']:.2f}) < {effective_min_conf:.2f} (effective threshold)"
                )
            if trades_today >= 3:
                return self._reject_signal(final_decision, f"ครบโควต้าซื้อรายวันแล้ว ({trades_today}/6)")

            quota = market_state.get("execution_quota", {}) or {}
            min_entries_by_now = int(quota.get("min_entries_by_now", 0) or 0)
            required_conf_next = float(quota.get("required_confidence_for_next_buy", self.min_confidence) or self.min_confidence)

            if not _force_buy_active and trades_today < min_entries_by_now and confidence < required_conf_next:
                return self._reject_signal(final_decision, f"ตาม scheduler ยังไม่ทัน และ conf ({confidence:.2f}) < {required_conf_next:.2f}")

            execution_check = llm_decision.get("execution_check", {}) or {}
            if execution_check.get("is_spread_covered") is False:
                if not _force_buy_active:
                    return self._reject_signal(final_decision, "LLM ระบุว่ายังไม่ครอบคลุม spread")
                logger.warning("[RiskManager] Emergency BUY bypassed LLM spread check")

            htf = market_state.get("pre_fetched_tools", {}).get("get_htf_trend", {})
            htf_trend = str(htf.get("trend", "")).lower() if isinstance(htf, dict) else ""
            if not _force_buy_active and "bear" in htf_trend and confidence < 0.67:
                return self._reject_signal(final_decision, f"HTF bearish ({htf.get('trend')}) — BUY ต้อง conf >= 0.67")

            spread_thb = max(0.0, buy_price_thb - sell_price_thb)
            market_data = market_state.get("market_data", {})
            spread_cov = market_data.get("spread_coverage", {}) if isinstance(market_data, dict) else {}
            expected_move_thb = float(spread_cov.get("expected_move_thb", 0.0) or 0.0)
            effective_spread = float(spread_cov.get("effective_spread", spread_thb) or spread_thb)
            edge_score = float(spread_cov.get("edge_score", 0.0) or 0.0)

            if effective_spread > 0 and expected_move_thb <= 0:
                # [FIX v11] fallback: ใช้ ATR ก่อน → candle % (sync กับ orchestrator.py)
                _atr_fallback = float(
                    (market_state.get("technical_indicators", {}) or {})
                    .get("atr", {}).get("value", 0) or 0
                )
                if _atr_fallback > 0:
                    expected_move_thb = _atr_fallback
                else:
                    trend_pct = abs(float((market_data.get("price_trend", {}) or {}).get("change_pct", 0.0) or 0.0))
                    expected_move_thb = buy_price_thb * (trend_pct / 100.0)
                edge_score = expected_move_thb / effective_spread if effective_spread > 0 else 0.0
                logger.debug("[RiskManager] fallback edge recalc: atr=%.0f expected=%.2f edge=%.4f",
                             _atr_fallback, expected_move_thb, edge_score)

            if effective_spread > 0 and edge_score < 0.8:
                # [FIX v11] threshold 1.0→0.8 (buffer สำหรับ ATR-based edge)
                # [FIX Bug 4] ยังอนุญาตได้ถ้าอยู่ใน quota urgent mode (ใกล้หมด session)
                if not is_quota_urgent:
                    return self._reject_signal(final_decision, f"เอ็จไม่พอชนะ spread (edge={edge_score:.2f})")
                else:
                    logger.warning(
                        "[RiskManager] Edge score %.2f < 1.0 — ยอมรับเพราะ quota urgent mode (mins_left=%s)",
                        edge_score, mins_left,
                    )

            if not can_trade:
                return self._reject_signal(final_decision, "เงินคงเหลือต่ำกว่าเกณฑ์ขั้นต่ำ")

            if not _force_buy_active and capital_mode == "critical" and confidence < 0.76:
                return self._reject_signal(final_decision, "ทุน critical ต้อง BUY conf >= 0.76")
            if not _force_buy_active and capital_mode == "defensive" and confidence < 0.68:
                return self._reject_signal(final_decision, "ทุน defensive ต้อง BUY conf >= 0.68")
            
            if not _force_buy_active and holding and profiting and confidence < 0.74:
                return self._reject_signal(final_decision, "มีกำไรอยู่แล้ว BUY เพิ่มต้อง conf >= 0.74")
            if not _force_buy_active and holding and not profiting and confidence < 0.80:
                return self._reject_signal(final_decision, "มีของขาดทุนอยู่ ไม่ถัวเพิ่มถ้า conf < 0.80")

        elif signal == "SELL" and final_decision["confidence"] < self.min_sell_confidence:
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
            if gold_grams > 1e-4 or holding:
                return self._reject_signal(final_decision, "Already holding gold")
            
            if cash_balance < self.min_trade_thb:
                return self._reject_signal(final_decision, "Low Cash")

            near_end    = session_gate.get("near_session_end", False)
            trades_done = session_gate.get("trades_this_session", 0)
            is_forced   = _force_buy_active or (near_end and (trades_done < 1))  # [V6] < 2 → < 1 (quota ลดเหลือ 3/วัน)

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

            # คำนวณ TP / SL — ใช้ค่าที่ปรับตาม Regime (Phase 4)
            min_move = buy_price_thb * 0.0007
            sl_distance = max(atr_value * _regime_atr_mult, min_move)
            tp_distance = max(sl_distance * _regime_rr_ratio, min_move)

            final_decision["entry_price"]        = buy_price_thb
            final_decision["position_size_thb"]  = round(investment_thb, 2)
            final_decision["stop_loss"]          = round(buy_price_thb - sl_distance, 2)
            final_decision["take_profit"]        = round(buy_price_thb + tp_distance, 2)
            
            final_decision["rationale"] = (
                f"{final_decision['rationale']}[RiskManager({market_regime}): ซื้อ {investment_thb:.0f}฿ "
                f"SL={final_decision['stop_loss']:,.0f} TP={final_decision['take_profit']:,.0f}]"
            )

            # [V5] บันทึก entry state สำหรับ trailing stop activation
            self._active_trailing_sl = 0.0
            self._entry_price_thb    = buy_price_thb
            self._entry_atr          = atr_value

            logger.info(
                "[RiskManager] → BUY entry=%.0f SL=%.0f TP=%.0f (ATR×%.1f / RR×%.1f) [regime=%s]",
                buy_price_thb, final_decision["stop_loss"], final_decision["take_profit"],
                _regime_atr_mult, _regime_rr_ratio, market_regime,
            )
            return final_decision

        elif signal == "SELL":
            if holding and profiting:
                logger.info("[RiskManager] SELL while profitable position → prioritize profit protection")

            if gold_grams <= 1e-4:
                return self._reject_signal(final_decision, "ไม่มีทองเพียงพอสำหรับการขาย")
            
            MIN_PROFIT_FILTER = 2.0  # [FIX v6] ลดจาก 10→2 THB — 10 THB สูงเกินไปสำหรับ position 1000 THB, ทำให้ไม่มีทางขายอัตโนมัติได้
            
            # ✅ [FIX] ดึงค่า final_decision["rationale"] มาเช็คเพื่อเลี่ยง NameError 
            current_rationale = final_decision.get("rationale", "")
            is_override = any(msg in current_rationale for msg in ["[SYSTEM OVERRIDE]", "[SESSION FORCE SELL]"])
            
            if not is_override:
                if unrealized_pnl > 0 and unrealized_pnl < MIN_PROFIT_FILTER:
                    return self._reject_signal(
                        final_decision, 
                        f"กำไร {unrealized_pnl:.2f} THB ยังไม่ถึงเกณฑ์ขั้นต่ำ {MIN_PROFIT_FILTER} THB (ไม่คุ้ม Spread)"
                    )

            gold_value_thb = gold_grams * (sell_price_thb / 15.244)
            
            final_decision["entry_price"]       = sell_price_thb
            final_decision["position_size_thb"] = round(gold_value_thb, 2)

            if not is_override:
                final_decision["rationale"] = (
                    f"{current_rationale}[RiskManager: ขาย {gold_grams:.4f}g ≈ {gold_value_thb:.2f} ฿]"
                )

            logger.info(f"RiskManager Approved SELL: {gold_value_thb:.2f} THB")
            return final_decision

        return final_decision

    # ─────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ─────────────────────────────────────────────────────────────────────────

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
