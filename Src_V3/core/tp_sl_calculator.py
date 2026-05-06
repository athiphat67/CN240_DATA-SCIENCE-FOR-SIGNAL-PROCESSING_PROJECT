"""
core/tp_sl_calculator.py — Phase 6: TP/SL Calculator

รับ order dict จาก Phase 5 + F_ATR_48 จาก Feature Engine
→ คำนวณ TP/SL price levels จาก ATR
→ validate ว่า distance อยู่ในช่วงที่ยอมรับได้
→ ส่ง order dict ที่สมบูรณ์ไป Phase 8 (insert positions) และ Phase 9 (Discord)

Price logic:
  TP/SL levels คำนวณจาก entry_bid (ราคาที่จะ SELL ออก) ไม่ใช่ entry_ask
  เพราะ Position Monitor ตรวจ current_bid vs tp_bid_price / sl_bid_price

  tp_bid = entry_bid + (ATR × 1.5)   ← bid ต้องขึ้นถึงตรงนี้จึง TP
  sl_bid = entry_bid − (ATR × 1.0)   ← bid ลงถึงตรงนี้ → SL

P&L basis:
  P&L คำนวณจาก bid เทียบกับ entry_ask (ต้นทุนที่จ่ายจริง)
  tp_pnl = (tp_bid − entry_ask) × gold_weight   → บวก (expected profit)
  sl_pnl = (sl_bid − entry_ask) × gold_weight   → ลบ (expected loss)

Validation rules (ทั้งสองต้องผ่านพร้อมกัน):
  tp_distance ≥ MIN_TP_DISTANCE_THB (50)   — TP ไม่ใกล้เกินไป (worth trading)
  sl_distance ≤ MAX_SL_DISTANCE_THB (200)  — SL ไม่ไกลเกินไป (risk controlled)
  ถ้าไม่ผ่าน → tp_sl_valid=False, reject_reason="invalid_tp_sl"
  Orchestrator (Phase 10) จะ skip position นี้
"""

from __future__ import annotations

import logging

from config.settings import (
    MAX_SL_DISTANCE_THB,
    MIN_TP_DISTANCE_THB,
    SL_ATR_MULTIPLIER,
    TP_ATR_MULTIPLIER,
)

logger = logging.getLogger("trading")


# ─── Input Validation ─────────────────────────────────────────────────────────

def _validate_inputs(order: dict, atr_48: float) -> None:
    """Raises ValueError ถ้า order หรือ ATR ผิดปกติ"""
    required = {
        "entry_ask_price", "entry_bid_price", "gold_weight",
        "position_id", "signal_id",
    }
    missing = required - set(order.keys())
    if missing:
        raise ValueError(
            f"[tp_sl_calculator] order ขาด keys: {sorted(missing)}"
        )
    if atr_48 <= 0:
        raise ValueError(
            f"[tp_sl_calculator] atr_48 ต้องมากกว่า 0, ได้ {atr_48}"
        )
    if order["gold_weight"] <= 0:
        raise ValueError(
            f"[tp_sl_calculator] gold_weight ต้องมากกว่า 0, ได้ {order['gold_weight']}"
        )


# ─── Main Public Function ─────────────────────────────────────────────────────

def calculate_tp_sl(order: dict, atr_48: float) -> dict:
    """
    คำนวณ TP/SL levels และ P&L estimates จาก ATR

    Parameters
    ----------
    order   : dict — ผลลัพธ์จาก simulate_buy() (Phase 5)
    atr_48  : float — F_ATR_48 จาก FeaturesRow (หน่วย THB)

    Returns
    -------
    dict — order dict เดิม extended ด้วย TP/SL fields:
        atr_used          : float — ATR ที่ใช้คำนวณ
        tp_bid_price      : float — bid target สำหรับ TP
        sl_bid_price      : float — bid level สำหรับ SL
        tp_distance_thb   : float — ATR × 1.5
        sl_distance_thb   : float — ATR × 1.0
        tp_pnl_thb        : float — P&L ถ้า TP hit (บวก)
        sl_pnl_thb        : float — P&L ถ้า SL hit (ลบ)
        risk_reward_ratio : float — tp_distance / sl_distance (= 1.5)
        tp_sl_valid       : bool  — True ถ้าผ่านทั้ง MIN_TP และ MAX_SL checks
        reject_reason     : str | None — "invalid_tp_sl" ถ้าไม่ผ่าน

    Raises
    ------
    ValueError — atr_48 ≤ 0, gold_weight ≤ 0, หรือ order ขาด required keys
    """
    _validate_inputs(order, atr_48)

    entry_ask: float = order["entry_ask_price"]
    entry_bid: float = order["entry_bid_price"]
    gold_weight: float = order["gold_weight"]

    # ── TP/SL distance (THB) ──────────────────────────────────────────────────
    tp_distance = atr_48 * TP_ATR_MULTIPLIER    # ATR × 1.5
    sl_distance = atr_48 * SL_ATR_MULTIPLIER    # ATR × 1.0

    # ── TP/SL price levels (bid-based) ───────────────────────────────────────
    tp_bid = entry_bid + tp_distance
    sl_bid = entry_bid - sl_distance

    # ── P&L estimates (bid vs entry_ask = true cost) ──────────────────────────
    tp_pnl = (tp_bid - entry_ask) * gold_weight   # expected profit (บวก)
    sl_pnl = (sl_bid - entry_ask) * gold_weight   # expected loss  (ลบ)

    # ── Risk/Reward ratio ─────────────────────────────────────────────────────
    rr = tp_distance / sl_distance if sl_distance > 0 else 0.0

    # ── Validation ────────────────────────────────────────────────────────────
    tp_ok   = tp_distance >= MIN_TP_DISTANCE_THB   # TP ไม่ใกล้เกินไป
    sl_ok   = sl_distance <= MAX_SL_DISTANCE_THB   # SL ไม่ไกลเกินไป
    valid   = tp_ok and sl_ok
    reject_reason = None if valid else "invalid_tp_sl"

    # ── Logging ───────────────────────────────────────────────────────────────
    pos_id = order.get("position_id", "?")
    if valid:
        logger.info(
            f"[tp_sl_calculator] ✅ TP/SL valid | pos={pos_id} | "
            f"ATR={atr_48:.2f} | "
            f"TP={tp_bid:,.2f} (+{tp_distance:.2f}) pnl={tp_pnl:+.4f} THB | "
            f"SL={sl_bid:,.2f} (-{sl_distance:.2f}) pnl={sl_pnl:+.4f} THB | "
            f"R/R={rr:.2f}"
        )
    else:
        fail_reasons = []
        if not tp_ok:
            fail_reasons.append(
                f"tp_distance {tp_distance:.2f} < MIN {MIN_TP_DISTANCE_THB}"
            )
        if not sl_ok:
            fail_reasons.append(
                f"sl_distance {sl_distance:.2f} > MAX {MAX_SL_DISTANCE_THB}"
            )
        logger.info(
            f"[tp_sl_calculator] ❌ TP/SL invalid | pos={pos_id} | "
            f"ATR={atr_48:.2f} | {' | '.join(fail_reasons)}"
        )

    return {
        **order,
        "atr_used"          : atr_48,
        "tp_bid_price"      : tp_bid,
        "sl_bid_price"      : sl_bid,
        "tp_distance_thb"   : tp_distance,
        "sl_distance_thb"   : sl_distance,
        "tp_pnl_thb"        : tp_pnl,
        "sl_pnl_thb"        : sl_pnl,
        "risk_reward_ratio" : rr,
        "tp_sl_valid"       : valid,
        "reject_reason"     : reject_reason,
    }