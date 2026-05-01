"""
main.py — นักขุดทอง v2 (XGBoost-based) Orchestration Loop
==========================================================

จุดเริ่มต้นของระบบ — ทำหน้าที่เป็น delegator ที่:
    1. Build runtime (orchestrator, signal engine, core, notifiers, db)
    2. ดึง market_state ผ่าน data_engine.GoldTradingOrchestrator
    3. แปลงเป็น 26-feature vector ผ่าน data_engine.extract_features.get_xgboost_feature_v2
    4. ส่งให้ ml_core.signal.XGBoostPredictor → (signal, confidence)
    5. ส่งให้ core.CoreDecision → fan-out ไป risk + session_gate (concurrent)
    6. ALL PASS  → ส่ง notification (Discord + Telegram) + บันทึก database
       REJECT/HOLD → ข้าม notification, แต่ยังบันทึก database เสมอ
    7. รอ interval (default 900s = 15 นาที) แล้ววนรอบใหม่

ระบบนี้ไม่มีส่วนใดเกี่ยวข้องกับ Generative Models / Agent loops
ทั้ง Decision Engine เป็น Pure ML (XGBoost) ตามสถาปัตยกรรม v2

ใช้งาน:
    python -m Src_V2.main                      # ใช้ default
    python Src_V2/main.py --interval 600       # รัน loop ทุก 10 นาที
    python Src_V2/main.py --no-save --once     # dry-run รอบเดียว

--- Changelog ---

[v2.2 — bugfix batch]

  FIX-1  session=Unknown ทุกรอบ (logic bug — ลำดับ resolve ผิด)
         ปัญหา: _resolve_session_label() อ่าน market_state["session_gate"]
                แต่ session_gate ถูก resolve ใน core.evaluate() ซึ่งเรียกทีหลัง
                ทำให้ XGBoost ได้รับ session="Unknown" ทุกรอบ
         แก้:  เพิ่ม resolve_session_gate() + attach_session_gate_to_market_state()
               ใน run_analysis_once() ก่อน _resolve_session_label() เสมอ
               → session label ถูกต้องตั้งแต่ step 1b แล้วส่งต่อ XGBoost และ CoreDecision
               Note: CoreDecision ยังคง resolve session ของตัวเองอยู่ (ไม่ใช้ค่านี้ซ้ำ)
               เพื่อป้องกัน clock drift ระหว่าง 2 รอบ

  FIX-2  NameError: top_features ไม่ถูก initialize ก่อน try block
         ปัญหา: top_features = getattr(xgb_out, ...) อยู่ใน try block
                ถ้า predict() throw exception → top_features ไม่มีค่า
                แต่โค้ดด้านล่าง (if top_features:) ใช้ตัวแปรนี้โดยตรง → NameError
         แก้:  เพิ่ม top_features: str = "" ก่อน try block

  FIX-3  _MockPredictor ใช้ _Stub() class แบบ dynamic — verbose และ brittle
         ปัญหา: _Stub class ถูก define ใน function scope ทุกครั้งที่เรียก predict()
                ไม่มี type hints, ลืม top_features field, ยาก debug
         แก้:  ใช้ types.SimpleNamespace แทน พร้อม attribute ครบตรงกับ XGBOutput
               (รวม top_features="") เพื่อป้องกัน AttributeError ในอนาคต

  FIX-4  import เพิ่ม resolve_session_gate และ attach_session_gate_to_market_state
         จาก ml_core.session_gate เพื่อรองรับ FIX-1
"""

from __future__ import annotations

import argparse
import logging
import os
import signal as _os_signal
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

# ── Path setup: ให้ import จาก Src_V2/* ทำงานได้ทั้งจาก root และ จากในโฟลเดอร์
_SELF_DIR = Path(__file__).resolve().parent
if str(_SELF_DIR) not in sys.path:
    sys.path.insert(0, str(_SELF_DIR))

# ── Domain imports (after sys.path tweak) ────────────────────
from core import CoreDecision, Decision  # noqa: E402
from data_engine.extract_features import get_xgboost_feature_v2  # noqa: E402
from data_engine.orchestrator import GoldTradingOrchestrator  # noqa: E402
from logs.api_logger import send_trade_log  # noqa: E402
from logs.logger_setup import sys_logger  # noqa: E402
from ml_core.risk import RiskManager  # noqa: E402
from ml_core.session_gate import (  # noqa: E402
    attach_session_gate_to_market_state,
    resolve_session_gate,
)

try:
    from watch_engine.watcher import WatcherEngine
