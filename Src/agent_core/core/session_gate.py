"""
Session Gate — ใช้เมื่อรันอยู่ในช่วง session เทรด (ออม NOW / condition_trade.md)

- เรียกก่อนเข้า LLM: ส่งบริบท session_id, ใกล้ปิด session หรือไม่, โหมด Edge vs Quota
- โควต้าไม้ต่อ session เป็นแค่ข้อมูลประกอบ — อนุญาตเทรดเกิน quota ได้ (ไม่บล็อก)
- ถ้าเวลาอยู่นอกช่วง session (รวม dead zone) → apply_gate=False ผู้เรียกไม่ต้องแปะบริบท gate
- force_bypass=True → ไม่ผ่าน gate แม้อยู่ในช่วง session (เช่น ทดสอบ)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None  # type: ignore

DEFAULT_TZ = "Asia/Bangkok"
URGENT_MINUTES_DEFAULT = 15
EMERGENCY_BUY_MINUTES = 20
EMERGENCY_SELL_MINUTES = 5

# วันจันทร์=0 ... อาทิตย์=6
_WEEKEND_DAYS = {5, 6}


@dataclass(frozen=True)
class SessionWindow:
    """ช่วงเวลาในวันเดียว (นาทีจากเที่ยงคืน inclusive)"""

    start_min: int  # inclusive
    end_min: int  # inclusive (ใช้เทียบกับเวลาปัจจุบันแบบนาทีเดียวกัน)
    session_id: str
    quota_group_id: str


def _t(h: int, m: int) -> int:
    return h * 60 + m


# ตารางตาม Src/agent_core/condition_trade.md — วันธรรมดา
_WEEKDAY_WINDOWS: tuple[SessionWindow, ...] = (
    SessionWindow(_t(0, 0), _t(1, 59), "evening", "evening"),
    SessionWindow(_t(6, 15), _t(11, 59), "morning", "morning"),
    SessionWindow(_t(12, 0), _t(17, 59), "noon", "noon"),
    SessionWindow(_t(18, 0), _t(23, 59), "evening", "evening"),
)

# เสาร์–อาทิตย์
_WEEKEND_WINDOWS: tuple[SessionWindow, ...] = (
    SessionWindow(_t(0, 0), _t(1, 59), "evening", "evening"),  # Continuation of evening session
    SessionWindow(_t(9, 30), _t(17, 30), "weekend", "weekend"),
)


@dataclass
class SessionGateResult:
    """ผลจาก resolve_session_gate — แปะลง market_state['session_gate'] เมื่อ apply_gate เป็น True"""

    apply_gate: bool
    session_id: Optional[str] = None
    quota_group_id: Optional[str] = None
    session_start_iso: Optional[str] = None  # ✅ [NEW] ISO timestamp ของจุดเริ่ม session
    quota_urgent: bool = False
    minutes_to_session_end: Optional[int] = None
    llm_mode: Optional[str] = None  # "edge" | "quota"
    suggested_min_confidence: Optional[float] = None
    notes: List[str] = field(default_factory=list)

    def to_market_dict(self) -> Dict[str, Any]:
        return {
            "apply_gate": self.apply_gate,
            "session_id": self.session_id,
            "quota_group_id": self.quota_group_id,
            "session_start_iso": self.session_start_iso,  # ✅ [NEW]
            "quota_urgent": self.quota_urgent,
            # ✅ [FIX Bug 1] alias keys ที่ risk.py ต้องการ
            "near_session_end": self.quota_urgent,            # alias → quota_urgent
            "is_dead_zone": not self.apply_gate,              # ✅ Gate 0a ต้องการ
            "minutes_to_session_end": self.minutes_to_session_end,
            "llm_mode": self.llm_mode,
            "suggested_min_confidence": self.suggested_min_confidence,
            "notes": list(self.notes),
            "trades_this_session": 0,  # ✅ default; inject จริงผ่าน attach_session_gate_to_market_state
            "is_emergency_buy": False,
            "is_emergency_sell": False,
            "emergency_mode": None,
            "emergency_reason": None,
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

    # ✅ [FIX] Handle cross-midnight session (evening part 1 -> part 2)
    # If the window ends at 23:59 and there is a continuation at 00:00 of the same session
    if win.end_min == _t(23, 59):
        next_win = _find_window(windows, 0)
        if next_win and next_win.session_id == win.session_id:
            mins_left += (next_win.end_min + 1)

    quota_urgent = 0 <= mins_left <= urgent_threshold_minutes

    if quota_urgent:
        llm_mode = "quota"
        suggested = 0.58
        notes.append(
            f"Near session end (~{mins_left} min left) — Quota mode: focus fast setups; suggested confidence around {suggested}."
        )
    else:
        llm_mode = "edge"
        suggested = 0.62
        notes.append(
            f"Edge mode: prefer quality setups with solid confirmation; suggested confidence around {suggested}."
        )

    if quota_snapshot:
        notes.append(f"quota_snapshot (informational only): {quota_snapshot!r}")

    # คำนวณ ISO timestamp ของจุดเริ่ม session สำหรับ query DB.
    # ช่วง 00:00-01:59 เป็น continuation ของ evening session วันก่อนหน้า
    # จึงต้องนับ trade ตั้งแต่ 18:00 ของวันก่อน ไม่ใช่เริ่มใหม่ที่ 00:00
    start_anchor = now
    start_min = win.start_min
    if win.start_min == 0:
        prev_anchor = now - timedelta(days=1)
        prev_windows = (
            _WEEKEND_WINDOWS
            if prev_anchor.weekday() in _WEEKEND_DAYS
            else _WEEKDAY_WINDOWS
        )
        prev_win = next(
            (
                w for w in prev_windows
                if w.session_id == win.session_id and w.end_min == _t(23, 59)
            ),
            None,
        )
        if prev_win is not None:
            start_anchor = prev_anchor
            start_min = prev_win.start_min

    start_dt = start_anchor.replace(
        hour=start_min // 60,
        minute=start_min % 60,
        second=0,
        microsecond=0,
    )
    session_start_iso = (
        start_dt.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )

    return SessionGateResult(
        apply_gate=True,
        session_id=win.session_id,
        quota_group_id=win.quota_group_id,
        session_start_iso=session_start_iso,
        quota_urgent=quota_urgent,
        minutes_to_session_end=mins_left,
        llm_mode=llm_mode,
        suggested_min_confidence=suggested,
        notes=notes,
    )


def attach_session_gate_to_market_state(
    market_state: dict,
    result: SessionGateResult,
    trades_this_session: int = 0,  # ✅ [FIX Bug 1] inject ค่าจริงจาก portfolio
    gold_grams: float = 0.0,
) -> None:
    """อัปเดต market_state ในก้อนเดียว — ลบ key ถ้าไม่ใช้ gate"""
    if result.apply_gate:
        d = result.to_market_dict()
        d["trades_this_session"] = trades_this_session  # inject ค่าจริง
        mins_left = d.get("minutes_to_session_end")
        held_gold = float(gold_grams or 0.0)

        is_emergency_sell = (
            mins_left is not None
            and mins_left <= EMERGENCY_SELL_MINUTES
            and held_gold > 1e-4
        )
        is_emergency_buy = (
            not is_emergency_sell
            and mins_left is not None
            and mins_left <= EMERGENCY_BUY_MINUTES
            and int(trades_this_session or 0) == 0
            and held_gold <= 1e-4
        )

        d["is_emergency_buy"] = is_emergency_buy
        d["is_emergency_sell"] = is_emergency_sell
        if is_emergency_sell:
            d["emergency_mode"] = "forced_sell"
            d["emergency_reason"] = (
                f"Session ends in {mins_left} mins and portfolio holds {held_gold:.4f}g."
            )
        elif is_emergency_buy:
            d["emergency_mode"] = "forced_buy"
            d["emergency_reason"] = (
                f"Session ends in {mins_left} mins and zero trades completed."
            )
        market_state["session_gate"] = d
    else:
        market_state.pop("session_gate", None)
