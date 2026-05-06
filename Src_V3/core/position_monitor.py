"""
core/position_monitor.py — Phase 7: Position Monitor

ตรวจสอบ open positions ทุก 1 นาที (Job B ใน Orchestrator)
→ เปรียบเทียบ current_bid กับ tp_bid_price / sl_bid_price
→ ตรวจ SESSION_END สำหรับ position ที่ค้างข้ามรอบ session
→ ส่ง close_event list กลับไป Orchestrator → Phase 8 update + Phase 9 Discord

Close priority (elif chain — ตรวจตามลำดับ):
  1. TP          — current_bid >= tp_bid_price
  2. SL          — current_bid <= sl_bid_price
  3. SESSION_END — ตลาดปิด AND position เปิดใน session นี้

P&L basis (เหมือน Phase 6):
  realized_pnl_thb = (close_bid − entry_ask) × gold_weight
  pnl_pct          = realized_pnl_thb / actual_cost_thb × 100

Key design:
  • pos["id"] = Supabase PRIMARY KEY = position_id จาก Phase 5
  • close_at ส่งเป็น ISO string (timezone-aware) — Supabase TIMESTAMPTZ
  • fetch_open_positions_from_supabase() lazy import → ไม่ circular import
  • is_market_hours / get_current_session / position_opened_this_session
    เป็น public functions — ใช้ใน Orchestrator (Job A early-return) ด้วย
"""

from __future__ import annotations

import logging
from datetime import datetime

import pytz

from config.settings import SESSION_HOURS, TIMEZONE

logger = logging.getLogger("trading")
TZ     = pytz.timezone(TIMEZONE)


# ─── Session Helpers (public — ใช้ใน Orchestrator ด้วย) ──────────────────────

def is_market_hours(dt: datetime) -> bool:
    """
    True ถ้า dt อยู่ในช่วงเวลาตลาดเปิด (Morning / Afternoon / Night)
    dt ควรเป็น timezone-aware (Asia/Bangkok) แต่รองรับ naive ด้วย
    """
    minutes = dt.hour * 60 + dt.minute
    return any(start <= minutes < end for start, end in SESSION_HOURS.values())


def get_current_session(dt: datetime) -> str:
    """
    คืนชื่อ session ที่ dt อยู่: "Morning" / "Afternoon" / "Night" / "Closed"
    """
    minutes = dt.hour * 60 + dt.minute
    for name, (start, end) in SESSION_HOURS.items():
        if start <= minutes < end:
            return name
    return "Closed"


def _last_active_session(dt: datetime) -> str | None:
    """
    คืน session ที่เพิ่งปิดก่อน dt ("session ล่าสุดที่ผ่านมาในวันนี้")

    ใช้ใน SESSION_END check:
    ตอนตลาดปิด get_current_session คืน "Closed" เสมอ จึงเปรียบเทียบ
    กับ session_name ของ position ไม่ได้
    แทนที่จะเปรียบเทียบ session_name ตรงๆ ให้หา session ที่มี end_time
    ≤ current_minutes ล่าสุด → นั่นคือ session ที่เพิ่งจบ

    คืน None ถ้ายังไม่มี session ใดเปิดในวันนี้ (เช่น 06:00)

    ตัวอย่าง:
      10:30 → Morning (end=630 ≤ 630) → "Morning"
      15:20 → Afternoon (end=920 ≤ 920) → "Afternoon"
      22:00 → Night (end=1320 ≤ 1320) → "Night"
      08:00 → None (ไม่มี session จบก่อน 08:00)
    """
    minutes = dt.hour * 60 + dt.minute
    last_name: str | None = None
    last_end:  int        = -1
    for name, (start, end) in SESSION_HOURS.items():
        if end <= minutes and end > last_end:
            last_name = name
            last_end  = end
    return last_name


def position_opened_this_session(pos: dict, current_time: datetime) -> bool:
    """
    True ถ้า position ถูกเปิดใน session ที่เพิ่งปิดสนิท (= last active session)

    ทำไมไม่ใช้ get_current_session(current_time):
      ตอนตลาดปิด current session = "Closed" → เปรียบเทียบกับ "Morning" ไม่ตรง
      → SESSION_END ไม่เคย fire (spec bug)

    Fix: เปรียบเทียบ position's session กับ _last_active_session(current_time)
      10:30 → last_active = "Morning" → pos session "Morning" → True ✅
      ถัดมา 13:00 → last_active = "Morning" → pos ยังไม่ถูกปิดซ้ำ (status=CLOSED แล้ว)

    Cross-day guard:
      position จาก Night เมื่อวาน, current = Morning ของวันใหม่ (10:30)
      → last_active = "Morning", pos.session = "Night" → False ✅ ไม่ปิดซ้ำ

    Parameters
    ----------
    pos          : dict — open position record (ต้องมี "entry_time" ISO8601)
    current_time : datetime — เวลาปัจจุบัน (timezone-aware)
    """
    last_session = _last_active_session(current_time)
    if last_session is None:
        return False   # ยังไม่มี session ใดจบในวันนี้
    entry_dt     = datetime.fromisoformat(pos["entry_time"]).astimezone(TZ)
    pos_session  = get_current_session(entry_dt)
    return pos_session == last_session