except Exception:  # pragma: no cover
    WatcherEngine = None  # type: ignore
    sys_logger.warning("[main] WatcherEngine import failed", exc_info=True)

# ── Optional dependencies (graceful import) ──────────────────
try:
    from ml_core.signal import XGBOutput, XGBoostPredictor
except Exception:  # pragma: no cover
    XGBoostPredictor = None  # type: ignore
    XGBOutput = None  # type: ignore
    sys_logger.warning(
        "[main] ml_core.signal import failed → using mock\n"
        "  💡 macOS M-series: run  brew install libomp\n"
        "  💡 Linux:          run  pip install xgboost --force-reinstall",
        exc_info=True,
    )

try:
    from database.database import RunDatabase
except Exception:  # pragma: no cover
    RunDatabase = None  # type: ignore
    sys_logger.warning("[main] database.database import failed → DB disabled", exc_info=True)

try:
    from notification.discord_notifier import DiscordNotifier
except Exception:  # pragma: no cover
    DiscordNotifier = None  # type: ignore
    sys_logger.warning("[main] DiscordNotifier import failed", exc_info=True)

try:
    from notification.telegram_notifier import TelegramNotifier
except Exception:  # pragma: no cover
    TelegramNotifier = None  # type: ignore
    sys_logger.warning("[main] TelegramNotifier import failed", exc_info=True)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Constants — อ้างอิงจาก Src_V2/about-main.md §1.3
# ─────────────────────────────────────────────────────────────

INITIAL_CAPITAL_THB: float = 1500.0  # ทุนเริ่มต้น (Aom NOW)
DEFAULT_INTERVAL_SEC: int = 900  # 15 นาที / รอบ

# ── v2.1: Dual-Model XGBoost (.pkl) ────────────────────────────
DEFAULT_MODEL_BUY_PATH: str = "models/model_buy.pkl"
DEFAULT_MODEL_SELL_PATH: str = "models/model_sell.pkl"
DEFAULT_FEATURE_SCHEMA: str = "models/feature_columns.json"

PROVIDER_TAG: str = "xgboost-v2"  # tag ที่จะบันทึกใน runs.provider
MIN_TRADE_THB: float = 1000.0
PORTFOLIO_DEFENSIVE_CASH_THB: float = 1400.0
BASE_CONFIDENCE: float = 0.60
CONFIDENCE_STEP: float = 0.02  # Increases required confidence by 2% per existing trade


# ─────────────────────────────────────────────────────────────
# Mock signal predictor — ใช้ตอน model file หาย (fail-safe)
# ─────────────────────────────────────────────────────────────


class _MockPredictor:
    """Fallback predictor ถ้าโหลด XGBoost ไม่ได้ — คืน HOLD เสมอเพื่อความปลอดภัย

    ใช้ SimpleNamespace แทน _Stub class เพื่อให้ code กระชับ ปลอดภัย
    และ attribute ครบตรงกับ XGBOutput เสมอ (รวม top_features)
    """

    def __init__(self, *_args, **_kwargs) -> None:
        self.loaded = False

    def predict(self, _features: Dict[str, Any], session: str = "Unknown"):
        from types import SimpleNamespace

        # ใช้ XGBOutput ตัวจริงก่อน (type-safe และ IDE-friendly)
        if XGBOutput is not None:
            return XGBOutput(
                prob_buy=0.0,
                prob_sell=0.0,
                direction="HOLD",
                confidence=0.0,
                session=session,
                is_high_accuracy_session=False,
                top_features="",
            )

        # last-resort — XGBOutput import ล้มเหลวด้วย ใช้ SimpleNamespace แทน _Stub
        return SimpleNamespace(
            direction="HOLD",
            confidence=0.0,
            prob_buy=0.0,
            prob_sell=0.0,
            session=session,
            is_high_accuracy_session=False,
            top_features="",
        )


# ─────────────────────────────────────────────────────────────
# Runtime container
# ─────────────────────────────────────────────────────────────


@dataclass
class Runtime:
    """รวม dependency ทั้งหมดที่ main loop ต้องใช้"""

    orchestrator: GoldTradingOrchestrator
    signal_engine: Any  # XGBoostPredictor | _MockPredictor
    core: CoreDecision
    database: Optional[Any]  # RunDatabase | None
    discord: Optional[Any]
    telegram: Optional[Any]
    save_to_db: bool = True


# ─────────────────────────────────────────────────────────────
# Adapter: เชื่อม Runtime (v2) → WatcherEngine interface
# ─────────────────────────────────────────────────────────────


