"""
ui/navbar/logs_page.py
🪵 Logs — dedicated monitoring page (new in v4)

Layout:
  ┌──────────────────────────────────────────────────────┐
  │  Refresh bar: [↻ Refresh Now]  Auto 15s  Last: HH:MM│
  ├─────────────────────────┬────────────────────────────┤
  │  🧠 LLM Trace           │  📋 System Log             │
  │  Tabs: DB | File        │  newest-first, color-coded │
  │                         │  auto-scroll via JS        │
  │  Structured cards per   │                            │
  │  LLM call:              │                            │
  │  - step / signal badge  │                            │
  │  - token stats          │                            │
  │  - [Prompt ▼]           │                            │
  │  - [Response ▼]         │                            │
  └─────────────────────────┴────────────────────────────┘

Features:
  - gr.Timer(15s) — auto-refresh both panels
  - LLM structured cards from DB (latest run)
  - System log newest-first (no scroll needed)
  - Manual refresh button
  - Bangkok timezone display

Import note for __init__.py:
    from .logs_page import LogsPage   ← add this line
"""

import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

import gradio as gr

from ui.core.renderers import StatusRenderer
from logs.logger_setup import sys_logger

from .base import PageBase, PageComponents, AppContext, navbar_page


# ─────────────────────────────────────────────────────────────────
# Bangkok timezone helper
# ─────────────────────────────────────────────────────────────────

_BKK = timezone(timedelta(hours=7))

def _now_bkk() -> str:
    return datetime.now(_BKK).strftime("%H:%M:%S")

def _now_bkk_full() -> str:
    return datetime.now(_BKK).strftime("%Y-%m-%d %H:%M:%S")


# ─────────────────────────────────────────────────────────────────
# Log file reader  (moved from analysis_page v3)
# ─────────────────────────────────────────────────────────────────

def _read_log_lines(log_filename: str) -> tuple:
    """
    Read log lines from likely locations.
    Returns: (lines: list[str], resolved_path: Path | None, error: str | None)
    """
    candidates = [
        Path("logs") / log_filename,
        Path("logs") / "logs" / log_filename,
        Path("Src") / "logs" / log_filename,
        Path("Src") / "logs" / "logs" / log_filename,
        Path.cwd() / "logs" / log_filename,
        Path.cwd() / "logs" / "logs" / log_filename,
        Path.cwd() / "Src" / "logs" / log_filename,
        Path.cwd() / "Src" / "logs" / "logs" / log_filename,
    ]

    seen = set()
    uniq = []
    for p in candidates:
        key = str(p.resolve()) if p.exists() else str(p)
        if key not in seen:
            seen.add(key)
            uniq.append(p)

    for path in uniq:
        if not path.exists():
            continue
        try:
            return path.read_text(encoding="utf-8", errors="replace").splitlines(), path, None
        except OSError as exc:
            return [], path, f"อ่านไฟล์ไม่ได้: {exc}"

    # rotated log fallback
    rotated: list[Path] = []
    for base in [
        Path("logs"), Path("logs") / "logs",
        Path("Src") / "logs", Path("Src") / "logs" / "logs",
        Path.cwd() / "logs", Path.cwd() / "logs" / "logs",
        Path.cwd() / "Src" / "logs", Path.cwd() / "Src" / "logs" / "logs",
    ]:
        if not base.exists() or not base.is_dir():
            continue
        for p in base.glob(f"{log_filename}*"):
            if p.is_file():
                rotated.append(p)

    if rotated:
        rotated.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        pick = rotated[0]
        try:
            return pick.read_text(encoding="utf-8", errors="replace").splitlines(), pick, None
        except OSError as exc:
            return [], pick, f"อ่านไฟล์ไม่ได้: {exc}"

    checked = "<br>".join(str(p) for p in uniq)
    return [], None, (
        f"ไม่พบไฟล์ log ({log_filename})"
        f"<br><small style='color:#546e7a'>checked:<br>{checked}</small>"
    )


# ─────────────────────────────────────────────────────────────────
# System Log renderer  (newest first — no scroll needed)
# ─────────────────────────────────────────────────────────────────

