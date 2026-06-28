# monitoring/pipeline_monitor.py
#
# Pipeline Feature Monitor — ติดตามความถูกต้องของแต่ละ layer ใน signal pipeline
#
# Pipeline layers:
#   L1  build_candles()         → M10 OHLCV DataFrame
#   L2  compute_features()      → FeaturesRow (30+ ML features)
#   L3  run_inference()         → ranker_score + SHAP
#   L4  evaluate_signal_gate()  → BUY / SELL / HOLD decision
#
# Terminal: Rich panel แสดง pass/fail + key metrics ทุก bar
# DB: upsert ลง Supabase table "v3_data_pipeline" (conflict on bar_time)
#
# Supabase table DDL (run once):
# ─────────────────────────────────────────────────────────────────────────────
# CREATE TABLE v3_data_pipeline (
#   id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
#   bar_time         text NOT NULL UNIQUE,
#   run_at           timestamptz DEFAULT now(),
#   session          text,
#   pipeline_status  text,         -- "ok" | "error" | "partial"
#   total_ms         int,
#
#   l1_status        text,         -- "ok" | "error"
#   l1_ms            int,
#   l1_bars          int,
#   l1_hsh_ask       numeric,
#   l1_hsh_bid       numeric,
#   l1_xau_close     numeric,
#   l1_usd_close     numeric,
#   l1_error         text,
#
#   l2_status        text,
#   l2_ms            int,
#   l2_atr_48        numeric,
#   l2_rsi_14        numeric,
#   l2_rsi_6         numeric,
#   l2_bb_pos        numeric,
#   l2_srvr          numeric,
#   l2_regime        int,
#   l2_spread_norm   numeric,
#   l2_features      jsonb,
#   l2_error         text,
#
#   l3_status        text,
#   l3_ms            int,
#   l3_score         numeric,
#   l3_model         text,
#   l3_top_shap_feat text,
#   l3_top_shap_val  numeric,
#   l3_error         text,
#
#   l4_status        text,
#   l4_ms            int,
#   l4_state_before  text,
#   l4_signal_type   text,
#   l4_passed        boolean,
#   l4_reject_reason text,
#   l4_gates         jsonb,
#   l4_error         text
# );
# ─────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("system")

PIPELINE_TABLE = "v3_data_pipeline"

# ─────────────────────────────────────────────────────────────────────────────
# Layer snapshot containers
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class L1Snapshot:
    status: str = "pending"
    ms: int = 0
    bars: int = 0
    hsh_ask: float = 0.0
    hsh_bid: float = 0.0
    xau_close: float = 0.0
    usd_close: float = 0.0
    error: str | None = None


@dataclass
class L2Snapshot:
    status: str = "pending"
    ms: int = 0
    atr_48: float = 0.0
    rsi_14: float = 0.0
    rsi_6: float = 0.0
    bb_pos: float = 0.0
    srvr: float = 0.0
    regime: int = 0
    spread_norm: float = 0.0
    features: dict = field(default_factory=dict)
    error: str | None = None


@dataclass
class L3Snapshot:
    status: str = "pending"
    ms: int = 0
    score: float = 0.0
    model: str = ""
    top_shap_feat: str = ""
    top_shap_val: float = 0.0
    error: str | None = None


@dataclass
class L4Snapshot:
    status: str = "pending"
    ms: int = 0
    state_before: str = ""
    signal_type: str = ""
    passed: bool = False
    reject_reason: str | None = None
    gates: dict = field(default_factory=dict)
    error: str | None = None


@dataclass
class PipelineRun:
    bar_time: str = ""
    session: str = ""
    pipeline_status: str = "pending"
    total_ms: int = 0
    l1: L1Snapshot = field(default_factory=L1Snapshot)
    l2: L2Snapshot = field(default_factory=L2Snapshot)
    l3: L3Snapshot = field(default_factory=L3Snapshot)
    l4: L4Snapshot = field(default_factory=L4Snapshot)
    _start_ts: float = field(default_factory=time.monotonic, repr=False)

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self._start_ts) * 1000)


# ─────────────────────────────────────────────────────────────────────────────
# Public API — called from orchestrator
# ─────────────────────────────────────────────────────────────────────────────

def new_run() -> PipelineRun:
    return PipelineRun(_start_ts=time.monotonic())


