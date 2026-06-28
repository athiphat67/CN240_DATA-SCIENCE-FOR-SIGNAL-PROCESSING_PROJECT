# notification/telegram_notifier.py
# GoldTrader v3.3 — Telegram Notification

import os
import html
import httpx
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# Format Helpers
# ─────────────────────────────────────────────

_SIGNAL_EMOJI = {
    "BUY":  "🟢",
    "SELL": "🔴",
    "HOLD": "🟡",
}

_CONFIDENCE_BAR_FILLED   = "█"
_CONFIDENCE_BAR_EMPTY    = "░"
_CONFIDENCE_BAR_LENGTH   = 10


def _confidence_bar(confidence: float) -> str:
    """Render a simple text progress bar for confidence level"""
    filled = max(0, min(_CONFIDENCE_BAR_LENGTH, round(confidence * _CONFIDENCE_BAR_LENGTH)))
    bar    = _CONFIDENCE_BAR_FILLED * filled + _CONFIDENCE_BAR_EMPTY * (_CONFIDENCE_BAR_LENGTH - filled)
    return f"<code>{bar}</code> {confidence:.0%}"


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
# Notifier
# ─────────────────────────────────────────────

class TelegramNotifier:
    def __init__(self):
        self.token        = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id      = os.environ.get("TELEGRAM_CHAT_ID", "")
        self.enabled      = os.environ.get("TELEGRAM_NOTIFY_ENABLED", "true").lower() == "true"
        self.notify_hold  = os.environ.get("TELEGRAM_NOTIFY_HOLD", "true").lower() == "true"
        self.min_conf     = float(os.environ.get("TELEGRAM_NOTIFY_MIN_CONF", "0.0"))
        
        self.api_url      = f"https://api.telegram.org/bot{self.token}/sendMessage"
        self._last_error: Optional[str] = None

    def notify(
        self,
        voting_result: dict,
        provider: str,
        period: str,
        interval_results: Optional[dict] = None,
        market_state: Optional[dict] = None,
        run_id: Optional[int] = None,
        **kwargs # ดักเผื่อโค้ดหลักมีการโยน arguments อื่นมาเพิ่ม
    ) -> bool:
        
        if not self.enabled or not self.token or not self.chat_id:
            self._last_error = "Telegram Notifier disabled or missing credentials"
            return False

        # ป้องกัน error กรณีไม่มีการส่งข้อมูลเข้ามา
        interval_results = interval_results or {}
        market_state = market_state or {}

        final_signal = voting_result.get("final_signal", "HOLD")
        confidence   = voting_result.get("weighted_confidence", 0.0)

        if final_signal == "HOLD" and not self.notify_hold:
            return False

        if confidence < self.min_conf:
            return False

        emoji = _SIGNAL_EMOJI.get(final_signal, "⚪")

        # หา Best interval (ทำเมื่อมีข้อมูลเท่านั้น)
        best_iv = None
        best = {}
        if interval_results:
            best_iv = max(interval_results.items(), key=lambda x: x[1].get("confidence", 0))[0]
            best = interval_results[best_iv]

        # Market prices
        md        = market_state.get("market_data", {})
        sell_thb  = md.get("thai_gold_thb", {}).get("sell_price_thb")
        buy_thb   = md.get("thai_gold_thb", {}).get("buy_price_thb")
        usd_thb   = md.get("forex", {}).get("usd_thb", 0)
        spot_usd  = md.get("spot_price_usd", {}).get("price_usd_per_oz")
        spot_conf = md.get("spot_price_usd", {}).get("confidence", 1.0)

        quality       = market_state.get("data_quality", {}).get("quality_score", "good")
        quality_badge = "⚠️ Degraded data" if quality == "degraded" else "✅ Good data"

        # ── Message Builder (HTML Mode) ──────────────────────────────────────
        msg = [
            f"<b>{emoji} 🦄🦄🦄🦄 GoldTrader — {final_signal}</b>",
        ]
        
        if interval_results:
            msg.append(f"Weighted conf: <b>{confidence:.1%}</b> across {len(interval_results)} interval(s)\n")
        else:
            msg.append(f"Weighted conf: <b>{confidence:.1%}</b>\n")

        msg.append(f"<b>Signal:</b> {emoji} <b>{final_signal}</b>")
        msg.append(f"<b>Conf:</b> {_confidence_bar(confidence)}\n")

        # Trade Targets (แสดงผลเฉพาะเมื่อข้อมูลมีค่า)
        entry = best.get("entry_price")
        sl    = best.get("stop_loss")
        tp    = best.get("take_profit")
        
        if any(v is not None for v in [entry, sl, tp]):
            msg.append("<b>🎯 Target Levels</b>")
            msg.append(f"• <b>Entry:</b> {_fmt_price(entry)}")
            msg.append(f"• <b>SL:</b> {_fmt_price(sl)}")
            msg.append(f"• <b>TP:</b> {_fmt_price(tp)}\n")

        # Market Data (แสดงผลเฉพาะเมื่อข้อมูลมีค่า)
        if sell_thb or buy_thb or spot_usd:
            msg.append("<b>📈 Market Data</b>")
            if sell_thb or buy_thb:
                msg.append(f"• <b>ออม NOW:</b> {_fmt_price(sell_thb)} (Sell) | {_fmt_price(buy_thb)} (Buy)")
                usd_str = f"{usd_thb:.2f}" if usd_thb else "N/A"
                msg.append(f"• <b>USD/THB:</b> <code>{usd_str}</code>")

            if spot_usd:
                spot_conf_str = f" <i>(conf {spot_conf:.0%})</i>" if spot_conf < 0.95 else ""
                msg.append(f"• <b>Spot (XAU/USD):</b> {_fmt_usd(spot_usd)}{spot_conf_str}")
                msg.append(f"• <b>Data Quality:</b> {quality_badge}")
            msg.append("") # blank line

        # Per-Interval Breakdown
        if len(interval_results) > 1:
            msg.append("<b>📊 Breakdown</b>")
            for iv, ir in sorted(interval_results.items()):
                iv_sig   = ir.get("signal", "HOLD")
                iv_conf  = ir.get("confidence", 0.0)
                iv_emoji = _SIGNAL_EMOJI.get(iv_sig, "⚪")
                is_best  = "◀" if iv == best_iv else ""
                msg.append(f"<code>{iv:4s}</code> {iv_emoji} {iv_sig:4s} — {iv_conf:.0%} {is_best}")
            msg.append("") # blank line

        # Voting Summary
        vb = voting_result.get("voting_breakdown", {})
        if vb:
            vb_lines = []
            for sig in ["BUY", "SELL", "HOLD"]:
                data = vb.get(sig, {})
                if data.get("count", 0) > 0:
                    vb_lines.append(f"{_SIGNAL_EMOJI.get(sig,'⚪')} {sig}: {data['count']} vote(s) (w: {data.get('weighted_score', 0):.3f})")
            if vb_lines:
                msg.append("<b>🗳️ Voting</b>")
                msg.extend(vb_lines)
                msg.append("") # blank line

        # Rationale
        rationale = best.get("rationale") or best.get("reasoning", "")
        if rationale:
            rationale = html.escape(rationale) # ป้องกัน HTML Injection ในข้อความ
            if len(rationale) > 800:
                rationale = rationale[:800] + "…"
            msg.append("<b>🧠 Rationale</b>")
            msg.append(f"<i>{rationale}</i>\n")

        # Meta
        meta_parts = [f"<code>{provider}</code>", f"<code>{period}</code>"]
        if run_id:
            meta_parts.append(f"<code>#{run_id}</code>")
        msg.append("ℹ️ " + " | ".join(meta_parts))

        payload = {
            "chat_id": self.chat_id,
            "text": "\n".join(msg),
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }

        try:
            resp = httpx.post(self.api_url, json=payload, timeout=10)
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
        os.environ["TELEGRAM_NOTIFY_HOLD"] = "true" if enabled else "false"

    def update_enabled(self, enabled: bool):
        self.enabled = enabled
        os.environ["TELEGRAM_NOTIFY_ENABLED"] = "true" if enabled else "false"

    def status(self) -> dict:
        return {
            "enabled":      self.enabled,
            "notify_hold":  self.notify_hold,
            "min_conf":     self.min_conf,
            "chat_id_set":  bool(self.chat_id),
            "token_set":    bool(self.token),
            "last_error":   self._last_error,
        }