def _render_system_log(n_lines: int = 300) -> str:
    lines, path, err = _read_log_lines("system.log")
    if err:
        return f"<div style='color:#888;padding:12px;font-size:0.85em'>{err}</div>"
    if not lines:
        return "<div style='color:#888;padding:12px;font-size:0.85em'>system.log ว่างเปล่า</div>"

    # newest first
    lines = lines[-n_lines:][::-1]

    LEVEL_COLOR = {
        "ERROR":    "#f44336",
        "CRITICAL": "#e91e63",
        "WARNING":  "#ff9800",
        "WARN":     "#ff9800",
        "INFO":     "#4caf50",
        "DEBUG":    "#546e7a",
    }

    rows = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        level = next((k for k in LEVEL_COLOR if k in raw.upper()), "DEBUG")
        color = LEVEL_COLOR[level]
        safe  = raw.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        rows.append(
            f'<div style="padding:3px 8px;border-bottom:1px solid #21262d;'
            f'font-family:monospace;font-size:0.78em;color:{color}">{safe}</div>'
        )

    source_html = (
        f'<div style="font-size:0.72em;color:#546e7a;padding:6px 8px;'
        f'border-bottom:2px solid #30363d;background:#161b22;">'
        f'📄 {path} · newest first</div>'
    ) if path else ""

    return (
        f'<div style="background:#0d1117;border-radius:10px;'
        f'max-height:520px;overflow-y:auto;'
        f'border:1px solid #30363d;">'
        f'{source_html}{"".join(rows)}</div>'
    )


# ─────────────────────────────────────────────────────────────────
# LLM Trace File renderer  (newest first)
# ─────────────────────────────────────────────────────────────────

def _render_llm_trace_file(n_lines: int = 200) -> str:
    lines, path, err = _read_log_lines("llm_trace.log")
    if err:
        return f"<div style='color:#888;padding:12px;font-size:0.85em'>{err}</div>"
    if not lines:
        return "<div style='color:#888;padding:12px;font-size:0.85em'>llm_trace.log ว่างเปล่า</div>"

    lines = lines[-n_lines:][::-1]  # newest first

    SIG_COLOR = {"BUY": "#1D9E75", "SELL": "#D85A30", "HOLD": "#BA7517"}
    rows = []

    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj     = json.loads(raw)
            ts      = obj.get("time") or obj.get("timestamp") or obj.get("ts") or ""
            step    = obj.get("step") or obj.get("label") or "—"
            signal  = obj.get("signal") or ""
            tok_tot = obj.get("token_total") or obj.get("tokens") or ""
            model   = obj.get("model") or ""
            note    = obj.get("note") or ""
            display = f"{ts[:19] if ts else ''}  {step}"
            extra = "  ".join(filter(None, [
                f'<span style="color:{SIG_COLOR.get(signal,"#888")};font-weight:600">{signal}</span>' if signal else "",
                f'<span style="color:#78909c">{tok_tot:,} tok</span>' if isinstance(tok_tot, int) and tok_tot else "",
                f'<span style="color:#78909c">{model}</span>' if model else "",
                f'<span style="color:#ffd54f">⚠ {note}</span>' if note else "",
            ]))
            rows.append(
                f'<div style="padding:4px 8px;border-bottom:1px solid #21262d;'
                f'font-family:monospace;font-size:0.78em;color:#c9d1d9">'
                f'{display}{"  " + extra if extra else ""}</div>'
            )
        except (json.JSONDecodeError, AttributeError):
            safe = raw.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
            rows.append(
                f'<div style="padding:3px 8px;border-bottom:1px solid #21262d;'
                f'font-family:monospace;font-size:0.78em;color:#8b949e">{safe}</div>'
            )

    source_html = (
        f'<div style="font-size:0.72em;color:#546e7a;padding:6px 8px;'
        f'border-bottom:2px solid #30363d;background:#161b22;">'
        f'📄 {path} · newest first</div>'
    ) if path else ""

    return (
        f'<div style="background:#0d1117;border-radius:10px;'
        f'max-height:520px;overflow-y:auto;border:1px solid #30363d;">'
        f'{source_html}{"".join(rows)}</div>'
    )


