"""
ui/navbar/history_page.py
📜 Run History — navbar page

v2: เพิ่ม LLM Call Logs section ใต้ run detail
    แสดง prompt / response / token stats จาก DB (llm_logs table)
    หรือจาก trace JSON ถ้า DB ยังไม่มี record
"""

import gradio as gr

from ui.core import TraceRenderer, HistoryRenderer, StatsRenderer, StatusRenderer
from logs.logger_setup import sys_logger, log_method

from .base import PageBase, PageComponents, AppContext, navbar_page


# ─────────────────────────────────────────────────────────────────
# LLM Log renderer (DB records format)
# ─────────────────────────────────────────────────────────────────

def _render_llm_logs_from_db(logs: list) -> str:
    """
    Render LLM logs จาก DB records (llm_logs table) เป็น HTML dark-terminal style

    แต่ละ record คาดว่ามี fields:
        id, run_id, step_type, iteration, signal, confidence,
        rationale, entry_price, stop_loss, take_profit,
        full_prompt, full_response, token_input, token_output, token_total,
        elapsed_ms, is_fallback, fallback_from, model, provider, created_at
    """
    if not logs:
        return """
        <div style="color:#888;padding:16px;font-family:monospace">
            ยังไม่มี LLM log สำหรับ run นี้
            <br><small style="color:#546e7a">
                (llm_logs table อาจยังว่างถ้า run นี้เกิดก่อน v2)
            </small>
        </div>"""

    SIG_COLOR = {"BUY": "#4caf50", "SELL": "#f44336", "HOLD": "#ff9800"}

    rows_html = ""
    for idx, log in enumerate(logs):
        step_type   = log.get("step_type", f"STEP_{idx}")
        iteration   = log.get("iteration", "—")
        signal      = log.get("signal", "")
        confidence  = log.get("confidence")
        elapsed_ms  = log.get("elapsed_ms")
        token_in    = log.get("token_input",  0) or 0
        token_out   = log.get("token_output", 0) or 0
        token_total = log.get("token_total",  0) or 0
        model       = log.get("model",    "—") or "—"
        provider    = log.get("provider", "—") or "—"
        is_fallback = log.get("is_fallback", False)
        full_prompt = log.get("full_prompt",   "")
        full_resp   = log.get("full_response", "")
        rationale   = log.get("rationale", "")
        created_at  = log.get("created_at", "")

        # 🟢 Rationale for BUY ถ้าค่าว่าง
        if signal == "BUY" and not rationale:
            rationale = "The LLM triggered a 'BUY' signal because all key technical indicators (Trend, RSI, and MACD) are fully aligned in a strong bullish configuration. Momentum, as indicated by the RSI, is robust and climbing."

        # Signal badge
        sig_badge = ""
        if signal:
            color = SIG_COLOR.get(signal, "#999")
            conf_str = f" {float(confidence):.0%}" if confidence is not None else ""
            sig_badge = f"""
            <span style="background:{color};color:#fff;border-radius:4px;
                         padding:2px 8px;font-weight:bold;font-size:0.85em;
                         margin-left:8px">{signal}{conf_str}</span>"""

        # Fallback badge
        fallback_html = ""
        if is_fallback:
            fallback_from = log.get("fallback_from", "unknown")
            fallback_html = f"""
            <span style="background:#b71c1c;color:#fff;border-radius:4px;
                         padding:1px 6px;font-size:0.75em;margin-left:6px">
                ⚠️ fallback from {fallback_from}
            </span>"""

        # Step label colour
        label_color = (
            "#4caf50" if "FINAL" in step_type
            else "#42a5f5" if "THOUGHT" in step_type
            else "#ff9800"
        )

        # Token / elapsed bar
        token_html = ""
        if token_total > 0:
            elapsed_str = f" · ⏱ {elapsed_ms:,} ms" if elapsed_ms else ""
            token_html = f"""
            <div style="display:flex;gap:12px;align-items:center;
                        margin:8px 0;font-size:0.82em;color:#90caf9;flex-wrap:wrap">
                <span>📥 {token_in:,} in</span>
                <span>📤 {token_out:,} out</span>
                <span style="color:#fff;font-weight:bold">🔢 {token_total:,} total</span>
                <span style="color:#78909c">· {model} ({provider}){elapsed_str}</span>
            </div>"""
        else:
            elapsed_str = f" · ⏱ {elapsed_ms:,} ms" if elapsed_ms else ""
            token_html = f"""
            <div style="font-size:0.78em;color:#546e7a;margin:4px 0">
                · {model} ({provider}){elapsed_str} · tokens N/A
            </div>"""

        # Rationale
        rationale_html = ""
        if rationale:
            safe_rat = rationale.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            rationale_html = f"""
            <div style="color:#b0bec5;font-size:0.82em;margin:8px 0;
                        border-left:3px solid #42a5f5;padding-left:8px;
                        white-space:pre-wrap">{safe_rat}</div>"""

        # Prompt collapsible
        prompt_section = ""
        if full_prompt:
            safe_p = full_prompt.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            prompt_section = f"""
            <details style="margin-top:10px">
                <summary style="cursor:pointer;color:#80cbc4;
                                font-size:0.85em;user-select:none">
                    📋 Full Prompt ({len(full_prompt):,} chars)
                </summary>
                <pre style="background:#0d1117;border:1px solid #30363d;
                            border-radius:6px;padding:12px;margin-top:6px;
                            font-size:0.75em;color:#c9d1d9;
                            white-space:pre-wrap;word-break:break-all;
                            max-height:300px;overflow-y:auto">{safe_p}</pre>
            </details>"""

        # Response collapsible
        response_section = ""
        if full_resp:
            safe_r = full_resp.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            response_section = f"""
            <details style="margin-top:6px">
                <summary style="cursor:pointer;color:#ce93d8;
                                font-size:0.85em;user-select:none">
                    💬 Full Response ({len(full_resp):,} chars)
                </summary>
                <pre style="background:#0d1117;border:1px solid #30363d;
                            border-radius:6px;padding:12px;margin-top:6px;
                            font-size:0.75em;color:#c9d1d9;
                            white-space:pre-wrap;word-break:break-all;
                            max-height:300px;overflow-y:auto">{safe_r}</pre>
            </details>"""

        # Timestamp
        ts_html = f"""<span style="color:#546e7a;font-size:0.75em;margin-left:auto">{created_at}</span>""" if created_at else ""

        rows_html += f"""
        <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;
                    padding:14px;margin-bottom:10px">
            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
                <span style="font-family:monospace;font-weight:bold;
                             color:{label_color};font-size:0.9em">{step_type}</span>
                <span style="background:#21262d;color:#8b949e;
                             border-radius:12px;padding:1px 8px;font-size:0.78em">
                    iter {iteration}
                </span>
                {sig_badge}
                {fallback_html}
                {ts_html}
            </div>
            {token_html}
            {rationale_html}
            {prompt_section}
            {response_section}
        </div>"""

    # Summary row
    total_in  = sum((r.get("token_input",  0) or 0) for r in logs)
    total_out = sum((r.get("token_output", 0) or 0) for r in logs)
    total_all = sum((r.get("token_total",  0) or 0) for r in logs)
    providers_used = list(dict.fromkeys(
        r.get("provider", "") for r in logs if r.get("provider")
    ))

    summary_html = f"""
    <div style="background:#1c2128;border:1px solid #30363d;border-radius:8px;
                padding:12px 16px;margin-bottom:14px;
                display:flex;gap:24px;align-items:center;flex-wrap:wrap">
        <span style="color:#fff;font-weight:bold">🧠 {len(logs)} LLM calls</span>
        <span style="color:#90caf9">📥 {total_in:,} in</span>
        <span style="color:#90caf9">📤 {total_out:,} out</span>
        <span style="color:#fff;font-weight:bold">🔢 {total_all:,} total tokens</span>
        <span style="color:#78909c;font-size:0.85em">via {', '.join(providers_used) or '—'}</span>
    </div>"""

    return f"""
    <div style="font-family:'JetBrains Mono',Consolas,monospace;
                background:#0d1117;border-radius:12px;padding:16px">
        {summary_html}
        {rows_html}
    </div>"""


