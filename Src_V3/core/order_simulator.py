"""
core/order_simulator.py — Phase 5: Order Simulator (Fractional Gold)

รับ ask/bid ราคาปัจจุบัน → คำนวณน้ำหนักทองที่ได้จาก investment_thb
→ ส่ง order dict ไป Phase 6 (TP/SL Calculator)

Key rule — TRUNCATION ไม่ใช่ ROUND:
  gold_weight = floor(investment / ask * 10^5) / 10^5
  ทำให้ actual_cost ≤ investment เสมอ (ไม่ซื้อเกินเงินที่มี)

Breakeven logic:
  ซื้อที่ ask → ขายได้ที่ bid
  breakeven_bid = entry_ask  (ต้องให้ bid ≥ entry ask จึงจะไม่ขาดทุน)
  ดังนั้น P&L = (close_bid − entry_ask) × gold_weight

Position ID:
  "pos_{signal_id}"  เช่น "pos_sig_20251006_093000"
  ผูกกับ signal_id เพื่อ traceability และ idempotency ใน Supabase
"""

from __future__ import annotations

import logging
import math
from datetime import datetime

import pytz

from config.settings import (
    DRY_RUN,
    GOLD_WEIGHT_DECIMALS,
    INVESTMENT_AMOUNT_THB,
    TIMEZONE,
)

logger = logging.getLogger("trading")
TZ     = pytz.timezone(TIMEZONE)


# ─── Input Validation ─────────────────────────────────────────────────────────

def _validate_prices(ask_price: float, bid_price: float, investment_thb: float) -> None:
    """
    Raises ValueError ถ้า input ไม่ถูกต้อง
    ตรวจก่อน simulate เสมอ — ป้องกัน ZeroDivisionError และ nonsense positions
    """
    if ask_price <= 0:
        raise ValueError(f"[order_simulator] ask_price ต้องมากกว่า 0, ได้ {ask_price}")
    if bid_price <= 0:
        raise ValueError(f"[order_simulator] bid_price ต้องมากกว่า 0, ได้ {bid_price}")
    if ask_price <= bid_price:
        raise ValueError(
            f"[order_simulator] ask_price ({ask_price}) ต้องมากกว่า bid_price ({bid_price})"
        )
    if investment_thb <= 0:
        raise ValueError(
            f"[order_simulator] investment_thb ต้องมากกว่า 0, ได้ {investment_thb}"
        )


# ─── Main Public Function ─────────────────────────────────────────────────────

def simulate_buy(
    ask_price: float,
    bid_price: float,
    signal_id: str,
    investment_thb: float = INVESTMENT_AMOUNT_THB,
    entry_time: datetime | None = None,
) -> dict:
    """
    คำนวณ fractional gold order จาก investment amount.

    Parameters
    ----------
    ask_price     : float — ราคาขาย (entry price ที่ระบบซื้อ)
    bid_price     : float — ราคารับซื้อ (ใช้คำนวณ spread + mark-to-market)
    signal_id     : str   — จาก Phase 4, ใช้สร้าง position_id
    investment_thb: float — จำนวนเงินลงทุน (default 1,000 THB จาก settings)
    entry_time    : datetime | None — ถ้า None จะใช้ datetime.now(TZ)

    Returns
    -------
    dict — order fields ที่ Phase 6 จะ extend ด้วย TP/SL
        position_id     : str   — "pos_{signal_id}"
        signal_id       : str
        status          : str   — "OPEN"
        entry_ask_price : float — ราคา ask ที่ซื้อ (entry)
        entry_bid_price : float — ราคา bid ณ เวลาซื้อ
        hsh_spread      : float — ask − bid (THB)
        entry_time      : str   — ISO8601 (Asia/Bangkok)
        investment_thb  : float — จำนวนเงินตั้งต้น
        gold_weight     : float — น้ำหนักทอง (บาทไทย), truncated 5 DP
        actual_cost_thb : float — เงินที่จ่ายจริง = gold_weight × ask ≤ investment
        spread_cost_thb : float — ต้นทุน spread = gold_weight × (ask − bid)
        mtm_value_thb   : float — mark-to-market ณ entry = gold_weight × bid
        breakeven_bid   : float — bid ที่ต้องขายได้จึงจะ breakeven = entry_ask
        dry_run         : bool

    Raises
    ------
    ValueError — ask ≤ 0, bid ≤ 0, ask ≤ bid, investment ≤ 0
    ValueError — gold_weight = 0 หลัง truncation (investment น้อยเกินไป)
    """
    _validate_prices(ask_price, bid_price, investment_thb)

    # ── Fractional gold weight (TRUNCATE — ห้าม round) ────────────────────────
    # truncate ป้องกัน actual_cost > investment ซึ่งจะเกิดถ้าใช้ round
    raw_weight  = investment_thb / ask_price
    multiplier  = 10 ** GOLD_WEIGHT_DECIMALS          # 10^5 = 100000
    gold_weight = math.floor(raw_weight * multiplier) / multiplier

    if gold_weight <= 0:
        raise ValueError(
            f"[order_simulator] gold_weight = 0 หลัง truncation — "
            f"investment_thb ({investment_thb:.2f}) น้อยเกินไปสำหรับ ask ({ask_price:.2f})\n"
            f"  ต้องการ investment ≥ {ask_price / multiplier:.4f} THB"
        )

    # ── Derived financials ────────────────────────────────────────────────────
    actual_cost_thb  = gold_weight * ask_price
    spread_cost_thb  = gold_weight * (ask_price - bid_price)
    mtm_value_thb    = gold_weight * bid_price

    # breakeven: ต้องขายที่ bid ≥ entry_ask จึงไม่ขาดทุน
    # (เพราะซื้อที่ ask แต่ขายได้ที่ bid ซึ่งต่ำกว่า ask เสมอ)
    breakeven_bid    = ask_price

    # ── Position identity ─────────────────────────────────────────────────────
    position_id = f"pos_{signal_id}"
    if entry_time is None:
        entry_time = datetime.now(TZ)
    elif entry_time.tzinfo is None:
        entry_time = TZ.localize(entry_time)

    order = {
        "position_id"    : position_id,
        "signal_id"      : signal_id,
        "status"         : "OPEN",
        "entry_ask_price": ask_price,
        "entry_bid_price": bid_price,
        "hsh_spread"     : ask_price - bid_price,
        "entry_time"     : entry_time.isoformat(),
        "investment_thb" : investment_thb,
        "gold_weight"    : gold_weight,
        "actual_cost_thb": actual_cost_thb,
        "spread_cost_thb": spread_cost_thb,
        "mtm_value_thb"  : mtm_value_thb,
        "breakeven_bid"  : breakeven_bid,
        "dry_run"        : DRY_RUN,
    }

    logger.info(
        f"[order_simulator] 🟡 BUY simulated | pos={position_id} | "
        f"ask={ask_price:,.2f} | bid={bid_price:,.2f} | "
        f"weight={gold_weight:.5f} บาทไทย | "
        f"cost={actual_cost_thb:,.4f} THB | "
        f"spread_cost={spread_cost_thb:.4f} THB"
    )

    return order