# ─────────────────────────────────────────────────────────────────
# Refresh status bar
# ─────────────────────────────────────────────────────────────────

def _render_refresh_status(last_time: str = "") -> str:
    t = last_time or _now_bkk()
    return f"""
    <div style="background:linear-gradient(135deg,#faf5ff,#fffbeb);
                border:1px solid #e9d5ff;border-radius:10px;
                padding:8px 16px;
                font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
                display:flex;align-items:center;gap:12px;font-size:12px;">
        <span style="display:inline-flex;align-items:center;gap:5px;color:#7c3aed;font-weight:600;">
            <span style="width:7px;height:7px;border-radius:50%;
                         background:linear-gradient(135deg,#6D28D9,#D97706);
                         display:inline-block;
                         animation:pg-pulse 2s ease-in-out infinite;"></span>
            Live Monitor
        </span>
        <span style="color:#9ca3af;">Auto-refresh: <strong style="color:#6D28D9;">15s</strong></span>
        <span style="color:#9ca3af;">Last update: <strong>{t}</strong> (BKK)</span>
    </div>
    <style>
    @keyframes pg-pulse {{
        0%,100% {{ opacity:1; transform:scale(1); }}
        50%      {{ opacity:.4; transform:scale(.85); }}
    }}
    </style>"""


# ─────────────────────────────────────────────────────────────────
# Page
# ─────────────────────────────────────────────────────────────────

@navbar_page("🪵 Logs")
class LogsPage(PageBase):
    """
    Dedicated log monitoring page.
    - Left: LLM Trace (DB structured | File raw) with tabs
    - Right: System Log (file, newest first, color-coded)
    - Auto-refreshes every 15 seconds
    """

    # ── Build ──────────────────────────────────────────────────────

    def build(self, ctx: AppContext) -> PageComponents:
        pc = PageComponents()

        # ── Refresh control bar ────────────────────────────────────
        with gr.Row():
            with gr.Column(scale=4):
                pc.register("refresh_status", gr.HTML(
                    value=_render_refresh_status(),
                    elem_id="logs-status-bar",
                ))
            with gr.Column(scale=0, min_width=130):
                pc.register("manual_refresh_btn", gr.Button(
                    "↻ Refresh Now",
                    variant="secondary",
                    size="sm",
                ))

        # ── 2-column log panels ────────────────────────────────────
        with gr.Row(equal_height=True):

            # ── LEFT: LLM Trace (tabs: DB structured | File raw) ──
            with gr.Column(scale=3):
                gr.Markdown("### 🧠 LLM Trace")

                with gr.Tabs():
                    with gr.Tab("DB — Structured (latest run)"):
                        pc.register("llm_db_html", gr.HTML(
                            value=self._empty_db_panel(),
                        ))

                    with gr.Tab("File — Raw log"):
                        pc.register("llm_file_html", gr.HTML(
                            value=_render_llm_trace_file(),
                        ))

            # ── RIGHT: System Log ──────────────────────────────────
            with gr.Column(scale=2):
                gr.Markdown("### 📋 System Log")
                pc.register("system_log_html", gr.HTML(
                    value=_render_system_log(),
                ))

        return pc

    # ── Wire ───────────────────────────────────────────────────────

    def wire(self, demo: gr.Blocks, ctx: AppContext, pc: PageComponents) -> None:
        _outputs = [
            pc.llm_db_html,
            pc.llm_file_html,
            pc.system_log_html,
            pc.refresh_status,
        ]

        pc.manual_refresh_btn.click(
            fn=self._handle_refresh(ctx),
            inputs=[],
            outputs=_outputs,
        )

        # Auto-refresh timer (15s)
        log_timer = gr.Timer(value=15, active=True)
        log_timer.tick(
            fn=self._handle_refresh(ctx),
            inputs=[],
            outputs=_outputs,
        )

        # Initial load
        demo.load(
            fn=self._handle_refresh(ctx),
            inputs=[],
            outputs=_outputs,
        )

    # ── Handlers ───────────────────────────────────────────────────

    def _handle_refresh(self, ctx: AppContext):
        services = ctx.services

        def _refresh():
            now = _now_bkk()

            # 1. LLM DB logs — latest run
            llm_db_html = self._empty_db_panel()
            try:
                from ui.navbar.analysis_page import _render_llm_logs_from_db

                runs = services["history"].get_recent_runs(limit=1)
                if runs:
                    run_id = runs[0].get("id")
                    if run_id and hasattr(services["history"], "get_llm_logs_for_run"):
                        logs = services["history"].get_llm_logs_for_run(run_id)
                        if logs:
                            sig   = runs[0].get("signal", "—")
                            conf  = runs[0].get("confidence", 0)
                            ts    = runs[0].get("run_at", "")
                            llm_db_html = (
                                _render_run_header(run_id, sig, conf, ts)
                                + _render_llm_logs_from_db(logs)
                            )
                        else:
                            llm_db_html = self._empty_db_panel(
                                "ไม่พบ LLM logs ใน DB — อาจเป็น run เก่าก่อน v2"
                            )
                    else:
                        llm_db_html = self._empty_db_panel(
                            "HistoryService ยังไม่รองรับ get_llm_logs_for_run()"
                        )
                else:
                    llm_db_html = self._empty_db_panel("ยังไม่มี run ในฐานข้อมูล")

            except Exception as exc:
                sys_logger.warning(f"LogsPage DB refresh error: {exc}")
                llm_db_html = self._empty_db_panel(f"Error: {exc}")

            # 2. LLM file log
            llm_file_html = _render_llm_trace_file()

            # 3. System log
            system_log_html = _render_system_log()

            # 4. Status
            refresh_status = _render_refresh_status(now)

            return llm_db_html, llm_file_html, system_log_html, refresh_status

        return _refresh

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _empty_db_panel(msg: str = "กด ↻ Refresh หรือรอ auto-refresh") -> str:
        return (
            f"<div style='background:#0d1117;border-radius:10px;"
            f"padding:32px;text-align:center;"
            f"border:1px solid #30363d;"
            f"font-family:monospace;font-size:0.85em;color:#546e7a'>"
            f"🧠 {msg}</div>"
        )


