"""
ui/navbar/analysis_page.py
📊 Live Analysis — navbar page (v4 redesign)

Layout:
  ┌─────────────────────────────────────────────────────┐
  │  STATUS BAR (full width) — signal · conf · last run │
  ├──────────────┬──────────────────────────────────────┤
  │  LEFT        │  RIGHT (อัพเดทเฉพาะส่วนนี้)          │
  │  Controls    │  ● Signal Card (hero, big)            │
  │  - Provider  │  ● Market State (4-section grid)      │
  │  - Period    │  ● Final Decision (text)              │
  │  - Interval  │  ● Step Reasoning (accordion)         │
  │  - Auto-run  │                                       │
  │  - Run btn   │                                       │
  └──────────────┴──────────────────────────────────────┘

v4 changes vs v3:
  - Log tabs removed → moved to new 🪵 Logs page
  - History/Stats removed → live in 📜 History page
  - run_outputs: 10 → 6 (cleaner)
  - gr.update() on disabled auto-run (no flicker)
  - Signal card is the hero element
  - Controls column never re-renders
"""

import json
import importlib
from pathlib import Path
from datetime import datetime

import gradio as gr

from ui.core.renderers import TraceRenderer, StatusRenderer
from ui.core.utils import format_error_message
from ui.core import (
    PERIOD_CHOICES,
    INTERVAL_CHOICES,
    AUTO_RUN_INTERVALS,
    DEFAULT_AUTO_RUN,
)
from ui.core.config import get_all_llm_choices
from logs.logger_setup import sys_logger, log_method

from .base import PageBase, PageComponents, AppContext, navbar_page


def _main_parser_defaults() -> dict:
    """
    Read parser defaults directly from main.py so Dashboard defaults
    follow CLI defaults without editing main.py.
    """
    try:
        cli_main = importlib.import_module("main")
        parser = cli_main._build_parser()
        defaults = vars(parser.parse_args([]))
        return {
            "provider": defaults.get("provider", "gemini-2.5-flash-lite-preview"),
            "period": defaults.get("period", "7d"),
            "interval": (defaults.get("intervals") or ["1h"])[0],
        }
    except Exception:
        return {
            "provider": "gemini-2.5-flash-lite-preview",
            "period": "7d",
            "interval": "1h",
        }


# ─────────────────────────────────────────────────────────────────
# Signal Card  (hero element — shown top-right)
# ─────────────────────────────────────────────────────────────────

def _render_signal_card_empty() -> str:
    return """
    <div style="background:#f8fafc;border:2px dashed #e9d5ff;border-radius:16px;
                padding:48px 24px;text-align:center;
                font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
        <div style="font-size:52px;margin-bottom:14px;opacity:.5;">⏳</div>
        <div style="font-size:20px;color:#94a3b8;font-weight:700;">
            กด ▶ Run Analysis เพื่อดูผล
        </div>
        <div style="font-size:13px;color:#c4b5fd;margin-top:8px;">
            หรือเปิด Auto-run เพื่อรันอัตโนมัติ
        </div>
    </div>"""


def _render_signal_card(
    signal: str,
    confidence: float,
    provider: str = "—",
    timestamp: str = "",
    interval: str = "—",
    entry_price: float = None,
    stop_loss: float = None,
    take_profit: float = None,
) -> str:
    SIG = {
        "BUY":  {"color": "#16a34a", "light": "#f0fdf4", "border": "#86efac", "icon": "🟢"},
        "SELL": {"color": "#dc2626", "light": "#fef2f2", "border": "#fca5a5", "icon": "🔴"},
        "HOLD": {"color": "#d97706", "light": "#fffbeb", "border": "#fcd34d", "icon": "🟡"},
    }
    s = SIG.get(signal, SIG["HOLD"])
    bar_pct = int(confidence * 100)

    # Price levels row
    def _price_item(label: str, value, color: str) -> str:
        v = f"฿{value:,.0f}" if value else "—"
        return (
            f'<div style="text-align:center;flex:1;">'
            f'<div style="font-size:10px;color:#6b7280;text-transform:uppercase;'
            f'letter-spacing:.1em;margin-bottom:5px;">{label}</div>'
            f'<div style="font-size:17px;font-weight:800;color:{color};">{v}</div>'
            f'</div>'
        )

    price_section = ""
    if any([entry_price, stop_loss, take_profit]):
        price_section = (
            f'<div style="display:flex;justify-content:space-around;align-items:center;'
            f'margin-top:20px;padding:14px 12px;'
            f'background:rgba(0,0,0,0.04);border-radius:12px;gap:8px;">'
            f'{_price_item("Entry", entry_price, "#374151")}'
            f'<div style="width:1px;height:32px;background:#e5e7eb;"></div>'
            f'{_price_item("Stop Loss", stop_loss, "#dc2626")}'
            f'<div style="width:1px;height:32px;background:#e5e7eb;"></div>'
            f'{_price_item("Take Profit", take_profit, "#16a34a")}'
            f'</div>'
        )

    # Meta row
    ts_display = timestamp[-8:] if timestamp and len(timestamp) > 8 else timestamp
    meta_parts = []
    if provider and provider != "—":
        meta_parts.append(f"🤖 {provider}")
    if interval and interval != "—":
        meta_parts.append(f"⏱ {interval}")
    if ts_display:
        meta_parts.append(f"🕐 {ts_display}")
    meta_html = (
        '<div style="font-size:11px;color:#9ca3af;margin-top:14px;'
        'display:flex;gap:16px;flex-wrap:wrap;justify-content:center;">'
        + "".join(f"<span>{m}</span>" for m in meta_parts)
        + "</div>"
    ) if meta_parts else ""

    return f"""
    <div style="background:{s['light']};
                border:2px solid {s['border']};
                border-top:4px solid {s['color']};
                border-radius:16px;padding:28px 24px;text-align:center;
                box-shadow:0 4px 24px rgba(0,0,0,0.08);
                font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">

        <!-- Purple-Gold AI badge -->
        <div style="display:inline-block;
                    background:linear-gradient(135deg,#6D28D9 0%,#D97706 100%);
                    border-radius:20px;padding:4px 14px;
                    font-size:10px;color:#fff;font-weight:800;
                    letter-spacing:.15em;margin-bottom:16px;
                    box-shadow:0 2px 8px rgba(109,40,217,0.30);">
            ✨ AI SIGNAL
        </div>

        <!-- Big Signal text -->
        <div style="font-size:56px;font-weight:900;color:{s['color']};
                    line-height:1;margin-bottom:8px;letter-spacing:-.02em;">
            {s['icon']} {signal}
        </div>

        <!-- Confidence label -->
        <div style="font-size:12px;color:#6b7280;margin-bottom:6px;
                    text-transform:uppercase;letter-spacing:.1em;">Confidence</div>

        <!-- Confidence bar -->
        <div style="background:#e5e7eb;border-radius:99px;height:8px;
                    margin:0 auto 8px;max-width:280px;overflow:hidden;">
            <div style="background:linear-gradient(90deg,{s['color']},{s['color']}cc);
                        border-radius:99px;height:8px;width:{bar_pct}%;
                        transition:width .6s ease;"></div>
        </div>

        <!-- Confidence number -->
        <div style="font-size:32px;font-weight:900;color:{s['color']};
                    letter-spacing:-.01em;">
            {confidence:.0%}
        </div>

        {price_section}
        {meta_html}
    </div>"""