class _AnalysisServiceAdapter:
    """
    Adapter ที่แปลง Runtime ของ v2 (XGBoost) ให้เข้ากับ interface
    ที่ WatcherEngine ต้องการ (analysis_service.run_analysis + persistence)

    WatcherEngine เรียก:
      - self.analysis_service.run_analysis(provider, period, intervals, bypass_session_gate)
      - self.analysis_service.persistence.get_portfolio()
      - self.analysis_service.persistence.save_portfolio(data)
      - self.analysis_service.persistence.record_emergency_sell_atomic(...)
    """

    def __init__(self, rt: 'Runtime') -> None:
        self._rt = rt
        # persistence → ชี้ไปที่ database (RunDatabase)
        self.persistence = rt.database

    def run_analysis(self, **kwargs) -> dict:
        """ปลุก XGBoost pipeline 1 รอบเต็ม แล้วส่งผลกลับในรูปแบบที่ WatcherEngine เข้าใจ"""
        try:
            decision = run_analysis_once(self._rt, skip_fetch=False)
            return {
                "status": "success",
                "voting_result": {
                    "final_signal": decision.final,
                    "weighted_confidence": decision.confidence,
                },
                "run_id": None,
            }
        except Exception as exc:
            sys_logger.error(f"[watcher→adapter] run_analysis failed: {exc}")
            return {"status": "error", "error": str(exc)}


# ─────────────────────────────────────────────────────────────
# Build runtime
# ─────────────────────────────────────────────────────────────


def build_runtime(
    *,
    model_buy_path: str = DEFAULT_MODEL_BUY_PATH,
    model_sell_path: str = DEFAULT_MODEL_SELL_PATH,
    feature_schema_path: str = DEFAULT_FEATURE_SCHEMA,
    enable_db: bool = True,
    enable_notify: bool = True,
) -> Runtime:
    """ประกอบ runtime สำหรับ main loop"""
    sys_logger.info("─" * 60)
    sys_logger.info("  🔨  Building runtime — XGBoost v2.1 dual-model pipeline")
    sys_logger.info("─" * 60)

    # 1) Data orchestrator (เริ่ม WebSocket interceptor ในตัว)
    orchestrator = GoldTradingOrchestrator()
    sys_logger.info("[main] ✓ GoldTradingOrchestrator ready")

    # 2) XGBoost dual-model signal engine — fail-safe fallback to mock
    signal_engine: Any
    have_models = os.path.exists(model_buy_path) and os.path.exists(model_sell_path)
    if XGBoostPredictor is not None and have_models:
        try:
            signal_engine = XGBoostPredictor(
                model_buy_path=model_buy_path,
                model_sell_path=model_sell_path,
                feature_schema_path=feature_schema_path,
            )
            sys_logger.info(
                f"[main] ✓ XGBoostPredictor loaded "
                f"(buy={model_buy_path}, sell={model_sell_path}, "
                f"features={len(signal_engine.feature_columns)})"
            )
        except Exception as exc:
            sys_logger.error(f"[main] XGBoostPredictor init failed: {exc} → mock")
            signal_engine = _MockPredictor()
    elif XGBoostPredictor is not None:
        # ไม่มี explicit paths → ลอง registry.json ก่อน
        _registry = os.path.join(os.path.dirname(model_buy_path), "registry.json")
        try:
            signal_engine = XGBoostPredictor.from_registry(_registry)
            sys_logger.info(
                "[main] ✓ XGBoostPredictor loaded from registry "
                "(features=%d)", len(signal_engine.feature_columns)
            )
        except Exception as exc:
            sys_logger.warning(
                f"[main] Model files not found & registry failed: {exc} → mock\n"
                f"  buy={model_buy_path} exists={os.path.exists(model_buy_path)}\n"
                f"  sell={model_sell_path} exists={os.path.exists(model_sell_path)}"
            )
            signal_engine = _MockPredictor()
    else:
        sys_logger.warning("[main] XGBoostPredictor unavailable → mock")
        signal_engine = _MockPredictor()

    # 3) Core decision (ภายในรัน RiskManager + SessionGate ขนานกัน)
    risk_manager = RiskManager()
    core = CoreDecision(risk_manager=risk_manager)
    sys_logger.info(
        "[main] ✓ CoreDecision (RiskManager + SessionGate concurrent) ready"
    )

    # 4) Database (optional)
    database: Optional[Any] = None
    if enable_db and RunDatabase is not None:
        try:
            database = RunDatabase()
            sys_logger.info("[main] ✓ RunDatabase connected")
        except Exception as exc:
            sys_logger.error(f"[main] RunDatabase init failed: {exc} → DB disabled")
            database = None

    # 5) Notifiers (optional)
    discord = None
    telegram = None
    if enable_notify:
        if DiscordNotifier is not None:
            try:
                discord = DiscordNotifier()
                sys_logger.info("[main] ✓ DiscordNotifier ready")
            except Exception as exc:
                sys_logger.warning(f"[main] DiscordNotifier disabled: {exc}")
        if TelegramNotifier is not None:
            try:
                telegram = TelegramNotifier()
                sys_logger.info("[main] ✓ TelegramNotifier ready")
            except Exception as exc:
                sys_logger.warning(f"[main] TelegramNotifier disabled: {exc}")

    return Runtime(
        orchestrator=orchestrator,
        signal_engine=signal_engine,
        core=core,
        database=database,
        discord=discord,
        telegram=telegram,
        save_to_db=enable_db and database is not None,
    )


