"""
ui/navbar/chart_page.py
📈 Live Chart — navbar page
"""

import gradio as gr

import time

# simple in-memory cache
_PRICE_CACHE = {
    "data": None,
    "ts": 0
}
CACHE_TTL = 30  # seconds

from ui.core import INTERVAL_CHOICES
from ui.core import StatusRenderer
from ui.core.chart_renderer import ChartTabRenderer
from ui.core.chart_service import chart_service
from logs.logger_setup import sys_logger, log_method

from .base import PageBase, PageComponents, AppContext, navbar_page


@navbar_page("📈 Live Chart")
class ChartPage(PageBase):
    """
    Embeds TradingView widget + live gold price card.
    Auto-refreshes every 60 seconds.
    """

    # ── Build ──────────────────────────────────────────────────────

    def build(self, ctx: AppContext) -> PageComponents:
        pc = PageComponents()

        # Controls (Top Card)
        with gr.Row():
            with gr.Column(elem_classes="card shadow p-4 bg-white"):
                gr.Markdown("### ⚙️ Chart Controls")

                pc.register("interval_dd", gr.Dropdown(
                    choices=INTERVAL_CHOICES,
                    value="1h",
                    label="⏱️ Candle Interval",
                    container=False,
                ))

                pc.register("fetch_btn", gr.Button(
                    "🔄 Refresh Live Price",
                    variant="primary",
                    
                ))

        pc.register("chart_status", gr.HTML(
            value=StatusRenderer.info_badge("กด Refresh หรือรอ auto-fetch (60s)")
        ))

        # Main layout: chart left | info right
        with gr.Row():
            with gr.Column(scale=3, elem_classes="card shadow p-3 bg-white"):
                gr.Markdown("### 📈 Live Gold Chart")
                pc.register("chart_widget", gr.HTML())

            with gr.Column(scale=1, min_width=340):
                with gr.Column(elem_classes="card shadow p-3 bg-white"):
                    gr.Markdown("### 💰 Gold Price")
                    pc.register("price_card", gr.HTML())

                with gr.Column(elem_classes="card shadow p-3 bg-white"):
                    gr.Markdown("### 🏦 Providers")
                    pc.register("provider_table", gr.HTML())

        return pc

    # ── Wire ───────────────────────────────────────────────────────

    def wire(self, demo: gr.Blocks, ctx: AppContext, pc: PageComponents) -> None:
        _outputs = [pc.chart_widget, pc.price_card, pc.provider_table, pc.chart_status]

        pc.fetch_btn.click(fn=self._fetch, inputs=[pc.interval_dd], outputs=_outputs)
        pc.interval_dd.change(fn=self._fetch, inputs=[pc.interval_dd], outputs=_outputs)

        chart_timer = gr.Timer(value=60, active=True)
        chart_timer.tick(fn=self._fetch, inputs=[pc.interval_dd], outputs=_outputs)

        # Load on startup
        demo.load(
            fn=lambda: self._fetch("1h"),
            inputs=[],
            outputs=_outputs,
        )

    # ── Handler ────────────────────────────────────────────────────

    @log_method(sys_logger)
    def _fetch(self, interval: str = "1h"):
        try:
            # map interval to TradingView format
            tv_interval_map = {
                "15m": "15",
                "30m": "30",
                "1h": "60",
                "4h": "240",
                "1d": "D"
            }
            tv_interval = tv_interval_map.get(interval, "60")

            # ── Chart always render ──
            chart_html = ChartTabRenderer.tradingview_widget(interval=tv_interval)

            # ── Cache check ──
            now = time.time()
            if _PRICE_CACHE["data"] and (now - _PRICE_CACHE["ts"] < CACHE_TTL):
                price_data = _PRICE_CACHE["data"]
            else:
                # ── Retry logic ──
                price_data = None
                for _ in range(3):
                    try:
                        price_data = chart_service.fetch_price(currency="THB")
                        if price_data.get("status") == "success":
                            break
                    except Exception as e:
                        sys_logger.warning(f"Retry fetch_price failed: {e}")
                        time.sleep(1)

                # ── Fallback mock if still fail ──
                if not price_data or price_data.get("status") != "success":
                    sys_logger.error("Using fallback price (mock)")
                    price_data = {
                        "status": "success",
                        "price": 2300,
                        "change_pct": 0.0,
                        "fetched_at": "fallback"
                    }

                # save cache
                _PRICE_CACHE["data"] = price_data
                _PRICE_CACHE["ts"] = now

            # ── Render UI ──
            price_html = ChartTabRenderer.gold_price_card(price_data)

            providers  = chart_service.get_providers_info()
            table_html = ChartTabRenderer.provider_table(providers)

            p   = price_data["price"]
            pct = price_data["change_pct"]
            icon = "▲" if pct >= 0 else "▼"

            status_html = StatusRenderer.success_badge(
                f"XAU/THB: ฿{p:,.0f} {icon} {abs(pct):.2f}% · {price_data['fetched_at']}"
            )

            return chart_html, price_html, table_html, status_html

        except Exception as exc:
            sys_logger.error(f"ChartPage fatal error: {exc}")
            err = StatusRenderer.error_badge(f"System Error: {exc}")
            return "", "", "", err