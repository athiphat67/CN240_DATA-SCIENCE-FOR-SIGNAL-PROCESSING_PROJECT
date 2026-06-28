"""
ui/navbar/portfolio_page.py
💼 Portfolio — navbar page
"""

import gradio as gr

from ui.core import PortfolioRenderer, StatusRenderer
from logs.logger_setup import sys_logger, log_method

from .base import PageBase, PageComponents, AppContext, navbar_page


@navbar_page("💼 Portfolio")
class PortfolioPage(PageBase):

    # ── Build ──────────────────────────────────────────────────────

    def build(self, ctx: AppContext) -> PageComponents:
        pc = PageComponents()

        gr.Markdown(
            "### 💼 Portfolio Management\n"
            "กรอกข้อมูลจากแอพ **ออม NOW** → กด **Save** → ดู summary"
        )

        pc.register("display", gr.HTML(label="Portfolio Summary"))

        with gr.Row():
            pc.register("cash",   gr.Number(label="💵 Cash Balance (฿)", value=1500.0, precision=2))
            pc.register("gold",   gr.Number(label="🥇 Gold (grams)",      value=0.0,    precision=4))
            pc.register("trades", gr.Number(label="🔄 Trades Today",      value=0,      precision=0))

        with gr.Row():
            pc.register("cost",    gr.Number(label="📥 Cost Basis (฿)",   value=0.0, precision=2))
            pc.register("cur_val", gr.Number(label="📊 Current Value (฿)",value=0.0, precision=2))
            pc.register("pnl",     gr.Number(label="📈 P&L (฿)",          value=0.0, precision=2))

        with gr.Row():
            pc.register("save_btn",   gr.Button("💾 Save Portfolio",     variant="primary"))
            pc.register("reload_btn", gr.Button("🔄 Load from Database"))
        
        pc.register("status",  gr.HTML(label="Status"))

        return pc

    # ── Wire ───────────────────────────────────────────────────────

    def wire(self, demo: gr.Blocks, ctx: AppContext, pc: PageComponents) -> None:
        _form_outputs = [
            pc.cash, pc.gold, pc.cost, pc.cur_val, pc.pnl, pc.trades,
            pc.status, pc.display,
        ]

        pc.save_btn.click(
            fn=self._handle_save(ctx),
            inputs=[pc.cash, pc.gold, pc.cost, pc.cur_val, pc.pnl, pc.trades],
            outputs=[pc.status, pc.display],
        )

        pc.reload_btn.click(
            fn=self._handle_load(ctx),
            inputs=[],
            outputs=_form_outputs,
        )

        demo.load(
            fn=self._handle_load(ctx),
            outputs=_form_outputs,
        )

    # ── Handlers ───────────────────────────────────────────────────

    def _handle_save(self, ctx: AppContext):
        services = ctx.services

        @log_method(sys_logger)
        def _save(cash, gold, cost, cur_val, pnl, trades):
            try:
                result = services["portfolio"].save_portfolio(
                    cash=cash, gold_grams=gold, cost_basis=cost,
                    current_value=cur_val, pnl=pnl, trades_today=trades,
                )
                if result["status"] == "success":
                    return (
                        StatusRenderer.success_badge(result["message"]),
                        PortfolioRenderer.format_portfolio_html(result["data"]),
                    )
                return StatusRenderer.error_badge(result["message"]), ""
            except Exception as exc:
                return StatusRenderer.error_badge(f"Save failed: {exc}"), ""

        return _save

    def _handle_load(self, ctx: AppContext):
        services = ctx.services

        @log_method(sys_logger)
        def _load():
            try:
                result = services["portfolio"].load_portfolio()
                pf     = result["data"]
                return (
                    gr.update(value=float(pf.get("cash_balance",      0))),
                    gr.update(value=float(pf.get("gold_grams",        0))),
                    gr.update(value=float(pf.get("cost_basis_thb",    0))),
                    gr.update(value=float(pf.get("current_value_thb", 0))),
                    gr.update(value=float(pf.get("unrealized_pnl",    0))),
                    gr.update(value=float(pf.get("trades_today",      0))),
                    StatusRenderer.success_badge("✅ Portfolio loaded"),
                    PortfolioRenderer.format_portfolio_html(pf),
                )
            except Exception as exc:
                badge = StatusRenderer.error_badge(f"Load failed: {exc}")
                return (*[gr.update(value=0)] * 6, badge, "")

        return _load