# ─────────────────────────────────────────────────────────────
# One full analysis cycle
# ─────────────────────────────────────────────────────────────


def run_analysis_once(rt: Runtime, *, skip_fetch: bool = False) -> Decision:
    """
    รันรอบ pipeline 1 ครั้ง:

        market_state → feature_list → (signal, conf) → CoreDecision → notify + persist

    คืน `Decision` สุดท้ายที่ตัดสินใจ
    """
    cycle_start = time.perf_counter()

    # ── 1. Data Engine ─────────────────────────────────────────
    sys_logger.info("🟢[cycle] (1/5) fetching market_state via orchestrator")
    market_state = rt.orchestrator.run(save_to_file=not skip_fetch)
    _attach_portfolio_state(rt, market_state)

    # ── 1b. Session Gate — ต้อง resolve ก่อน XGBoost predict ────
    # เหตุผล: _resolve_session_label() อ่าน market_state["session_gate"]
    # ถ้า resolve ทีหลัง (ใน core.evaluate) session_label จะเป็น "Unknown" ทุกรอบ
    _sg_result = resolve_session_gate()
    attach_session_gate_to_market_state(market_state, _sg_result)

    # ── [v4.0] Attach session_quota จาก DB จริง ──────────────────
    # ให้ risk gate รู้ว่า session นี้ยังทำรอบอยู่ไหม → ใช้ force trade logic
    if rt.database is not None and _sg_result.apply_gate and _sg_result.session_id:
        try:
            _sq = rt.database.get_session_quota(_sg_result.session_id)
            if "session_gate" in market_state:
                market_state["session_gate"]["session_quota"] = _sq
            sys_logger.info(
                "🟢[cycle] session_quota: session=%s rounds_done=%d is_complete=%s has_open=%s",
                _sg_result.session_id,
                _sq.get("rounds_done", 0),
                _sq.get("is_complete", False),
                _sq.get("has_open_position", False),
            )
        except Exception as _sq_err:
            sys_logger.warning("[cycle] get_session_quota failed: %s", _sq_err)

    sys_logger.info(
        "🟢[cycle] session_gate resolved: id=%s apply=%s mode=%s",
        _sg_result.session_id or "outside",
        _sg_result.apply_gate,
        _sg_result.llm_mode or "-",
    )

    # ── 2. Feature extraction (26-dim, v2 schema) ──────────────
    sys_logger.info("🟢[cycle] (2/5) extracting 26-dim feature vector (v2)")
    try:
        feature_dict = get_xgboost_feature_v2(market_state)
    except Exception as exc:
        sys_logger.exception(f"🔴[cycle] feature extraction failed: {exc}")
        return Decision(
            final="HOLD",
            model_signal="HOLD",
            confidence=0.0,
            reject_reason=f"feature_error:{exc}",
            notify=False,
        )

    # ── 3. Dual-model XGBoost prediction → (signal, confidence)
    sys_logger.info("🟢[cycle] (3/5) XGBoost dual-model predict_proba")
    session_label = _resolve_session_label(market_state)
    prob_buy = prob_sell = 0.0
    # [BUGFIX] initialize top_features ก่อน try เพื่อป้องกัน NameError
    # ถ้า predict() throw exception แล้ว top_features ไม่ถูก assign
    # โค้ดด้านล่าง (if top_features:) จะ crash ด้วย NameError
    top_features: str = ""
    try:
        xgb_out = rt.signal_engine.predict(feature_dict, session=session_label)
        signal = str(getattr(xgb_out, "direction", "HOLD")).upper()
        confidence = float(getattr(xgb_out, "confidence", 0.0))
        prob_buy = float(getattr(xgb_out, "prob_buy", 0.0))
        prob_sell = float(getattr(xgb_out, "prob_sell", 0.0))
        top_features = getattr(xgb_out, "top_features", "")
    except Exception as exc:
        sys_logger.exception(f"🔴[cycle] XGBoost predict failed: {exc}")
        signal, confidence = "HOLD", 0.0

    sys_logger.info(
        f"🟢[cycle] XGBoost → {signal} (conf={confidence:.3f}) "
        f"| prob_buy={prob_buy:.3f} prob_sell={prob_sell:.3f} session={session_label}"
    )

    # ── 4. Core decision (fan-out gates) ───────────────────────
    sys_logger.info("🟢[cycle] (4/5) CoreDecision evaluating gates concurrently")
    if top_features:
        rationale_str = f"🔴ระบบมองเห็นโอกาส {signal} (ความมั่นใจ {confidence:.2%}) โดยมีปัจจัยหลักจาก {top_features}"
    else:
        rationale_str = f"🔴ระบบประเมินว่าควร {signal} (ความมั่นใจ {confidence:.2%})"

    decision = rt.core.evaluate(
        signal=signal,
        confidence=confidence,
        market_state=market_state,
        rationale=rationale_str,
    )

    sys_logger.info(
        f"🟢[cycle] Decision: final={decision.final} notify={decision.notify} "
        f"reject={decision.reject_reason or '-'}"
    )

    # ── 5. Notify (YES only) + Persist (always) ────────────────
    sys_logger.info("🟢[cycle] (5/5) notify + persist")
    run_id = _persist_run(rt, decision, market_state)
    _notify_if_pass(rt, decision, market_state, run_id=run_id)
    # send_trade_log_from_result(decision, market_state, run_id=run_id, emit_logs=True)
    elapsed_ms = (time.perf_counter() - cycle_start) * 1000

    # ── ผลลัพธ์สรุป — อ่านง่ายบน terminal ────────────────────
    _SIG_ICON = {"BUY": "🟢", "SELL": "🔴"}.get(decision.final, "⚫")
    _notify_icon = "✅ NOTIFY" if decision.notify else "🔕 no notify"
    _reject_str  = f"  ↳ reject: {decision.reject_reason}" if decision.reject_reason else ""
    sys_logger.info(
        "\n%s\n  %s  %-5s | conf=%-6s | %s | %.0f ms%s\n%s",
        "─" * 60,
        _SIG_ICON,
        decision.final,
        f"{decision.confidence:.1%}",
        _notify_icon,
        elapsed_ms,
        _reject_str,
        "─" * 60,
    )
    return decision


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _attach_portfolio_state(rt: Runtime, market_state: Dict[str, Any]) -> None:
    """
    Attach DB portfolio state before CoreDecision/RiskManager.

    XGBoost remains stateless; portfolio data is only used by rule gates.
    """
    existing = market_state.get("portfolio")
    portfolio = existing if isinstance(existing, dict) else {}

    if rt.database is not None:
        try:
            db_portfolio = rt.database.get_portfolio()
            if isinstance(db_portfolio, dict):
                portfolio = db_portfolio
                sys_logger.info(
                    "[portfolio] attached from DB: cash=%.2f gold=%.4fg trades_today=%s",
                    _safe_float(portfolio.get("cash_balance")),
                    _safe_float(portfolio.get("gold_grams")),
                    _safe_int(portfolio.get("trades_today")),
                )
            else:
                sys_logger.warning(
                    "[portfolio] get_portfolio returned non-dict; using orchestrator state"
                )
        except Exception as exc:
            sys_logger.warning(
                f"[portfolio] get_portfolio failed; using orchestrator state: {exc}"
            )
    else:
        sys_logger.debug("[portfolio] DB disabled; using orchestrator state")

    market_state["portfolio"] = portfolio
    _refresh_execution_quota(market_state, portfolio)
    _refresh_portfolio_summary(market_state, portfolio)