# ─────────────────────────────────────────────────────────────────
# Status Bar  (full-width top strip)
# ─────────────────────────────────────────────────────────────────

def _render_status_bar_empty() -> str:
    return """
    <div style="background:linear-gradient(135deg,#faf5ff 0%,#fffbeb 100%);
                border:1px solid #e9d5ff;border-radius:10px;
                padding:10px 18px;
                font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
                display:flex;align-items:center;gap:10px;
                font-size:12px;color:#a78bfa;">
        <span>⏳</span>
        <span>ยังไม่มีข้อมูล — กด ▶ Run Analysis หรือเปิด Auto-run</span>
    </div>"""


def _render_status_bar(
    signal: str = "",
    confidence: float = 0.0,
    last_run: str = "",
    provider: str = "",
    interval: str = "",
) -> str:
    if not signal:
        return _render_status_bar_empty()

    SIG_COLOR = {"BUY": "#16a34a", "SELL": "#dc2626", "HOLD": "#d97706"}
    SIG_ICON  = {"BUY": "🟢",      "SELL": "🔴",      "HOLD": "🟡"}
    color     = SIG_COLOR.get(signal, "#6b7280")
    icon      = SIG_ICON.get(signal, "⚪")
    ts        = last_run[-8:] if last_run and len(last_run) > 8 else last_run

    items = []
    if ts:
        items.append(f'<span style="color:#9ca3af;font-size:12px;">Last: <strong>{ts}</strong></span>')
    if provider:
        items.append(f'<span style="color:#9ca3af;font-size:12px;">🤖 {provider}</span>')
    if interval and interval != "—":
        items.append(f'<span style="color:#9ca3af;font-size:12px;">⏱ {interval}</span>')

    right_html = (
        '<div style="margin-left:auto;display:flex;gap:14px;align-items:center;">'
        + "".join(items)
        + "</div>"
    ) if items else ""

    return f"""
    <div style="background:linear-gradient(135deg,#faf5ff 0%,#fffbeb 100%);
                border:1px solid #e9d5ff;border-radius:10px;
                padding:10px 18px;
                font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
                display:flex;align-items:center;gap:14px;flex-wrap:wrap;
                box-shadow:0 2px 8px rgba(109,40,217,0.06);">

        <!-- Signal pill -->
        <span style="font-size:20px;font-weight:900;color:{color};
                     display:flex;align-items:center;gap:6px;">
            {icon} {signal}
        </span>

        <!-- Divider -->
        <span style="width:1px;height:20px;background:#e9d5ff;display:inline-block;"></span>

        <!-- Confidence -->
        <span style="font-size:13px;color:#6b7280;">
            Conf: <strong style="color:{color};font-size:15px;">{confidence:.0%}</strong>
        </span>

        <!-- Purple-Gold dot pulse indicator -->
        <span style="display:inline-flex;align-items:center;gap:5px;
                     background:linear-gradient(135deg,rgba(109,40,217,.08),rgba(217,119,6,.08));
                     padding:3px 10px;border-radius:99px;font-size:11px;color:#7c3aed;">
            <span style="width:6px;height:6px;border-radius:50%;
                         background:linear-gradient(135deg,#6D28D9,#D97706);
                         display:inline-block;
                         animation:pg-pulse 2s ease-in-out infinite;"></span>
            AI Active
        </span>

        {right_html}
    </div>
    <style>
    @keyframes pg-pulse {{
        0%,100% {{ opacity:1; transform:scale(1); }}
        50%      {{ opacity:.4; transform:scale(.85); }}
    }}
    </style>"""


# ─────────────────────────────────────────────────────────────────
# Market State  (structured HTML grid)
# ─────────────────────────────────────────────────────────────────