def record_l1(run: PipelineRun, candles_df: Any, ms: int) -> None:
    """Layer 1: Candle builder result."""
    try:
        last = candles_df.iloc[-1]
        run.l1 = L1Snapshot(
            status="ok",
            ms=ms,
            bars=len(candles_df),
            hsh_ask=float(last["hsh_close_ask"]),
            hsh_bid=float(last["hsh_close_bid"]),
            xau_close=float(last["xau_close"]),
            usd_close=float(last["usd_close"]),
        )
    except Exception as e:
        run.l1 = L1Snapshot(status="error", ms=ms, error=str(e))


def record_l1_error(run: PipelineRun, ms: int, error: str) -> None:
    run.l1 = L1Snapshot(status="error", ms=ms, error=error)


def record_l2(run: PipelineRun, features_row: dict, ms: int) -> None:
    """Layer 2: Feature engine result."""
    try:
        safe_features = {
            k: float(v) if isinstance(v, (int, float)) else v
            for k, v in features_row.items()
            if k not in ("bar_time", "session")
        }
        run.bar_time = features_row.get("bar_time", "")
        run.session = features_row.get("session", "")
        run.l2 = L2Snapshot(
            status="ok",
            ms=ms,
            atr_48=float(features_row.get("F_ATR_48", 0.0)),
            rsi_14=float(features_row.get("F_RSI_14", 0.0)),
            rsi_6=float(features_row.get("F_RSI_6", 0.0)),
            bb_pos=float(features_row.get("F_BB_Pos", 0.0)),
            srvr=float(features_row.get("F_SRVR", 0.0)),
            regime=int(features_row.get("F_Regime", 0)),
            spread_norm=float(features_row.get("F_XAU_Spread_Norm", 0.0)),
            features=safe_features,
        )
    except Exception as e:
        run.l2 = L2Snapshot(status="error", ms=ms, error=str(e))


def record_l2_error(run: PipelineRun, ms: int, error: str) -> None:
    run.l2 = L2Snapshot(status="error", ms=ms, error=error)


def record_l3(run: PipelineRun, inference_result: dict, ms: int) -> None:
    """Layer 3: Model inference result."""
    try:
        shap_vals = inference_result.get("shap_values", [])
        feat_names = inference_result.get("feature_names", [])
        top_feat, top_val = "", 0.0
        if shap_vals and feat_names and len(shap_vals) == len(feat_names):
            best_idx = max(range(len(shap_vals)), key=lambda i: abs(shap_vals[i]))
            top_feat = feat_names[best_idx]
            top_val = float(shap_vals[best_idx])

        run.l3 = L3Snapshot(
            status="ok",
            ms=ms,
            score=float(inference_result.get("ranker_score", 0.0)),
            model=str(inference_result.get("model_version", "")),
            top_shap_feat=top_feat,
            top_shap_val=top_val,
        )
    except Exception as e:
        run.l3 = L3Snapshot(status="error", ms=ms, error=str(e))


def record_l3_error(run: PipelineRun, ms: int, error: str) -> None:
    run.l3 = L3Snapshot(status="error", ms=ms, error=error)


def record_l4(run: PipelineRun, gate_result: dict, ms: int) -> None:
    """Layer 4: Signal gate result."""
    try:
        gates = gate_result.get("gates_detail", {})
        safe_gates = {k: bool(v) if isinstance(v, bool) else v for k, v in gates.items()}
        run.l4 = L4Snapshot(
            status="ok",
            ms=ms,
            state_before=str(gate_result.get("state_before", "")),
            signal_type=str(gate_result.get("signal_type", "")),
            passed=bool(gate_result.get("passed", False)),
            reject_reason=gate_result.get("reject_reason"),
            gates=safe_gates,
        )
    except Exception as e:
        run.l4 = L4Snapshot(status="error", ms=ms, error=str(e))


def record_l4_error(run: PipelineRun, ms: int, error: str) -> None:
    run.l4 = L4Snapshot(status="error", ms=ms, error=error)


def finalize(run: PipelineRun) -> None:
    """ปิด run — คำนวณ total_ms + pipeline_status."""
    run.total_ms = run.elapsed_ms()
    statuses = [run.l1.status, run.l2.status, run.l3.status, run.l4.status]
    if all(s == "ok" for s in statuses):
        run.pipeline_status = "ok"
    elif all(s == "error" for s in statuses):
        run.pipeline_status = "error"
    else:
        run.pipeline_status = "partial"


# ─────────────────────────────────────────────────────────────────────────────
# Terminal display (Rich)
# ─────────────────────────────────────────────────────────────────────────────

