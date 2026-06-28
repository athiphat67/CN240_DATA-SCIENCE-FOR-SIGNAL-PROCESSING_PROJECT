"""
ui/dashboard.py v3.2 (REFACTORED)
Pure Gradio UI layer — Business logic moved to core/services.py

"""

import os
import argparse
import gradio as gr
from dotenv import load_dotenv
import importlib

import sys
from ui.navbar import NavbarBuilder, AppContext

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logs.logger_setup import sys_logger, log_method


# ✅ Import from refactored modules
from ui.core import (
    UI_CONFIG,
    PROVIDER_CHOICES,
    PERIOD_CHOICES,
    INTERVAL_CHOICES,
    AUTO_RUN_INTERVALS,
    DEFAULT_AUTO_RUN,
)
from ui.core.renderers import (
    TraceRenderer,
    HistoryRenderer,
    PortfolioRenderer,
    StatsRenderer,
    StatusRenderer,
)
from ui.core.utils import (
    format_voting_summary,
    format_error_message,
)
from ui.core.config import get_all_llm_choices

try:
    from backtest.engine.csv_orchestrator import CSVOrchestrator
except ImportError as e:
    sys_logger.error(f"⚠️  Import error: {e}")
    raise

load_dotenv()

# ─────────────────────────────────────────────
# Global Initialization
# ─────────────────────────────────────────────

base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Registries + Runtime Services
# Keep Dashboard wired to main.py symbols so CLI changes propagate here.
main_runtime = importlib.import_module("main")

skill_registry = main_runtime.SkillRegistry()
skill_registry.load_from_json(
    os.path.join(base_dir, "agent_core", "config", "skills.json")
)

role_registry = main_runtime.RoleRegistry(skill_registry)
role_registry.load_from_json(
    os.path.join(base_dir, "agent_core", "config", "roles.json")
)

print("Registered roles:", list(role_registry.roles.keys()))
print("Registered skills:", list(skill_registry.skills.keys()))

# Data + Database
orchestrator = main_runtime.GoldTradingOrchestrator()
db = main_runtime.RunDatabase()

# Services (business logic)
services = main_runtime.init_services(skill_registry, role_registry, orchestrator, db)

ctx = AppContext(services=services, orchestrator=orchestrator, db=db)

# ── WatcherEngine (background thread) ───────────────────────────────────────
_watcher = None
try:
    from engine.engine import WatcherEngine

    _watcher = WatcherEngine(
        analysis_service  = services["analysis"],
        data_orchestrator = orchestrator,
        watcher_config    = {
            "provider":  "gemini",
            "period":    "1d",
            "interval":  "5m",
        },
    )
    _watcher.start()
    sys_logger.info("🔭 WatcherEngine started (dashboard background thread)")
except Exception as _we:
    sys_logger.warning(f"WatcherEngine not started: {_we}")

sys_logger.info("Dashboard initialized")

# ─────────────────────────────────────────────
# Event Handlers (Callbacks)
# ─────────────────────────────────────────────


