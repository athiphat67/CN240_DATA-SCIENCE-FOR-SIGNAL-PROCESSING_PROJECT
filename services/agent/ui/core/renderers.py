"""
core/renderers.py — HTML/UI Rendering Components
Gold Trading Agent v3.2

Design System: "High-End Editorial Financial Intelligence"
ใช้ design tokens จาก code.html + DESIGN.md:
  - Typography  : Noto Serif (headline) + IBM Plex Mono (data) + Inter (body)
  - Colors      : primary #0058be, surface #f6fafe, on-tertiary-container #10b981
  - Elevation   : tonal layering — ไม่ใช้ border ตัดแบ่ง section
  - Shadows     : ambient blue-tint  0px 12px 32px rgba(0,88,190,0.06)
  - Glass panel : rgba(255,255,255,0.8) + backdrop-blur
"""

from datetime import datetime, timedelta
from typing import List, Dict

# ─────────────────────────────────────────────
# Design Tokens  (single source of truth)
# ─────────────────────────────────────────────

DT = {
    # Surfaces
    "surface":          "#f6fafe",
    "surface_low":      "#f0f4f8",
    "surface_high":     "#e4e9ed",
    "surface_highest":  "#dfe3e7",
    "surface_lowest":   "#ffffff",
    "surface_container":"#eaeef2",

    # Brand
    "primary":          "#0058be",
    "primary_container":"#2170e4",
    "primary_fixed_dim":"#adc6ff",

    # Semantic
    "success":          "#10b981",   # BUY / profit
    "error":            "#ef4444",   # SELL / loss
    "warning":          "#f59e0b",   # HOLD / caution
    "on_surface":       "#171c1f",
    "on_surface_var":   "#424754",
    "outline_var":      "#c2c6d6",
    "inverse_surface":  "#1e293b",   # dark chart bg

    # Shadows
    "shadow_ambient":   "0px 12px 32px rgba(0,88,190,0.06)",
    "shadow_float":     "0px 24px 48px rgba(0,88,190,0.10)",
}

