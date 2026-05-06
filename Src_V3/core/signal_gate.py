"""
core/signal_gate.py — Phase 4: Signal Gate

รับ inference_result จาก Phase 3 + features_row จาก Phase 2
→ ตรวจ 6 gate conditions ทุกข้อ (AND logic)
→ ถ้าผ่านทั้งหมด → passed=True → Phase 5 เปิด position
→ ถ้าล้มเหลวข้อใดข้อหนึ่ง → passed=False พร้อม reject_reason

Gate Conditions (ทุกข้อต้อง True จึงผ่าน):
  1. score_gate        — ranker_score >= SIGNAL_THRESHOLD (0.65)
  2. no_open_position  — ไม่มี position เปิดอยู่ (MAX_CONCURRENT_TRADES = 1)
  3. market_open       — session ≠ "Closed"
  4. srvr_gate         — F_SRVR >= 0.15  (volatility เหลือพอสำหรับ TP)
  5. spread_gate       — F_XAU_Spread_Norm < 2.5  (liquidity ปกติ)
  6. regime_gate       — F_Regime == 1  (uptrend เท่านั้น)

reject_reason = key ของ gate แรกที่ล้มเหลว (ตามลำดับ gates dict)
signal_id     = "sig_YYYYMMDD_HHMMSS"  (PRIMARY KEY ใน Supabase — idempotent)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from config.settings import (
    DRY_RUN,
    SIGNAL_THRESHOLD,
)

if TYPE_CHECKING:
    from core.feature_engine import FeaturesRow

logger = logging.getLogger("trading")

# ─── Gate thresholds (ค่าคงที่ที่ไม่ได้อยู่ใน settings.py) ──────────────────
_SRVR_MIN         = 0.15   # F_SRVR ต่ำกว่านี้ → volatility เหลือน้อย → skip
_SPREAD_NORM_MAX  = 2.5    # F_XAU_Spread_Norm สูงกว่านี้ → liquidity ต่ำ → skip
_REGIME_REQUIRED  = 1      # +1 = uptrend only


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _make_signal_id(bar_time_iso: str) -> str:
    """
    สร้าง signal_id จาก bar_time ISO8601.

    "2025-10-16T09:30:00+07:00" → "sig_20251016_093000"

    ใช้ 19 ตัวอักษรแรก (YYYY-MM-DDTHH:MM:SS) เพื่อตัด timezone offset ออก
    แล้ว strip เครื่องหมาย '-', ':', 'T'
    """
    ts_clean = bar_time_iso[:19]          # "2025-10-16T09:30:00"
    ts_clean = ts_clean.replace("-", "")  # "20251016T09:30:00"
    ts_clean = ts_clean.replace(":", "")  # "20251016T093000"
    ts_clean = ts_clean.replace("T", "_") # "20251016_093000"
    return f"sig_{ts_clean}"


def _count_open_positions() -> int:
    """
    Lazy import count_open_positions จาก supabase_writer.
    Lazy import ป้องกัน circular dependency และทำให้ unit test mock ง่าย
    (ไม่ต้องการ Supabase connection ตอน import module นี้)
    """
    from db.supabase_writer import count_open_positions
    return count_open_positions()


# ─── Main Public Function ─────────────────────────────────────────────────────

def evaluate_signal_gate(
    inference_result: dict,
    features_row: "FeaturesRow",
) -> dict:
    """
    ตรวจ 6 gate conditions และสร้าง signal record พร้อมส่งไป Phase 5 / Phase 8.

    Parameters
    ----------
    inference_result : dict
        ผลลัพธ์จาก run_inference() — ต้องมี "ranker_score", "features_snap"
    features_row : FeaturesRow
        ผลลัพธ์จาก compute_features() — ต้องมี session, F_SRVR, F_XAU_Spread_Norm,
        F_Regime, bar_time

    Returns
    -------
    dict with keys:
        signal_id      : str   — "sig_YYYYMMDD_HHMMSS"  (Supabase PRIMARY KEY)
        bar_time       : str   — ISO8601 bar timestamp
        session        : str   — "Morning" / "Afternoon" / "Night" / "Closed"
        signal_type    : str   — always "BUY" (long-only system)
        ranker_score   : float — raw model score
        gates_passed   : dict  — {gate_name: bool} ทุก gate
        passed         : bool  — True iff ทุก gate ผ่าน
        reject_reason  : str | None — key ของ gate แรกที่ล้มเหลว
        dry_run        : bool  — mirror ของ DRY_RUN setting
        features_snap  : dict  — full feature snapshot จาก inference
    """
    score              = inference_result["ranker_score"]
    session: str       = features_row["session"]
    F_SRVR: float      = features_row["F_SRVR"]
    F_XAU_Spread_Norm  = features_row["F_XAU_Spread_Norm"]
    F_Regime: int      = features_row["F_Regime"]
    bar_time: str      = features_row["bar_time"]

    # ── Open position count (0 ใน DRY_RUN เสมอ — ไม่ query DB จริง) ─────────
    open_positions = _count_open_positions()

    # ── 6 Gates (ลำดับสำคัญ: reject_reason = แรกที่ล้มเหลว) ─────────────────
    gates: dict[str, bool] = {
        "score_gate"       : score >= SIGNAL_THRESHOLD,
        "no_open_position" : open_positions == 0,
        "market_open"      : session != "Closed",
        "srvr_gate"        : F_SRVR >= _SRVR_MIN,
        "spread_gate"      : F_XAU_Spread_Norm < _SPREAD_NORM_MAX,
        "regime_gate"      : F_Regime == _REGIME_REQUIRED,
    }

    passed = all(gates.values())
    reject_reason: str | None = (
        None if passed
        else next(k for k, v in gates.items() if not v)
    )

    signal_id = _make_signal_id(bar_time)

    # ── Logging ───────────────────────────────────────────────────────────────
    if passed:
        logger.info(
            f"[signal_gate] ✅ PASS | id={signal_id} | "
            f"score={score:.4f} | session={session} | "
            f"SRVR={F_SRVR:.3f} | spread_norm={F_XAU_Spread_Norm:.2f} | "
            f"regime={F_Regime}"
        )
    else:
        failed_gates = {k: v for k, v in gates.items() if not v}
        logger.info(
            f"[signal_gate] ❌ REJECT | id={signal_id} | "
            f"reason={reject_reason} | "
            f"score={score:.4f} | session={session} | "
            f"failed={list(failed_gates.keys())}"
        )

    return {
        "signal_id"    : signal_id,
        "bar_time"     : bar_time,
        "session"      : session,
        "signal_type"  : "BUY",
        "ranker_score" : score,
        "gates_passed" : gates,
        "passed"       : passed,
        "reject_reason": reject_reason,
        "dry_run"      : DRY_RUN,
        "features_snap": inference_result["features_snap"],
    }