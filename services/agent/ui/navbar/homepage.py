"""
ui/navbar/homepage.py
🏠 Home — Overview dashboard (first tab)

Layout — 2×2 card grid:
  ┌─────────────────────┬─────────────────────┐
  │  📊 Latest Signal   │  💰 Gold Price Live  │
  │  BUY/SELL/HOLD      │  ฿XX,XXX / change%  │
  ├─────────────────────┼─────────────────────┤
  │  💼 Portfolio       │  📜 Recent Runs      │
  │  cash/gold/P&L      │  last 7 rows         │
  └─────────────────────┴─────────────────────┘

Data sources:
  • ctx.services["history"]   → latest signal + recent runs
  • ctx.services["portfolio"] → portfolio snapshot
  • core.chart_service        → live gold price
  • core.config               → market open/closed
"""

from __future__ import annotations
from datetime import datetime

import gradio as gr

from ui.core import StatusRenderer
from ui.core.chart_service import chart_service

from logs.logger_setup import sys_logger, log_method

from .base import PageBase, PageComponents, AppContext, navbar_page


# ─────────────────────────────────────────────
# Design token
# ─────────────────────────────────────────────

_FONT = "font-family:'IBM Plex Mono',monospace;"

# Google Font injected once per page build
_FONT_IMPORT = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600;700;800&display=swap');
  @keyframes hp-blink {0%,100%{opacity:1} 50%{opacity:.15}}