# Google Fonts — loaded once via CSS inject (Gradio allows this in gr.HTML)
FONT_IMPORT = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif:wght@700&family=IBM+Plex+Mono:wght@400;500&family=Inter:wght@400;500;600&display=swap');
</style>
"""

# ─────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────

def _sig_color(signal: str) -> str:
    return {"BUY": DT["success"], "SELL": DT["error"]}.get(signal, DT["warning"])

def _sig_bg(signal: str) -> str:
    return {"BUY": "#ecfdf5", "SELL": "#fef2f2"}.get(signal, "#fffbeb")

def _sig_icon(signal: str) -> str:
    return {"BUY": "▲", "SELL": "▼"}.get(signal, "●")

def _mono(text: str, color: str = DT["on_surface"]) -> str:
    return (f'<span style="font-family:\'IBM Plex Mono\',monospace;'
            f'font-size:12px;color:{color};">{text}</span>')

def _label(text: str) -> str:
    return (f'<span style="font-family:Inter,sans-serif;font-size:10px;'
            f'font-weight:600;text-transform:uppercase;letter-spacing:1.2px;'
            f'color:{DT["on_surface_var"]};">{text}</span>')

def _card(content: str, extra_style: str = "") -> str:
    """surface-container-lowest card with ambient shadow"""
    return (f'<div style="background:{DT["surface_lowest"]};border-radius:12px;'
            f'box-shadow:{DT["shadow_ambient"]};padding:20px;{extra_style}">'
            f'{content}</div>')


# ─────────────────────────────────────────────
# Trace Renderer
# ─────────────────────────────────────────────

class TraceRenderer:
    """
    Render ReAct trace — dark terminal aesthetic (inverse-surface)
    เหมือน ReAct Thought Trace panel ใน code.html
    """

    @staticmethod
    def format_trace_html(react_trace: list) -> str:
        if not react_trace:
            return f"""
            {FONT_IMPORT}
            <div style="background:{DT['inverse_surface']};border-radius:12px;
                        padding:32px;text-align:center;
                        font-family:'IBM Plex Mono',monospace;font-size:12px;
                        color:#475569;">
                No trace data available.
            </div>"""

        steps_html = ""
        for idx, entry in enumerate(react_trace, 1):
            step      = entry.get("step", "?")
            iteration = entry.get("iteration", "?")
            response  = entry.get("response", {})
            note      = entry.get("note", "")
            action    = response.get("action", entry.get("tool_name", ""))
            thought   = response.get("thought", "")

            # Color coding
            if "FINAL" in step:
                label_color, dot_color = "#10b981", "#10b981"
            elif step == "TOOL_EXECUTION":
                label_color, dot_color = "#f59e0b", "#f59e0b"
            elif "THOUGHT" in step:
                label_color, dot_color = "#adc6ff", "#adc6ff"
            else:
                label_color, dot_color = "#64748b", "#64748b"

            # Timestamp placeholder (use idx)
            ts_str = f"[{idx:02d}:{iteration}]"

            block = f"""
            <div style="margin-bottom:14px;display:flex;gap:10px;align-items:flex-start;">
                <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;
                             color:#475569;flex-shrink:0;padding-top:2px;">{ts_str}</span>
                <div style="flex:1;">"""

            if thought:
                block += f"""
                    <p style="margin:0 0 4px 0;font-family:'IBM Plex Mono',monospace;
                               font-size:11px;color:{label_color};font-weight:500;">
                        {step}{' — ' + note if note else ''}
                    </p>
                    <p style="margin:0;font-family:'IBM Plex Mono',monospace;
                               font-size:11px;color:#94a3b8;line-height:1.6;">{thought}</p>"""

            if action:
                block += f"""
                    <p style="margin:4px 0 0 0;font-family:'IBM Plex Mono',monospace;
                               font-size:11px;color:#adc6ff;">
                        <span style="color:#64748b;">Action: </span>{action}
                    </p>"""

            if response.get("signal"):
                sig  = response["signal"]
                conf = response.get("confidence", 0)
                block += f"""
                    <div style="margin-top:8px;display:inline-flex;align-items:center;
                                gap:8px;background:rgba(255,255,255,0.05);
                                padding:6px 12px;border-radius:6px;">
                        <span style="font-family:'IBM Plex Mono',monospace;font-size:12px;
                                     font-weight:700;color:{_sig_color(sig)};">
                            {_sig_icon(sig)} {sig}
                        </span>
                        <span style="font-family:'IBM Plex Mono',monospace;font-size:11px;
                                     color:#64748b;">conf: {conf:.0%}</span>
                    </div>"""

            if "observation" in entry:
                obs    = entry["observation"]
                status = obs.get("status", "?")
                s_col  = "#10b981" if status == "success" else "#ef4444"
                obs_d  = str(obs.get("data") or obs.get("error", ""))[:200]
                block += f"""
                    <p style="margin:6px 0 0 0;font-family:'IBM Plex Mono',monospace;
                               font-size:10px;color:#475569;">
                        <span style="color:{s_col};">[{status}]</span> {obs_d}
                    </p>"""

            block += "</div></div>"
            steps_html += block

        # macOS-style terminal chrome
        return f"""
        {FONT_IMPORT}
        <div style="background:{DT['inverse_surface']};border-radius:12px;overflow:hidden;
                    box-shadow:{DT['shadow_float']};">
            <!-- Terminal chrome -->
            <div style="background:#1e2d3d;padding:10px 16px;
                        display:flex;align-items:center;justify-content:space-between;">
                <div style="display:flex;gap:6px;align-items:center;">
                    <span style="width:10px;height:10px;border-radius:50%;background:#ef4444;display:inline-block;"></span>
                    <span style="width:10px;height:10px;border-radius:50%;background:#f59e0b;display:inline-block;"></span>
                    <span style="width:10px;height:10px;border-radius:50%;background:#10b981;display:inline-block;"></span>
                    <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;
                                 color:#475569;margin-left:12px;">ReAct Thought Trace</span>
                </div>
                <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;
                             color:#334155;">{len(react_trace)} steps</span>
            </div>
            <!-- Trace content -->
            <div style="padding:16px 20px;max-height:400px;overflow-y:auto;
                        scrollbar-width:thin;scrollbar-color:#334155 transparent;">
                {steps_html}
                <p style="margin:8px 0 0 0;font-family:'IBM Plex Mono',monospace;
                           font-size:12px;color:#10b981;">
                    <span style="animation:blink 1s infinite;">_</span>
                </p>
            </div>
        </div>
        <style>@keyframes blink{{0%,100%{{opacity:1}}50%{{opacity:0}}}}</style>"""


# ─────────────────────────────────────────────
# History Renderer
# ─────────────────────────────────────────────