def _render_market_state(state: dict) -> str:
    if not state:
        return "<div style='color:#5a6270;padding:12px'>No data — run analysis first</div>"

    md   = state.get("market_data", {})
    ti   = state.get("technical_indicators", {})
    port = state.get("portfolio", {})
    news = state.get("news", []) 

    spot      = md.get("spot_price_usd", {}).get("price_usd_per_oz", 0)
    usd_thb   = md.get("forex", {}).get("usd_thb", 0)
    thai      = md.get("thai_gold_thb", {})
    sell_thb  = thai.get("sell_price_thb") or thai.get("spot_price_thb", 0)
    buy_thb   = thai.get("buy_price_thb")  or thai.get("spot_price_thb", 0)

    rsi_val   = float(ti.get("rsi", {}).get("value", 50))
    macd      = ti.get("macd", {})
    macd_line = float(macd.get("macd_line", 0) or 0)
    sig_line  = float(macd.get("signal_line", 0) or 0)
    hist      = float(macd.get("histogram", 0) or 0)
    trend     = ti.get("trend", {})
    ema20     = float(trend.get("ema_20", 0) or 0)
    ema50     = float(trend.get("ema_50", 0) or 0)
    bb        = ti.get("bollinger", {})
    bb_upper  = float(bb.get("upper", 0) or 0)
    bb_lower  = float(bb.get("lower", 0) or 0)
    atr_val   = float(ti.get("atr", {}).get("value", 0) or 0)

    # ── Derived interpretations ────────────────────────────────
    rsi_pct = min(max(rsi_val, 0), 100)
    if rsi_val < 30:
        rsi_label, rsi_pill, rsi_explain = "Oversold", ("pill-blue", "Possible bounce"), "Price has fallen a lot — buyers may step in"
    elif rsi_val < 50:
        rsi_label, rsi_pill, rsi_explain = "Bearish neutral", ("pill-amber", "Below midpoint"), "Momentum leaning downward"
    elif rsi_val < 60:
        rsi_label, rsi_pill, rsi_explain = "Neutral", ("pill-green", "Balanced"), "No strong signal either way"
    elif rsi_val < 70:
        rsi_label, rsi_pill, rsi_explain = "Bullish", ("pill-amber", "Near overbought"), "Strong run — may pause soon"
    else:
        rsi_label, rsi_pill, rsi_explain = "Overbought", ("pill-red", "Overbought"), "Price rose fast — pullback likely"

    macd_bull  = macd_line > sig_line
    hist_color = "#27500A" if hist > 0 else "#791F1F"
    hist_bg    = "#EAF3DE" if hist > 0 else "#FCEBEB"
    hist_sign  = "+" if hist >= 0 else ""

    trend_up   = ema20 > ema50
    trend_pill = ("pill-green", "Uptrend") if trend_up else ("pill-red", "Downtrend")
    trend_explain = "Fast average above slow — recent gains accelerating" if trend_up else "Fast average below slow — recent losses accelerating"

    bb_range = bb_upper - bb_lower if bb_upper > bb_lower else 1
    price_in_band = min(max((ema20 - bb_lower) / bb_range * 100, 0), 100)
    atr_thb = round(atr_val * usd_thb) if usd_thb else 0

    cash          = port.get("cash_balance", 0) or 0
    gold_g        = port.get("gold_grams", 0) or 0
    cost_basis    = port.get("cost_basis", 0) or 0      
    current_value = port.get("current_value", 0) or 0   
    pnl           = port.get("unrealized_pnl", 0) or 0
    trades        = port.get("trades_today", 0) or 0
    
    pnl_color = "#27500A" if pnl >= 0 else "#791F1F"
    can_buy   = cash >= 1010

    pill_css = """
    .pill-green{background:#EAF3DE;color:#27500A}
    .pill-amber{background:#FAEEDA;color:#633806}
    .pill-red{background:#FCEBEB;color:#791F1F}
    .pill-blue{background:#E6F1FB;color:#0C447C}
    """

    def pill(cls, text):
        return f'<span style="display:inline-block;font-size:10px;font-weight:500;padding:2px 7px;border-radius:4px" class="{cls}">{text}</span>'

    def card(content):
        return f'<div style="background:#fff;border:0.5px solid #e0ddd5;border-radius:12px;padding:14px 16px">{content}</div>'

    def section_lbl(t):
        return f'<div style="font-size:10px;font-weight:500;color:#5a6270;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px">{t}</div>'

    def insight(dot_color, text):
        return (f'<div style="display:flex;gap:8px;padding:6px 0;border-bottom:0.5px solid #ece9e0">'
                f'<div style="width:7px;height:7px;border-radius:50%;background:{dot_color};flex-shrink:0;margin-top:3px"></div>'
                f'<div style="font-size:12px;color:#2c2c2a">{text}</div></div>')

    rsi_gauge = f"""
    {card(f'''
    {section_lbl("RSI 14 — buying momentum")}
    <div style="display:flex;justify-content:space-between;margin-bottom:5px">
      <span style="font-size:12px;color:#5a6270">0</span>
      <span style="font-size:16px;font-weight:500;color:#171c1f">{rsi_val:.1f}</span>
      <span style="font-size:12px;color:#5a6270">100</span>
    </div>
    <div style="position:relative;height:14px;border-radius:7px;overflow:hidden">
      <div style="position:absolute;inset:0;display:flex">
        <div style="width:30%;background:#E6F1FB"></div>
        <div style="width:40%;background:#EAF3DE"></div>
        <div style="width:30%;background:#FCEBEB"></div>
      </div>
      <div style="position:absolute;top:2px;bottom:2px;width:4px;border-radius:2px;background:#2C2C2A;left:calc({rsi_pct:.1f}% - 2px)"></div>
    </div>
    <div style="display:flex;justify-content:space-between;font-size:10px;color:#5a6270;margin-top:3px">
      <span>Oversold</span><span>Neutral</span><span>Overbought</span>
    </div>
    <div style="margin-top:7px;display:flex;gap:6px;align-items:center">
      {pill(rsi_pill[0], rsi_pill[1])}
      <span style="font-size:11px;color:#5a6270">{rsi_explain}</span>
    </div>''')}"""

    macd_card = f"""
    {card(f'''
    {section_lbl("MACD — trend momentum")}
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
      {pill("pill-green" if macd_bull else "pill-red", "Bullish" if macd_bull else "Bearish")}
      <span style="font-size:11px;color:#5a6270">{"MACD above signal — buyers in control" if macd_bull else "MACD below signal — sellers in control"}</span>
    </div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:7px">
      <div style="background:#f5f3ee;border-radius:7px;padding:7px;text-align:center">
        <div style="font-size:10px;color:#5a6270;margin-bottom:2px">MACD</div>
        <div style="font-size:14px;font-weight:500;color:{"#27500A" if macd_line > 0 else "#791F1F"}">{macd_line:.3f}</div>
      </div>
      <div style="background:#f5f3ee;border-radius:7px;padding:7px;text-align:center">
        <div style="font-size:10px;color:#5a6270;margin-bottom:2px">Signal</div>
        <div style="font-size:14px;font-weight:500;color:#2c2c2a">{sig_line:.3f}</div>
      </div>
      <div style="background:{hist_bg};border-radius:7px;padding:7px;text-align:center">
        <div style="font-size:10px;color:#5a6270;margin-bottom:2px">Histogram</div>
        <div style="font-size:14px;font-weight:500;color:{hist_color}">{hist_sign}{hist:.3f}</div>
      </div>
    </div>''')}"""

    trend_card = f"""
    {card(f'''
    {section_lbl("Trend — EMA 20 vs EMA 50")}
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
      <div style="flex:1;background:#FAEEDA;border-radius:7px;padding:8px;text-align:center">
        <div style="font-size:10px;color:#854F0B">EMA 50 (slow)</div>
        <div style="font-size:15px;font-weight:500;color:#633806">{ema50:,.2f}</div>
      </div>
      <div style="font-size:20px;color:{"#3B6D11" if trend_up else "#A32D2D"};font-weight:500">{"→" if trend_up else "←"}</div>
      <div style="flex:1;background:{"#EAF3DE" if trend_up else "#FCEBEB"};border-radius:7px;padding:8px;text-align:center">
        <div style="font-size:10px;color:{"#3B6D11" if trend_up else "#A32D2D"}">EMA 20 (fast)</div>
        <div style="font-size:15px;font-weight:500;color:{"#27500A" if trend_up else "#791F1F"}">{ema20:,.2f}</div>
      </div>
    </div>
    <div style="display:flex;gap:6px;align-items:center">
      {pill(trend_pill[0], trend_pill[1])}
      <span style="font-size:11px;color:#5a6270">{trend_explain}</span>
    </div>''')}"""

    bb_card = f"""
    {card(f'''
    {section_lbl("Bollinger bands — price range")}
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-bottom:7px">
      <div style="background:#E6F1FB;border-radius:7px;padding:7px;text-align:center">
        <div style="font-size:10px;color:#0C447C">Lower (support)</div>
        <div style="font-size:13px;font-weight:500;color:#0C447C">{bb_lower:,.2f}</div>
      </div>
      <div style="background:#f5f3ee;border-radius:7px;padding:7px;text-align:center">
        <div style="font-size:10px;color:#5a6270">Mid (EMA 20)</div>
        <div style="font-size:13px;font-weight:500;color:#2c2c2a">{ema20:,.2f}</div>
      </div>
      <div style="background:#FCEBEB;border-radius:7px;padding:7px;text-align:center">
        <div style="font-size:10px;color:#791F1F">Upper (resistance)</div>
        <div style="font-size:13px;font-weight:500;color:#791F1F">{bb_upper:,.2f}</div>
      </div>
    </div>
    <div style="position:relative;height:10px;border-radius:5px;overflow:hidden;margin-bottom:6px">
      <div style="position:absolute;inset:0;background:#f5f3ee"></div>
      <div style="position:absolute;top:2px;bottom:2px;width:4px;border-radius:2px;background:#2C2C2A;left:calc({price_in_band:.1f}% - 2px)"></div>
    </div>
    <div style="font-size:11px;color:#5a6270">
      Price near upper band — tends to revert toward mid. Typical daily swing: ฿{atr_thb:,}/gram (ATR {atr_val:.2f}).
    </div>''')}"""

    # Synced styling: muted grey (#5a6270) for secondary data, dark (#2c2c2a) for primary
    portfolio_card = f"""
    {card(f'''
    {section_lbl("Portfolio")}
    <table style="width:100%;font-size:12px;border-collapse:collapse">
      <tr><td style="padding:4px 0;color:#5a6270">Cash</td><td style="text-align:right;font-weight:500;color:#2c2c2a">฿{cash:,.2f}</td></tr>
      <tr><td style="padding:4px 0;color:#5a6270">Gold held</td><td style="text-align:right;color:#5a6270">{gold_g:.4f} g</td></tr>
      <tr><td style="padding:4px 0;color:#5a6270">Cost basis</td><td style="text-align:right;color:#5a6270">฿{cost_basis:,.2f}</td></tr>
      <tr><td style="padding:4px 0;color:#5a6270">Current value</td><td style="text-align:right;font-weight:500;color:#2c2c2a">฿{current_value:,.2f}</td></tr>
      <tr><td style="padding:4px 0;color:#5a6270">Unrealized PnL</td><td style="text-align:right;font-weight:500;color:{pnl_color}">฿{pnl:,.2f}</td></tr>
      <tr><td style="padding:4px 0;color:#5a6270">Trades today</td><td style="text-align:right;color:#2c2c2a">{trades}</td></tr>
    </table>
    <div style="background:#{"EAF3DE" if can_buy else "FCEBEB"};border-radius:7px;padding:7px;margin-top:8px;font-size:11px;color:#{"27500A" if can_buy else "791F1F"}">
      {"Can enter 1 buy position (min ฿1,010)" if can_buy else f"Cannot buy — need ฿{1010 - cash:.0f} more"}
    </div>''')}"""

    # Synced styling: properly matching the muted section labels and primary text colors
    if not news:
        news_html = "<div style='font-size:11px;color:#5a6270'>ไม่มีข่าว</div>"
    elif isinstance(news, str):
        news_html = f"<div style='font-size:12px;color:#2c2c2a'>{news}</div>"
    else:
        news_items = "".join([f"<div style='font-size:12px;color:#2c2c2a;margin-bottom:4px;line-height:1.4'>• {n}</div>" for n in news])
        news_html = f"<div style='max-height:120px;overflow-y:auto;padding-right:4px'>{news_items}</div>"

    news_card = f"""
    {card(f'''
    {section_lbl("News")}
    {news_html}''')}"""

    insights = ""
    if trend_up:
        insights += insight("#639922", "Trend is up — EMA 20 is above EMA 50, recent prices rising faster")
    else:
        insights += insight("#E24B4A", "Trend is down — EMA 20 below EMA 50, recent price declining")
    if macd_bull and hist > 0:
        insights += insight("#639922", f"MACD histogram +{hist:.3f} — buying pressure growing")
    elif not macd_bull:
        insights += insight("#E24B4A", "MACD bearish — selling pressure dominating")
    if rsi_val >= 70:
        insights += insight("#BA7517", f"RSI {rsi_val:.1f} — overbought, pullback risk is high")
    elif rsi_val >= 60:
        insights += insight("#BA7517", f"RSI {rsi_val:.1f} — strong but near overbought zone")
    elif rsi_val <= 30:
        insights += insight("#378ADD", f"RSI {rsi_val:.1f} — oversold, potential bounce entry")
    if price_in_band > 75:
        insights += insight("#BA7517", "Price near upper Bollinger Band — statistically likely to revert toward mid")

    reasoning_card = f"""
    {card(f'''
    {section_lbl("Why this signal?")}
    {insights}''')}"""

    return f"""
    <style>
      .pill-green{{background:#EAF3DE;color:#27500A}}
      .pill-amber{{background:#FAEEDA;color:#633806}}
      .pill-red{{background:#FCEBEB;color:#791F1F}}
      .pill-blue{{background:#E6F1FB;color:#0C447C}}
    </style>
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:4px 0">

      <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-bottom:14px">
        <div style="background:#fff;border:0.5px solid #e0ddd5;border-radius:12px;padding:14px 16px;border-top:3px solid #888780">
          <div style="font-size:10px;font-weight:500;color:#5a6270;text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px">Signal</div>
          <div style="font-size:22px;font-weight:500;color:#888780">HOLD</div>
          <div style="font-size:11px;color:#5a6270;margin-top:2px">Confidence 50%</div>
        </div>
        <div style="background:#fff;border:0.5px solid #e0ddd5;border-radius:12px;padding:14px 16px">
          <div style="font-size:10px;font-weight:500;color:#5a6270;text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px">Gold sell price</div>
          <div style="font-size:22px;font-weight:500;color:#2c2c2a">฿{sell_thb:,}</div>
          <div style="font-size:11px;color:#5a6270;margin-top:2px">Buy ฿{buy_thb:,} · spread ฿{sell_thb - buy_thb:,}</div>
        </div>
        <div style="background:#fff;border:0.5px solid #e0ddd5;border-radius:12px;padding:14px 16px">
          <div style="font-size:10px;font-weight:500;color:#5a6270;text-transform:uppercase;letter-spacing:.06em;margin-bottom:3px">Gold in USD</div>
          <div style="font-size:22px;font-weight:500;color:#2c2c2a">${spot:,.0f}</div>
          <div style="font-size:11px;color:#5a6270;margin-top:2px">USD/THB {usd_thb:.2f}</div>
        </div>
      </div>

      <div style="display:grid;grid-template-columns:minmax(0,1.5fr) minmax(0,1fr);gap:14px">
        <div style="display:flex;flex-direction:column;gap:12px">
          {rsi_gauge}
          {macd_card}
          {trend_card}
          {bb_card}
        </div>
        <div style="display:flex;flex-direction:column;gap:12px">
          {portfolio_card}
          {news_card}
          {reasoning_card}
        </div>
      </div>
    </div>"""

