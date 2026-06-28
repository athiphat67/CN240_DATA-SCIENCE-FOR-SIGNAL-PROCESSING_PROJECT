# notification/discord_notifier.py
# GoldTrader v3.3 — Discord Webhook Notification

import os
import httpx
from datetime import datetime, timezone
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# Signal config
# ─────────────────────────────────────────────

_SIGNAL_EMOJI = {
    "BUY":  "🟢",
    "SELL": "🔴",
    "HOLD": "🟡",
}

_SIGNAL_COLOR = {
    "BUY":  0x1D9E75,   # teal green
    "SELL": 0xD85A30,   # coral red
    "HOLD": 0x888780,   # gray
}

_CONFIDENCE_BAR_FILLED   = "█"
_CONFIDENCE_BAR_EMPTY    = "░"
_CONFIDENCE_BAR_LENGTH   = 10


def _confidence_bar(confidence: float) -> str:
    """Render a simple text progress bar for confidence level"""
    # [แก้ไขแล้ว] บังคับค่าให้อยู่ในช่วง 0-10 เพื่อป้องกัน Error เวลาโมเดลส่งค่าแปลกๆ มา
    filled = max(0, min(_CONFIDENCE_BAR_LENGTH, round(confidence * _CONFIDENCE_BAR_LENGTH)))
    bar    = _CONFIDENCE_BAR_FILLED * filled + _CONFIDENCE_BAR_EMPTY * (_CONFIDENCE_BAR_LENGTH - filled)
    return f"`{bar}` {confidence:.0%}"


def _fmt_price(value, fallback: str = "N/A") -> str:
    """Format price with comma separator"""
    if value is None:
        return fallback
    try:
        return f"฿{float(value):,.0f}"
    except (ValueError, TypeError):
        return fallback


def _fmt_usd(value, fallback: str = "N/A") -> str:
    """Format USD price"""
    if value is None:
        return fallback
    try:
        return f"${float(value):,.2f}"
    except (ValueError, TypeError):
        return fallback


# ─────────────────────────────────────────────
# Embed Builder
# ─────────────────────────────────────────────

