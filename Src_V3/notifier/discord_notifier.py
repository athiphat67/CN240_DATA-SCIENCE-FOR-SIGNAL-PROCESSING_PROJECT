"""
notifier/discord_notifier.py — Phase 9: Discord Notifier

Fire-and-forget Discord webhook notifications for all major trading events.

Public API:
  send_discord(content)                   — base sender (raw string)
  send_discord_buy_alert(order, signal)   — BUY opened
  send_discord_close_alert(close_event, position) — TP / SL / SESSION_END
  send_discord_error(error_msg)           — pipeline error with @mention

Design:
  • Non-blocking: all sends are fire-and-forget (exceptions logged, not raised)
  • DRY_RUN prefix: "[DRY RUN] " prepended to every message
  • Timeout: 10s per request (prevents blocking trading loop)
  • @mention (DISCORD_MENTION_ID) only on SL and ERROR events

Message formats:
  BUY     → 🟡 detailed entry + TP/SL levels + key features
  TP      → ✅ close price + hold time + P&L
  SL      → ❌ close price + hold time + P&L + @mention
  SESSION_END → 🔔 close price + hold time + P&L
  ERROR   → ⚠️ error message + @mention
  (Heartbeat is sent directly via send_discord() from Orchestrator)
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx
import pytz

from config.settings import (
    DISCORD_MENTION_ID,
    DISCORD_WEBHOOK_URL,
    DRY_RUN,
    SIGNAL_THRESHOLD,
    TIMEZONE,
)

logger = logging.getLogger("trading")
TZ = pytz.timezone(TIMEZONE)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _fmt_thb(value: float) -> str:
    """Format a THB value: ฿70,123.45"""
    return f"฿{value:,.2f}"


def _fmt_pnl(pnl_thb: float, pnl_pct: float) -> str:
    """Format P&L line: +฿6.84 (+0.685%)  or  −฿4.44 (−0.444%)"""
    sign     = "+" if pnl_thb >= 0 else "−"
    abs_thb  = abs(pnl_thb)
    abs_pct  = abs(pnl_pct)
    return f"{sign}฿{abs_thb:.2f} ({sign}{abs_pct:.3f}%)"


def _hold_minutes(entry_time_iso: str, close_time_iso: str) -> int:
    """
    Compute hold duration in minutes between entry and close.
    Both strings must be ISO8601 (timezone-aware preferred).
    """
    try:
        entry = datetime.fromisoformat(entry_time_iso)
        close = datetime.fromisoformat(close_time_iso)
        return max(0, int((close - entry).total_seconds() / 60))
    except Exception:
        return 0


def _format_bar_time(bar_time_iso: str) -> str:
    """
    "2025-08-01T09:50:00+07:00" → "01 Aug 09:50"
    Falls back to raw string on parse error.
    """
    try:
        dt = datetime.fromisoformat(bar_time_iso).astimezone(TZ)
        return dt.strftime("%-d %b %H:%M")
    except Exception:
        return bar_time_iso[:16]


def _format_time(iso: str) -> str:
    """
    "2025-08-01T10:30:00+07:00" → "10:30"
    """
    try:
        return datetime.fromisoformat(iso).astimezone(TZ).strftime("%H:%M")
    except Exception:
        return iso[11:16]


# ─── Base Sender ──────────────────────────────────────────────────────────────

def send_discord(content: str) -> None:
    """
    Send a raw Discord message. Fire-and-forget.

    Prepends "[DRY RUN] " when DRY_RUN=True.
    Silent no-op when DISCORD_WEBHOOK_URL not configured.
    Logs warning on failure — never raises.
    """
    if not DISCORD_WEBHOOK_URL:
        logger.debug("[discord] DISCORD_WEBHOOK_URL not set — skipping notification")
        return

    dry_prefix = "[DRY RUN] " if DRY_RUN else ""
    full_content = dry_prefix + content

    try:
        httpx.post(
            DISCORD_WEBHOOK_URL,
            json={"content": full_content},
            timeout=10.0,
        )
        logger.debug(f"[discord] Sent: {full_content[:80]}...")
    except Exception as exc:
        logger.warning(f"[discord] Webhook failed (non-critical): {exc}")


# ─── BUY Alert ────────────────────────────────────────────────────────────────

def send_discord_buy_alert(order: dict, signal: dict) -> None:
    """
    Send BUY signal notification with full entry details.

    Parameters
    ----------
    order  : dict — output of calculate_tp_sl() (has entry, TP/SL, weight, cost)
    signal : dict — output of evaluate_signal_gate() (has score, session, features_snap)

    Message format:
      🟡 BUY SIGNAL — HSH Gold
      ━━━━━━━━━━━━━━━━━━━━━━━━━
      📊 Score: X.XXXX  (threshold: 0.65)
      ⏰ Bar: DD Mon HH:MM  (Session)

      💰 Entry
        • Ask : ฿XX,XXX.XX · Bid : ฿XX,XXX.XX
        • Gold: X.XXXXX บาทไทย · Cost: ฿XXX.XX

      🎯 TP/SL
        • TP : ฿XX,XXX  (+฿XXX · R/R X.X)
        • SL : ฿XX,XXX  (−฿XXX)

      📈 Regime: ↑/↓ · SRVR: X.XX · RSI14: XX.X
      🆔 signal_id
    """
    score   = signal.get("ranker_score", 0.0)
    session = signal.get("session", "?")
    sig_id  = signal.get("signal_id", "?")
    bar_ts  = signal.get("bar_time", "")
    features = signal.get("features_snap", {})

    regime_arrow = "↑" if features.get("F_Regime", -1) == 1 else "↓"
    srvr         = features.get("F_SRVR", 0.0)
    rsi14        = features.get("F_RSI_14", 0.0)

    ask     = order.get("entry_ask_price", 0.0)
    bid     = order.get("entry_bid_price", 0.0)
    weight  = order.get("gold_weight", 0.0)
    cost    = order.get("actual_cost_thb", 0.0)
    tp_bid  = order.get("tp_bid_price", 0.0)
    sl_bid  = order.get("sl_bid_price", 0.0)
    tp_dist = order.get("tp_distance_thb", 0.0)
    sl_dist = order.get("sl_distance_thb", 0.0)
    rr      = order.get("risk_reward_ratio", 0.0)

    msg = (
        f"🟡 **BUY SIGNAL — HSH Gold**\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 **Score:** {score:.4f}  (threshold: {SIGNAL_THRESHOLD})\n"
        f"⏰ **Bar:** {_format_bar_time(bar_ts)} ({session})\n"
        f"\n"
        f"💰 **Entry**\n"
        f"  • Ask : {_fmt_thb(ask)} · Bid : {_fmt_thb(bid)}\n"
        f"  • Gold: {weight:.5f} บาทไทย · Cost: {_fmt_thb(cost)}\n"
        f"\n"
        f"🎯 **TP/SL**\n"
        f"  • TP : {_fmt_thb(tp_bid)}  (+฿{tp_dist:.0f} · R/R {rr:.1f})\n"
        f"  • SL : {_fmt_thb(sl_bid)}  (−฿{sl_dist:.0f})\n"
        f"\n"
        f"📈 Regime: {regime_arrow} · SRVR: {srvr:.2f} · RSI14: {rsi14:.1f}\n"
        f"🆔 `{sig_id}`"
    )
    send_discord(msg)


# ─── Close Alert (TP / SL / SESSION_END) ─────────────────────────────────────

def send_discord_close_alert(close_event: dict, position: dict) -> None:
    """
    Send close notification for TP, SL, or SESSION_END.

    SL events include @mention for DISCORD_MENTION_ID.

    Parameters
    ----------
    close_event : dict — from monitor_positions() (Phase 7)
        Keys: close_reason, close_bid_price, close_at, realized_pnl_thb, pnl_pct
    position    : dict — open position record from Supabase
        Keys: entry_time, entry_ask_price, id

    Message format (TP):
      ✅ TAKE PROFIT — HSH Gold
      🕐 HH:MM · ฿XX,XXX.XX · Hold: XXm
      💵 P&L: +฿X.XX (+X.XXX%)

    Message format (SL):
      ❌ STOP LOSS — HSH Gold <@mention>
      🕐 HH:MM · ฿XX,XXX.XX · Hold: XXm
      💵 P&L: −฿X.XX (−X.XXX%)

    Message format (SESSION_END):
      🔔 SESSION END — HSH Gold
      🕐 HH:MM · ฿XX,XXX.XX · Hold: XXm
      💵 P&L: ±฿X.XX (±X.XXX%)
    """
    reason       = close_event.get("close_reason", "UNKNOWN")
    close_bid    = close_event.get("close_bid_price", 0.0)
    close_at     = close_event.get("close_at", "")
    pnl_thb      = close_event.get("realized_pnl_thb", 0.0)
    pnl_pct      = close_event.get("pnl_pct", 0.0)
    entry_time   = position.get("entry_time", "")
    hold_min     = _hold_minutes(entry_time, close_at)

    if reason == "TP":
        header  = "✅ **TAKE PROFIT — HSH Gold**"
        mention = ""
    elif reason == "SL":
        mention = f" <@{DISCORD_MENTION_ID}>" if DISCORD_MENTION_ID else ""
        header  = f"❌ **STOP LOSS — HSH Gold**{mention}"
        mention = ""   # already in header
    else:  # SESSION_END
        header  = "🔔 **SESSION END — HSH Gold**"
        mention = ""

    msg = (
        f"{header}\n"
        f"🕐 {_format_time(close_at)} · {_fmt_thb(close_bid)} · Hold: {hold_min}m\n"
        f"💵 P&L: **{_fmt_pnl(pnl_thb, pnl_pct)}**"
    )
    send_discord(msg)


# ─── Error Alert ──────────────────────────────────────────────────────────────

def send_discord_error(error_msg: str) -> None:
    """
    Send pipeline error alert with @mention (DISCORD_MENTION_ID).
    Used by Orchestrator on unhandled exceptions in Job A / B.
    """
    mention = f" <@{DISCORD_MENTION_ID}>" if DISCORD_MENTION_ID else ""
    msg = f"⚠️ **Pipeline Error**{mention}\n```\n{error_msg}\n```"
    send_discord(msg)