# ─────────────────────────────────────────────────────────────────
# LLM Log renderers  (kept here — imported by history_page & logs_page)
# ─────────────────────────────────────────────────────────────────

def _render_llm_logs_from_trace(trace: list) -> str:
    """Render LLM call logs from react_trace list — dark terminal style."""
    if not trace:
        return "<div style='color:#888;padding:16px'>ยังไม่มี LLM log — กด ▶ Run Analysis ก่อน</div>"

    llm_steps = [
        s for s in trace
        if s.get("step", "").startswith("THOUGHT") or s.get("prompt_text")
    ]
    if not llm_steps:
        return "<div style='color:#888;padding:16px'>ไม่พบ LLM call ใน trace</div>"

    SIG_COLOR = {"BUY": "#4caf50", "SELL": "#f44336", "HOLD": "#ff9800"}
    rows_html = ""

    for idx, step in enumerate(llm_steps):
        step_label   = step.get("step", f"STEP_{idx}")
        iteration    = step.get("iteration", "—")
        response     = step.get("response", {})
        prompt_text  = step.get("prompt_text",  "")
        response_raw = step.get("response_raw", "")
        token_in     = step.get("token_input",  0)
        token_out    = step.get("token_output", 0)
        token_total  = step.get("token_total",  0)
        model        = step.get("model",    "—")
        provider     = step.get("provider", "—")
        note         = step.get("note",     "")

        sig    = response.get("signal", "")
        conf   = response.get("confidence", None)
        action = response.get("action", "")

        sig_badge = ""
        if sig:
            color = SIG_COLOR.get(sig, "#999")
            sig_badge = f'<span style="background:{color};color:#fff;border-radius:4px;padding:2px 8px;font-weight:bold;font-size:0.85em;margin-left:8px">{sig}</span>'
            if conf is not None:
                try:
                    sig_badge += f'<span style="color:#aaa;font-size:0.82em;margin-left:6px">{float(conf):.0%}</span>'
                except (TypeError, ValueError):
                    pass
        elif action:
            sig_badge = f'<span style="background:#5c6bc0;color:#fff;border-radius:4px;padding:2px 8px;font-size:0.82em;margin-left:8px">{action}</span>'

        label_color = (
            "#4caf50" if "FINAL" in step_label
            else "#42a5f5" if step_label.startswith("THOUGHT")
            else "#ff9800"
        )

        token_html = (
            f'<div style="display:flex;gap:12px;align-items:center;margin:8px 0;font-size:0.82em;color:#90caf9">'
            f'<span>IN {token_in:,}</span><span>OUT {token_out:,}</span>'
            f'<span style="color:#fff;font-weight:bold">TOTAL {token_total:,}</span>'
            f'<span style="color:#78909c">· {model} ({provider})</span></div>'
            if token_total > 0 else
            f'<div style="font-size:0.78em;color:#546e7a;margin:4px 0">· {model} ({provider}) · tokens N/A</div>'
        )

        note_html = f'<div style="color:#ffd54f;font-size:0.78em;margin-top:4px">⚠ {note}</div>' if note else ""

        prompt_section = ""
        if prompt_text:
            safe_p = prompt_text.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            prompt_section = (
                f'<details style="margin-top:10px">'
                f'<summary style="cursor:pointer;color:#80cbc4;font-size:0.85em">Full Prompt ({len(prompt_text):,} chars)</summary>'
                f'<pre style="background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:12px;margin-top:6px;'
                f'font-size:0.75em;color:#c9d1d9;white-space:pre-wrap;word-break:break-all;max-height:300px;overflow-y:auto">{safe_p}</pre>'
                f'</details>'
            )

        response_section = ""
        if response_raw:
            safe_r = response_raw.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            response_section = (
                f'<details style="margin-top:6px">'
                f'<summary style="cursor:pointer;color:#ce93d8;font-size:0.85em">Raw Response ({len(response_raw):,} chars)</summary>'
                f'<pre style="background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:12px;margin-top:6px;'
                f'font-size:0.75em;color:#c9d1d9;white-space:pre-wrap;word-break:break-all;max-height:300px;overflow-y:auto">{safe_r}</pre>'
                f'</details>'
            )

        rows_html += (
            f'<div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px;margin-bottom:10px">'
            f'<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">'
            f'<span style="font-family:monospace;font-weight:bold;color:{label_color};font-size:0.9em">{step_label}</span>'
            f'<span style="background:#21262d;color:#8b949e;border-radius:12px;padding:1px 8px;font-size:0.78em">iter {iteration}</span>'
            f'{sig_badge}</div>'
            f'{token_html}{note_html}{prompt_section}{response_section}'
            f'</div>'
        )

    total_in  = sum(s.get("token_input",  0) for s in llm_steps)
    total_out = sum(s.get("token_output", 0) for s in llm_steps)
    total_all = sum(s.get("token_total",  0) for s in llm_steps)
    providers = list(dict.fromkeys(s.get("provider","") for s in llm_steps if s.get("provider")))

    summary_html = (
        f'<div style="background:#1c2128;border:1px solid #30363d;border-radius:8px;'
        f'padding:12px 16px;margin-bottom:14px;display:flex;gap:24px;align-items:center;flex-wrap:wrap">'
        f'<span style="color:#fff;font-weight:bold">{len(llm_steps)} LLM calls</span>'
        f'<span style="color:#90caf9">IN {total_in:,}</span>'
        f'<span style="color:#90caf9">OUT {total_out:,}</span>'
        f'<span style="color:#fff;font-weight:bold">TOTAL {total_all:,} tokens</span>'
        f'<span style="color:#78909c;font-size:0.85em">via {", ".join(providers) or "—"}</span>'
        f'</div>'
    )

    return (
        f'<div style="font-family:\'JetBrains Mono\',Consolas,monospace;'
        f'background:#0d1117;border-radius:12px;padding:16px">'
        f'{summary_html}{rows_html}</div>'
    )