def build_embed(
    voting_result:    dict,
    interval_results: dict,
    market_state:     dict,
    provider:         str,
    period:           str,
    run_id:           Optional[int] = None,
) -> dict:
    
    # [แก้ไขแล้ว] ป้องกันกรณีไม่ได้ส่ง interval_results มา แล้วฟังก์ชัน max() พัง
    if not interval_results:
        return {
            "title": "⚠️ System Warning",
            "description": "Failed to generate embed: `interval_results` is empty.",
            "color": 0xD85A30,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    final_signal = voting_result.get("final_signal", "HOLD")
    confidence   = voting_result.get("weighted_confidence", 0.0)
    emoji        = _SIGNAL_EMOJI.get(final_signal, "⚪")
    color        = _SIGNAL_COLOR.get(final_signal, 0x888780)

    # Best interval — highest confidence
    best_iv = max(interval_results.items(), key=lambda x: x[1].get("confidence", 0))[0]
    best    = interval_results[best_iv]

    # Market prices
    md        = market_state.get("market_data", {})
    sell_thb  = md.get("thai_gold_thb", {}).get("sell_price_thb")
    buy_thb   = md.get("thai_gold_thb", {}).get("buy_price_thb")
    usd_thb   = md.get("forex", {}).get("usd_thb", 0)
    spot_usd  = md.get("spot_price_usd", {}).get("price_usd_per_oz")
    spot_conf = md.get("spot_price_usd", {}).get("confidence", 1.0)

    # Data quality warning
    quality       = market_state.get("data_quality", {}).get("quality_score", "good")
    quality_badge = "⚠️ Degraded data" if quality == "degraded" else "✅ Good data"

    now_utc = datetime.now(timezone.utc)
    ts_iso  = now_utc.isoformat()

    # ── Fields ──────────────────────────────────────────────────────────────
    fields = []

    fields.append({"name": "Signal", "value": f"{emoji} **{final_signal}**", "inline": True})
    fields.append({"name": "Confidence", "value": _confidence_bar(confidence), "inline": True})
    fields.append({"name": "\u200b", "value": "\u200b", "inline": True}) 

    entry    = best.get("entry_price")
    sl       = best.get("stop_loss")
    tp       = best.get("take_profit")

    fields.append({"name": "Entry", "value": _fmt_price(entry), "inline": True})
    fields.append({"name": "Stop Loss", "value": _fmt_price(sl), "inline": True})
    fields.append({"name": "Take Profit", "value": _fmt_price(tp), "inline": True})

    if sell_thb or buy_thb:
        fields.append({"name": "ออม NOW (Sell)", "value": _fmt_price(sell_thb), "inline": True})
        fields.append({"name": "ออม NOW (Buy)", "value": _fmt_price(buy_thb), "inline": True})
        usd_str = f"{usd_thb:.2f}" if usd_thb else "N/A"
        fields.append({"name": "USD/THB", "value": f"`{usd_str}`", "inline": True})

    if spot_usd:
        fields.append({
            "name":   "Spot (XAU/USD)",
            "value":  _fmt_usd(spot_usd) + (f" _(conf {spot_conf:.0%})_" if spot_conf < 0.95 else ""),
            "inline": True,
        })
        fields.append({"name": "Data Quality", "value": quality_badge, "inline": True})
        fields.append({"name": "\u200b", "value": "\u200b", "inline": True})

    if len(interval_results) > 1:
        breakdown_lines = []
        for iv, ir in sorted(interval_results.items()):
            iv_sig   = ir.get("signal", "HOLD")
            iv_conf  = ir.get("confidence", 0.0)
            iv_emoji = _SIGNAL_EMOJI.get(iv_sig, "⚪")
            is_best  = "◀" if iv == best_iv else ""
            breakdown_lines.append(f"`{iv:4s}` {iv_emoji} {iv_sig:4s} — {iv_conf:.0%} {is_best}")
        fields.append({"name": "📊 Per-Interval Breakdown", "value": "\n".join(breakdown_lines), "inline": False})

    vb = voting_result.get("voting_breakdown", {})
    if vb:
        vb_lines = []
        for sig in ["BUY", "SELL", "HOLD"]:
            data = vb.get(sig, {})
            if data.get("count", 0) > 0:
                vb_lines.append(f"{_SIGNAL_EMOJI.get(sig,'⚪')} {sig}: {data['count']} vote(s) — weighted {data.get('weighted_score', 0):.3f}")
        if vb_lines:
            fields.append({"name": "🗳️ Voting Summary", "value": "\n".join(vb_lines), "inline": False})

    rationale = best.get("rationale") or best.get("reasoning", "")
    if rationale:
        if len(rationale) > 900:
            rationale = rationale[:900] + "…"
        fields.append({"name": "🧠 Rationale", "value": rationale, "inline": False})

    meta_parts = [f"Provider: `{provider}`", f"Period: `{period}`"]
    if run_id:
        meta_parts.append(f"Run ID: `#{run_id}`")
    fields.append({"name": "ℹ️ Meta", "value": " | ".join(meta_parts), "inline": False})

    return {
        "title":       f"{emoji} GoldTrader — {final_signal} - 🦄🦄🦄🦄🦄🦄🦄",
        "description": f"Weighted confidence: **{confidence:.1%}** across {len(interval_results)} interval(s)",
        "color":       color,
        "fields":      fields,
        "footer":      {"text": "GoldTrader v3.3 | ออม NOW Platform"},
        "timestamp":   ts_iso,
    }


# ─────────────────────────────────────────────
# Notifier
# ─────────────────────────────────────────────

class DiscordNotifier:
    def __init__(self):
        self.webhook_url  = os.environ.get("DISCORD_WEBHOOK_URL", "")
        self.enabled      = os.environ.get("DISCORD_NOTIFY_ENABLED", "true").lower() == "true"
        self.notify_hold  = os.environ.get("DISCORD_NOTIFY_HOLD", "true").lower() == "true"
        self.min_conf     = float(os.environ.get("DISCORD_NOTIFY_MIN_CONF", "0.0"))
        self._last_error: Optional[str] = None

    def notify(
        self,
        voting_result:    dict,
        interval_results: dict,
        market_state:     dict,
        provider:         str,
        period:           str,
        run_id:           Optional[int] = None,
    ) -> bool:
        
        if not self.enabled:
            return False

        if not self.webhook_url:
            self._last_error = "DISCORD_WEBHOOK_URL not set"
            return False

        final_signal = voting_result.get("final_signal", "HOLD")
        confidence   = voting_result.get("weighted_confidence", 0.0)

        if final_signal == "HOLD" and not self.notify_hold:
            return False

        if confidence < self.min_conf:
            return False

        try:
            embed = build_embed(
                voting_result=voting_result,
                interval_results=interval_results,
                market_state=market_state,
                provider=provider,
                period=period,
                run_id=run_id,
            )
            payload = {
                "username":   "GoldTrader 🟡",
                "avatar_url": "https://em-content.zobj.net/source/twitter/376/bar-chart_1f4ca.png",
                "embeds":     [embed],
            }
            # Timeout 10 วิ ยังคงอยู่ เพื่อป้องกันเน็ตค้างนานเกินไป
            resp = httpx.post(self.webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            self._last_error = None
            return True

        except httpx.HTTPStatusError as e:
            self._last_error = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            return False
        except Exception as e:
            self._last_error = str(e)
            return False

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def update_hold_toggle(self, enabled: bool):
        self.notify_hold = enabled
        os.environ["DISCORD_NOTIFY_HOLD"] = "true" if enabled else "false"

    def update_enabled(self, enabled: bool):
        self.enabled = enabled
        os.environ["DISCORD_NOTIFY_ENABLED"] = "true" if enabled else "false"

    def status(self) -> dict:
        return {
            "enabled":      self.enabled,
            "notify_hold":  self.notify_hold,
            "min_conf":     self.min_conf,
            "webhook_set":  bool(self.webhook_url),
            "last_error":   self._last_error,
        }