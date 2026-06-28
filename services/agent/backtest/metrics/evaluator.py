import pandas as pd
import logging
from typing import Dict

# 🚨 อย่าลืม import สองตัวนี้มาจาก calculator ของเดิมที่คุณมี
from metrics.calculator import calculate_trade_metrics, add_calmar 

logger = logging.getLogger(__name__)

class BacktestEvaluator:
    def __init__(self, timeframe: str, days: int, portfolio, session_manager):
        self.timeframe = timeframe
        self.days = days
        self.portfolio = portfolio
        self.session_manager = session_manager
        self._PERIODS_PER_YEAR = { "1m": 362_880, "5m": 72_576, "15m": 24_192, "30m": 12_096, "1h": 6_048, "4h": 1_512, "1d": 252 }

    def _get_current_price(self, df: pd.DataFrame) -> float:
        for col in ("close_thai", "price", "close"):
            if col in df.columns and len(df[col].dropna()) > 0:
                try:
                    return float(df[col].dropna().iloc[-1])
                except Exception:
                    continue
        return 0.0

    def _get_eval_timestamp(self, df: pd.DataFrame):
        if "timestamp" not in df.columns or len(df["timestamp"].dropna()) == 0:
            return None
        try:
            return pd.to_datetime(df["timestamp"].dropna().iloc[-1])
        except Exception:
            return None

    def _compute_open_trade_metrics(self, df: pd.DataFrame) -> Dict[str, float]:
        if not self.portfolio:
            return {
                "unrealized_pnl_thb": 0.0,
                "open_capital_per_year_thb": 0.0,
            }

        current_price = self._get_current_price(df)
        unrealized = 0.0
        if current_price > 0:
            try:
                unrealized = float(self.portfolio.unrealized_pnl(current_price))
            except Exception as exc:
                logger.warning(f"unrealized_pnl calculation failed: {exc}")

        open_capital_per_year = 0.0
        open_trade = getattr(self.portfolio, "_open_trade", None)
        eval_ts = self._get_eval_timestamp(df)
        if open_trade is not None and eval_ts is not None:
            try:
                entry_ts = pd.to_datetime(getattr(open_trade, "entry_time", None))
                holding_days = max((eval_ts - entry_ts).days + 1, 1)
                position_thb = float(getattr(open_trade, "position_thb", 0.0))
                if position_thb > 0:
                    open_capital_per_year = (position_thb * holding_days) / 365.0
            except Exception as exc:
                logger.warning(f"open position capital/year calculation failed: {exc}")

        return {
            "unrealized_pnl_thb": round(unrealized, 2),
            "open_capital_per_year_thb": round(open_capital_per_year, 2),
        }

    def _compute_risk_metrics(self, df: pd.DataFrame) -> dict:
        """
        คำนวณ MDD / Sharpe / Sortino จาก equity curve ใน portfolio_total_value

        สูตร:
          MDD     = max drawdown จาก running peak
          Sharpe  = mean(excess_return) / std(excess_return) * sqrt(ppy)
          Sortino = mean(excess_return) / downside_std * sqrt(ppy)
                    โดย downside_std คำนวณจากเฉพาะ return ที่ต่ำกว่า risk-free
        """
        if "portfolio_total_value" not in df.columns:
            logger.warning("portfolio_total_value column missing — skip risk metrics")
            return {"note": "portfolio_total_value column missing (see patch [A])"}

        equity = df["portfolio_total_value"].astype(float).values
        n = len(equity)
        if n < 2:
            return {"note": "not enough candles"}

        # annualization factor ตาม timeframe
        ppy = self._PERIODS_PER_YEAR.get(self.timeframe, 6_048)
        rf_per_period = 0.02 / ppy  # risk-free rate 2% ต่อปี

        # ── Total Return ─────────────────────────────────────────────
        initial = equity[0]
        final = equity[-1]
        total_return = (final - initial) / initial if initial else 0.0

        # ── Per-candle returns ────────────────────────────────────────
        returns = pd.Series(equity).pct_change().dropna()

        # ── Maximum Drawdown ─────────────────────────────────────────
        peak = pd.Series(equity).cummax()
        drawdown = (pd.Series(equity) - peak) / peak

        mdd = float(drawdown.min())  # ค่าลบ เช่น -0.12 = -12%
        trough_idx = int(drawdown.idxmin())

        # หา peak index ก่อน trough — idxmax() หาตำแหน่ง equity สูงสุดก่อนถึง trough
        equity_s = pd.Series(equity)
        peak_idx = int(equity_s.iloc[: trough_idx + 1].idxmax())

        def _get_ts(i: int) -> str:
            try:
                return str(df["timestamp"].iloc[i])
            except Exception:
                return str(i)

        # ── Sharpe Ratio ──────────────────────────────────────────────
        excess = returns - rf_per_period
        sharpe = 0.0
        std_e = excess.std(ddof=1)
        if std_e > 1e-12:
            sharpe = float((excess.mean() / std_e) * (ppy**0.5))

        # ── Sortino Ratio ─────────────────────────────────────────────
        downside = excess[excess < 0]
        sortino = 0.0
        if len(downside) > 0:
            downside_std = float((downside**2).mean() ** 0.5)  # semi-deviation
            if downside_std > 1e-12:
                sortino = float((excess.mean() / downside_std) * (ppy**0.5))

        # ── Annualized metrics ────────────────────────────────────────
        ann_return = float((1 + returns.mean()) ** ppy - 1) if n > 1 else 0.0
        volatility = float(returns.std(ddof=1) * (ppy**0.5)) if n > 1 else 0.0

        # Warning: annualized extrapolation จาก data สั้นไม่น่าเชื่อถือ
        actual_days = (
            int((df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]).days)
            if "timestamp" in df.columns
            else self.days
        )
        ann_reliable = actual_days >= 60
        if not ann_reliable:
            logger.warning(
                f"⚠ annualized_return ({ann_return * 100:.1f}%) extrapolated จาก {actual_days} วัน "
                f"→ ไม่น่าเชื่อถือ ต้องการอย่างน้อย 60 วัน"
            )

        return {
            "initial_portfolio_thb": round(initial, 2),
            "final_portfolio_thb": round(final, 2),
            "total_return_pct": round(total_return * 100, 2),
            "annualized_return_pct": round(ann_return * 100, 2),
            "annualized_reliable": ann_reliable,  # False = extrapolated จาก data < 60 วัน
            "annualized_volatility_pct": round(volatility * 100, 2),
            # ── MDD ──────────────────────────────────────────────────
            "mdd_pct": round(mdd * 100, 2),  # ลบ = ขาดทุน
            "mdd_peak_timestamp": _get_ts(peak_idx),
            "mdd_trough_timestamp": _get_ts(trough_idx),
            # ── Risk-adjusted returns ─────────────────────────────────
            "sharpe_ratio": round(sharpe, 3),
            "sortino_ratio": round(sortino, 3),
            # ── Meta ──────────────────────────────────────────────────
            "candles_total": n,
            "periods_per_year": ppy,
            "risk_free_rate_pct": 2.0,
        }

    def calculate_all(self, result_df: pd.DataFrame) -> dict:
        """รวมการคำนวณทั้งหมดไว้ที่นี่"""
        df = result_df.copy()
        metrics = {}

        # 1. Signal Metrics (LLM vs Final)
        for prefix in ["llm", "final"]:
            active = df[df[f"{prefix}_signal"] != "HOLD"]
            total = len(active)

            if total == 0:
                metrics[prefix] = {"note": "all HOLD"}
                continue

            correct = active[f"{prefix}_correct"].sum()
            profitable = active[f"{prefix}_profitable"].sum()
            accuracy = correct / total * 100
            sensitivity = total / len(df) * 100

            correct_rows = active[active[f"{prefix}_correct"]]
            avg_pnl = correct_rows["net_pnl_thb"].mean() if len(correct_rows) else 0.0

            buy_count = (active[f"{prefix}_signal"] == "BUY").sum()
            sell_count = (active[f"{prefix}_signal"] == "SELL").sum()
            rejected = df["rejection_reason"].notna().sum() if prefix == "final" else 0

            metrics[prefix] = {
                "directional_accuracy_pct": round(accuracy, 2),
                "signal_sensitivity_pct": round(sensitivity, 2),
                "total_signals": total,
                "buy_signals": int(buy_count),
                "sell_signals": int(sell_count),
                "correct_signals": int(correct),
                "correct_profitable": int(profitable),
                "avg_net_pnl_thb": round(avg_pnl, 2),
                "rejected_by_risk": int(rejected),
                "avg_confidence": round(active[f"{prefix}_confidence"].mean(), 3),
            }

        # 2. Risk Metrics (MDD, Sharpe, etc.)
        risk = self._compute_risk_metrics(df)
        metrics["risk"] = risk

        # 3. Session Compliance (ตรวจเช็คการทำตามโควตา)
        if self.session_manager:
            compliance = self.session_manager.compliance_report()
            metrics["session_compliance"] = {
                "total_sessions": compliance.get("total_sessions", 0),
                "passed_sessions": compliance.get("passed_sessions", 0),
                "failed_sessions": compliance.get("failed_sessions", 0),
                "no_data_sessions": compliance.get("no_data_sessions", 0),
                "compliance_pct": compliance.get("compliance_pct", 0.0),
                "session_fail_flag": compliance.get("session_fail_flag", False),
            }

        # 4. Trade Metrics (Win Rate, PnL)
        if self.portfolio:
            trade_m = calculate_trade_metrics(self.portfolio.closed_trades)
            open_metrics = self._compute_open_trade_metrics(df)
            trade_m["unrealized_pnl_thb"] = open_metrics["unrealized_pnl_thb"]
            trade_m["avg_capital_per_year_thb"] = round(
                float(trade_m.get("avg_capital_per_year_thb", 0.0))
                + open_metrics["open_capital_per_year_thb"],
                2,
            )
            trade_m = add_calmar(trade_m, risk)  # เพิ่ม calmar_ratio
            metrics["trade"] = trade_m
            # bust_flag สำหรับ deploy_gate
            metrics["bust_flag"] = getattr(self.portfolio, "bust_flag", False)

        # 5. สั่ง Print
        self._print_summary(metrics)
        return metrics

    def _print_summary(self, metrics: dict):
        """จัด Format การปริ้นท์ให้สวยงาม"""
        logger.info("\n" + "=" * 60)
        logger.info("METRICS SUMMARY")
        logger.info("=" * 60)

        for name, m in metrics.items():
            logger.info(f"\n{name.upper()}:")
            if not isinstance(m, dict):
                logger.info(f"  {m}")
                continue

            if name == "risk":
                logger.info(f"  {'initial_portfolio_thb':<40} {m.get('initial_portfolio_thb', '-')} THB")
                logger.info(f"  {'final_portfolio_thb':<40} {m.get('final_portfolio_thb', '-')} THB")
                logger.info(f"  {'total_return_pct':<40} {m.get('total_return_pct', '-')}%")
                logger.info(f"  {'annualized_return_pct':<40} {m.get('annualized_return_pct', '-')}%")
                logger.info(f"  {'annualized_volatility_pct':<40} {m.get('annualized_volatility_pct', '-')}%")
                logger.info(f"  {'─' * 50}")
                logger.info(f"  {'mdd_pct':<40} {m.get('mdd_pct', '-')}%  ← จุดเจ็บปวดสุด")
                logger.info(f"  {'mdd_peak_timestamp':<40} {m.get('mdd_peak_timestamp', '-')}")
                logger.info(f"  {'mdd_trough_timestamp':<40} {m.get('mdd_trough_timestamp', '-')}")
                logger.info(f"  {'─' * 50}")
                logger.info(f"  {'sharpe_ratio':<40} {m.get('sharpe_ratio', '-')}  ← >1 ดี / >2 ดีมาก")
                logger.info(f"  {'sortino_ratio':<40} {m.get('sortino_ratio', '-')}  ← >2 ดี / >3 ยอดเยี่ยม")
            elif name == "trade":
                logger.info(f"  {'total_trades':<40} {m.get('total_trades', '-')}")
                logger.info(f"  {'winning_trades':<40} {m.get('winning_trades', '-')}")
                logger.info(f"  {'losing_trades':<40} {m.get('losing_trades', '-')}")
                logger.info(f"  {'win_rate_pct':<40} {m.get('win_rate_pct', '-')}%  ← >50% ดี")
                logger.info(f"  {'profit_factor':<40} {m.get('profit_factor', '-')}  ← >1.2 ดี / >2.0 ดีมาก")
                logger.info(f"  {'calmar_ratio':<40} {m.get('calmar_ratio', '-')}  ← >1.0 ดี")
                logger.info(f"  {'─' * 50}")
                logger.info(f"  {'avg_win_thb':<40} {m.get('avg_win_thb', '-')} THB")
                logger.info(f"  {'avg_loss_thb':<40} {m.get('avg_loss_thb', '-')} THB")
                logger.info(f"  {'expectancy_thb':<40} {m.get('expectancy_thb', '-')} THB/trade")
                logger.info(f"  {'max_consec_losses':<40} {m.get('max_consec_losses', '-')}  ← สาย loss ยาวสุด")
                logger.info(f"  {'net_pnl_thb':<40} {m.get('net_pnl_thb', '-')} THB")
                logger.info(f"  {'unrealized_pnl_thb':<40} {m.get('unrealized_pnl_thb', '-')} THB")
                logger.info(f"  {'total_cost_thb':<40} {m.get('total_cost_thb', '-')} THB  ← spread+commission")
                logger.info(f"  {'largest_win_thb':<40} {m.get('largest_win_thb', '-')} THB")
                logger.info(f"  {'largest_loss_thb':<40} {m.get('largest_loss_thb', '-')} THB")
                logger.info(f"  {'best_annualized_trade_pct':<40} {m.get('best_annualized_trade_pct', '-')}%")
                logger.info(f"  {'worst_annualized_trade_pct':<40} {m.get('worst_annualized_trade_pct', '-')}%")
                logger.info(f"  {'median_annualized_pct':<40} {m.get('median_annualized_pct', '-')}%")
                logger.info(f"  {'top10_annualized_trade_pct':<40} {m.get('top10_annualized_trade_pct', '-')}%")
                logger.info(f"  {'bottom10_annualized_trade_pct':<40} {m.get('bottom10_annualized_trade_pct', '-')}%")
                logger.info(f"  {'xirr_pct':<40} {m.get('xirr_pct', '-')}%")
                logger.info(f"  {'avg_capital_per_year_thb':<40} {m.get('avg_capital_per_year_thb', '-')} THB")
            else:
                for k, v in m.items():
                    logger.info(f"  {k:<40} {v}")