def print_terminal(run: PipelineRun) -> None:
    try:
        from rich.console import Console
        from rich.table import Table
        from rich.panel import Panel
        from rich.text import Text
        from rich import box

        console = Console()

        def _status_icon(status: str) -> str:
            return "[green]✅[/green]" if status == "ok" else "[red]❌[/red]"

        def _gate_icon(v: Any) -> str:
            if isinstance(v, bool):
                return "[green]✅[/green]" if v else "[red]❌[/red]"
            return str(v)

        # ── Header ────────────────────────────────────────────────────────────
        status_color = {"ok": "green", "error": "red", "partial": "yellow"}.get(
            run.pipeline_status, "white"
        )
        header = Text()
        header.append("PIPELINE MONITOR  ", style="bold white")
        header.append(run.bar_time[:19] if run.bar_time else "N/A", style="cyan")
        header.append(f"  {run.session}", style="yellow")
        header.append(
            f"  [{run.pipeline_status.upper()}]",
            style=f"bold {status_color}",
        )
        header.append(f"  {run.total_ms}ms", style="dim")

        # ── Layer table ───────────────────────────────────────────────────────
        tbl = Table(box=box.SIMPLE_HEAD, show_header=True, header_style="bold magenta")
        tbl.add_column("Layer", style="bold", width=14)
        tbl.add_column("St", width=3)
        tbl.add_column("ms", width=5)
        tbl.add_column("Key Metrics", min_width=55)

        # L1
        l1 = run.l1
        l1_metrics = (
            f"bars={l1.bars}  HSH ask={l1.hsh_ask:,.0f}  bid={l1.hsh_bid:,.0f}  "
            f"XAU={l1.xau_close:.1f}  USD={l1.usd_close:.3f}"
            if l1.status == "ok"
            else f"[red]{l1.error}[/red]"
        )
        tbl.add_row("L1 Candles", _status_icon(l1.status), str(l1.ms), l1_metrics)

        # L2
        l2 = run.l2
        l2_metrics = (
            f"ATR={l2.atr_48:.2f}  RSI14={l2.rsi_14:.1f}  RSI6={l2.rsi_6:.1f}  "
            f"BB={l2.bb_pos:+.3f}  SRVR={l2.srvr:.2f}  Regime={l2.regime:+d}  "
            f"SpreadNorm={l2.spread_norm:.2f}"
            if l2.status == "ok"
            else f"[red]{l2.error}[/red]"
        )
        tbl.add_row("L2 Features", _status_icon(l2.status), str(l2.ms), l2_metrics)

        # L3
        l3 = run.l3
        from config.settings import SIGNAL_THRESHOLD
        score_color = "green" if l3.score >= SIGNAL_THRESHOLD else "yellow"
        l3_metrics = (
            f"score=[{score_color}]{l3.score:.4f}[/{score_color}]"
            f" (thr={SIGNAL_THRESHOLD})  "
            f"model={l3.model}  "
            f"top_shap=[cyan]{l3.top_shap_feat}[/cyan] {l3.top_shap_val:+.4f}"
            if l3.status == "ok"
            else f"[red]{l3.error}[/red]"
        )
        tbl.add_row("L3 Inference", _status_icon(l3.status), str(l3.ms), l3_metrics)

        # L4
        l4 = run.l4
        signal_color = {"BUY": "green", "SELL": "red", "HOLD": "yellow"}.get(
            l4.signal_type, "white"
        )
        if l4.status == "ok":
            gate_strs = []
            for k, v in l4.gates.items():
                if isinstance(v, bool):
                    gate_strs.append(f"{_gate_icon(v)} {k}")
            gates_line = "  ".join(gate_strs) if gate_strs else "(no gates)"
            reject_part = f"  reject=[red]{l4.reject_reason}[/red]" if l4.reject_reason else ""
            l4_metrics = (
                f"state={l4.state_before}  "
                f"signal=[{signal_color}]{l4.signal_type}[/{signal_color}]  "
                f"passed={'✅' if l4.passed else '❌'}"
                f"{reject_part}\n  {gates_line}"
            )
        else:
            l4_metrics = f"[red]{l4.error}[/red]"
        tbl.add_row("L4 Gate", _status_icon(l4.status), str(l4.ms), l4_metrics)

        panel = Panel(tbl, title=header, border_style=status_color, padding=(0, 1))
        console.print(panel)

    except Exception as e:
        logger.warning(f"[Monitor] terminal print failed: {e}")
        _fallback_print(run)