@log_method(sys_logger)
def handle_run_analysis(provider: str, period: str, intervals: list):
    """Handle 'Run Analysis' button click - calls AnalysisService"""
    try:
        args = argparse.Namespace(
            provider=provider,
            period=period,
            intervals=intervals,
            skip_fetch=False,
            no_save=False,
            bypass_session_gate=False,
        )
        result = main_runtime.run_analysis_once(args, services, emit_logs=False)

        # Handle error response
        if result["status"] == "error":
            error_msg = format_error_message(result)
            error_badge = StatusRenderer.error_badge(
                error_msg, is_validation=(result.get("error_type") == "validation")
            )
            return ("", "", error_msg, error_badge, "", "", "", error_badge)

        # Extract successful data
        voting_result    = result["voting_result"]
        interval_results = result["data"]["interval_results"]
        market_open      = result.get("market_open", True)

        # Market status badge
        if not market_open:
            market_status = StatusRenderer.warning_badge("⚠️ ตลาดทองไทยปิดอยู่ (weekend/holiday) — ราคาอาจล่าช้า")
        else:
            market_status = StatusRenderer.success_badge("✅ ตลาดทองไทยเปิด")

        # Extract THB prices from best interval result
        best_interval = max(interval_results.items(), key=lambda x: x[1]["confidence"])[0]
        best_ir = interval_results.get(best_interval, {})
        md = result["data"]["market_state"].get("market_data", {})
        usd_thb    = md.get("forex", {}).get("usd_thb", 0)
        sell_thb   = md.get("thai_gold_thb", {}).get("sell_price_thb", "N/A")
        buy_thb    = md.get("thai_gold_thb", {}).get("buy_price_thb", "N/A")

        def usd_to_thb_gram(usd_oz):
            if usd_oz and usd_thb:
                return round(usd_oz / 31.1035 * usd_thb, 0)
            return None

        entry_thb = usd_to_thb_gram(best_ir.get("entry_price"))
        stop_thb  = usd_to_thb_gram(best_ir.get("stop_loss"))
        take_thb  = usd_to_thb_gram(best_ir.get("take_profit"))

        # Format outputs
        market_txt = str(result["data"]["market_state"])[:1000]
        voting_summary = format_voting_summary(voting_result)

        final_decision_txt = f"""{voting_summary}

        Final Signal: {voting_result['final_signal']}
        Confidence: {voting_result['weighted_confidence']:.1%}

        ── ราคา ออม NOW Reference ──
        ราคาตลาด:  ฿{sell_thb} (ขาย) / ฿{buy_thb} (ซื้อ)  [THB/gram]
        USD/THB:   {usd_thb}

        ── Price Levels (USD/oz → THB/gram) ──
        Entry:      ${best_ir.get('entry_price', 'N/A')} → ฿{entry_thb or 'N/A'}/gram
        Stop Loss:  ${best_ir.get('stop_loss', 'N/A')} → ฿{stop_thb or 'N/A'}/gram
        Take Profit:${best_ir.get('take_profit', 'N/A')} → ฿{take_thb or 'N/A'}/gram

        Per-Interval Details:
        """
        for iv, ir in interval_results.items():
            icon = {"BUY": "🟢", "SELL": "🔴"}.get(ir["signal"], "🟡")
            final_decision_txt += (
                f"  {iv:5s} → {icon} {ir['signal']:4s} ({ir['confidence']:.0%})\n"
            )

        explain_html = TraceRenderer.format_trace_html(
            interval_results.get(best_interval, {}).get("trace", [])
        )

        # Get history and stats
        history_html = HistoryRenderer.format_history_html(
            services["history"].get_recent_runs(limit=20)
        )
        stats = services["history"].get_statistics()
        stats_html = StatsRenderer.format_stats_html(stats)

        # Create summary card
        summary_html = f"""
        <div style="background:linear-gradient(135deg, #e3f2fd, #f3e5f5);border:2px solid #4c84af;border-radius:12px;padding:20px;">
            <h3 style="margin-top:0;color:#1a4a7a;">📊 Analysis Result</h3>
            <p>🏦 ออม NOW: <b>฿{sell_thb}</b> sell / <b>฿{buy_thb}</b> buy</p>
            {voting_summary}
        </div>
        """

        success_badge = StatusRenderer.success_badge(
            f"Analysis complete - {voting_result['final_signal']} signal"
        )
        
        main_runtime.send_trade_log_from_result(result, emit_logs=False)

        return (
            market_txt,
            f"Trace from {best_interval} interval ({len(interval_results.get(best_interval, {}).get('trace', []))} steps)",
            final_decision_txt,
            explain_html,
            history_html,
            stats_html,
            summary_html,
            market_status,
        )

    except Exception as e:
        sys_logger.error(f"Error in analysis: {e}")
        error_badge = StatusRenderer.error_badge(f"Unexpected error: {str(e)}")
        return ("", "", f"❌ {str(e)}", error_badge, "", "", "", error_badge)


@log_method(sys_logger)
def handle_refresh_history():
    """Handle 'Refresh' button in History tab"""
    try:
        history_html = HistoryRenderer.format_history_html(
            services["history"].get_recent_runs(limit=50)
        )
        stats = services["history"].get_statistics()
        stats_html = StatsRenderer.format_stats_html(stats)
        return history_html, stats_html
    except Exception as e:
        sys_logger.error(f"Error refreshing history: {e}")
        return StatusRenderer.error_badge(f"Failed to load history: {e}"), ""


@log_method(sys_logger)
def handle_load_run_detail(run_id_str: str):
    """Load detail for specific run from history"""
    try:
        run_id = int(run_id_str.lstrip("#"))
        detail = services["history"].get_run_detail(run_id)

        if detail["status"] == "error":
            return StatusRenderer.error_badge(detail["message"]), ""

        run = detail["data"]
        trace_html = TraceRenderer.format_trace_html(run.get("trace", []))
        fd_txt = f"""Signal: {run.get('signal', 'HOLD')}
        Confidence: {run.get('confidence', 0):.0%}
        Provider: {run.get('provider', '—')}
        Time: {run.get('run_at', '—')}"""

        return trace_html, fd_txt
    except Exception as e:
        return StatusRenderer.error_badge(f"Failed to load run: {e}"), ""