def _render_llm_logs_from_db(logs: list) -> str:
    """Render LLM logs from DB (llm_logs table) — used by logs_page & history_page."""
    if not logs:
        return "<div style='color:#888;padding:16px'>ยังไม่มี LLM log ในฐานข้อมูลสำหรับ run นี้</div>"

    SIG_COLOR = {"BUY": "#4caf50", "SELL": "#f44336", "HOLD": "#ff9800"}
    rows_html = ""

    for idx, log in enumerate(logs):
        step_type   = log.get("step_type", f"STEP_{idx}")
        iteration   = log.get("iteration", "—")
        signal      = log.get("signal", "")
        confidence  = log.get("confidence")
        token_in    = log.get("token_input", 0) or 0
        token_out   = log.get("token_output", 0) or 0
        token_total = log.get("token_total", 0) or 0
        model       = log.get("model", "—") or "—"
        provider    = log.get("provider", "—") or "—"
        rationale   = log.get("rationale", "")
        full_prompt = log.get("full_prompt", "")
        full_resp   = log.get("full_response", "")
        elapsed_ms  = log.get("elapsed_ms")
        logged_at   = log.get("logged_at", "")
        is_fallback = bool(log.get("is_fallback", False))
        fallback_from = log.get("fallback_from", "")

        sig_badge = ""
        if signal:
            color = SIG_COLOR.get(signal, "#999")
            conf_str = ""
            if confidence is not None:
                try:
                    conf_str = f" {float(confidence):.0%}"
                except (TypeError, ValueError):
                    conf_str = ""
            sig_badge = (
                f'<span style="background:{color};color:#fff;border-radius:4px;'
                f'padding:2px 8px;font-weight:bold;font-size:0.85em;margin-left:8px">'
                f'{signal}{conf_str}</span>'
            )

        fallback_html = ""
        if is_fallback:
            fallback_html = (
                f'<span style="background:#b71c1c;color:#fff;border-radius:4px;'
                f'padding:1px 6px;font-size:0.75em;margin-left:6px">⚠ fallback from {fallback_from or "unknown"}</span>'
            )

        token_html = (
            f'<div style="display:flex;gap:12px;align-items:center;margin:8px 0;'
            f'font-size:0.82em;color:#90caf9;flex-wrap:wrap">'
            f'<span>IN {token_in:,}</span><span>OUT {token_out:,}</span>'
            f'<span style="color:#fff;font-weight:bold">TOTAL {token_total:,}</span>'
            f'<span style="color:#78909c">· {model} ({provider})'
            f'{" · " + f"{elapsed_ms:,} ms" if elapsed_ms else ""}</span></div>'
        )

        rationale_html = ""
        if rationale:
            safe_rat = rationale.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            rationale_html = (
                f'<div style="color:#b0bec5;font-size:0.82em;margin:8px 0;'
                f'border-left:3px solid #42a5f5;padding-left:8px;white-space:pre-wrap">{safe_rat}</div>'
            )

        prompt_html = ""
        if full_prompt:
            safe_p = full_prompt.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            prompt_html = (
                f'<details style="margin-top:8px"><summary style="cursor:pointer;color:#80cbc4;font-size:0.85em">'
                f'Full Prompt ({len(full_prompt):,} chars)</summary>'
                f'<pre style="background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:12px;'
                f'margin-top:6px;font-size:0.75em;color:#c9d1d9;white-space:pre-wrap;word-break:break-all;'
                f'max-height:300px;overflow-y:auto">{safe_p}</pre></details>'
            )

        response_html = ""
        if full_resp:
            safe_r = full_resp.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            response_html = (
                f'<details style="margin-top:6px"><summary style="cursor:pointer;color:#ce93d8;font-size:0.85em">'
                f'Raw Response ({len(full_resp):,} chars)</summary>'
                f'<pre style="background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:12px;'
                f'margin-top:6px;font-size:0.75em;color:#c9d1d9;white-space:pre-wrap;word-break:break-all;'
                f'max-height:300px;overflow-y:auto">{safe_r}</pre></details>'
            )

        rows_html += (
            f'<div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px;margin-bottom:10px">'
            f'<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">'
            f'<span style="font-family:monospace;font-weight:bold;color:#42a5f5;font-size:0.9em">{step_type}</span>'
            f'<span style="background:#21262d;color:#8b949e;border-radius:12px;padding:1px 8px;font-size:0.78em">iter {iteration}</span>'
            f'{sig_badge}{fallback_html}'
            f'<span style="color:#546e7a;font-size:0.75em;margin-left:auto">{logged_at}</span>'
            f'</div>{token_html}{rationale_html}{prompt_html}{response_html}</div>'
        )

    total_in  = sum((r.get("token_input", 0) or 0) for r in logs)
    total_out = sum((r.get("token_output", 0) or 0) for r in logs)
    total_all = sum((r.get("token_total", 0) or 0) for r in logs)
    providers = list(dict.fromkeys(r.get("provider","") for r in logs if r.get("provider")))

    return (
        f'<div style="font-family:\'JetBrains Mono\',Consolas,monospace;background:#0d1117;border-radius:12px;padding:16px">'
        f'<div style="background:#1c2128;border:1px solid #30363d;border-radius:8px;padding:12px 16px;'
        f'margin-bottom:14px;display:flex;gap:24px;align-items:center;flex-wrap:wrap">'
        f'<span style="color:#fff;font-weight:bold">{len(logs)} LLM calls</span>'
        f'<span style="color:#90caf9">IN {total_in:,}</span>'
        f'<span style="color:#90caf9">OUT {total_out:,}</span>'
        f'<span style="color:#fff;font-weight:bold">TOTAL {total_all:,} tokens</span>'
        f'<span style="color:#78909c;font-size:0.85em">via {", ".join(providers) or "—"}</span>'
        f'</div>{rows_html}</div>'
    )