# ─── Lazy DB import ───────────────────────────────────────────────────────────

def _fetch_open_positions() -> list[dict]:
    """Lazy import ป้องกัน circular dependency + unit test mock ง่าย"""
    from db.supabase_writer import fetch_open_positions_from_supabase
    return fetch_open_positions_from_supabase()


# ─── Input Validation ─────────────────────────────────────────────────────────

def _validate_position(pos: dict) -> None:
    """Raise ValueError ถ้า position record ขาด required fields"""
    required = {
        "id", "entry_ask_price", "entry_bid_price",
        "tp_bid_price", "sl_bid_price",
        "gold_weight", "actual_cost_thb", "entry_time",
    }
    missing = required - set(pos.keys())
    if missing:
        raise ValueError(
            f"[position_monitor] position '{pos.get('id', '?')}' "
            f"ขาด required fields: {sorted(missing)}"
        )


# ─── Main Public Function ─────────────────────────────────────────────────────

def monitor_positions(
    current_bid: float,
    current_time: datetime,
) -> list[dict]:
    """
    ตรวจ open positions ทั้งหมด → คืน close_events ที่ต้องปิด

    Parameters
    ----------
    current_bid  : float    — bid ราคาปัจจุบัน จาก fetch_latest_bid()
    current_time : datetime — เวลาปัจจุบัน (timezone-aware, Asia/Bangkok)

    Returns
    -------
    list[dict] — close events (อาจว่างถ้าไม่มี position ถึง TP/SL/SESSION_END)
        แต่ละ element มี:
            position_id      : str   — Supabase id ของ position
            close_reason     : str   — "TP" / "SL" / "SESSION_END"
            close_bid_price  : float — bid ณ เวลาปิด
            close_at         : str   — ISO8601 timestamp (timezone-aware)
            realized_pnl_thb : float — P&L จริง = (close_bid − entry_ask) × weight
            pnl_pct          : float — P&L เป็น % ของ actual_cost
    """
    if current_time.tzinfo is None:
        current_time = TZ.localize(current_time)

    open_positions: list[dict] = _fetch_open_positions()

    if not open_positions:
        return []

    close_events: list[dict] = []

    for pos in open_positions:
        try:
            _validate_position(pos)
        except ValueError as exc:
            logger.error(f"[position_monitor] Skipping invalid position: {exc}")
            continue

        close_event: dict | None = None

        # ── Priority 1: TP ────────────────────────────────────────────────────
        if current_bid >= pos["tp_bid_price"]:
            close_event = {
                "close_reason"   : "TP",
                "close_bid_price": current_bid,
            }

        # ── Priority 2: SL ────────────────────────────────────────────────────
        elif current_bid <= pos["sl_bid_price"]:
            close_event = {
                "close_reason"   : "SL",
                "close_bid_price": current_bid,
            }

        # ── Priority 3: SESSION_END ───────────────────────────────────────────
        # ตลาดปิด AND position นี้เปิดขึ้นมาใน session ปัจจุบัน
        # (ป้องกัน position เก่าจาก session ก่อนหน้าถูก SESSION_END ซ้ำ)
        elif (
            not is_market_hours(current_time)
            and position_opened_this_session(pos, current_time)
        ):
            close_event = {
                "close_reason"   : "SESSION_END",
                "close_bid_price": current_bid,
            }

        if close_event is None:
            continue

        # ── P&L calculation ───────────────────────────────────────────────────
        close_bid       = close_event["close_bid_price"]
        entry_ask       = pos["entry_ask_price"]
        gold_weight     = pos["gold_weight"]
        actual_cost_thb = pos["actual_cost_thb"]

        realized_pnl_thb = (close_bid - entry_ask) * gold_weight
        pnl_pct          = (
            realized_pnl_thb / actual_cost_thb * 100
            if actual_cost_thb != 0 else 0.0
        )

        close_record = {
            "position_id"     : pos["id"],
            "close_reason"    : close_event["close_reason"],
            "close_bid_price" : close_bid,
            "close_at"        : current_time.isoformat(),
            "realized_pnl_thb": realized_pnl_thb,
            "pnl_pct"         : pnl_pct,
        }
        close_events.append(close_record)

        logger.info(
            f"[position_monitor] {'✅' if close_event['close_reason'] == 'TP' else '❌'} "
            f"{close_event['close_reason']} | pos={pos['id']} | "
            f"bid={current_bid:,.2f} | "
            f"pnl={realized_pnl_thb:+.4f} THB ({pnl_pct:+.4f}%)"
        )

    return close_events