class HistoryRenderer:
    """
    Run history table — light editorial style
    เหมือน History Table section ใน code.html
    """

    @staticmethod
    def format_history_html(rows: List[Dict]) -> str:
        if not rows:
            return f"""
            {FONT_IMPORT}
            <div style="background:{DT['surface_lowest']};border-radius:12px;
                        padding:40px;text-align:center;box-shadow:{DT['shadow_ambient']};
                        font-family:Inter,sans-serif;color:{DT['on_surface_var']};">
                📊 No runs recorded yet.
            </div>"""

        rows_html = ""
        for idx, r in enumerate(rows):
            sig      = r.get("signal", "HOLD")
            sig_col  = _sig_color(sig)
            sig_bg   = _sig_bg(sig)
            conf     = r.get("confidence")
            conf_str = f"{conf:.0%}" if conf is not None else "—"
            price_str= f"฿{r['gold_price']:,.0f}" if r.get("gold_price") else "—"
            rsi_str  = f"{r['rsi']:.1f}" if r.get("rsi") else "—"

            # Timestamp → Bangkok
            raw_ts = r.get("run_at")
            if raw_ts:
                try:
                    dt_utc = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                    ts = (dt_utc + timedelta(hours=7)).strftime("%m-%d %H:%M")
                except:
                    ts = raw_ts
            else:
                ts = "—"

            provider_str = r.get("provider", "—")
            intervals_str = r.get("interval_tf", "—")
            row_bg = DT["surface_lowest"] if idx % 2 == 0 else DT["surface_low"]

            rows_html += f"""
            <tr style="background:{row_bg};transition:background 0.15s;">
                <td style="padding:12px 16px;font-family:'IBM Plex Mono',monospace;
                           font-size:11px;color:{DT['on_surface_var']};">
                    #<strong style="color:{DT['on_surface']};">{r.get('id','?')}</strong>
                </td>
                <td style="padding:12px 16px;font-family:'IBM Plex Mono',monospace;
                           font-size:11px;color:{DT['on_surface_var']};">{ts}</td>
                <td style="padding:12px 16px;font-family:Inter,sans-serif;
                           font-size:11px;color:{DT['on_surface_var']};">{provider_str}</td>
                <td style="padding:12px 16px;font-family:'IBM Plex Mono',monospace;
                           font-size:11px;color:{DT['on_surface_var']};">{intervals_str}</td>
                <td style="padding:12px 16px;">
                    <span style="padding:2px 10px;background:{sig_bg};color:{sig_col};
                                 border-radius:4px;font-family:Inter,sans-serif;
                                 font-size:10px;font-weight:700;">
                        {sig}
                    </span>
                </td>
                <td style="padding:12px 16px;font-family:'IBM Plex Mono',monospace;
                           font-size:11px;text-align:right;color:{sig_col};
                           font-weight:500;">{conf_str}</td>
                <td style="padding:12px 16px;font-family:'IBM Plex Mono',monospace;
                           font-size:11px;text-align:right;
                           color:{DT['on_surface']};">{price_str}</td>
                <td style="padding:12px 16px;font-family:'IBM Plex Mono',monospace;
                           font-size:11px;text-align:right;
                           color:{DT['on_surface_var']};">{rsi_str}</td>
                <td style="padding:12px 16px;font-family:'IBM Plex Mono',monospace;
                           font-size:11px;text-align:right;
                           color:{DT['on_surface_var']};">
                    {r.get('iterations_used','—')}
                </td>
            </tr>"""

        th_style = (f"padding:10px 16px;text-align:left;font-family:Inter,sans-serif;"
                    f"font-size:10px;font-weight:700;text-transform:uppercase;"
                    f"letter-spacing:1px;color:{DT['on_surface_var']};")

        return f"""
        {FONT_IMPORT}
        <div style="background:{DT['surface_lowest']};border-radius:12px;
                    overflow:hidden;box-shadow:{DT['shadow_ambient']};
                    border:1px solid {DT['surface_container']};">
            <div style="overflow-x:auto;">
                <table style="width:100%;border-collapse:collapse;
                              font-family:'IBM Plex Mono',monospace;">
                    <thead>
                        <tr style="background:{DT['surface_low']};
                                   border-bottom:1px solid {DT['surface_container']};">
                            <th style="{th_style}">ID</th>
                            <th style="{th_style}">Time (TH)</th>
                            <th style="{th_style}">Provider</th>
                            <th style="{th_style}">Intervals</th>
                            <th style="{th_style}">Signal</th>
                            <th style="{th_style}text-align:right;">Conf</th>
                            <th style="{th_style}text-align:right;">Price</th>
                            <th style="{th_style}text-align:right;">RSI</th>
                            <th style="{th_style}text-align:right;">Iter</th>
                        </tr>
                    </thead>
                    <tbody>{rows_html}</tbody>
                </table>
            </div>
        </div>"""


# ─────────────────────────────────────────────
# Portfolio Renderer
# ─────────────────────────────────────────────

