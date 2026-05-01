"""
Session Gate — ใช้เมื่อรันอยู่ในช่วง session เทรด (ออม NOW / condition_trade.md)

- เรียกก่อนเข้า LLM: ส่งบริบท session_id, ใกล้ปิด session หรือไม่, โหมด Edge vs Quota
- โควต้าไม้ต่อ session เป็นแค่ข้อมูลประกอบ — อนุญาตเทรดเกิน quota ได้ (ไม่บล็อก)
- ถ้าเวลาอยู่นอกช่วง session (รวม dead zone) → apply_gate=False ผู้เรียกไม่ต้องแปะบริบท gate
- force_bypass=True → ไม่ผ่าน gate แม้อยู่ในช่วง session (เช่น ทดสอบ)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any, Dict, List, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore

DEFAULT_TZ = "Asia/Bangkok"
URGENT_MINUTES_DEFAULT = 15

# วันจันทร์=0 ... อาทิตย์=6
_WEEKEND_DAYS = {5, 6}


@dataclass(frozen=True)
class SessionWindow:
    """ช่วงเวลาในวันเดียว (นาทีจากเที่ยงคืน inclusive)"""

    start_min: int  # inclusive
    end_min: int  # inclusive (ใช้เทียบกับเวลาปัจจุบันแบบนาทีเดียวกัน)
    session_id: str
    quota_group_id: str
    session_index: int  # [v4.0] 0=morning, 1=noon, 2=evening, 3=weekend — สำหรับ quota tracking


def _t(h: int, m: int) -> int:
    return h * 60 + m


# ตารางตาม spec (วันธรรมดา):
#   เช้า  06:00–11:59   (6 ชม.)
#   บ่าย  12:00–17:59   (6 ชม.)
#   เย็น  18:00–23:59 + 00:00–02:00 วันถัดไป (8 ชม. รวมกัน)
#
# [BUG 4 FIX] แก้ 3 จุด:
#   1. ลบ "night" window เดิม (0:00-1:59) — ช่วงนี้คือส่วนต่อเนื่องของ "evening" ตาม spec
#   2. เพิ่ม window 0:00-2:00 เป็น "evening" (วันถัดไปต่อจาก 18:00-23:59)
#   3. เลื่อน morning start จาก 6:15 → 6:00 ให้ตรง spec
_WEEKDAY_WINDOWS: tuple[SessionWindow, ...] = (
    SessionWindow(_t(0, 0),  _t(2, 0),   "evening", "evening", 2),   # ต่อเนื่องจาก evening วันก่อน (FIX: 01:59→02:00)
    SessionWindow(_t(6, 0),  _t(11, 59), "morning", "morning", 0),
    SessionWindow(_t(12, 0), _t(17, 59), "noon",    "noon",    1),
    SessionWindow(_t(18, 0), _t(23, 59), "evening", "evening", 2),
)

# เสาร์–อาทิตย์
_WEEKEND_WINDOWS: tuple[SessionWindow, ...] = (
    SessionWindow(_t(9, 30), _t(17, 30), "weekend", "weekend", 0),
)


@dataclass
class SessionGateResult:
    """ผลจาก resolve_session_gate — แปะลง market_state['session_gate'] เมื่อ apply_gate เป็น True"""

    apply_gate: bool
    session_id: Optional[str] = None
    quota_group_id: Optional[str] = None
    quota_urgent: bool = False
    minutes_to_session_end: Optional[int] = None
    llm_mode: Optional[str] = None  # "edge" | "quota"
    suggested_min_confidence: Optional[float] = None
    session_index: int = -1        # [v4.0] 0=morning, 1=noon, 2=evening, 3=weekend
    notes: List[str] = field(default_factory=list)

    def to_market_dict(self) -> Dict[str, Any]:
        return {
            "apply_gate": self.apply_gate,
            "session_id": self.session_id,
            "quota_group_id": self.quota_group_id,
            "quota_urgent": self.quota_urgent,
            "minutes_to_session_end": self.minutes_to_session_end,
            "llm_mode": self.llm_mode,
            "suggested_min_confidence": self.suggested_min_confidence,
            "session_index": self.session_index,
            "notes": list(self.notes),
        }


def _now_local(tz_name: str) -> datetime:
    if ZoneInfo is None:
        raise RuntimeError("zoneinfo required (Python 3.9+)")
    tz = ZoneInfo(tz_name)
    return datetime.now(tz)


def _minute_of_day(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def _find_window(windows: tuple[SessionWindow, ...], minute: int) -> Optional[SessionWindow]:
    for w in windows:
        if w.start_min <= minute <= w.end_min:
            return w
    return None


def resolve_session_gate(
    now: Optional[datetime] = None,
    *,
    tz_name: str = DEFAULT_TZ,
    force_bypass: bool = False,
    urgent_threshold_minutes: int = URGENT_MINUTES_DEFAULT,
    quota_snapshot: Optional[Dict[str, Any]] = None,
) -> SessionGateResult:
    """
    คืนผลว่าควรแปะ Session Gate ก่อน LLM หรือไม่

    Parameters
    ----------
    now
        เวลาปัจจุบัน (ควรมี tz); ถ้า None ใช้เวลา Asia/Bangkok
    force_bypass
        True = ไม่ใช้ gate แม้อยู่ในช่วง session
    urgent_threshold_minutes
        เหลือเวลาไม่เกิน N นาทีถึงปลายช่วง → quota_urgent และโหมด Quota
    quota_snapshot
        ข้อมูลเสริม (ไม่บังคับ) เช่น จำนวนไม้ที่ทำแล้ว — ใช้แค่ใส่ใน notes ไม่บล็อกการเทรด
    """
    notes: List[str] = [
        "Minimum per-session trade counts are informational; recommending BUY/SELL beyond quota is allowed.",
    ]

    if force_bypass:
        return SessionGateResult(apply_gate=False, notes=["Session gate bypassed (force_bypass=True)."])

    if now is None:
        now = _now_local(tz_name)
    elif now.tzinfo is None and ZoneInfo is not None:
        now = now.replace(tzinfo=ZoneInfo(tz_name))

    dow = now.weekday()
    minute = _minute_of_day(now)

    if dow in _WEEKEND_DAYS:
        windows = _WEEKEND_WINDOWS
    else:
        windows = _WEEKDAY_WINDOWS

    win = _find_window(windows, minute)
    if win is None:
        return SessionGateResult(
            apply_gate=False,
            notes=["Outside trading session window — session gate not applied."],
        )

    mins_left = win.end_min - minute
    quota_urgent = 0 < mins_left <= urgent_threshold_minutes

    if quota_urgent:
        llm_mode = "quota"
        suggested = 0.1
        notes.append(
            f"Near session end (~{mins_left} min left) — Quota mode: focus fast setups; suggested confidence around {suggested}."
        )
    else:
        llm_mode = "edge"
        suggested = 0.2
        notes.append(
            f"Edge mode: prefer quality setups with solid confirmation; suggested confidence around {suggested}."
        )

    if quota_snapshot:
        notes.append(f"quota_snapshot (informational only): {quota_snapshot!r}")

    return SessionGateResult(
        apply_gate=True,
        session_id=win.session_id,
        quota_group_id=win.quota_group_id,
        quota_urgent=quota_urgent,
        minutes_to_session_end=mins_left,
        llm_mode=llm_mode,
        suggested_min_confidence=suggested,
        session_index=win.session_index,   # [v4.0]
        notes=notes,
    )


def attach_session_gate_to_market_state(
    market_state: dict,
    result: SessionGateResult,
) -> None:
    """อัปเดต market_state ในก้อนเดียว — ลบ key ถ้าไม่ใช้ gate"""
    if result.apply_gate:
        market_state["session_gate"] = result.to_market_dict()
    else:
        market_state.pop("session_gate", None)