# ─────────────────────────────────────────────────────────────────
# Run header  (shown above LLM cards in DB view)
# ─────────────────────────────────────────────────────────────────

def _render_run_header(run_id: int, signal: str, confidence: float, ts: str) -> str:
    SIG_COLOR = {"BUY": "#1D9E75", "SELL": "#D85A30", "HOLD": "#BA7517"}
    SIG_ICON  = {"BUY": "🟢",      "SELL": "🔴",      "HOLD": "🟡"}
    color     = SIG_COLOR.get(signal, "#888")
    icon      = SIG_ICON.get(signal, "⚪")

    # Convert ts to BKK
    ts_display = ts
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        ts_display = dt.astimezone(_BKK).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass

    return f"""
    <div style="background:linear-gradient(135deg,#1c2128,#161b22);
                border:1px solid #30363d;border-radius:10px;
                padding:12px 16px;margin-bottom:10px;
                display:flex;align-items:center;gap:16px;flex-wrap:wrap;
                font-family:monospace;">

        <!-- Purple-gold badge -->
        <span style="background:linear-gradient(135deg,#6D28D9,#D97706);
                     padding:3px 10px;border-radius:20px;
                     font-size:10px;color:#fff;font-weight:800;letter-spacing:.1em;">
            RUN #{run_id}
        </span>

        <!-- Signal -->
        <span style="font-size:15px;font-weight:800;color:{color};">
            {icon} {signal}
        </span>
        <span style="color:#546e7a;font-size:12px;">{confidence:.0%}</span>

        <!-- Divider -->
        <span style="width:1px;height:16px;background:#30363d;display:inline-block;"></span>

        <span style="color:#546e7a;font-size:12px;">{ts_display}</span>
    </div>"""