class PortfolioRenderer:
    """
    Portfolio summary — 5-card top strip + allocation bar
    เหมือน Portfolio Stats Cards ใน code.html
    """

    @staticmethod
    def format_portfolio_html(p: dict) -> str:
        if not p:
            return f"""
            {FONT_IMPORT}
            <div style="background:{DT['surface_lowest']};border-radius:12px;
                        padding:32px;text-align:center;color:{DT['on_surface_var']};
                        font-family:Inter,sans-serif;">
                📊 No portfolio data.
            </div>"""

        cash    = p.get("cash_balance", 0.0)
        gold_g  = p.get("gold_grams", 0.0)
        cost    = p.get("cost_basis_thb", 0.0)
        cur_val = p.get("current_value_thb", 0.0)
        pnl     = p.get("unrealized_pnl", 0.0)
        trades  = p.get("trades_today", 0)
        updated = p.get("updated_at", "")

        total_value = cash + cur_val
        cash_pct    = (cash / total_value * 100) if total_value > 0 else 0
        gold_pct    = (cur_val / total_value * 100) if total_value > 0 else 0
        roi         = ((cur_val - cost) / cost * 100) if cost > 0 else 0
        can_buy     = cash >= 1000
        can_sell    = gold_g > 0

        pnl_color = DT["success"] if pnl >= 0 else DT["error"]
        roi_color = DT["success"] if roi >= 0 else DT["error"]
        pnl_sign  = "+" if pnl >= 0 else ""

        ts_th = ""
        if updated:
            try:
                dt_utc = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                ts_th = (dt_utc + timedelta(hours=7)).strftime("%Y-%m-%d %H:%M:%S")
            except:
                ts_th = updated

        def stat_card(label: str, value: str, sub: str = "",
                      accent_color: str = DT["primary"],
                      accent_border: bool = False) -> str:
            border_style = (f"border-left:3px solid {accent_color};"
                            if accent_border else "")
            return f"""
            <div style="background:{DT['surface_lowest']};border-radius:12px;
                        padding:18px 20px;box-shadow:{DT['shadow_ambient']};
                        {border_style}">
                {_label(label)}
                <div style="margin-top:8px;font-family:'IBM Plex Mono',monospace;
                            font-size:18px;font-weight:700;
                            color:{accent_color};">{value}</div>
                {f'<div style="margin-top:4px;font-family:Inter,sans-serif;font-size:11px;color:{DT["on_surface_var"]};">{sub}</div>' if sub else ''}
            </div>"""

        cards = f"""
        <div style="display:grid;grid-template-columns:repeat(5,1fr);
                    gap:12px;margin-bottom:20px;">
            {stat_card("Cash Balance", f"฿{cash:,.0f}", f"{cash_pct:.1f}% of total")}
            {stat_card("Gold Holdings", f"{gold_g:.4f} g", f"≈ ฿{cur_val:,.0f}",
                       accent_color="#92400e")}
            {stat_card("Current Value", f"฿{cur_val:,.0f}", f"Cost: ฿{cost:,.0f}",
                       accent_color=DT["primary"], accent_border=True)}
            {stat_card("Net P&L", f"{pnl_sign}฿{abs(pnl):,.0f}", f"ROI: {roi:+.1f}%",
                       accent_color=pnl_color)}
            {stat_card("Trades Today", str(int(trades)), "")}
        </div>"""

        # Allocation bar
        alloc = f"""
        <div style="background:{DT['surface_lowest']};border-radius:12px;
                    padding:18px 20px;box-shadow:{DT['shadow_ambient']};margin-bottom:16px;">
            {_label("Asset Allocation")}
            <div style="margin-top:10px;height:8px;border-radius:4px;
                        overflow:hidden;background:{DT['surface_low']};display:flex;">
                <div style="width:{cash_pct}%;background:{DT['primary']};
                            transition:width 0.4s;"></div>
                <div style="width:{gold_pct}%;background:#b45309;
                            transition:width 0.4s;"></div>
            </div>
            <div style="display:flex;gap:16px;margin-top:8px;
                        font-family:Inter,sans-serif;font-size:11px;
                        color:{DT['on_surface_var']};">
                <span>
                    <span style="display:inline-block;width:8px;height:8px;
                                 border-radius:2px;background:{DT['primary']};
                                 margin-right:5px;vertical-align:middle;"></span>
                    Cash {cash_pct:.1f}%
                </span>
                <span>
                    <span style="display:inline-block;width:8px;height:8px;
                                 border-radius:2px;background:#b45309;
                                 margin-right:5px;vertical-align:middle;"></span>
                    Gold {gold_pct:.1f}%
                </span>
            </div>
        </div>"""

        # Trading constraints
        def badge(ok: bool, label: str) -> str:
            c = DT["success"] if ok else DT["error"]
            bg = "#ecfdf5" if ok else "#fef2f2"
            icon = "✓" if ok else "✗"
            return (f'<span style="padding:5px 12px;background:{bg};color:{c};'
                    f'border-radius:6px;font-family:Inter,sans-serif;'
                    f'font-size:11px;font-weight:600;">{icon} {label}</span>')

        constraints = f"""
        <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;">
            {badge(can_buy, "Can Buy (min ฿1,000)")}
            {badge(can_sell, f"Can Sell ({gold_g:.4f}g)")}
            <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;
                         color:{DT['on_surface_var']};">Updated: {ts_th}</span>
        </div>"""

        return f"{FONT_IMPORT}{cards}{alloc}{constraints}"


# ─────────────────────────────────────────────
# Stats Renderer
# ─────────────────────────────────────────────