</style>"""


# ─────────────────────────────────────────────
# Shared card shell
# ─────────────────────────────────────────────

def _card(accent: str, body: str, min_h: str = "270px") -> str:
    """Dark glass card with coloured top border."""
    return f"""
    <div style="
        background:white;
        border:1px solid #e2e8f0;
        border-top:3px solid {accent};
        border-radius:14px;
        padding:24px 26px;
        min-height:{min_h};
        box-shadow:0 4px 12px rgba(0,0,0,.08);
        {_FONT}
        color:#0f172a;
        position:relative;
        overflow:hidden;
    ">
      <div style="
          position:absolute;top:-50px;right:-50px;
          width:140px;height:140px;border-radius:50%;
          background:radial-gradient(rgba(0,0,0,0.04),transparent 70%);
          pointer-events:none;
      "></div>
      {body}
    </div>"""


def _section_label(icon_text: str, color: str) -> str:
    return (f'<div style="font-size:10px;letter-spacing:.2em;text-transform:uppercase;'
            f'color:{color};margin-bottom:14px;">{icon_text}</div>')


# ─────────────────────────────────────────────
# Card 1 — Latest Signal
# ─────────────────────────────────────────────

def _signal_card(signal: str, confidence: float, provider: str, run_at: str) -> str:
    _META = {
        "BUY":  ("#16a34a", "#4ade80", "▲"),
        "SELL": ("#dc2626", "#f87171", "▼"),
        "HOLD": ("#ca8a04", "#fde047", "◆"),
    }
    bg, accent, arrow = _META.get(signal, ("#475569", "#94a3b8", "?"))
    bar = int(confidence * 100)

    body = f"""
    {_section_label("📊 Latest Signal", "#0f172a")}

    <div style="
        display:inline-flex;align-items:center;gap:12px;
        background:{bg}1a;
        border:1.5px solid {bg};
        border-radius:10px;
        padding:10px 20px;
        margin-bottom:20px;
    ">
      <span style="font-size:30px;font-weight:800;color:{accent};
                   letter-spacing:-.01em;line-height:1;">
          {arrow} {signal}
      </span>
    </div>

    <div>
      <div style="font-size:10px;color:#475569;letter-spacing:.12em;
                  text-transform:uppercase;margin-bottom:5px;">Confidence</div>
      <div style="background:#e2e8f0;border-radius:99px;height:6px;">
        <div style="background:{accent};border-radius:99px;
                    height:6px;width:{bar}%;transition:width .5s ease;"></div>
      </div>
      <div style="font-size:28px;font-weight:800;color:#0f172a;margin-top:6px;">
          {confidence:.0%}
      </div>
    </div>

    <div style="display:flex;gap:16px;flex-wrap:wrap;font-size:11px;
                color:#475569;margin-top:16px;padding-top:12px;
                border-top:1px solid rgba(255,255,255,.05);">
      <span>🤖 {provider or '—'}</span>
      <span>🕐 {run_at or '—'}</span>
    </div>"""

    return _card(accent, body)


# ─────────────────────────────────────────────
# Card 2 — Gold Price
# ─────────────────────────────────────────────

def _price_card(price_data: dict) -> str:
    ok    = price_data.get("status") == "success"
    price = price_data.get("price", 0)
    chg   = price_data.get("change_pct", 0)
    ts    = price_data.get("fetched_at", "—")

    if ok:
        price_str = f"฿{price:,.0f}"
        arrow     = "▲" if chg >= 0 else "▼"
        chg_color = "#4ade80" if chg >= 0 else "#f87171"
        chg_str   = f"{arrow} {abs(chg):.2f}%"
    else:
        price_str = "—"
        chg_color = "#64748b"
        chg_str   = price_data.get("error", "fetch error")[:40]

    body = f"""
    {_section_label("💰 Gold Price  ·  XAU/THB", "#495bff")}

    <div style="font-size:36px;font-weight:800;color:#0f172a;
                letter-spacing:-.02em;line-height:1.1;margin-bottom:8px;">
        {price_str}
    </div>

    <div style="font-size:20px;font-weight:700;color:{chg_color};
                margin-bottom:20px;">
        {chg_str}
    </div>

    <div style="
        display:inline-block;background:rgba(255,255,255,.05);
        border-radius:6px;padding:3px 10px;
        font-size:11px;color:#475569;
    ">per gram</div>

    <div style="font-size:11px;color:#334155;margin-top:16px;
                padding-top:12px;border-top:1px solid rgba(255,255,255,.05);">
        updated {ts}
    </div>"""

    return _card("#3b82f6", body)


# ─────────────────────────────────────────────
# Card 3 — Portfolio Snapshot
# ─────────────────────────────────────────────

def _portfolio_card(pf: dict) -> str:
    cash    = float(pf.get("cash_balance",      0))
    gold    = float(pf.get("gold_grams",        0))
    pnl     = float(pf.get("unrealized_pnl",    0))
    cur_val = float(pf.get("current_value_thb", 0))
    total   = cash + cur_val

    pnl_color = "#4ade80" if pnl >= 0 else "#f87171"
    pnl_icon  = "▲" if pnl >= 0 else "▼"

    def _row(label: str, val: str, col: str = "#cbd5e1") -> str:
        return f"""
        <div style="display:flex;justify-content:space-between;align-items:center;
                    padding:8px 0;border-bottom:1px solid rgba(255,255,255,.04);">
          <span style="font-size:11px;color:#475569;">{label}</span>
          <span style="font-size:13px;font-weight:600;color:{col};">{val}</span>
        </div>"""

    body = f"""
    {_section_label("💼 Portfolio Snapshot", "#3300ff")}

    <div style="font-size:28px;font-weight:800;color:#0f172a;
                margin-bottom:18px;line-height:1;">
        ฿{total:,.2f}
        <span style="font-size:12px;color:#475569;font-weight:400;"> total</span>
    </div>

    {_row("Cash Balance",    f"฿{cash:,.2f}")}
    {_row("Gold Held",       f"{gold:.4f} g")}
    {_row("Gold Value",      f"฿{cur_val:,.2f}")}
    {_row("Unrealized P&L",  f"{pnl_icon} ฿{abs(pnl):,.2f}", pnl_color)}"""

    return _card("#8b5cf6", body)


# ─────────────────────────────────────────────
# Card 4 — Recent Runs
# ─────────────────────────────────────────────

def _history_card(runs: list) -> str:
    _SIG_COL = {"BUY": "#007f2e", "SELL": "#f87171", "HOLD": "#ffd500"}

    if not runs:
        body = (f'{_section_label("📜 Recent Runs", "#a37500")}'
                '<div style="color:#475569;font-size:13px;padding:8px 0;">No runs yet.</div>')
        return _card("#f59e0b", body)

    # Sort runs by run_at descending and remove duplicates
    seen = set()
    runs_sorted = []
    for r in sorted(runs, key=lambda r: r.get("run_at", ""), reverse=True):
        if r.get("run_at") not in seen:
            seen.add(r.get("run_at"))
            runs_sorted.append(r)

    rows_html = ""
    for r in runs_sorted[:7]:
        sig   = r.get("signal", "HOLD")
        conf  = float(r.get("confidence", 0))
        prov  = str(r.get("provider", "—"))[:12]
        ts    = str(r.get("run_at", "—"))
        color = _SIG_COL.get(sig, "#006aff")
        # Convert ts from UTC ISO to Bangkok local time for display
        from datetime import datetime
        import pytz
        try:
            utc_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            local_dt = utc_dt.astimezone(pytz.timezone("Asia/Bangkok"))
            ts_display = local_dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            ts_display = ts

        rows_html += f"""
        <tr style="border-bottom:1px solid rgba(255,255,255,.03);">
          <td style="padding:7px 10px 7px 25px;white-space:nowrap;text-align:left;">
            <span style="color:{color};font-size:8px;">●</span>
            <span style="color:{color};font-weight:700;font-size:12px;
                         margin-left:5px;">{sig}</span>
          </td>
          <td style="padding:7px 8px;color:#94a3b8;font-size:12px;text-align:left;">{conf:.0%}</td>
          <td style="padding:7px 8px;color:#64748b;font-size:11px;text-align:left;">{prov}</td>
          <td style="padding:7px 8px 7px 15px;color:#475569;font-size:10px;
                     text-align:left;white-space:nowrap;">{ts_display}</td>
        </tr>"""

    thead = """
    <tr>
      <th style="padding:0 10px 8px 20px;font-size:10px;color:#334155;
                 font-weight:500;text-align:left;letter-spacing:.1em;">SIG</th>
      <th style="padding:0 8px 8px;font-size:10px;color:#334155;
                 font-weight:500;text-align:left;">CONF</th>
      <th style="padding:0 8px 8px;font-size:10px;color:#334155;
                 font-weight:500;text-align:left;">PROVIDER</th>
      <th style="padding:0 8px 8px 15px;font-size:10px;color:#334155;
                 font-weight:500;text-align:left;">TIME</th>
    </tr>"""

    body = f"""
    {_section_label("📜 Recent Runs", "#ff5100")}
    <table style="width:100%;border-collapse:collapse;">
      <thead>{thead}</thead>
      <tbody>{rows_html}</tbody>
    </table>"""

    return _card("#f59e0b", body)


# ─────────────────────────────────────────────
# Market status bar
# ─────────────────────────────────────────────

def _status_bar(is_open: bool) -> str:
    now   = datetime.now().strftime("%d %b %Y  %H:%M:%S")
    color = "#4ade80" if is_open else "#f87171"
    label = "MARKET OPEN" if is_open else "MARKET CLOSED"

    return f"""
    {_FONT_IMPORT}
    <div style="
        display:flex;align-items:center;gap:10px;
        padding:7px 14px;
        background:rgba(255,255,255,.02);
        border:1px solid rgba(255,255,255,.06);
        border-radius:8px;
        {_FONT}
    ">
      <span style="color:{color};font-size:8px;
                   animation:hp-blink 1.4s infinite;">●</span>
      <span style="color:{color};font-size:11px;letter-spacing:.15em;">{label}</span>
      <span style="color:#334155;font-size:11px;margin-left:auto;">🕐 {now}</span>
    </div>"""


# ─────────────────────────────────────────────
# Page class
# ─────────────────────────────────────────────

@navbar_page("🏠 Home")
class HomePage(PageBase):
    """2×2 card grid overview — first tab."""

    # ── Build ──────────────────────────────────────────────────────

    def build(self, ctx: AppContext) -> PageComponents:
        pc = PageComponents()

        # Main container (centered, max-width)
        with gr.Column(elem_id="hp-container"):

            # Header (more formal)
            pc.register("page_header", gr.Markdown(
                """