def _refresh_execution_quota(
    market_state: Dict[str, Any], portfolio: Dict[str, Any]
) -> None:
    trades_today = max(0, _safe_int(portfolio.get("trades_today")))
    required_conf_next = BASE_CONFIDENCE + CONFIDENCE_STEP * trades_today

    quota = market_state.get("execution_quota")
    if not isinstance(quota, dict):
        quota = {}

    quota.update(
        {
            "entries_done": trades_today,
            "required_confidence_for_next_buy": required_conf_next,
            "recommended_next_position_thb": MIN_TRADE_THB,
        }
    )
    market_state["execution_quota"] = quota


def _refresh_portfolio_summary(
    market_state: Dict[str, Any], portfolio: Dict[str, Any]
) -> None:
    cash_balance = _safe_float(portfolio.get("cash_balance"))
    gold_grams = _safe_float(portfolio.get("gold_grams"))
    unrealized_pnl = _safe_float(portfolio.get("unrealized_pnl"))

    if cash_balance < MIN_TRADE_THB:
        mode = "critical"
    elif cash_balance < PORTFOLIO_DEFENSIVE_CASH_THB:
        mode = "defensive"
    else:
        mode = "normal"

    market_state["portfolio_summary"] = {
        "holding": gold_grams > 0,
        "profit": unrealized_pnl > 0,
        "can_trade": cash_balance >= MIN_TRADE_THB,
        "mode": mode,
    }