def _render_reasoning_from_db_logs(logs: list) -> str:
    """Fallback reasoning panel when trace is missing."""
    if not logs:
        return "<div style='color:#888;padding:12px'>No trace data available.</div>"
    rows = []
    for log in logs:
        step      = log.get("step_type", "THOUGHT_FINAL")
        provider  = log.get("provider", "—")
        rationale = (log.get("rationale") or "").strip()
        if not rationale:
            continue
        safe_rat = rationale.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        rows.append(
            f"<li style='margin-bottom:8px'><b>{step}</b> "
            f"<span style='color:#78909c'>({provider})</span><br>{safe_rat}</li>"
        )
    if not rows:
        return "<div style='color:#888;padding:12px'>No trace data available.</div>"
    return (
        "<div style='background:#0d1117;border:1px solid #30363d;border-radius:10px;padding:12px'>"
        "<div style='color:#e6edf3;font-weight:600;margin-bottom:8px'>Reasoning (from DB)</div>"
        f"<ol style='color:#c9d1d9;padding-left:20px;margin:0'>{''.join(rows)}</ol>"
        "</div>"
    )


# ─────────────────────────────────────────────────────────────────
# Page
# ─────────────────────────────────────────────────────────────────

@navbar_page("📊 Live Analysis")
class AnalysisPage(PageBase):
    """
    Live Analysis tab — v4 layout

    Left column (fixed, never re-renders):
      Controls: provider, period, interval, auto-run, run button

    Right column (updates on each run):
      Signal card → Market state → Decision text → Reasoning (accordion)

    run_outputs: 6 components
      [0] status_bar_html
      [1] signal_card_html
      [2] market_html
      [3] verdict_box
      [4] explain_html
      [5] auto_status
    """

    # ── Build ──────────────────────────────────────────────────────

    def build(self, ctx: AppContext) -> PageComponents:
        pc = PageComponents()
        defaults = _main_parser_defaults()

        # ── Full-width Status Bar ──────────────────────────────────
        pc.register("status_bar_html", gr.HTML(
            value=_render_status_bar_empty(),
            elem_id="analysis-status-bar",
        ))

        # ── 2-column Main Layout ───────────────────────────────────
        with gr.Row(equal_height=False):

            # ── LEFT: Controls (never re-renders) ─────────────────
            with gr.Column(scale=1, min_width=270, elem_classes="controls-col"):

                with gr.Group():
                    gr.Markdown("### ⚙️ Model Settings")
                    pc.register("provider_dd", gr.Dropdown(
                        choices=get_all_llm_choices(),
                        value=defaults["provider"],
                        label="LLM Provider",
                    ))
                    pc.register("period_dd", gr.Dropdown(
                        choices=PERIOD_CHOICES,
                        value=defaults["period"],
                        label="Data Period",
                    ))

                with gr.Group():
                    gr.Markdown("### 🕐 Execution")
                    pc.register("interval_dd", gr.Dropdown(
                        choices=INTERVAL_CHOICES,
                        value=defaults["interval"],
                        label="Candle Interval",
                    ))
                    pc.register("auto_interval_dd", gr.Dropdown(
                        choices=list(AUTO_RUN_INTERVALS.keys()),
                        value=DEFAULT_AUTO_RUN,
                        label="Auto-run Every",
                    ))

                with gr.Group():
                    gr.Markdown("### 🎮 Controls")
                    pc.register("run_btn", gr.Button(
                        "▶ Run Analysis",
                        variant="primary",
                        size="lg",
                    ))
                    pc.register("auto_check", gr.Checkbox(
                        label="⚡ Enable Auto-run",
                        value=False,
                    ))
                    pc.register("auto_status", gr.HTML(
                        value=StatusRenderer.info_badge("⏸ Auto-run disabled"),
                    ))

            # ── RIGHT: Results (updates on run) ───────────────────
            with gr.Column(scale=3, elem_classes="results-col"):

                # Hero: Signal Card
                pc.register("signal_card_html", gr.HTML(
                    value=_render_signal_card_empty(),
                ))

                # Market State
                gr.Markdown("#### 📊 Market State")
                pc.register("market_html", gr.HTML(
                    value=(
                        "<div style='color:#a78bfa;padding:16px;font-size:14px;"
                        "border:1px dashed #e9d5ff;border-radius:10px;text-align:center;'>"
                        "⏳ กด ▶ Run Analysis เพื่อดูข้อมูลตลาด</div>"
                    ),
                ))

                # Final Decision
                pc.register("verdict_box", gr.Textbox(
                    label="📋 Final Decision",
                    lines=7,
                    interactive=False,
                ))

                # Step Reasoning (collapsible)
                with gr.Accordion(label="🧠 Step-by-Step Reasoning", open=False):
                    pc.register("explain_html", gr.HTML(
                        value="<div style='color:#888;padding:12px'>Run analysis to see reasoning steps.</div>",
                    ))

        return pc

    # ── Wire ───────────────────────────────────────────────────────

    def wire(self, demo: gr.Blocks, ctx: AppContext, pc: PageComponents) -> None:

        # 6 outputs — controls stay fixed, only right column updates
        run_outputs = [
            pc.status_bar_html,    # 0: full-width top bar
            pc.signal_card_html,   # 1: hero signal card
            pc.market_html,        # 2: market state grid
            pc.verdict_box,        # 3: decision text
            pc.explain_html,       # 4: reasoning trace
            pc.auto_status,        # 5: badge in controls
        ]

        pc.run_btn.click(
            fn=self._handle_run(ctx),
            inputs=[pc.provider_dd, pc.period_dd, pc.interval_dd],
            outputs=run_outputs,
        )

        pc.auto_check.change(
            fn=self._handle_timer_toggle,
            inputs=[pc.auto_check],
            outputs=[pc.auto_status],
        )

        timer = gr.Timer(value=900, active=True)
        timer.tick(
            fn=self._handle_auto_run(ctx),
            inputs=[
                pc.auto_check, pc.provider_dd, pc.period_dd,
                pc.interval_dd, pc.auto_interval_dd,
            ],
            outputs=run_outputs,
        )

    # ── Private handlers ───────────────────────────────────────────

    def _handle_run(self, ctx: AppContext):
        services = ctx.services

        @log_method(sys_logger)
        def _run(provider: str, period: str, interval: str):
            # ── Error helper ──────────────────────────────────────
            def _err(msg: str, badge):
                return (
                    _render_status_bar_empty(),
                    _render_signal_card_empty(),
                    "<div style='color:#ef4444;padding:12px'>" + msg + "</div>",
                    msg,
                    "",
                    badge,
                )

            try:
                result = services["analysis"].run_analysis(provider, period, [interval])

                if result["status"] == "error":
                    error_msg = format_error_message(result)
                    badge = StatusRenderer.error_badge(
                        error_msg,
                        is_validation=(result.get("error_type") == "validation"),
                    )
                    return _err(error_msg, badge)

                voting_result    = result["voting_result"]
                interval_results = result["data"]["interval_results"]
                signal           = voting_result["final_signal"]
                confidence       = voting_result["weighted_confidence"]
                iv_name          = next(iter(interval_results))
                ir               = interval_results[iv_name]
                run_id           = result.get("run_id")
                provider_used    = ir.get("provider_used", provider)
                timestamp        = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                icon             = {"BUY": "🟢", "SELL": "🔴"}.get(signal, "🟡")

                # [1] Signal card
                signal_card = _render_signal_card(
                    signal=signal,
                    confidence=confidence,
                    provider=provider_used,
                    timestamp=timestamp,
                    interval=iv_name,
                    entry_price=ir.get("entry_price"),
                    stop_loss=ir.get("stop_loss"),
                    take_profit=ir.get("take_profit"),
                )

                # [0] Status bar
                status_bar = _render_status_bar(
                    signal=signal,
                    confidence=confidence,
                    last_run=timestamp,
                    provider=provider_used,
                    interval=iv_name,
                )

                # [2] Market state
                market_html = _render_market_state(result["data"]["market_state"])

                # [3] Decision text
                decision_txt = (
                    f"Interval:   {iv_name}\n"
                    f"Provider:   {provider_used}\n"
                    f"Signal:     {icon} {signal}\n"
                    f"Confidence: {confidence:.1%}\n"
                    f"\nReasoning:\n{ir.get('reasoning', ir.get('rationale', '—'))}\n"
                )
                if ir.get("entry_price"):
                    decision_txt += f"\nEntry:       ฿{ir['entry_price']:,.0f}"
                if ir.get("stop_loss"):
                    decision_txt += f"\nStop Loss:   ฿{ir['stop_loss']:,.0f}"
                if ir.get("take_profit"):
                    decision_txt += f"\nTake Profit: ฿{ir['take_profit']:,.0f}"

                # [4] Reasoning trace
                best_trace   = ir.get("trace", [])
                explain_html = TraceRenderer.format_trace_html(best_trace)

                if run_id and hasattr(services["history"], "get_llm_logs_for_run"):
                    db_logs = services["history"].get_llm_logs_for_run(run_id)
                    if db_logs:
                        if not best_trace:
                            explain_html = _render_reasoning_from_db_logs(db_logs)

                # [5] Auto status badge
                badge = StatusRenderer.success_badge(
                    f"Analysis complete — {signal} signal"
                )

                return (
                    status_bar,    # 0
                    signal_card,   # 1
                    market_html,   # 2
                    decision_txt,  # 3
                    explain_html,  # 4
                    badge,         # 5
                )

            except Exception as exc:
                sys_logger.error(f"AnalysisPage error: {exc}")
                badge = StatusRenderer.error_badge(f"Unexpected error: {exc}")
                return _err(f"❌ {exc}", badge)

        return _run

    def _handle_auto_run(self, ctx: AppContext):
        _run = self._handle_run(ctx)

        def _auto(enabled, provider, period, interval, interval_minutes):
            if not enabled:
                # gr.update() = no-op — don't clear the display when auto is off
                return (
                    gr.update(),
                    gr.update(),
                    gr.update(),
                    gr.update(),
                    gr.update(),
                    StatusRenderer.info_badge("⏸ Auto-run disabled"),
                )
            result    = list(_run(provider, period, interval))
            result[5] = StatusRenderer.success_badge(
                f"✅ Running every {interval_minutes} min"
            )
            return tuple(result)

        return _auto

    @staticmethod
    def _handle_timer_toggle(enabled: bool):
        return (
            StatusRenderer.success_badge("✅ Auto-run enabled")
            if enabled
            else StatusRenderer.info_badge("⏸ Auto-run disabled")
        )