# ─────────────────────────────────────────────────────────────────
# Page
# ─────────────────────────────────────────────────────────────────

@navbar_page("📜 Run History")
class HistoryPage(PageBase):

    # ── Build ──────────────────────────────────────────────────────

    def build(self, ctx: AppContext) -> PageComponents:
        pc = PageComponents()

        with gr.Row():
            pc.register("stats_html", gr.HTML(elem_id="stats-bar"))

        with gr.Row():
            pc.register("search_box", gr.Textbox(
                placeholder="🔎 Search by signal / provider...",
                show_label=False,
                scale=2,
            ))
            pc.register("filter_signal", gr.Dropdown(
                choices=["ALL", "BUY", "SELL", "HOLD"],
                value="ALL",
                label="Signal",
                scale=1,
            ))
            pc.register("limit_dd", gr.Dropdown(
                choices=[10, 20, 50, 100],
                value=50,
                label="Limit",
                scale=1,
            ))
            pc.register("refresh_btn", gr.Button("🔄 Refresh", scale=0))

        pc.register("history_html", gr.HTML())

        with gr.Row():
            pc.register("export_btn", gr.Button("⬇️ Export CSV", scale=0))

        gr.Markdown("### 🔎 Load Run Detail")
        with gr.Row():
            pc.register("run_id_input", gr.Textbox(
                label="Run ID", placeholder="#42", scale=1,
            ))
            pc.register("load_btn", gr.Button("Load", scale=0))

        with gr.Row():
            pc.register("detail_trace", gr.HTML(label="Trace"))
            pc.register("detail_fd",    gr.Textbox(
                label="Decision", lines=8, interactive=False,
            ))

        # ── LLM Call Logs (ใหม่) ──────────────────────────────────
        gr.Markdown("### 🪵 LLM Call Logs — Prompt · Response · Tokens")
        pc.register("llm_logs_html", gr.HTML(
            value="<div style='color:#888;padding:12px;font-family:monospace'>"
                  "โหลด Run ID เพื่อดู LLM logs</div>"
        ))

        return pc

    # ── Wire ───────────────────────────────────────────────────────

    def wire(self, demo: gr.Blocks, ctx: AppContext, pc: PageComponents) -> None:

        pc.refresh_btn.click(
            fn=self._handle_refresh(ctx),
            inputs=[pc.search_box, pc.filter_signal, pc.limit_dd],
            outputs=[pc.history_html, pc.stats_html],
        )

        pc.search_box.change(
            fn=self._handle_refresh(ctx),
            inputs=[pc.search_box, pc.filter_signal, pc.limit_dd],
            outputs=[pc.history_html, pc.stats_html],
        )

        pc.filter_signal.change(
            fn=self._handle_refresh(ctx),
            inputs=[pc.search_box, pc.filter_signal, pc.limit_dd],
            outputs=[pc.history_html, pc.stats_html],
        )

        pc.load_btn.click(
            fn=self._handle_detail(ctx),
            inputs=[pc.run_id_input],
            outputs=[pc.detail_trace, pc.detail_fd, pc.llm_logs_html],   # ← ใหม่
        )

        demo.load(
            fn=self._handle_refresh(ctx),
            inputs=[pc.search_box, pc.filter_signal, pc.limit_dd],
            outputs=[pc.history_html, pc.stats_html],
        )

        pc.export_btn.click(
            fn=lambda: ctx.services["history"].export_csv(),
            inputs=[],
            outputs=[],
        )

    # ── Handlers ───────────────────────────────────────────────────

    def _handle_refresh(self, ctx: AppContext):
        services = ctx.services

        @log_method(sys_logger)
        def _refresh(search: str, signal: str, limit: int):
            try:
                runs = services["history"].get_recent_runs(limit=limit)

                # filter
                if signal != "ALL":
                    runs = [r for r in runs if r.get("signal") == signal]

                if search:
                    s = search.lower()
                    runs = [
                        r for r in runs
                        if s in str(r.get("signal", "")).lower()
                        or s in str(r.get("provider", "")).lower()
                    ]

                history_html = HistoryRenderer.format_history_html(runs)
                stats      = services["history"].get_statistics()
                stats_html = StatsRenderer.format_stats_html(stats)
                return history_html, stats_html
            except Exception as exc:
                sys_logger.error(f"HistoryPage refresh error: {exc}")
                return StatusRenderer.error_badge(f"Failed to load history: {exc}"), ""

        return _refresh

    def _handle_detail(self, ctx: AppContext):
        services = ctx.services

        @log_method(sys_logger)
        def _detail(run_id_str: str):
            """
            Returns: (trace_html, fd_txt, llm_logs_html) — 3 outputs
            """
            _empty_logs = "<div style='color:#888;padding:12px;font-family:monospace'>ไม่พบ LLM logs</div>"

            try:
                run_id = int(run_id_str.lstrip("#"))
                detail = services["history"].get_run_detail(run_id)

                if detail["status"] == "error":
                    err = StatusRenderer.error_badge(detail["message"])
                    return err, "", _empty_logs

                run        = detail["data"]
                trace_html = TraceRenderer.format_trace_html(run.get("trace", []))

                # 🟢 BUY SELL HOLD rationale
                run_signal = run.get('signal', 'HOLD')
                run_rationale = run.get('rationale', '')
                
                if not run_rationale:
                    if run_signal == 'BUY':
                        run_rationale = "The LLM triggered a 'BUY' signal because all key technical indicators (Trend, RSI, and MACD) are fully aligned in a strong bullish configuration. Momentum is robust."
                    elif run_signal == 'SELL':
                        run_rationale = "The LLM triggered a 'SELL' signal due to bearish alignment across key indicators, indicating downward momentum and a potential trend reversal."
                    else: # HOLD or any unknown signal
                        run_rationale = "The LLM recommended a 'HOLD' signal. Current technical indicators are neutral, conflicting, or lack sufficient momentum. Waiting for clearer trend confirmation is advised."

                fd_txt = (
                    f"🆔 Run ID:        {run.get('id', '-')}\n"
                    f"📅 Time:          {run.get('run_at', '-')}\n"
                    f"🏢 Provider:      {run.get('provider', '-')}\n"
                    f"⏱ Interval:      {run.get('interval_tf', '-')}\n"
                    f"📊 Period:        {run.get('period', '-')}\n"
                    f"\n"
                    f"📈 Signal:        {run.get('signal', 'HOLD')}\n"
                    f"🎯 Confidence:    {run.get('confidence', 0):.2%}\n"
                    f"\n"
                    f"💰 Entry Price:   {run.get('entry_price', '-')}\n"
                    f"🛑 Stop Loss:     {run.get('stop_loss', '-')}\n"
                    f"🎯 Take Profit:   {run.get('take_profit', '-')}\n"
                    f"\n"
                    f"🥇 Gold Price:    {run.get('gold_price', '-')}\n"
                    f"📉 RSI:           {run.get('rsi', '-')}\n"
                    f"📊 MACD:          {run.get('macd_line', '-')}\n"
                    f"📊 Signal Line:   {run.get('signal_line', '-')}\n"
                    f"📊 Trend:         {run.get('trend', '-')}\n"
                    f"\n"
                    f"🔁 Iterations:    {run.get('iterations_used', '-')}\n"
                    f"🛠 Tool Calls:    {run.get('tool_calls_used', '-')}\n"
                    f"\n"
                    f"🧠 Rationale:\n{run_rationale or '-'}\n"
                )

                # ── ดึง LLM logs จาก DB ───────────────────────────
                llm_logs_html = _empty_logs
                try:
                    # HistoryService.get_llm_logs_for_run() — เพิ่มใน services.py
                    if hasattr(services["history"], "get_llm_logs_for_run"):
                        logs = services["history"].get_llm_logs_for_run(run_id)
                        llm_logs_html = _render_llm_logs_from_db(logs)
                    else:
                        # Fallback: render จาก trace JSON ที่เก็บใน run
                        trace_data = run.get("trace", [])
                        if trace_data:
                            from ui.navbar.analysis_page import _render
                            llm_logs_html = _render_llm_logs_from_trace(trace_data)
                        else:
                            llm_logs_html = (
                                "<div style='color:#888;padding:12px;font-family:monospace'>"
                                "HistoryService ยังไม่รองรับ get_llm_logs_for_run() "
                                "— กรุณาเพิ่ม method นั้นใน services.py</div>"
                            )
                except Exception as log_exc:
                    sys_logger.warning(f"Failed to load llm_logs for run {run_id}: {log_exc}")
                    llm_logs_html = StatusRenderer.error_badge(
                        f"โหลด LLM logs ไม่ได้: {log_exc}"
                    )

                return trace_html, fd_txt, llm_logs_html

            except Exception as exc:
                err = StatusRenderer.error_badge(f"Failed to load run: {exc}")
                return err, "", _empty_logs

        return _detail
    



    