def _resolve_session_label(market_state: Dict[str, Any]) -> str:
    """แปลง session_gate.session_id → label ที่ XGBoost รู้จัก (Morning/Afternoon/Evening)
    
    [BUG 4 FIX] ลบ "night" ออกจาก mapping เพราะ session_gate ไม่มี "night" อีกต่อไป
    ช่วง 00:00-02:00 ถูก remap เป็น "evening" ตาม spec แล้ว
    """
    sg = market_state.get("session_gate") or {}
    sid = (sg.get("session_id") or "").lower()
    if sid == "morning":
        return "Morning"
    if sid == "noon":
        return "Afternoon"
    if sid == "evening":
        return "Evening"
    return "Unknown"


def _notify_if_pass(
    rt: Runtime,
    decision: Decision,
    market_state: Dict[str, Any],
    run_id: Optional[int] = None,
) -> None:

    """ส่ง Discord + Telegram เฉพาะกรณี ALL PASS (decision.notify == True)"""
    if not decision.notify:
        sys_logger.debug("[notify] skipped — gate not all-pass")
        return

    voting_result = {
        "final_signal": decision.final,
        "weighted_confidence": float(decision.confidence),
        "rationale": decision.rationale,
    }
    interval_results = {
        "xgb": {
            "signal": decision.final,
            "confidence": float(decision.confidence),
            "entry_price": decision.entry_price,
            "stop_loss": decision.stop_loss,
            "take_profit": decision.take_profit,
            "provider": PROVIDER_TAG,
        }
    }

    # if rt.discord is not None:
    #     try:
    #         ok = rt.discord.notify(
    #             voting_result=voting_result,
    #             interval_results=interval_results,
    #             market_state=market_state,
    #             provider=PROVIDER_TAG,
    #             period="live",
    #             run_id=run_id,
    #         )
    #         sys_logger.info(f"[notify] discord sent={ok}")
    #     except Exception as exc:
    #         sys_logger.error(f"[notify] discord failed: {exc}")

    if rt.telegram is not None:
        try:
            ok = rt.telegram.notify(
                voting_result=voting_result,
                provider=PROVIDER_TAG,
                period="live",
                interval_results=interval_results,
                market_state=market_state,
                run_id=run_id,
            )
            sys_logger.info(f"[notify] telegram sent={ok}")
        except Exception as exc:
            sys_logger.error(f"[notify] telegram failed: {exc}")


def _persist_run(
    rt: Runtime, decision: Decision, market_state: Dict[str, Any]
) -> Optional[int]:
    """บันทึกลง DB เสมอ (ทั้ง YES และ HOLD) — ตามหลัก database-first ใน spec §11.1"""
    if not rt.save_to_db or rt.database is None:
        sys_logger.debug("[persist] skipped — DB disabled")
        return None

    try:
        run_id = rt.database.save_run(
            provider=PROVIDER_TAG,
            result=decision.to_persist_dict(),
            market_state=market_state,
            interval_tf=str(market_state.get("interval", "")),
            period="live",
        )
        sys_logger.info(f"[persist] run saved → id={run_id}")

        # ── [v4.0] อัปเดต session_quota เมื่อ trade execute จริง ────────────
        sg = market_state.get("session_gate") or {}
        session_id = sg.get("session_id")
        if decision.notify and session_id:
            try:
                if decision.final == "BUY":
                    rt.database.mark_session_buy(session_id)
                    sys_logger.info(f"[persist] session_quota mark_buy: session={session_id}")
                elif decision.final == "SELL":
                    rt.database.mark_session_sell(session_id)
                    sys_logger.info(f"[persist] session_quota mark_sell: session={session_id}")
            except Exception as sq_err:
                sys_logger.error(f"[persist] session_quota update failed: {sq_err}")

        return run_id
    except Exception as exc:
        sys_logger.error(f"[persist] save_run failed: {exc}")
        return None


