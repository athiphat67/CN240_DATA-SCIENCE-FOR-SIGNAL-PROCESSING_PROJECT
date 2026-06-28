"""
backtest/metrics/deploy_gate.py
══════════════════════════════════════════════════════════════════════
Deploy Gate — รับ metrics dict ทั้งหมด → คืน PASS / FAIL พร้อม reason

เรียกหลัง calculate_metrics() เสร็จ ใน run_main_backtest.py

Thresholds (จาก GOLDTRADER_BACKTEST_CONTEXT.md section 7):
  sharpe_ratio        > 1.0
  win_rate            > 50%
  max_drawdown        < 20%   (absolute)
  profit_factor       > 1.2
  session_compliance  > 80%
  portfolio_not_bust  = True
  calmar_ratio        > 1.0

Usage:
  from backtest.metrics.deploy_gate import deploy_gate, print_gate_report

  gate = deploy_gate(metrics)
  print_gate_report(gate)
  # gate["verdict"] == "✅ DEPLOY" หรือ "❌ NOT READY"
══════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ── Thresholds ────────────────────────────────────────────────────────
_THRESHOLDS = {
    "sharpe_ratio":       (">",  1.0),
    "win_rate_pct":       (">",  50.0),
    "mdd_pct_abs":        ("<",  20.0),   # abs(mdd_pct)
    "profit_factor":      (">",  1.2),
    "session_compliance": (">",  80.0),   # compliance_pct
    "portfolio_not_bust": ("==", True),
    "calmar_ratio":       (">",  1.0),
}


def deploy_gate(metrics: dict) -> dict:
    """
    ตรวจสอบ metrics ทั้งหมดว่า pass threshold หรือไม่

    Parameters
    ----------
    metrics : dict ที่ได้จาก MainPipelineBacktest.calculate_metrics()
              ต้องมี sub-keys: "risk", "trade", "session_compliance"

    Returns
    -------
    {
        "verdict":       "✅ DEPLOY" | "❌ NOT READY",
        "checks":        {check_name: True/False},
        "values":        {check_name: actual_value},
        "thresholds":    {check_name: threshold_str},
        "passed_count":  int,
        "total_count":   int,
        "fail_reasons":  [str],
        "bust_flag":     bool,
    }
    """
    risk    = metrics.get("risk",    {})
    trade   = metrics.get("trade",   {})
    session = metrics.get("session_compliance", {})

    # ── ดึงค่า actual ────────────────────────────────────────────────
    sharpe    = _safe(risk,    "sharpe_ratio",       default=0.0)
    win_rate  = _safe(trade,   "win_rate_pct",        default=0.0)
    mdd_abs   = abs(_safe(risk, "mdd_pct",            default=-100.0))
    pf        = _safe(trade,   "profit_factor",       default=0.0)
    compliance= _safe(session, "compliance_pct",      default=0.0)
    bust_flag = _safe(metrics, "bust_flag",           default=False)
    calmar    = _safe(trade,   "calmar_ratio",        default=0.0)

    # bust_flag อาจอยู่ใน risk dict ด้วย (backtest บาง path เก็บไว้ที่นั่น)
    if not isinstance(bust_flag, bool):
        bust_flag = bool(bust_flag)

    # ── ตรวจสอบแต่ละ check ───────────────────────────────────────────
    checks   = {}
    values   = {}
    threshold_strs = {}

    checks["sharpe_ratio"]       = sharpe    > 1.0
    checks["win_rate_pct"]       = win_rate  > 50.0
    checks["mdd_pct_abs"]        = mdd_abs   < 20.0
    checks["profit_factor"]      = pf        > 1.2
    checks["session_compliance"] = compliance > 80.0
    checks["portfolio_not_bust"] = not bust_flag
    checks["calmar_ratio"]       = calmar    > 1.0

    values["sharpe_ratio"]       = round(sharpe, 3)
    values["win_rate_pct"]       = round(win_rate, 2)
    values["mdd_pct_abs"]        = round(mdd_abs, 2)
    values["profit_factor"]      = round(pf, 3)
    values["session_compliance"] = round(compliance, 2)
    values["portfolio_not_bust"] = not bust_flag
    values["calmar_ratio"]       = round(calmar, 3)

    threshold_strs["sharpe_ratio"]       = "> 1.0"
    threshold_strs["win_rate_pct"]       = "> 50%"
    threshold_strs["mdd_pct_abs"]        = "< 20%"
    threshold_strs["profit_factor"]      = "> 1.2"
    threshold_strs["session_compliance"] = "> 80%"
    threshold_strs["portfolio_not_bust"] = "= True (no bust)"
    threshold_strs["calmar_ratio"]       = "> 1.0"

    # ── Verdict ───────────────────────────────────────────────────────
    passed_count = sum(1 for v in checks.values() if v)
    total_count  = len(checks)
    passed_all   = passed_count == total_count

    fail_reasons = [
        f"{name}: {values[name]} (need {threshold_strs[name]})"
        for name, ok in checks.items()
        if not ok
    ]

    verdict = "✅ DEPLOY" if passed_all else "❌ NOT READY"

    result = {
        "verdict":      verdict,
        "checks":       checks,
        "values":       values,
        "thresholds":   threshold_strs,
        "passed_count": passed_count,
        "total_count":  total_count,
        "fail_reasons": fail_reasons,
        "bust_flag":    bust_flag,
    }

    logger.info(f"Deploy Gate: {verdict} ({passed_count}/{total_count} checks passed)")
    if fail_reasons:
        for r in fail_reasons:
            logger.warning(f"  ✗ {r}")

    return result


def print_gate_report(gate: dict, prefix: str = "") -> None:
    """
    พิมพ์ gate report แบบ readable
    """
    p = prefix
    verdict      = gate["verdict"]
    passed       = gate["passed_count"]
    total        = gate["total_count"]
    checks       = gate["checks"]
    values       = gate["values"]
    thresholds   = gate["thresholds"]
    fail_reasons = gate["fail_reasons"]

    sep = "=" * 60
    print(f"\n{p}{sep}")
    print(f"{p}  DEPLOY GATE — {verdict}  ({passed}/{total} checks)")
    print(f"{p}{sep}")

    for name, ok in checks.items():
        icon = "✅" if ok else "❌"
        val  = values.get(name, "?")
        thr  = thresholds.get(name, "")
        print(f"{p}  {icon}  {name:<28} {str(val):<12}  (need {thr})")

    if fail_reasons:
        print(f"{p}\n  ── Fail reasons ──")
        for r in fail_reasons:
            print(f"{p}  • {r}")

    print(f"{p}{sep}\n")


# ── Helper ───────────────────────────────────────────────────────────

def _safe(d: dict, key: str, default: Any = 0.0) -> Any:
    """dict.get ที่ return default ถ้าค่าเป็น None ด้วย"""
    v = d.get(key, default)
    return default if v is None else v


# ── Self-test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Test 1: PASS scenario
    metrics_pass = {
        "risk": {
            "sharpe_ratio":          1.35,
            "mdd_pct":               -14.2,
            "annualized_return_pct": 22.5,
        },
        "trade": {
            "win_rate_pct":     54.0,
            "profit_factor":    1.45,
            "calmar_ratio":     1.58,
        },
        "session_compliance": {
            "compliance_pct": 87.5,
        },
        "bust_flag": False,
    }
    g1 = deploy_gate(metrics_pass)
    print_gate_report(g1)
    assert g1["verdict"] == "✅ DEPLOY", f"Expected DEPLOY, got {g1['verdict']}"

    # Test 2: FAIL scenario
    metrics_fail = {
        "risk": {
            "sharpe_ratio":          0.72,
            "mdd_pct":               -25.8,
            "annualized_return_pct": -5.0,
        },
        "trade": {
            "win_rate_pct":     44.0,
            "profit_factor":    0.88,
            "calmar_ratio":     -0.2,
        },
        "session_compliance": {
            "compliance_pct": 60.0,
        },
        "bust_flag": True,
    }
    g2 = deploy_gate(metrics_fail)
    print_gate_report(g2)
    assert g2["verdict"] == "❌ NOT READY"
    assert g2["passed_count"] == 0

    print("DONE ✓")