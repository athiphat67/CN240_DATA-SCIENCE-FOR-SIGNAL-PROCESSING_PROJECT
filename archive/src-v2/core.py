"""
core.py — Core Decision (fan-out → fan-in)
==========================================

ตัวกลางระหว่าง XGBoost signal และ gates ทั้งสอง

หน้าที่:
    1. รับ (signal, confidence, market_state) จาก signal.py
    2. ถ้าสัญญาณเป็น HOLD → bypass gates
    3. ถ้าเป็น BUY/SELL → รัน risk.py และ session_gate.py แบบ concurrent
       (ThreadPoolExecutor max_workers=2)
    4. รวมผล:
         - ALL PASS  → คงสัญญาณเดิม + notify=True
         - any REJECT → บังคับเป็น HOLD + notify=False
    5. คืน `Decision` ให้ main.py ส่งต่อไปยัง notification + database

สถาปัตยกรรมนี้สอดคล้องกับ Src_V2/about-main.md (Section 8)
และไม่มีส่วนใดเกี่ยวข้องกับ Generative Models / Agent loops

--- Changelog ---

[v1.1 — bugfix batch]

  FIX-1  _eval_session_gate ส่ง naive datetime.now() ให้ resolve_session_gate()
         ปัญหา: resolve_session_gate() รับ naive datetime แล้ว ใช้ .replace(tzinfo=...)
                ซึ่งแค่ "ติดฉลาก" timezone โดยไม่แปลงเวลา
                → ถ้า server อยู่ใน UTC (เช่น production container) session window
                  จะคำนวณผิดไป 7 ชั่วโมง ทำให้ gate block สัญญาณในเวลาที่ควรเทรดได้
         แก้:  ส่ง datetime.now(ZoneInfo("Asia/Bangkok")) ซึ่งเป็น tz-aware ที่ถูกต้อง
               มี fallback สำหรับ Python < 3.9 ที่ไม่มี zoneinfo (ส่ง None → resolve ดึงเอง)

  FIX-2  เพิ่ม _BKK_TZ module-level constant เพื่อ import ZoneInfo ครั้งเดียว
         และ guard ImportError สำหรับ Python < 3.9
"""

from __future__ import annotations

import concurrent.futures as cf
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    _BKK_TZ = ZoneInfo("Asia/Bangkok")
except ImportError:  # pragma: no cover
    _BKK_TZ = None  # type: ignore

from ml_core.risk import RiskManager
from ml_core.session_gate import SessionGateResult, resolve_session_gate

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Public dataclass — ผลลัพธ์ที่ main.py จะนำไปใช้
# ─────────────────────────────────────────────────────────────


@dataclass
class Decision:
    """ผลการตัดสินใจสุดท้ายหลังผ่าน Core + Gates"""

    final: str                                  # "BUY" | "SELL" | "HOLD"
    model_signal: str                           # signal ดิบจาก XGBoost (ก่อน gate)
    confidence: float                           # 0.0–1.0

    entry_price: Optional[float] = None         # THB/baht-weight (NULL ถ้า HOLD)
    stop_loss:   Optional[float] = None
    take_profit: Optional[float] = None
    position_size_thb: float = 0.0

    rationale: str = ""
    reject_reason: Optional[str] = None
    notify: bool = False                        # True เฉพาะ ALL PASS

    # Snapshot ของ session ณ เวลาตัดสินใจ
    session_info: Dict[str, Any] = field(default_factory=dict)

    def to_persist_dict(self) -> Dict[str, Any]:
        """แปลงเป็น dict สำหรับส่งให้ RunDatabase.save_run()"""
        return {
            "signal":        self.final,
            "confidence":    float(self.confidence),
            "entry_price":   self.entry_price,
            "stop_loss":     self.stop_loss,
            "take_profit":   self.take_profit,
            "position_size_thb": self.position_size_thb,
            "rationale":     self.rationale or self.reject_reason or "",
            "rejection_reason": self.reject_reason,
            "model_signal":  self.model_signal,
            "iterations_used": 0,
            "tool_calls_used": 0,
        }