def send_trade_log_from_result(
    decision: Decision,
    market_state: Dict[str, Any],
    *,
    run_id: Optional[int] = None,
    emit_logs: bool = True,
) -> None:
    """Send trade log via logs.api_logger.send_trade_log when decision.notify is True."""
    if not decision.notify:
        if emit_logs:
            sys_logger.debug("[trade_log] skipped — decision.notify=False")
        return

    team_api_key = os.getenv("TEAM_API_KEY")
    if not team_api_key:
        if emit_logs:
            sys_logger.error("[trade_log] TEAM_API_KEY missing, cannot send trade log")
        return

    price = decision.entry_price if decision.entry_price is not None else "MARKET"
    reason = decision.rationale or f"Auto-generated signal based on {decision.final}"
    confidence = float(decision.confidence)
    stop_loss = float(decision.stop_loss) if decision.stop_loss is not None else 0.0
    take_profit = (
        float(decision.take_profit) if decision.take_profit is not None else 0.0
    )

    try:
        send_trade_log(
            action=decision.final,
            price=price,
            reason=reason,
            api_key=team_api_key,
            # confidence=confidence,
            # stop_loss=stop_loss,
            # take_profit=take_profit,
            # provider=PROVIDER_TAG,
            # session_id=market_state.get("session_gate", {}).get("session_id"),
            # run_id=run_id,
        )
        if emit_logs:
            sys_logger.info("[trade_log] sent")
    except Exception as exc:
        if emit_logs:
            sys_logger.error(f"[trade_log] failed: {exc}")


# ─────────────────────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────────────────────


_SHUTDOWN = False


def _install_signal_handlers() -> None:
    """ดักจับ SIGINT/SIGTERM เพื่อ graceful shutdown"""

    def _handler(signum, _frame):
        global _SHUTDOWN
        sys_logger.warning(f"[main] received signal {signum} → graceful shutdown")
        _SHUTDOWN = True

    try:
        _os_signal.signal(_os_signal.SIGINT, _handler)
        _os_signal.signal(_os_signal.SIGTERM, _handler)
    except (AttributeError, ValueError):  # Windows / non-main thread
        pass


def _build_watcher(rt: Runtime) -> Optional[Any]:
    """
    สร้าง WatcherEngine สำหรับ monitor ตลาดระหว่าง sleep
    คืน None ถ้า import ไม่ได้ หรือ database ไม่พร้อม
    """
    if WatcherEngine is None:
        sys_logger.info("[main] WatcherEngine not available → sleep-only mode")
        return None

    if rt.database is None:
        sys_logger.info("[main] Database disabled → WatcherEngine skipped (needs portfolio)")
        return None

    try:
        adapter = _AnalysisServiceAdapter(rt)
        watcher = WatcherEngine(
            analysis_service=adapter,
            data_orchestrator=rt.orchestrator,
            watcher_config={
                "provider": PROVIDER_TAG,
                "period": "1d",
                "interval": "5m",
                "cooldown_minutes": 5,
                "min_price_step": 1.5,
                "rsi_oversold": 30.0,
                "rsi_overbought": 70.0,
                "trailing_stop_profit_trigger": 20.0,
                "trailing_stop_lock_in": 5.0,
                "hard_stop_loss_per_gram": 15.0,
                "loop_sleep_seconds": 30,
            },
        )
        sys_logger.info("[main] ✓ WatcherEngine initialized")
        return watcher
    except Exception as exc:
        sys_logger.warning(f"[main] WatcherEngine init failed: {exc} → sleep-only mode")
        return None


