"""
run_main_backtest.py  ← PATCHED: เพิ่ม MDD / Sharpe / Sortino
══════════════════════════════════════════════════════════════════════
การเปลี่ยนแปลงจาก version เดิม (ค้นหา # ★ เพื่อดู diff):
  [A] run()               → บันทึก portfolio_total_value ต่อ candle
  [B] _compute_risk_metrics() → method ใหม่
  [C] calculate_metrics() → รวม risk metrics
  [D] export_csv()        → เพิ่ม 3 portfolio columns
══════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from config.config_loader import load_config
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import numpy as np
from data.csv_loader import load_gold_csv
from engine.market_state_builder import MarketStateBuilder
from engine.news_provider import NewsProvider, NullNewsProvider, create_news_provider
from engine.session_manager import TradingSessionManager
from engine.portfolio import (
    SimPortfolio,
    PortfolioBustException,
    DEFAULT_CASH,
    BUST_THRESHOLD,
    WIN_THRESHOLD,
    SPREAD_THB,
    COMMISSION_THB,
    GOLD_GRAM_PER_BAHT,
)
from metrics.calculator import calculate_trade_metrics, add_calmar
from metrics.deploy_gate import deploy_gate, print_gate_report
from data.csv_loader import load_gold_csv, merge_external_data
from metrics.evaluator import BacktestEvaluator
from engine.directive_builder import DirectiveBuilder

# ── path setup ─────────────────────────────────────────────────────
_THIS_DIR = Path(__file__).parent.resolve()
for candidate in [_THIS_DIR.parent, _THIS_DIR]:
    if (candidate / "agent_core").exists():
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
        break

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════════

# NOTE: GOLD_GRAM_PER_BAHT, SPREAD_THB, COMMISSION_THB, DEFAULT_CASH
#       imported จาก backtest.engine.portfolio — ห้าม redefine ที่นี่
DEFAULT_CACHE_DIR = "output/backtest_cache_main"
DEFAULT_OUTPUT_DIR = "output/backtest_results_main"
MIN_CONFIDENCE = 0.6

# ★ [B-helper] จำนวน candle ต่อปี (gold ~24/5 ~252 วัน)
_PERIODS_PER_YEAR: Dict[str, int] = {
    "1m": 362_880,
    "5m": 72_576,
    "15m": 24_192,
    "30m": 12_096,
    "1h": 6_048,
    "4h": 1_512,
    "1d": 252,
}


# ══════════════════════════════════════════════════════════════════
# Time Estimator
# ══════════════════════════════════════════════════════════════════


class TimeEstimator:
    """คาดเดาเวลาที่เหลือจาก rolling average ของ candle ที่ผ่านมา"""

    def __init__(self, window: int = 10):
        from collections import deque

        self.times: deque = deque(maxlen=window)
        self._start: float = 0.0
        self.session_start: float = time.time()

    def tick_start(self):
        self._start = time.time()

    def tick_end(self, current: int, total: int, from_cache: bool = False) -> str:
        elapsed = time.time() - self._start
        if not from_cache:
            self.times.append(elapsed)

        session_elapsed = time.time() - self.session_start
        se_h = int(session_elapsed // 3600)
        se_m = int((session_elapsed % 3600) // 60)
        se_s = int(session_elapsed % 60)

        if not self.times:
            return f"  ⏱ elapsed={se_h:02d}:{se_m:02d}:{se_s:02d}"

        avg = sum(self.times) / len(self.times)
        remaining_sec = (total - current) * avg
        r_h = int(remaining_sec // 3600)
        r_m = int((remaining_sec % 3600) // 60)
        r_s = int(remaining_sec % 60)

        speed = f"{elapsed:.1f}s" if not from_cache else "CACHE"
        return (
            f"  ⏱ {speed}/candle | "
            f"elapsed={se_h:02d}:{se_m:02d}:{se_s:02d} | "
            f"ETA={r_h:02d}:{r_m:02d}:{r_s:02d} | "
            f"avg={avg:.1f}s"
        )


# ══════════════════════════════════════════════════════════════════
# Cache Layer
# ══════════════════════════════════════════════════════════════════


class CandleCache:
    def __init__(self, cache_dir: str, model: str):
        self.dir = Path(cache_dir)
        self.slug = re.sub(r"[^a-zA-Z0-9_-]", "_", model)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._hits = self._misses = 0

    def _path(self, ts: pd.Timestamp) -> Path:
        return self.dir / f"{self.slug}_{ts.strftime('%Y%m%dT%H%M')}.json"

    def get(self, ts: pd.Timestamp) -> Optional[dict]:
        p = self._path(ts)
        if not p.exists():
            self._misses += 1
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            self._hits += 1
            return data
        except Exception:
            self._misses += 1
            return None

    def set(self, ts: pd.Timestamp, data: dict):
        p = self._path(ts)
        
        # 🟢 เพิ่มคำสั่งนี้: ให้เช็คและสร้างโฟลเดอร์ก่อนเขียนไฟล์เสมอ (ถ้าไม่มีจะสร้างให้)
        p.parent.mkdir(parents=True, exist_ok=True) 
        
        p.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    @property
    def stats(self) -> dict:
        total = self._hits + self._misses
        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 3) if total else 0.0,
        }


# ══════════════════════════════════════════════════════════════════
# Main Backtest Class
# ══════════════════════════════════════════════════════════════════


class MainPipelineBacktest:
    def __init__(
        self,
        gold_csv: str,
        news_provider: NewsProvider = None,
        news_csv: str = "",
        external_csv: str = "",
        provider: str = "gemini",
        model: str = "",
        timeframe: str = "1h",
        days: int = 30,
        start_date: str = None,  # 🌟 [NEW] เพิ่มรับค่า start_date
        end_date: str = None,    # 🌟 [NEW] เพิ่มรับค่า end_date
        cache_dir: str = DEFAULT_CACHE_DIR,
        output_dir: str = DEFAULT_OUTPUT_DIR,
        react_max_iter: int = 5,
        request_delay: float = 0.3,
    ):
        self.gold_csv = gold_csv
        self.external_csv = external_csv
        self.timeframe = timeframe
        self.days = days
        self.start_date = start_date # 🌟 [NEW] เก็บลง self
        self.end_date = end_date     # 🌟 [NEW] เก็บลง self
        self.output_dir = output_dir
        self.react_max_iter = react_max_iter
        self.request_delay = request_delay

        # ── LLM Client ──────────────────────────────────────────────────
        from agent_core.llm.client import LLMClientFactory

        kwargs = {"model": model} if model else {}
        self.llm_client = LLMClientFactory.create(provider, **kwargs)
        _model_slug = model or getattr(self.llm_client, "model", provider)
        self.cache = CandleCache(cache_dir=cache_dir, model=_model_slug)
        self.timer = TimeEstimator()

        self.raw_df: Optional[pd.DataFrame] = None
        self.agg_df: Optional[pd.DataFrame] = None
        self.result_df: Optional[pd.DataFrame] = None
        self.results: List[dict] = []
        self.metrics: dict = {}

        self._prompt_builder = None
        self._react = None
        self._risk_mgr = None

        # Session Engine — Phase 2
        self.session_manager = TradingSessionManager()

        # News provider — backward compat: ถ้าส่ง news_csv มา ใช้ CSV mode
        if news_provider is not None:
            self.news_provider = news_provider
        elif news_csv:
            self.news_provider = create_news_provider("csv", csv_path=news_csv)
        else:
            self.news_provider = NullNewsProvider()

        # SimPortfolio v2 — ใหม่
        self.portfolio = SimPortfolio(
            initial_cash=DEFAULT_CASH,
            bust_threshold=BUST_THRESHOLD,
            win_threshold=WIN_THRESHOLD,  # Bug B fix: WIN_THRESHOLD ไม่ใช่ DEFAULT_CASH
        )

    # ── Load & aggregate data ───────────────────────────────────

    def load_and_aggregate(self):
        df = load_gold_csv(
            self.gold_csv,
            external_csv=self.external_csv or None,
            timeframe=self.timeframe,
        )

        # 1. Rename คอลัมน์ให้รองรับทั้งไฟล์ใหม่ (Merged) และไฟล์เก่า
        if "sell_price" in df.columns:
            df = df.rename(columns={
                "sell_price": "Mock_HSH_Sell_Close",
                "buy_price": "Mock_HSH_Buy_Close",
                "spot_price_usd": "CLOSE_XAUUSD",
                "usd_thb": "CLOSE_USDTHB",
                "news_overall_sentiment": "news_sentiment",
                "open": "Mock_HSH_Sell_Open",
                "high": "Mock_HSH_Sell_High",
                "low": "Mock_HSH_Sell_Low",
            })
        else:
            df = df.rename(columns={
                "close": "Mock_HSH_Sell_Close",
                "open": "Mock_HSH_Sell_Open",
                "high": "Mock_HSH_Sell_High",
                "low": "Mock_HSH_Sell_Low",
            })

        df = df.loc[:, ~df.columns.duplicated()].copy()

         # =================================================================
        # 🌟 [NEW] ระบบคัดกรองวันที่ (Train / Test Split & Days Back)
        # =================================================================
        if self.start_date and self.end_date:
            # โหมด 1: Train / Test Split (มี start_date และ end_date)
            start_ts = pd.to_datetime(self.start_date)
            end_ts   = pd.to_datetime(self.end_date) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)

            # จัดการ Timezone ให้ตรงกับ DataFrame
            if df["timestamp"].dt.tz is not None:
                start_ts = start_ts.tz_localize("Asia/Bangkok")
                end_ts   = end_ts.tz_localize("Asia/Bangkok")

            df = df[(df["timestamp"] >= start_ts) & (df["timestamp"] <= end_ts)].reset_index(drop=True)
            logger.info(f"📅 [Data Filter] Train/Test Mode: {self.start_date} ถึง {self.end_date}")
            
        else:
            # โหมด 2: ดึงข้อมูลย้อนหลังตามจำนวน Days (Fallback)
            
            # 🚨 กัน Error กรณีลืมใส่ตัวเลขใน yaml (Fallback to 7 days)
            safe_days = self.days if self.days is not None else 7 
            
            cutoff = df["timestamp"].max() - pd.Timedelta(days=safe_days)
            df = df[df["timestamp"] >= cutoff].reset_index(drop=True)
            logger.info(f"📅 [Data Filter] Recent Mode: ย้อนหลัง {safe_days} วันล่าสุด")

        if df.empty:
            raise ValueError("❌ ไม่พบข้อมูลในช่วงเวลาที่กำหนด กรุณาตรวจสอบ start_date / end_date ใน config.yaml หรือ CSV")
        # =================================================================

        # 2. ป้องกันการ Resample ซ้ำซ้อน
        is_merged_file = "merged" in str(self.gold_csv).lower()
        
        if self.timeframe == "5m" or is_merged_file:
            self.raw_df = self.agg_df = df.copy()
            logger.info(f"✓ Data ready: {len(df):,} candles (Merged or 5m - Skipped Resample)")
            return

        freq_map = {"15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h", "1d": "1D"}
        freq = freq_map.get(self.timeframe, "1h")
  

        freq_map = {"15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h", "1d": "1D"}
        freq = freq_map.get(self.timeframe, "1h")

        agg_rules = {
            "open_thai": "first",
            "high_thai": "max",
            "low_thai": "min",
            "close_thai": "last",
            "volume": "sum",
            "rsi": "last",
            "macd_line": "last",
            "signal_line": "last",
            "macd_hist": "last",
            "ema_20": "last",
            "ema_50": "last",
            "bb_upper": "last",
            "bb_lower": "last",
            "bb_mid": "last",
            "atr": "last",
            "CLOSE_XAUUSD": "last",
            "CLOSE_USDTHB": "last",
            "SPREAD_XAUUSD": "last",
            "SPREAD_USDTHB": "last",
            "Mock_HSH_Buy_Close": "last",
            "Mock_HSH_Sell_Close": "last",
            "premium_buy": "last",
            "premium_sell": "last",
            "pred_premium_buy": "last",
            "pred_premium_sell": "last",
        }
        valid_rules = {k: v for k, v in agg_rules.items() if k in df.columns}
        df.set_index("timestamp", inplace=True)
        agg = (
            df.resample(freq)
            .agg(valid_rules)
            .dropna(subset=["Mock_HSH_Sell_Close"])
            .reset_index()
        )
        self.raw_df = df.reset_index()
        self.agg_df = agg

        logger.info(f"✓ Data ready: {len(agg):,} candles ({self.timeframe})")

    # ── Main system components ─────────────────────────────────

    def _load_main_components(self):
        """Init ReactOrchestrator + PromptBuilder + RiskManager"""
        if self._react is not None:
            return

        from agent_core.core.prompt import (
            SkillRegistry,
            RoleRegistry,
            PromptBuilder,
            AIRole,
        )
        from agent_core.core.react import ReactOrchestrator, ReactConfig
        from agent_core.core.risk import RiskManager

        # __file__ = Src/backtest/run_main_backtest.py → .parent.parent = Src/
        _src_root = Path(__file__).parent.parent

        # ── Load skills.json ────────────────────────────────────────
        skill_registry = SkillRegistry()
        skills_path = _src_root / "agent_core/config/roles.json"
        if skills_path.exists():
            skill_registry.load_from_json(str(skills_path))
            logger.info(
                f"✓ Loaded {len(skill_registry.skills)} skills from {skills_path}"
            )
        else:
            logger.warning(f"skills.json not found at {skills_path}")

        # ── Load roles.json ─────────────────────────────────────────
        role_registry = RoleRegistry(skill_registry)
        roles_path = _src_root / "agent_core/config/roles.json"
        if roles_path.exists():
            role_registry.load_from_json(str(roles_path))
            logger.info(f"✓ Loaded {len(role_registry.roles)} roles from {roles_path}")
        else:
            logger.warning(f"roles.json not found at {roles_path}")

        # ── เลือก role พร้อม fallback ───────────────────────────────
        trading_role = AIRole.ANALYST
        if not role_registry.get(trading_role):
            registered = list(role_registry.roles.keys())
            if not registered:
                raise ValueError("ไม่มี role ใดถูก register — ตรวจสอบ roles.json")
            trading_role = registered[0]
            logger.warning(f"⚠ AIRole.ANALYST ไม่พบ → fallback to: {trading_role}")

        # ── สร้าง components ─────────────────────────────────────────
        self.risk_manager = RiskManager(

        )
        self._react = ReactOrchestrator(
            llm_client=self.llm_client,
            prompt_builder=PromptBuilder(role_registry, trading_role),
            tool_registry={},
            config=ReactConfig(max_iterations=self.react_max_iter),
            risk_manager=self.risk_manager,
        )
        self._risk_manager = self.risk_manager
        logger.info(f"✓ Components ready | role={trading_role}")

    # ── Per-candle runner ───────────────────────────────────────

    def _run_candle(self, row: pd.Series) -> dict:
        
        ts = pd.Timestamp(row["timestamp"])
        session_info = self.session_manager.process_candle(ts)

        # 🌟 ดึงราคามาเพื่อทำ Trailing Stop & Auto Exit
        price = float(row["Mock_HSH_Sell_Close"]) # ราคาโบรกเกอร์ขาย (ราคาเราใช้ซื้อ)
        current_bid = float(row.get("Mock_HSH_Buy_Close", row.get("Buy", price))) # ราคาเราใช้ขายคืน
        
        # 🌟 อัปเดตเลื่อน Stop loss ตามกำไร (Lock-in profit)
        atr_val = float(row.get("atr", 110.0))
        trailing_dist = max(110.0, atr_val * 1.0)
        self.portfolio.update_trailing_stop(current_bid, trailing_dist)

        # 🌟 เช็คว่าราคาชน TP หรือ SL ที่ตั้งไว้หรือไม่
        exit_reason = self.portfolio.check_auto_exit(current_bid)
        
        if exit_reason:
            # 🚨 คืนค่า SIGNAL = "SELL" อย่างถูกต้อง ตรงไปตรงมา
            # เพื่อให้ _apply_to_portfolio นำไป execute และลง log 
            return {
                "timestamp": str(ts),
                "close_thai": price,
                "llm_signal": f"AUTO_{exit_reason}", # ให้รู้ว่าไม่ได้มาจาก AI แต่มาจากระบบ
                "llm_confidence": 1.0,
                "llm_rationale": f"System forced execution: Hit {exit_reason} at {current_bid}",
                "final_signal": "SELL",  # <--- เปลี่ยนเป็น SELL แล้วครับ!
                "final_confidence": 1.0,
                "rejection_reason": f"Auto-closed by {exit_reason}",
                "position_size_thb": 0.0,
                "stop_loss": 0.0,
                "take_profit": 0.0,
                "iterations_used": 0,
                "news_sentiment": float(row.get("overall_sentiment", 0.0)),
                "from_cache": False,
                "session_id": session_info.session_id,
                "can_execute": session_info.can_execute,
            }
            
        # 🌟 [NEW] ถ้าตลาดปิด (Dead Zone) ให้คืนค่า HOLD ทันที ประหยัดค่า API!
        if not session_info.can_execute:
            return {
                "timestamp": str(ts),
                "close_thai": price,
                "llm_signal": "HOLD",
                "llm_confidence": 1.0,
                "llm_rationale": "Market is closed (Dead Zone). Sleeping...",
                "final_signal": "HOLD",
                "final_confidence": 1.0,
                "rejection_reason": "Outside trading hours",
                "position_size_thb": 0.0,
                "stop_loss": 0.0,
                "take_profit": 0.0,
                "iterations_used": 0,
                "news_sentiment": float(row.get("overall_sentiment", 0.0)),
                "from_cache": False,
                "session_id": session_info.session_id,
                "can_execute": False,
            }

        # ถ้าไม่โดน SL/TP ค่อยมาเช็คว่ามี Cache ไว้ไหม
        cached = self.cache.get(ts)
        if cached:
            # inject session_info ใหม่ทุกครั้ง (ไม่เชื่อ cached value ที่อาจ stale)
            cached["session_id"] = session_info.session_id
            cached["can_execute"] = session_info.can_execute
            return {**cached, "from_cache": True}

        news = self.news_provider.get(ts)

        self.portfolio.reset_daily(ts.strftime("%Y-%m-%d"))
        past_5 = self.agg_df[self.agg_df["timestamp"] <= ts].tail(5)
        market_state = MarketStateBuilder.build(
            row=row,
            past_5_rows=past_5,
            current_time=ts,
            portfolio_dict=self.portfolio.to_market_state_dict(price),
            news_data=news,
            interval=self.timeframe,
        )

        # ── [BACKTEST PATCH] Inject time/date ให้ RiskManager อ่านได้ ─────
        market_state["time"] = ts.strftime("%H:%M")
        market_state["date"] = ts.strftime("%Y-%m-%d")

        # ── [v2.3 PATCH] Directive สำหรับ LLM (Refactored) ──────
        quota_ctx = self.session_manager.get_session_quota_context(ts)
        market_state["backtest_directive"] = DirectiveBuilder.build_session_directive(
            portfolio=self.portfolio,
            quota_ctx=quota_ctx
        )
        # ─────────────────────────────────────────────────────────────────────

        try:
            result = self._react.run(market_state)
        except Exception as e:
            logger.error(f"  ✗ React error at {ts}: {e}")
            result = {
                "final_decision": {
                    "signal": "HOLD",
                    "confidence": 0.5,
                    "rationale": f"error: {e}",
                    "rejection_reason": str(e),
                    "position_size_thb": 0.0,
                    "stop_loss": 0.0,
                    "take_profit": 0.0,
                },
                "react_trace": [],
                "iterations_used": 0,
            }

        fd = result.get("final_decision", {})
        trace = result.get("react_trace", [])
        llm_signal = "HOLD"
        llm_confidence = 0.5
        llm_rationale = ""
        for step in reversed(trace):
            resp = step.get("response", {})
            if isinstance(resp, dict) and "signal" in resp:
                llm_signal = resp.get("signal", "HOLD")
                llm_confidence = float(resp.get("confidence", 0.5))
                # ใช้ 'or ""' เพื่อบังคับว่าถ้าดึงมาแล้วเป็น None หรือค่าว่าง ให้กลายเป็น "" เสมอ
                llm_rationale = resp.get("rationale") or ""
                break

        # ── Session check ────────────────────────────────────
        candle_result = {
            "timestamp": str(ts),
            "close_thai": price,
            "llm_signal": llm_signal,
            "llm_confidence": llm_confidence,
            "llm_rationale": llm_rationale[:200],
            "final_signal": fd.get("signal", "HOLD"),
            "final_confidence": fd.get("confidence", llm_confidence),
            "rejection_reason": fd.get("rejection_reason"),
            "position_size_thb": fd.get("position_size_thb", 0.0),
            "stop_loss": fd.get("stop_loss", 0.0),
            "take_profit": fd.get("take_profit", 0.0),
            "iterations_used": result.get("iterations_used", 1),
            "news_sentiment": news.get("overall_sentiment", 0.0) if news else 0.0,
            "from_cache": False,
            "session_id": session_info.session_id,
            "can_execute": session_info.can_execute,
        }
        self.cache.set(ts, candle_result)
        return candle_result

    def _apply_to_portfolio(self, candle_result: dict, timestamp: str = ""):
        signal = candle_result["final_signal"]
        price = candle_result["close_thai"]
        pos_size = candle_result["position_size_thb"]
        can_execute = candle_result.get("can_execute", True)

        # นอก session → override เป็น HOLD ไม่ execute
        if not can_execute:
            logger.debug(f"  [OUT] {timestamp} outside session → HOLD (was {signal})")
            return

        if signal == "BUY":
            # Bug C fix: ถ้า LLM ไม่ set position_size → fallback ใช้ 60% ของ cash
            if pos_size <= 0:
                pos_size = round(self.portfolio.cash_balance * 0.6, 2)
                logger.debug(
                    f"  BUY pos_size=0 → fallback {pos_size:.0f} THB (60% cash)"
                )
            ok = self.portfolio.execute_buy(price, pos_size, timestamp=timestamp)
            if not ok:
                logger.debug(f"  BUY skipped: {self.portfolio.cash_balance:.0f} THB")
            else:
                # [v2.2 PATCH] บันทึก TP/SL price จาก final_decision เข้า portfolio
                # เพื่อให้ risk.py อ่านราคาจริงแทน absolute THB threshold
                _tp = float(candle_result.get("take_profit", 0.0) or 0.0)
                _sl = float(candle_result.get("stop_loss",   0.0) or 0.0)
                self.portfolio.set_open_tp_sl(_tp, _sl)
                logger.debug(f"  TP/SL stored: TP={_tp:,.0f} SL={_sl:,.0f}")
                # บันทึก trade เข้า session compliance
                self.session_manager.record_trade(
                    pd.Timestamp(timestamp),
                )
        elif signal == "SELL":
            ok = self.portfolio.execute_sell(price, timestamp=timestamp)
            if ok:  # 🌟 [FIX] บันทึกเฉพาะตอนที่ขายได้เงินจริงๆ เท่านั้น!
                self.session_manager.record_trade(pd.Timestamp(timestamp))
        # PortfolioBustException propagates ขึ้น run() อัตโนมัติ

    # ── Full run ────────────────────────────────────────────────

    def run(self):
        if self.agg_df is None:
            self.load_and_aggregate()
        self._load_main_components()

        total = len(self.agg_df)
        logger.info(f"\n{'=' * 60}")
        logger.info(
            f"Starting backtest: {total} candles | {self.timeframe} | {self.days}d"
        )
        logger.info(f"{'=' * 60}")

        for idx, row in self.agg_df.iterrows():
            self.timer.tick_start()
            ts = row["timestamp"]

            result = self._run_candle(row)
            try:
                self._apply_to_portfolio(result, timestamp=str(ts))
            except PortfolioBustException as bust:
                logger.error(f"\n{'=' * 60}")
                logger.error(f"🔴 PORTFOLIO BUST at candle [{idx + 1}/{total}]")
                logger.error(str(bust))
                logger.error(f"{'=' * 60}\n")
                result["bust"] = True
                result["portfolio_total_value"] = round(
                    self.portfolio.bust_equity or 0, 2
                )
                result["portfolio_cash"] = round(self.portfolio.cash_balance, 2)
                result["portfolio_gold_grams"] = round(self.portfolio.gold_grams, 4)
                self.results.append(result)
                break

            # ────────────────────────────────────────────────────────────
            port_val = self.portfolio.total_value(result["close_thai"])

            result["portfolio_total_value"] = round(float(port_val), 2)
            result["portfolio_cash"] = round(float(self.portfolio.cash_balance), 2)
            result["portfolio_gold_grams"] = round(float(self.portfolio.gold_grams), 4)

            self.results.append(result)

            cache_tag = "[CACHE]" if result["from_cache"] else ""
            eta_str = self.timer.tick_end(idx + 1, total, result["from_cache"])
            logger.info(
                f"  [{idx + 1}/{total}] {ts} | "
                f"LLM={result['llm_signal']}({result['llm_confidence']:.2f}) → "
                f"FINAL={result['final_signal']} "
                f"{'[REJECTED]' if result['rejection_reason'] else ''} "
                f"{'[OUT]' if not result.get('can_execute', True) else result.get('session_id', '') or ''} "
                f"{cache_tag} | "
                f"Equity={result['portfolio_total_value']:.0f} THB"
            )
            logger.info(eta_str)

        # Session Engine: finalize ปิด session สุดท้าย
        self.session_manager.finalize()
        logger.info(f"\n✓ Backtest complete | cache: {self.cache.stats}")
        self._add_validation()

    def _add_validation(self):
        df = pd.DataFrame(self.results)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["next_close"] = df["close_thai"].shift(-1)
        df["price_change"] = df["next_close"] - df["close_thai"]
        df["actual_direction"] = df["price_change"].apply(
            lambda x: "UP" if x > 0 else ("DOWN" if x < 0 else "FLAT")
        )
        df["net_pnl_thb"] = df["price_change"] - SPREAD_THB - COMMISSION_THB

        for col_prefix in ["llm", "final"]:
            sig_col = f"{col_prefix}_signal"
            corr_col = f"{col_prefix}_correct"
            prof_col = f"{col_prefix}_profitable"
            df[corr_col] = df.apply(
                lambda r: _signal_correct(r[sig_col], r["actual_direction"]), axis=1
            )
            df[prof_col] = df[corr_col] & (df["net_pnl_thb"] > 0)

        self.result_df = df

    # ── Metrics & export ─────────────────────────────────────────

    def calculate_metrics(self) -> dict:
        # โยนภาระไปให้ Evaluator จัดการ
        evaluator = BacktestEvaluator(
            timeframe=self.timeframe,
            days=self.days,
            portfolio=self.portfolio,
            session_manager=self.session_manager
        )
        
        # รับค่าที่คำนวณและ print เสร็จแล้วกลับมาเก็บในคลาส
        self.metrics = evaluator.calculate_all(self.result_df)
        
        return self.metrics

    def export_csv(self, filename: str = None) -> str:
        os.makedirs(self.output_dir, exist_ok=True)

        if filename is None:
            ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            _model_name = getattr(
                self.llm_client,
                "model",
                getattr(self.llm_client, "PROVIDER_NAME", "unknown"),
            )
            model_slug = re.sub(r"[^a-zA-Z0-9_-]", "_", _model_name)
            filename = f"main_{model_slug}_{self.timeframe}_{self.days}d_{ts_str}.csv"

        path = os.path.join(self.output_dir, filename)
        df = self.result_df.copy()

        # ★ [D] เพิ่ม portfolio columns ──────────────────────────────
        export_cols = [
            "timestamp",
            "close_thai",
            "portfolio_total_value",  # ★ equity curve
            "portfolio_cash",  # ★ cash component
            "portfolio_gold_grams",  # ★ gold held
            "actual_direction",
            "price_change",
            "net_pnl_thb",
            "news_sentiment",
            "llm_signal",
            "llm_confidence",
            "llm_rationale",
            "llm_correct",
            "llm_profitable",
            "final_signal",
            "final_confidence",
            "final_correct",
            "final_profitable",
            "rejection_reason",
            "position_size_thb",
            "stop_loss",
            "take_profit",
            "iterations_used",
            "from_cache",
            "session_id",  # Phase 2
            "can_execute",  # Phase 2
        ]
        # ────────────────────────────────────────────────────────────
        export_cols = [c for c in export_cols if c in df.columns]

        with open(path, "w", encoding="utf-8-sig") as f:
            _hdr_model = getattr(
                self.llm_client,
                "model",
                getattr(self.llm_client, "PROVIDER_NAME", "unknown"),
            )
            f.write(f"=== MAIN PIPELINE BACKTEST — SUMMARY ({_hdr_model}) ===\n")
            if hasattr(self, "metrics"):
                for name, m in self.metrics.items():
                    if isinstance(m, dict):
                        for k, v in m.items():
                            f.write(f"{name}_{k},{v}\n")
            f.write("\n=== DETAILED SIGNAL LOG ===\n")
            df[export_cols].to_csv(f, index=False)

        logger.info(f"✓ Exported: {path}")
        return path


# ══════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════


def _signal_correct(signal: str, actual: str) -> bool:
    if signal == "HOLD":
        return actual == "FLAT"
    if signal == "BUY":
        return actual == "UP"
    if signal == "SELL":
        return actual == "DOWN"
    return False


# ══════════════════════════════════════════════════════════════════
# Standalone runner
# ══════════════════════════════════════════════════════════════════


def run_main_backtest(
    gold_csv: str,
    news_csv: str = "",
    external_csv: str = "",
    timeframe: str = "1h",
    days: int = 30,
    start_date: str = None, # 🌟 [NEW]
    end_date: str = None,   # 🌟 [NEW]
    provider: str = "gemini",
    model: str = "",
    cache_dir: str = DEFAULT_CACHE_DIR,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    react_max_iter: int = 5,
) -> dict:
    bt = MainPipelineBacktest(
        gold_csv=gold_csv,
        news_csv=news_csv,
        external_csv=external_csv,
        provider=provider,
        model=model,
        timeframe=timeframe,
        days=days,
        start_date=start_date, # 🌟 [NEW]
        end_date=end_date,     # 🌟 [NEW]
        cache_dir=cache_dir,
        output_dir=output_dir,
        react_max_iter=react_max_iter,
    )
    bt.run()
    metrics = bt.calculate_metrics()
    bt.export_csv()

    # Phase 4: Deploy Gate — พิมพ์ PASS/FAIL report ท้าย backtest
    gate = deploy_gate(metrics)
    print_gate_report(gate)
    metrics["deploy_gate"] = gate

    return metrics


# ══════════════════════════════════════════════════════════════════
# Entry Point
# ══════════════════════════════════════════════════════════════════

def main():
    import argparse
    import logging
    import sys
    import yaml  # 🌟 [NEW] เพิ่มไลบรารีนี้เพื่ออ่าน yaml โดยตรง

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )

    # โหลด Config โครงสร้างเดิม
    config = load_config("config/config.yaml")

    # 🌟 [NEW] แอบอ่านไฟล์ yaml โดยตรง เพื่อดึงค่า start_date / end_date (หลบข้อจำกัดของ Loader)
    cfg_start = None
    cfg_end = None
    try:
        with open("config/config.yaml", "r", encoding="utf-8") as f:
            raw_yaml = yaml.safe_load(f)
            cfg_start = raw_yaml.get("backtest", {}).get("start_date")
            cfg_end   = raw_yaml.get("backtest", {}).get("end_date")
    except Exception as e:
        logging.warning(f"Failed to read start_date from yaml: {e}")

    parser = argparse.ArgumentParser(description="Main Pipeline Backtest")
    parser.add_argument("--days", type=int, default=config.days, help="Override days in config")
    parser.add_argument("--timeframe", default=config.timeframe)
    # รับค่าที่ดึงมาได้เข้า Argument Parser
    parser.add_argument("--start_date", type=str, default=cfg_start, help="Start Date YYYY-MM-DD")
    parser.add_argument("--end_date", type=str, default=cfg_end, help="End Date YYYY-MM-DD")
    args = parser.parse_args()

    # สร้างข้อความสำหรับพิมพ์ Log ว่าใช้โหมดไหน
    mode_text = f"{args.start_date} to {args.end_date}" if (args.start_date and args.end_date) else f"{args.days or 7} Days"

    print("=" * 65)
    print(f"  MAIN PIPELINE BACKTEST — {config.provider} / {args.timeframe} / {mode_text}")
    print("=" * 65)

    try:
        # โยนค่าเข้าฟังก์ชันหลัก
        metrics = run_main_backtest(
            gold_csv=config.gold_csv,
            news_csv=config.news_csv,
            external_csv=config.external_csv,
            timeframe=args.timeframe,
            days=args.days,
            start_date=args.start_date, # 🌟 โยนค่าเข้าไป
            end_date=args.end_date,     # 🌟 โยนค่าเข้าไป
            provider=config.provider,
            model=config.model,
            cache_dir=config.cache_dir,
            output_dir=config.output_dir,
            react_max_iter=config.react_max_iter,
        )
        print("\n✓ Done.")
        return metrics
    
    except Exception as e:
        logging.exception(f"✗ Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()