@log_method(sys_logger)
def handle_save_portfolio(cash, gold, cost, cur_val, pnl, trades):
    """Save portfolio to database"""
    try:
        result = services["portfolio"].save_portfolio(
            cash=cash,
            gold_grams=gold,
            cost_basis=cost,
            current_value=cur_val,
            pnl=pnl,
            trades_today=trades,
        )

        if result["status"] == "success":
            portfolio_html = PortfolioRenderer.format_portfolio_html(result["data"])
            status_msg = StatusRenderer.success_badge(result["message"])
            return status_msg, portfolio_html
        else:
            status_msg = StatusRenderer.error_badge(result["message"])
            return status_msg, ""

    except Exception as e:
        status_msg = StatusRenderer.error_badge(f"Save failed: {e}")
        return status_msg, ""


@log_method(sys_logger)
def handle_load_portfolio():
    """Load portfolio from database and fill form"""
    try:
        result = services["portfolio"].load_portfolio()
        pf = result["data"]

        portfolio_html = PortfolioRenderer.format_portfolio_html(pf)
        status_msg = StatusRenderer.success_badge("✅ Portfolio loaded")

        return (
            gr.update(value=float(pf.get("cash_balance", 0))),
            gr.update(value=float(pf.get("gold_grams", 0))),
            gr.update(value=float(pf.get("cost_basis_thb", 0))),
            gr.update(value=float(pf.get("current_value_thb", 0))),
            gr.update(value=float(pf.get("unrealized_pnl", 0))),
            gr.update(value=float(pf.get("trades_today", 0))),
            status_msg,
            portfolio_html,
        )

    except Exception as e:
        status_msg = StatusRenderer.error_badge(f"Load failed: {e}")
        return (
            gr.update(value=0),  # pf_cash
            gr.update(value=0),  # pf_gold
            gr.update(value=0),  # pf_cost
            gr.update(value=0),  # pf_curval
            gr.update(value=0),  # pf_pnl
            gr.update(value=0),  # pf_trade
            status_msg,  # pf_status
            "",  # pf_display
        )


def handle_auto_run(
    enabled: bool, provider: str, period: str, intervals: list, interval_minutes: str
):
    """Handle auto-run timer tick"""
    if not enabled:
        return [gr.update()] * 8 + [StatusRenderer.info_badge("⏸️  Auto-run disabled")]

    result = handle_run_analysis(provider, period, intervals)
    interval_sec = AUTO_RUN_INTERVALS.get(interval_minutes, 900)

    return list(result[:-1]) + [
        StatusRenderer.success_badge(f"✅ Running every {interval_minutes} min")
    ]


def handle_timer_toggle(enabled: bool):
    """Toggle auto-run timer display"""
    return (
        StatusRenderer.success_badge("✅ Auto-run enabled")
        if enabled
        else StatusRenderer.info_badge("⏸️  Auto-run disabled")
    )


def handle_refresh_watcher_logs():
    """Poll WatcherEngine logs for Gradio Watcher tab"""
    if _watcher is None:
        return "⚠️  WatcherEngine ไม่ได้ start (engine module ไม่พบ หรือ config ผิด)"
    logs = _watcher.get_logs()
    if not logs:
        return "— ยังไม่มี log —"
    return "\n".join(reversed(logs))  # ล่าสุดขึ้นก่อน


# ─────────────────────────────────────────────
# Gradio UI Definition
# ─────────────────────────────────────────────

from ui.core.dashboard_css import DASHBOARD_CSS
import base64

try:
    with open("assets/logo.png", "rb") as img_file:
        b64_logo = base64.b64encode(img_file.read()).decode('utf-8')
    logo_src = f"data:image/png;base64,{b64_logo}"
except Exception as e:
    print(f"Could not load logo: {e}")
    logo_src = ""

FINAL_CSS = DASHBOARD_CSS + f"""
.tab-nav button:first-child {{
    background-image: url('{logo_src}') !important;
    background-size: 18px !important;
    background-repeat: no-repeat !important;
    background-position: left 12px center !important;
    padding-left: 38px !important;
}}
"""