def main_loop(
    rt: Runtime, *, interval_sec: int, skip_fetch: bool, run_once: bool
) -> None:
    """ลูปหลัก — รันต่อเนื่องทุก interval_sec วินาที จนกว่าจะถูก signal shutdown

    ระหว่าง sleep จะเปิด WatcherEngine เฝ้าดูตลาดแบบ event-driven:
    - ถ้าราคาเข้าเงื่อนไข (RSI extreme, SL hit) → Watcher จะปลุก run_analysis_once ขึ้นมาเอง
    - ถ้าตลาดนิ่ง → Watcher แค่ log แล้วรอจนครบ interval ปกติ
    """
    # สร้าง Watcher 1 ครั้ง แล้ว reuse ตลอด
    watcher = _build_watcher(rt)

    cycle_no = 0
    while not _SHUTDOWN:
        cycle_no += 1
        from datetime import datetime, timezone, timedelta
        _now_ict = datetime.now(timezone(timedelta(hours=7))).strftime("%d %b %Y  %H:%M:%S")
        sys_logger.info(
            "\n%s\n  🔄  Cycle #%d  |  %s\n%s",
            "─" * 60, cycle_no, _now_ict, "─" * 60,
        )

        # ── หยุด Watcher ก่อนรัน scheduled cycle (ป้องกัน concurrent analysis)
        if watcher is not None and watcher.is_running:
            watcher.stop()
            sys_logger.info("[main] ⏸️ WatcherEngine paused for scheduled cycle")

        try:
            run_analysis_once(rt, skip_fetch=skip_fetch)
        except Exception as exc:  # pragma: no cover - top-level safety
            sys_logger.exception(f"[main] cycle {cycle_no} crashed: {exc}")

        if run_once:
            sys_logger.info("[main] --once flag set → exiting after 1 cycle")
            break

        if _SHUTDOWN:
            break

        # ── เปิด Watcher ระหว่าง sleep ─────────────────────────────
        if watcher is not None:
            watcher.start()
            sys_logger.info(
                f"[main] 👁️ WatcherEngine active — monitoring market "
                f"for {interval_sec}s until next scheduled cycle"
            )

        sys_logger.info(f"[main] sleeping {interval_sec}s until next cycle")
        # sleep แบบ chunk เล็ก ๆ เพื่อให้ตอบ shutdown signal เร็ว
        for _ in range(interval_sec):
            if _SHUTDOWN:
                break
            time.sleep(1)

        # ── หยุด Watcher เมื่อหมดเวลา sleep ───────────────────────
        if watcher is not None and watcher.is_running:
            watcher.stop()
            sys_logger.info("[main] ⏹️ WatcherEngine stopped — resuming scheduled cycle")


# ─────────────────────────────────────────────────────────────
# CLI entrypoint
# ─────────────────────────────────────────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nakkhutthong-v2",
        description="นักขุดทอง v2 — XGBoost-based gold trading signal loop",
    )
    p.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_SEC,
        help=f"loop interval in seconds (default {DEFAULT_INTERVAL_SEC})",
    )
    p.add_argument(
        "--model-buy",
        type=str,
        default=DEFAULT_MODEL_BUY_PATH,
        help=f"path to BUY classifier .pkl (default {DEFAULT_MODEL_BUY_PATH})",
    )
    p.add_argument(
        "--model-sell",
        type=str,
        default=DEFAULT_MODEL_SELL_PATH,
        help=f"path to SELL classifier .pkl (default {DEFAULT_MODEL_SELL_PATH})",
    )
    p.add_argument(
        "--feature-schema",
        type=str,
        default=DEFAULT_FEATURE_SCHEMA,
        help=f"path to feature_columns.json (default {DEFAULT_FEATURE_SCHEMA})",
    )
    p.add_argument(
        "--skip-fetch",
        action="store_true",
        help="ใช้ snapshot ล่าสุด ไม่บันทึก payload ใหม่",
    )
    p.add_argument(
        "--no-save",
        action="store_true",
        help="ไม่บันทึกผลลง database (dry run)",
    )
    p.add_argument(
        "--no-notify",
        action="store_true",
        help="ปิดการส่ง Discord/Telegram",
    )
    p.add_argument(
        "--once",
        action="store_true",
        help="รันรอบเดียวแล้วจบ (สำหรับเทสต์)",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    _install_signal_handlers()

    sys_logger.info("═" * 60)
    sys_logger.info("  ⛏️  นักขุดทอง v2.1  —  XGBoost Gold Signal Loop")
    sys_logger.info("─" * 60)
    sys_logger.info("  💰 capital    ฿%s", f"{INITIAL_CAPITAL_THB:,.0f}")
    sys_logger.info("  ⏱  interval   %ss", args.interval)
    sys_logger.info("  🤖 model_buy  %s", args.model_buy)
    sys_logger.info("  🤖 model_sell %s", args.model_sell)
    sys_logger.info("  📐 features   %s", args.feature_schema)
    sys_logger.info(
        "  🔧 flags      skip_fetch=%s  no_save=%s  once=%s",
        args.skip_fetch, args.no_save, args.once,
    )
    sys_logger.info("═" * 60)

    try:
        rt = build_runtime(
            model_buy_path=args.model_buy,
            model_sell_path=args.model_sell,
            feature_schema_path=args.feature_schema,
            enable_db=not args.no_save,
            enable_notify=not args.no_notify,
        )
    except Exception as exc:
        sys_logger.exception(f"[main] build_runtime failed: {exc}")
        return 2

    try:
        main_loop(
            rt,
            interval_sec=max(1, int(args.interval)),
            skip_fetch=args.skip_fetch,
            run_once=args.once,
        )
    finally:
        if rt.database is not None:
            try:
                rt.database.close()
            except Exception:
                pass
        sys_logger.info("[main] shutdown complete")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())