class StatsRenderer:
    """Compact signal statistics bar — inline badges"""

    @staticmethod
    def format_stats_html(stats: dict) -> str:
        total = stats.get("total", 0)
        if total == 0:
            return (f'<span style="font-family:Inter,sans-serif;font-size:12px;'
                    f'color:{DT["on_surface_var"]};">📊 No data yet</span>')

        buy_c   = stats.get("buy_count", 0)
        sell_c  = stats.get("sell_count", 0)
        hold_c  = stats.get("hold_count", 0)
        avg_conf= stats.get("avg_confidence", 0)
        avg_p   = stats.get("avg_price", 0)

        def pill(label: str, value: str, color: str, bg: str) -> str:
            return (f'<span style="padding:4px 12px;background:{bg};color:{color};'
                    f'border-radius:6px;font-family:Inter,sans-serif;'
                    f'font-size:11px;font-weight:600;">{label} {value}</span>')

        return f"""
        {FONT_IMPORT}
        <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;
                    padding:10px 14px;background:{DT['surface_low']};
                    border-radius:10px;">
            <span style="font-family:'IBM Plex Mono',monospace;font-size:11px;
                         color:{DT['on_surface_var']};font-weight:500;">
                {total} runs
            </span>
            {pill("BUY", f"{buy_c} ({buy_c/total:.0%})", DT['success'], '#ecfdf5')}
            {pill("SELL", f"{sell_c} ({sell_c/total:.0%})", DT['error'], '#fef2f2')}
            {pill("HOLD", f"{hold_c} ({hold_c/total:.0%})", DT['warning'], '#fffbeb')}
            <span style="font-family:'IBM Plex Mono',monospace;font-size:11px;
                         color:{DT['on_surface_var']};">
                avg conf <strong style="color:{DT['on_surface']};">{avg_conf:.0%}</strong>
            </span>
            <span style="font-family:'IBM Plex Mono',monospace;font-size:11px;
                         color:{DT['on_surface_var']};">
                avg price <strong style="color:{DT['on_surface']};">฿{avg_p:,.0f}</strong>
            </span>
        </div>"""


# ─────────────────────────────────────────────
# Status Renderer
# ─────────────────────────────────────────────

class StatusRenderer:
    """
    Status badges — glass-panel aesthetic
    ไม่ใช้ border หนัก ใช้ tonal background แทน
    """

    @staticmethod
    def error_badge(message: str, is_validation: bool = False) -> str:
        bg     = "#fef2f2" if is_validation else "#fffbeb"
        color  = DT["error"] if is_validation else "#92400e"
        icon   = "✗" if is_validation else "⚠"
        return f"""
        {FONT_IMPORT}
        <div style="padding:12px 18px;background:{bg};border-radius:10px;
                    font-family:Inter,sans-serif;font-size:13px;
                    font-weight:500;color:{color};
                    box-shadow:{DT['shadow_ambient']};">
            {icon} {message}
        </div>"""

    @staticmethod
    def success_badge(message: str) -> str:
        return f"""
        {FONT_IMPORT}
        <div style="padding:12px 18px;background:#ecfdf5;border-radius:10px;
                    font-family:Inter,sans-serif;font-size:13px;
                    font-weight:500;color:{DT['success']};
                    box-shadow:{DT['shadow_ambient']};">
            ✓ {message}
        </div>"""

    @staticmethod
    def info_badge(message: str) -> str:
        return f"""
        {FONT_IMPORT}
        <div style="padding:12px 18px;background:#eff6ff;border-radius:10px;
                    font-family:Inter,sans-serif;font-size:13px;
                    font-weight:500;color:{DT['primary']};
                    box-shadow:{DT['shadow_ambient']};">
            ℹ {message}
        </div>"""

    @staticmethod
    def signal_decision_card(signal: str, confidence: float,
                              entry_price: float = 0,
                              stop_loss: float = 0,
                              take_profit: float = 0) -> str:
        """
        Final Intelligence Decision card — เหมือน Final Decision Box ใน code.html
        สำหรับ summary_html ใน Live Analysis tab
        """
        sig_color = _sig_color(signal)
        sig_bg    = _sig_bg(signal)
        sig_icon  = {"BUY": "rocket_launch", "SELL": "trending_down"}.get(signal, "pause")

        strength_level = "normal"
        if confidence >= 0.85:
            strength_level = "strong"

        label_map = {
            "BUY":  "STRONG BUY" if strength_level == "strong" else "BUY",
            "SELL": "STRONG SELL" if strength_level == "strong" else "SELL",
            "HOLD": "HOLD",
        }
        display_label = label_map.get(signal, signal)

        rows = ""
        if entry_price:
            rows += f"""
            <div style="padding:10px 14px;background:{DT['surface_container']};
                        border-radius:8px;display:flex;justify-content:space-between;
                        margin-bottom:8px;">
                <span style="font-family:Inter,sans-serif;font-size:12px;
                             color:{DT['on_surface_var']};">Entry</span>
                <span style="font-family:'IBM Plex Mono',monospace;font-size:12px;
                             font-weight:600;color:{DT['on_surface']};">
                    ฿{entry_price:,.2f}
                </span>
            </div>"""
        if stop_loss:
            rows += f"""
            <div style="padding:10px 14px;background:{DT['surface_container']};
                        border-radius:8px;display:flex;justify-content:space-between;
                        margin-bottom:8px;">
                <span style="font-family:Inter,sans-serif;font-size:12px;
                             color:{DT['on_surface_var']};">Stop Loss</span>
                <span style="font-family:'IBM Plex Mono',monospace;font-size:12px;
                             font-weight:600;color:{DT['error']};">
                    ฿{stop_loss:,.2f}
                </span>
            </div>"""
        if take_profit:
            rows += f"""
            <div style="padding:10px 14px;background:{DT['surface_container']};
                        border-radius:8px;display:flex;justify-content:space-between;">
                <span style="font-family:Inter,sans-serif;font-size:12px;
                             color:{DT['on_surface_var']};">Take Profit</span>
                <span style="font-family:'IBM Plex Mono',monospace;font-size:12px;
                             font-weight:600;color:{DT['success']};">
                    ฿{take_profit:,.2f}
                </span>
            </div>"""

        return f"""
        {FONT_IMPORT}
        <div style="background:{DT['surface_lowest']};border-radius:14px;padding:24px;
                    box-shadow:{DT['shadow_float'] if strength_level!='strong' else '0px 0px 0px 2px rgba(16,185,129,0.25), 0px 24px 48px rgba(16,185,129,0.18)'};
                    border:1.5px solid {sig_color if strength_level=='strong' else 'rgba(0,88,190,0.08)'};">
            {_label("Final Intelligence Decision")}
            <div style="display:flex;align-items:center;gap:14px;
                        margin:16px 0 20px 0;">
                <div style="width:48px;height:48px;background:{sig_bg};
                            border-radius:50%;display:flex;align-items:center;
                            justify-content:center;font-size:22px;">
                    {'🚀🔥' if signal=='BUY' and strength_level=='strong' else ('📉🔥' if signal=='SELL' and strength_level=='strong' else ('🚀' if signal=='BUY' else ('📉' if signal=='SELL' else '⏸')))}
                </div>
                <div>
                    <div style="font-family:'Noto Serif',serif;font-size:24px;
                                font-weight:800;color:{sig_color};line-height:1;
                                letter-spacing:0.5px;">
                        {display_label}
                        {"🔥" if strength_level == "strong" else ""}
                    </div>
                    <div style="font-family:'IBM Plex Mono',monospace;font-size:11px;
                                color:{DT['on_surface_var']};margin-top:4px;">
                        Confidence Score: {confidence:.1%}
                    </div>
                </div>
            </div>
            {rows}
        </div>"""