# 🟡 Gold Intelligence Platform
### Institutional Dashboard — Real-time AI Trading System
"""
            ))

            # Top control bar
            with gr.Row():
                pc.register("status_bar",
                    gr.HTML(value=self._initial_status(), elem_id="hp-statusbar")
                )
                pc.register("refresh_btn",
                    gr.Button("⟳ Refresh Data", scale=0, size="sm", variant="secondary")
                )

            # KPI Row (full width, evenly spaced)
            with gr.Row():
                pc.register("kpi_1", gr.HTML())
                pc.register("kpi_2", gr.HTML())
                pc.register("kpi_3", gr.HTML())
                pc.register("kpi_4", gr.HTML())

            # Primary Section — Signal (full width emphasis)
            with gr.Row():
                pc.register("signal_card", gr.HTML(elem_id="hp-signal"))

            # Secondary Section — Price + Portfolio
            with gr.Row(equal_height=True):
                pc.register("price_card",  gr.HTML(elem_id="hp-price"))
                pc.register("portfolio_card", gr.HTML(elem_id="hp-portfolio"))

            # Bottom Section — History (full width)
            with gr.Row():
                pc.register("history_card",   gr.HTML(elem_id="hp-history"))

            # NEW: System Status Panel
            pc.register("system_status", gr.HTML())

        # Error / success feedback (hidden until needed)
        pc.register("load_status", gr.HTML())

        return pc

    # ── Wire ───────────────────────────────────────────────────────

    def wire(self, demo: gr.Blocks, ctx: AppContext, pc: PageComponents) -> None:
        _out = [
            pc.kpi_1, pc.kpi_2, pc.kpi_3, pc.kpi_4,
            pc.signal_card,
            pc.price_card, pc.portfolio_card,
            pc.history_card,
            pc.status_bar, pc.system_status, pc.load_status,
        ]

        pc.refresh_btn.click(fn=self._handle_refresh(ctx), inputs=[], outputs=_out)

        gr.Timer(value=60, active=True).tick(
            fn=self._handle_refresh(ctx), inputs=[], outputs=_out
        )

        demo.load(fn=self._handle_refresh(ctx), outputs=_out)

    # ── Handler factory ────────────────────────────────────────────

    def _handle_refresh(self, ctx: AppContext):
        services = ctx.services

        @log_method(sys_logger)
        def _refresh():
            try:
                # 1. Signal
                runs       = services["history"].get_recent_runs(limit=7)
                latest     = runs[0] if runs else {}
                signal     = latest.get("signal", "HOLD")
                confidence = float(latest.get("confidence", 0.0))
                provider   = latest.get("provider", "—")
                run_at     = latest.get("run_at", "—")

                # 2. Gold price
                price_data = chart_service.fetch_price(currency="THB")

                # 3. Portfolio
                pf = services["portfolio"].load_portfolio().get("data", {})

                # 4. Market status
                from ui.core.config import is_thailand_market_open
                is_open = is_thailand_market_open()

                badge = StatusRenderer.success_badge(
                    f"Updated · {datetime.now().strftime('%H:%M:%S')}"
                )

                # KPI calculations
                total_runs = len(runs)
                win_rate = sum(1 for r in runs if r.get("signal") == "BUY") / total_runs if total_runs else 0
                avg_conf = sum(float(r.get("confidence", 0)) for r in runs) / total_runs if total_runs else 0

                def kpi(label, value):
                    return f"""
                    <div style="
                        background:white;
                        border-radius:10px;
                        padding:14px;
                        box-shadow:0 4px 12px rgba(0,0,0,.08);
                        font-family:Inter,sans-serif;
                    ">
                        <div style="font-size:10px;color:#64748b;text-transform:uppercase;">
                            {label}
                        </div>
                        <div style="font-size:18px;font-weight:700;color:#0f172a;">
                            {value}
                        </div>
                    </div>
                    """

                return (
                    kpi("Total Runs", total_runs),
                    kpi("Win Rate", f"{win_rate:.0%}"),
                    kpi("Avg Confidence", f"{avg_conf:.0%}"),
                    kpi("Market", "OPEN" if is_open else "CLOSED"),
                    _signal_card(signal, confidence, provider, run_at),
                    _price_card(price_data),
                    _portfolio_card(pf),
                    _history_card(runs),
                    _status_bar(is_open),
                    f"""
                    <div style="
                        background:white;
                        border-radius:12px;
                        padding:16px;
                        box-shadow:0 6px 18px rgba(0,0,0,.08);
                        font-family:Inter,sans-serif;
                        margin-top:10px;
                    ">
                        <div style="font-size:12px;color:#64748b;margin-bottom:8px;">
                            ⚙️ System Status
                        </div>
                        <div style="display:flex;gap:20px;font-size:13px;">
                            <span>🤖 Model: {provider}</span>
                            <span>📊 Runs: {total_runs}</span>
                            <span>📈 Avg Conf: {avg_conf:.0%}</span>
                            <span>🟢 Market: {"Open" if is_open else "Closed"}</span>
                        </div>
                    </div>
                    """,
                    badge,
                )

            except Exception as exc:
                sys_logger.error(f"HomePage refresh error: {exc}")
                return (
                    "", "", "", "",
                    "",
                    "", "",
                    "",
                    self._initial_status(),
                    "",
                    StatusRenderer.error_badge(f"Refresh error: {exc}"),
                )

        return _refresh

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _initial_status() -> str:
        try:
            from ui.core.config import is_thailand_market_open
            return _status_bar(is_thailand_market_open())
        except Exception:
            return _status_bar(False)
        