def _fallback_print(run: PipelineRun) -> None:
    """ANSI fallback เมื่อ Rich ใช้ไม่ได้"""
    lines = [
        f"\n{'='*70}",
        f"  PIPELINE MONITOR | {run.bar_time} | {run.session} | {run.pipeline_status.upper()} | {run.total_ms}ms",
        f"  L1 Candles  [{run.l1.status}] {run.l1.ms}ms  bars={run.l1.bars}  ask={run.l1.hsh_ask:.0f}",
        f"  L2 Features [{run.l2.status}] {run.l2.ms}ms  ATR={run.l2.atr_48:.2f}  RSI14={run.l2.rsi_14:.1f}  score(L3)={run.l3.score:.4f}",
        f"  L3 Inference[{run.l3.status}] {run.l3.ms}ms  score={run.l3.score:.4f}",
        f"  L4 Gate     [{run.l4.status}] {run.l4.ms}ms  signal={run.l4.signal_type}  passed={run.l4.passed}",
        f"{'='*70}\n",
    ]
    print("\n".join(lines))


# ─────────────────────────────────────────────────────────────────────────────
# Supabase persistence
# ─────────────────────────────────────────────────────────────────────────────

def save_to_db(run: PipelineRun) -> bool:
    """Upsert pipeline run snapshot ลง v3_data_pipeline (conflict on bar_time)."""
    if not run.bar_time:
        logger.warning("[Monitor] bar_time missing — skip DB save")
        return False

    try:
        from db.supabase_writer import get_supabase_client
        import json

        l2_features_safe: dict | None = None
        if run.l2.features:
            try:
                l2_features_safe = json.loads(
                    json.dumps(run.l2.features, default=lambda o: float(o))
                )
            except Exception:
                l2_features_safe = None

        l4_gates_safe: dict | None = None
        if run.l4.gates:
            try:
                l4_gates_safe = json.loads(
                    json.dumps(run.l4.gates, default=lambda o: str(o))
                )
            except Exception:
                l4_gates_safe = None

        row = {
            "bar_time":        run.bar_time,
            "run_at":          datetime.now(timezone.utc).isoformat(),
            "session":         run.session or None,
            "pipeline_status": run.pipeline_status,
            "total_ms":        run.total_ms,
            # L1
            "l1_status":  run.l1.status,
            "l1_ms":      run.l1.ms,
            "l1_bars":    run.l1.bars or None,
            "l1_hsh_ask": run.l1.hsh_ask or None,
            "l1_hsh_bid": run.l1.hsh_bid or None,
            "l1_xau_close": run.l1.xau_close or None,
            "l1_usd_close": run.l1.usd_close or None,
            "l1_error":   run.l1.error,
            # L2
            "l2_status":     run.l2.status,
            "l2_ms":         run.l2.ms,
            "l2_atr_48":     run.l2.atr_48 or None,
            "l2_rsi_14":     run.l2.rsi_14 or None,
            "l2_rsi_6":      run.l2.rsi_6 or None,
            "l2_bb_pos":     run.l2.bb_pos if run.l2.status == "ok" else None,
            "l2_srvr":       run.l2.srvr or None,
            "l2_regime":     run.l2.regime if run.l2.status == "ok" else None,
            "l2_spread_norm": run.l2.spread_norm or None,
            "l2_features":   l2_features_safe,
            "l2_error":      run.l2.error,
            # L3
            "l3_status":        run.l3.status,
            "l3_ms":            run.l3.ms,
            "l3_score":         run.l3.score if run.l3.status == "ok" else None,
            "l3_model":         run.l3.model or None,
            "l3_top_shap_feat": run.l3.top_shap_feat or None,
            "l3_top_shap_val":  run.l3.top_shap_val if run.l3.status == "ok" else None,
            "l3_error":         run.l3.error,
            # L4
            "l4_status":       run.l4.status,
            "l4_ms":           run.l4.ms,
            "l4_state_before": run.l4.state_before or None,
            "l4_signal_type":  run.l4.signal_type or None,
            "l4_passed":       run.l4.passed if run.l4.status == "ok" else None,
            "l4_reject_reason": run.l4.reject_reason,
            "l4_gates":        l4_gates_safe,
            "l4_error":        run.l4.error,
        }

        client = get_supabase_client()
        client.table(PIPELINE_TABLE).upsert(row, on_conflict="bar_time").execute()
        logger.info(f"[Monitor] ✅ DB saved → {PIPELINE_TABLE} | {run.bar_time}")
        return True

    except Exception as e:
        logger.warning(f"[Monitor] DB save failed: {e}")
        return False