FINAL_CSS = DASHBOARD_CSS + f"""
.tab-nav button:first-child {{
    background-image: url('{logo_src}') !important;
    background-size: 18px !important;
    background-repeat: no-repeat !important;
    background-position: left 12px center !important;
    padding-left: 38px !important;
}}
"""

FORCE_LIGHT_JS = """
function() {
    // 1. Destroy LocalStorage theme setting
    localStorage.setItem('gradio-theme', 'light');
    
    const htmlElement = document.documentElement;
    
    // 2. The Enforcer Function
    const enforceLight = () => {
        if (htmlElement.classList.contains('dark')) {
            htmlElement.classList.remove('dark');
            htmlElement.classList.add('light');
            htmlElement.style.colorScheme = 'light';
        }
    };
    
    enforceLight(); // Run immediately
    
    // 3. The Security Guard: Watches the entire page for changes
    const observer = new MutationObserver(() => {
        // Instantly block dark mode if Gradio tries to apply it
        enforceLight();
        
        // Vaporize the "Display Theme" text if the Settings menu opens
        const xpath = "//text()[normalize-space()='Display Theme']";
        const matchingText = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
        
        if (matchingText && matchingText.parentElement) {
            // Find the wrapper box and hide it completely
            const container = matchingText.parentElement.closest('.block, fieldset') || matchingText.parentElement.parentElement;
            if (container) container.style.display = 'none';
        }
    });
    
    // Start watching the page
    observer.observe(document, { attributes: true, childList: true, subtree: true });
}
"""

# ── ADD js=FORCE_LIGHT_JS TO gr.Blocks ──
with gr.Blocks(title=UI_CONFIG["title"],
               theme=gr.themes.Soft(),
               css=FINAL_CSS,
               js=FORCE_LIGHT_JS) as demo:
    gr.Markdown(f"""
        <h1>
            <img src='{logo_src}' style='height: 40px; vertical-align: middle; margin-right: 10px; margin-bottom: 5px; display: inline-block;' /> 
            AI Gold Trading Agent Dashboard
        </h1>
        """)
        
    gr.Markdown("**ReAct LLM loop with weighted voting — real-time gold analysis**")
 
    NavbarBuilder.build_all(demo, ctx)

    # ── Watcher Engine Tab ───────────────────────────────────────────────────
    with gr.Tab("🔭 Watcher Logs"):
        gr.Markdown("### WatcherEngine — Real-time Market Monitor")
        gr.Markdown(
            "Watcher รัน background thread ตรวจ RSI + Trailing Stop ทุก 3 วินาที  \n"
            "กด **Refresh** เพื่อดู log ล่าสุด หรือเปิด **Auto-refresh** (ทุก 10 วิ)"
        )
        with gr.Row():
            watcher_refresh_btn  = gr.Button("🔄 Refresh Logs", variant="secondary")
            watcher_auto_refresh = gr.Checkbox(label="Auto-refresh (10s)", value=False)

        watcher_status = gr.Textbox(
            label="Watcher Status",
            value="⏳ กด Refresh เพื่อดู log",
            lines=20,
            interactive=False,
        )

        watcher_refresh_btn.click(
            fn=handle_refresh_watcher_logs,
            inputs=[],
            outputs=[watcher_status],
        )

        watcher_timer = gr.Timer(value=10, active=False)
        watcher_auto_refresh.change(
            fn=lambda enabled: gr.update(active=enabled),
            inputs=[watcher_auto_refresh],
            outputs=[watcher_timer],
        )
        watcher_timer.tick(
            fn=handle_refresh_watcher_logs,
            inputs=[],
            outputs=[watcher_status],
        )


# ─────────────────────────────────────────────
# Launch
# ─────────────────────────────────────────────

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("🟡 GoldTrader Dashboard v3.2 (Refactored)")
    print(f"   Services: ✅ AnalysisService | ✅ PortfolioService | ✅ HistoryService")
    print(f"   Config: ✅ core/config.py")
    print(f"   Renderers: ✅ core/renderers.py")
    print(f"   Utils: ✅ core/utils.py")
    print("=" * 70)
    env_port = os.environ.get("PORT", UI_CONFIG["port"])
    admin_user = os.environ.get("DASHBOARD_USER", "admin")
    admin_pass = os.environ.get("DASHBOARD_PASS", "team@nakkhutthong69")
    demo.launch(server_name="0.0.0.0", server_port=int(env_port), show_error=True, auth=(admin_user, admin_pass), theme=gr.themes.Soft(), css=FINAL_CSS)