# ─────────────────────────────────────────────────────────────
# Internal gate result types
# ─────────────────────────────────────────────────────────────


@dataclass
class _GateResult:
    """ผลร่วมของ gate ตัวใดตัวหนึ่ง"""

    passed: bool
    reason: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None


# ─────────────────────────────────────────────────────────────
# CoreDecision — fan-out / fan-in coordinator
# ─────────────────────────────────────────────────────────────


class CoreDecision:
    """
    Coordinator ที่รัน Risk gate + Session gate ขนานกัน
    แล้วรวมผลให้เป็น `Decision`
    """

    GATE_TIMEOUT_SEC: float = 2.0

    def __init__(
        self,
        risk_manager: RiskManager,
        *,
        gate_timeout_sec: Optional[float] = None,
    ) -> None:
        self.risk = risk_manager
        if gate_timeout_sec is not None:
            self.GATE_TIMEOUT_SEC = float(gate_timeout_sec)

    # ── Public API ───────────────────────────────────────────

    def evaluate(
        self,
        signal: str,
        confidence: float,
        market_state: Dict[str, Any],
        *,
        rationale: str = "",
    ) -> Decision:
        """
        ประเมินสัญญาณผ่าน gate ทั้งสอง

        Parameters
        ----------
        signal      : "BUY" | "SELL" | "HOLD" จาก XGBoost
        confidence  : 0.0–1.0 จาก XGBoost.predict_proba()
        market_state: snapshot จาก orchestrator.run()
        rationale   : ข้อความเสริม (optional)
        """
        signal_norm = (signal or "HOLD").upper().strip()
        conf_safe = max(0.0, min(1.0, float(confidence)))

        # ── Fast path: HOLD ไม่ต้องเสียเวลาเรียก gate ─────────
        if signal_norm == "HOLD":
            logger.info("🟡[Core] Model said HOLD — skipping gates")
            return Decision(
                final="HOLD",
                model_signal="HOLD",
                confidence=conf_safe,
                rationale=rationale or "model_hold",
                reject_reason=None,
                notify=False,
            )

        # ── Concurrent gate evaluation ───────────────────────
        risk_res, session_res = self._run_gates_concurrent(
            signal_norm, conf_safe, market_state, rationale
        )

        all_pass = risk_res.passed and session_res.passed

        if not all_pass:
            reasons = [r for r in (risk_res.reason, session_res.reason) if r]
            reject_reason = " | ".join(reasons) if reasons else "gate_rejected"
            logger.info(" 🔴 [Core] Gate REJECTED %s → HOLD (%s)", signal_norm, reject_reason)
            return Decision(
                final="HOLD",
                model_signal=signal_norm,
                confidence=conf_safe,
                rationale=rationale,
                reject_reason=reject_reason,
                notify=False,
                session_info=(session_res.payload or {}),
            )

        # ── ALL PASS — คงสัญญาณเดิม + ดึงค่า SL/TP จาก risk ───
        risk_payload = risk_res.payload or {}
        return Decision(
            final=signal_norm,
            model_signal=signal_norm,
            confidence=conf_safe,
            entry_price=risk_payload.get("entry_price"),
            stop_loss=risk_payload.get("stop_loss"),
            take_profit=risk_payload.get("take_profit"),
            position_size_thb=float(risk_payload.get("position_size_thb", 0.0) or 0.0),
            rationale=risk_payload.get("rationale") or rationale,
            reject_reason=None,
            notify=True,
            session_info=(session_res.payload or {}),
        )

    # ── Internal: concurrent runner ──────────────────────────

    def _run_gates_concurrent(
        self,
        signal: str,
        confidence: float,
        market_state: Dict[str, Any],
        rationale: str,
    ) -> tuple[_GateResult, _GateResult]:
        """รัน gate ทั้งสองขนานกันด้วย ThreadPoolExecutor (2 workers)"""
        with cf.ThreadPoolExecutor(max_workers=2, thread_name_prefix="core-gate") as ex:
            f_risk = ex.submit(
                self._eval_risk_gate, signal, confidence, market_state, rationale
            )
            f_session = ex.submit(self._eval_session_gate, confidence, market_state)

            try:
                risk_res = f_risk.result(timeout=self.GATE_TIMEOUT_SEC)
            except cf.TimeoutError:
                logger.error("🔴 [Core] Risk gate timed out (>%ss)", self.GATE_TIMEOUT_SEC)
                risk_res = _GateResult(passed=False, reason="risk_gate_timeout")

            try:
                session_res = f_session.result(timeout=self.GATE_TIMEOUT_SEC)
            except cf.TimeoutError:
                logger.error("🔴[Core] Session gate timed out (>%ss)", self.GATE_TIMEOUT_SEC)
                session_res = _GateResult(passed=False, reason="session_gate_timeout")

        return risk_res, session_res

    # ── Gate adapters ────────────────────────────────────────

    def _eval_risk_gate(
        self,
        signal: str,
        confidence: float,
        market_state: Dict[str, Any],
        rationale: str,
    ) -> _GateResult:
        """
        เรียก RiskManager.evaluate() ซึ่งคืน dict
        ถ้า rejection_reason ไม่ใช่ None → REJECT
        """
        try:
            decision_input = {
                "signal":         signal,
                "confidence":     confidence,
                "market_context": rationale,
                "position_size_thb": 0.0,
                "execution_check": {"is_spread_covered": True},
            }
            result = self.risk.evaluate(decision_input, market_state)
        except Exception as exc:  # pragma: no cover - safety
            logger.exception("🔴[Core] RiskManager raised: %s", exc)
            return _GateResult(passed=False, reason=f"risk_error:{exc}")

        rej = result.get("rejection_reason")
        if rej:
            return _GateResult(passed=False, reason=str(rej), payload=result)

        # บางกรณี RiskManager downgrade เป็น HOLD โดยไม่ตั้ง rejection_reason
        if str(result.get("signal", "HOLD")).upper() != signal:
            return _GateResult(
                passed=False,
                reason=f"risk_downgrade_to_{result.get('signal')}",
                payload=result,
            )

        return _GateResult(passed=True, reason=None, payload=result)

    def _eval_session_gate(
        self, confidence: float, market_state: Dict[str, Any]
    ) -> _GateResult:
        """
        เรียก resolve_session_gate() แล้วแปลงเป็น pass/reject:
            - apply_gate == False → outside window / dead zone → REJECT
            - confidence < suggested_min_confidence → REJECT
        ผลลัพธ์ payload เก็บ session info เพื่อใช้ส่งต่อ

        [BUGFIX] ส่ง timezone-aware datetime (Asia/Bangkok) แทน naive datetime.now()
        resolve_session_gate ใช้ .replace(tzinfo=...) กับ naive dt ซึ่งแค่ "ติดฉลาก"
        โดยไม่ convert — ถ้า system clock เป็น UTC จะทำให้ session window ผิดทั้งหมด
        """
        try:
            if _BKK_TZ is not None:
                now_bkk = datetime.now(_BKK_TZ)
            else:
                # fallback: Python < 3.9 ที่ไม่มี zoneinfo
                # resolve_session_gate จะดึง tz เองผ่าน _now_local()
                now_bkk = None  # type: ignore
            res: SessionGateResult = resolve_session_gate(now=now_bkk)
        except Exception as exc:  # pragma: no cover - safety
            logger.exception("🔴[Core] resolve_session_gate raised: %s", exc)
            return _GateResult(passed=False, reason=f"session_error:{exc}")

        payload = res.to_market_dict()

        if not res.apply_gate:
            return _GateResult(
                passed=False,
                reason="outside_session_or_dead_zone",
                payload=payload,
            )

        threshold = res.suggested_min_confidence or 0.0
        if confidence + 1e-9 < threshold:
            return _GateResult(
                passed=False,
                reason=f"confidence_below_session_min({confidence:.2f}<{threshold:.2f},{res.llm_mode})",
                payload=payload,
            )

        return _GateResult(passed=True, reason=None, payload=payload)