# ─────────────────────────────────────────────
# LLM Log Renderer
# ─────────────────────────────────────────────

class LlmLogRenderer:
    """
    Render LLM thinking logs จาก DB — dark terminal aesthetic
    แสดงกระบวนการคิดของ LLM ต่อ 1 run: token usage, elapsed, trace, rationale
    ใช้ใน History tab (load run detail) และ Analysis tab (สรุปผลล่าสุด)
    """

    @staticmethod
    def format_llm_logs_html(logs: list) -> str:
        """Render list ของ llm_log entries จาก DB"""
        if not logs:
            return f"""
            {FONT_IMPORT}
            <div style="background:{DT['inverse_surface']};border-radius:12px;
                        padding:32px;text-align:center;
                        font-family:'IBM Plex Mono',monospace;font-size:12px;
                        color:#475569;">
                No LLM thinking logs recorded for this run.
            </div>"""

        entries_html = ""
        for log in logs:
            entries_html += LlmLogRenderer._render_log_entry(log)

        return f"""
        {FONT_IMPORT}
        <div style="background:{DT['inverse_surface']};border-radius:12px;
                    overflow:hidden;box-shadow:{DT['shadow_float']};">
            <!-- Terminal chrome -->
            <div style="background:#1e2d3d;padding:10px 16px;
                        display:flex;align-items:center;justify-content:space-between;">
                <div style="display:flex;gap:6px;align-items:center;">
                    <span style="width:10px;height:10px;border-radius:50%;background:#ef4444;display:inline-block;"></span>
                    <span style="width:10px;height:10px;border-radius:50%;background:#f59e0b;display:inline-block;"></span>
                    <span style="width:10px;height:10px;border-radius:50%;background:#10b981;display:inline-block;"></span>
                    <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;
                                 color:#475569;margin-left:12px;">🧠 LLM Thinking Log</span>
                </div>
                <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;
                             color:#334155;">{len(logs)} interval(s)</span>
            </div>
            <!-- Log content -->
            <div style="padding:16px 20px;max-height:500px;overflow-y:auto;
                        scrollbar-width:thin;scrollbar-color:#334155 transparent;">
                {entries_html}
                <p style="margin:8px 0 0 0;font-family:'IBM Plex Mono',monospace;
                           font-size:12px;color:#10b981;">
                    <span style="animation:blink 1s infinite;">_</span>
                </p>
            </div>
        </div>
        <style>@keyframes blink{{0%,100%{{opacity:1}}50%{{opacity:0}}}}</style>"""

    @staticmethod
    def _render_log_entry(log: dict) -> str:
        """Render 1 llm_log row เป็น HTML block"""
        interval  = log.get("interval_tf", "?")
        provider  = log.get("provider", "?")
        signal    = log.get("signal", "HOLD")
        conf      = log.get("confidence", 0.0)
        rationale = log.get("rationale", "")
        logged_at = log.get("logged_at", "")

        # ── prices ──────────────────────────────────────────────────────────
        entry  = log.get("entry_price")
        stop   = log.get("stop_loss")
        take   = log.get("take_profit")

        entry_str = f"฿{entry:,.0f}" if entry else "—"
        stop_str  = f"฿{stop:,.0f}"  if stop  else "—"
        take_str  = f"฿{take:,.0f}"  if take  else "—"

        # ── tokens ──────────────────────────────────────────────────────────
        tok_in    = log.get("token_input")
        tok_out   = log.get("token_output")
        tok_total = log.get("token_total")
        elapsed   = log.get("elapsed_ms")
        iters     = log.get("iterations_used", 0)
        tools     = log.get("tool_calls_used", 0)

        tok_str  = (
            f"in:{tok_in} out:{tok_out} total:{tok_total}"
            if tok_total else "tokens: N/A"
        )
        time_str = f"{elapsed:,}ms" if elapsed else "—"

        # ── fallback ─────────────────────────────────────────────────────────
        is_fallback   = log.get("is_fallback", False)
        fallback_from = log.get("fallback_from", "")
        fallback_badge = ""
        if is_fallback and fallback_from:
            fallback_badge = (
                f'<span style="background:rgba(239,83,80,0.15);color:#ef5350;'
                f'padding:1px 6px;border-radius:4px;font-size:9px;font-weight:700;">'
                f'FALLBACK from {fallback_from}</span> '
            )

        sig_color = {"BUY": "#10b981", "SELL": "#ef4444"}.get(signal, "#f59e0b")
        sig_icon  = {"BUY": "▲", "SELL": "▼"}.get(signal, "●")

        # ── trace steps (compact) ────────────────────────────────────────────
        trace_items = log.get("trace_json") or []
        trace_html  = ""
        if isinstance(trace_items, list) and trace_items:
            trace_rows = ""
            for step in trace_items:
                if not isinstance(step, dict):
                    continue
                s_type  = step.get("step", "?")
                s_iter  = step.get("iteration", "?")
                resp    = step.get("response", {})
                thought = resp.get("thought", "") or step.get("note", "")
                if thought:
                    thought = thought[:200] + ("…" if len(thought) > 200 else "")
                thought_html = (
                    f"<br><span style='color:#94a3b8;font-size:10px;line-height:1.4;'>"
                    f"{thought}</span>"
                    if thought else ""
                )
                trace_rows += (
                    f'<div style="padding:3px 0;border-bottom:1px solid rgba(255,255,255,0.04);">'
                    f'<span style="color:#475569;font-size:9px;">[{s_iter}] {s_type}</span>'
                    f'{thought_html}'
                    f'</div>'
                )
            trace_html = (
                f'<div style="margin-top:8px;padding:8px 10px;'
                f'background:rgba(255,255,255,0.03);border-radius:6px;">'
                f'<p style="margin:0 0 4px 0;font-family:\'IBM Plex Mono\',monospace;'
                f'font-size:9px;color:#475569;text-transform:uppercase;letter-spacing:1px;">'
                f'ReAct Steps</p>'
                f'{trace_rows}'
                f'</div>'
            )

        # ── full prompt/response (ถ้ามี) ────────────────────────────────────
        full_prompt   = log.get("full_prompt")
        full_response = log.get("full_response")
        prompt_html   = ""
        if full_prompt:
            fp = full_prompt[:500] + ("…" if len(full_prompt) > 500 else "")
            prompt_html += (
                f'<div style="margin-top:8px;padding:8px 10px;'
                f'background:rgba(0,88,190,0.08);border-radius:6px;">'
                f'<p style="margin:0 0 3px 0;font-family:\'IBM Plex Mono\',monospace;'
                f'font-size:9px;color:#adc6ff;text-transform:uppercase;letter-spacing:1px;">'
                f'Prompt</p>'
                f'<p style="margin:0;font-family:\'IBM Plex Mono\',monospace;font-size:10px;'
                f'color:#64748b;line-height:1.5;white-space:pre-wrap;">{fp}</p>'
                f'</div>'
            )
        if full_response:
            fr = full_response[:500] + ("…" if len(full_response) > 500 else "")
            prompt_html += (
                f'<div style="margin-top:8px;padding:8px 10px;'
                f'background:rgba(16,185,129,0.06);border-radius:6px;">'
                f'<p style="margin:0 0 3px 0;font-family:\'IBM Plex Mono\',monospace;'
                f'font-size:9px;color:#10b981;text-transform:uppercase;letter-spacing:1px;">'
                f'Response</p>'
                f'<p style="margin:0;font-family:\'IBM Plex Mono\',monospace;font-size:10px;'
                f'color:#64748b;line-height:1.5;white-space:pre-wrap;">{fr}</p>'
                f'</div>'
            )

        # ── rationale (คำนวณก่อน f-string เพื่อหลีกเลี่ยง backslash ใน f-string) ──
        rationale_html = ""
        if rationale:
            r_text = rationale[:400] + ("…" if len(rationale) > 400 else "")
            rationale_html = (
                f'<p style="margin:0 0 4px 0;font-family:\'IBM Plex Mono\',monospace;'
                f'font-size:10px;color:#94a3b8;line-height:1.6;">{r_text}</p>'
            )

        return f"""
        <div style="margin-bottom:16px;padding:12px 14px;
                    background:rgba(255,255,255,0.03);border-radius:8px;
                    border-left:3px solid {sig_color};">

            <!-- Header row -->
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:6px;">
                <span style="font-family:'IBM Plex Mono',monospace;font-size:11px;
                             color:#adc6ff;font-weight:700;">{interval}</span>
                <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;
                             color:#475569;">via {provider}</span>
                {fallback_badge}
                <span style="margin-left:auto;font-family:'IBM Plex Mono',monospace;
                             font-size:9px;color:#334155;">{logged_at}</span>
            </div>

            <!-- Signal + confidence -->
            <div style="display:inline-flex;align-items:center;gap:8px;
                        background:rgba(255,255,255,0.05);
                        padding:5px 12px;border-radius:6px;margin-bottom:8px;">
                <span style="font-family:'IBM Plex Mono',monospace;font-size:13px;
                             font-weight:800;color:{sig_color};">
                    {sig_icon} {signal}
                </span>
                <span style="font-family:'IBM Plex Mono',monospace;font-size:11px;
                             color:#64748b;">conf: {conf:.0%}</span>
            </div>

            <!-- Prices -->
            <div style="display:flex;gap:16px;margin-bottom:8px;flex-wrap:wrap;">
                <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:#64748b;">
                    Entry <strong style="color:#e2e8f0;">{entry_str}</strong>
                </span>
                <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:#64748b;">
                    SL <strong style="color:#ef4444;">{stop_str}</strong>
                </span>
                <span style="font-family:'IBM Plex Mono',monospace;font-size:10px;color:#64748b;">
                    TP <strong style="color:#10b981;">{take_str}</strong>
                </span>
            </div>

            <!-- Token + elapsed stats -->
            <div style="display:flex;gap:16px;margin-bottom:6px;flex-wrap:wrap;">
                <span style="font-family:'IBM Plex Mono',monospace;font-size:9px;color:#475569;">
                    🪙 {tok_str}
                </span>
                <span style="font-family:'IBM Plex Mono',monospace;font-size:9px;color:#475569;">
                    ⏱ {time_str}
                </span>
                <span style="font-family:'IBM Plex Mono',monospace;font-size:9px;color:#475569;">
                    iterations:{iters} tool_calls:{tools}
                </span>
            </div>

            <!-- Rationale -->
            {rationale_html}
            {trace_html}
            {prompt_html}
        </div>"""

    @staticmethod
    def format_llm_log_summary_html(logs: list) -> str:
        """
        Compact token/elapsed summary bar — แสดงใน Analysis tab
        ใต้ Trace panel เพื่อดู token usage ทันทีหลัง run
        """
        if not logs:
            return ""

        total_tokens  = sum(l.get("token_total") or 0 for l in logs)
        total_elapsed = sum(l.get("elapsed_ms") or 0 for l in logs)
        providers     = list({l.get("provider", "?") for l in logs})
        fallbacks     = [l for l in logs if l.get("is_fallback")]

        elapsed_str = (
            f"{total_elapsed/1000:.1f}s" if total_elapsed >= 1000
            else f"{total_elapsed}ms"
        )

        fallback_info = ""
        if fallbacks:
            fallback_info = (
                f'<span style="padding:2px 8px;background:rgba(239,83,80,0.15);'
                f'color:#ef5350;border-radius:4px;font-size:10px;">'
                f'⚠ {len(fallbacks)} fallback(s)</span>'
            )

        return f"""
        {FONT_IMPORT}
        <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;
                    padding:8px 14px;background:{DT['surface_low']};
                    border-radius:8px;font-family:'IBM Plex Mono',monospace;">
            <span style="font-size:11px;color:{DT['on_surface_var']};">
                🧠 LLM
            </span>
            <span style="font-size:11px;color:{DT['on_surface_var']};">
                🪙 tokens: <strong style="color:{DT['on_surface']};">{total_tokens:,}</strong>
            </span>
            <span style="font-size:11px;color:{DT['on_surface_var']};">
                ⏱ elapsed: <strong style="color:{DT['on_surface']};">{elapsed_str}</strong>
            </span>
            <span style="font-size:11px;color:{DT['on_surface_var']};">
                via: <strong style="color:{DT['on_surface']};">{', '.join(providers)}</strong>
            </span>
            {fallback_info}
        </div>"""