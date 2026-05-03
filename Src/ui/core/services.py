"""
services.py — Business logic layer (independent from Gradio/UI)
Gold Trading Agent v3.4

Changes v3.4:
  - Remove: multi-interval weighted voting — single interval only
  - Result from _run_single_interval used directly as final decision
  - voting_result structure kept for backward compat (no multi-vote logic)

Changes v3.3:
  - Fix: provider name normalization (gemini_2.5_flash → gemini)
  - Fix: save_run double-call — @log_method removed from db.save_run
  - New: save llm_logs per interval after each run (thinking log → DB)
  - New: llm_log data extracted from react_result and interval result
"""

import time
import json
import numpy as np
import asyncio
import logging
from typing import Optional, Dict, List, Any
from datetime import datetime, timezone
from agent_core.core.prompt import AIRole
from logs.logger_setup import sys_logger, log_method
from ui.core.config import (
    SERVICE_CONFIG,
    VALIDATION,
    INTERVAL_CHOICES,
    DEFAULT_PORTFOLIO,
    is_thailand_market_open,
)
from ui.core.utils import validate_portfolio_update
from notification.discord_notifier import DiscordNotifier
from notification.telegram_notifier import TelegramNotifier
from data_engine.tools.tool_registry import TOOL_REGISTRY
from data_engine.thailand_timestamp import get_thai_time

from agent_core.core.risk import RiskManager
from datetime import datetime

try:
    from data_engine.orchestrator import GoldTradingOrchestrator
    from agent_core.core.react import ReactOrchestrator, ReactConfig, ReadinessConfig
    from agent_core.llm.client import LLMClientFactory, LLMClient
    from agent_core.core.prompt import PromptBuilder, RoleRegistry, SkillRegistry
except ImportError as e:
    sys_logger.error(f"Import error: {e}")
    raise


import os
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
load_dotenv()

from data_engine.analysis_tools.pre_fetch import pre_fetch_market_data
from agent_core.core.xgboost_signal import XGBoostPredictor, SignalAggregator

# ─────────────────────────────────────────────
# Provider Name Normalization
# ─────────────────────────────────────────────
# FIX: UI อาจส่งชื่อที่ไม่ตรงกับ config เช่น "gemini_2.5_flash" แทน "gemini"
# map ทุก variant ที่เป็นไปได้ → canonical name

_PROVIDER_ALIASES: dict[str, str] = {
    # Gemini 3.1 variants (new primary)
    "gemini_3.1_flash_lite_preview":  "gemini",
    "gemini-3.1-flash-lite-preview":  "gemini",
    "gemini 3.1 flash lite preview":  "gemini",
    "gemini_3.1_flash_lite":          "gemini",
    # Gemini 2.5 variants
    "gemini_2.5_flash":             "gemini",
    "gemini_2.5_flash_lite":        "gemini",
    "gemini-2.5-flash":             "gemini",
    "gemini-2.5-flash-preview":     "gemini",
    "gemini-2.5-flash-lite":        "gemini",
    "gemini 2.5 flash":             "gemini",
    "gemini 2.5 flash lite":        "gemini",
    # Groq variants
    "groq_llama":                   "groq",
    "llama-3.3-70b-versatile":      "groq",
    "groq llama 3.3 70b versatile": "groq",
    # OpenRouter — old underscore names → new colon syntax
    "openrouter_llama_70b":         "openrouter:llama-70b",
    "openrouter_qwen_72b":          "openrouter:llama-70b",
    "openrouter_mistral_7b":        "openrouter:mistral-small",
    # Others
    "mock-v1":                      "mock",
    "mock_v1":                      "mock",
}


def _normalize_provider(provider: str) -> str:
    """
    แปลง provider name จาก UI/CLI ให้เป็น canonical name
    - "openrouter:xxx" หรือ "openrouter" → ส่งผ่านตรงๆ ไม่ normalize
    - underscored old names → colon syntax ใหม่ (ผ่าน _PROVIDER_ALIASES)
    - case-insensitive, underscore/hyphen-tolerant สำหรับ non-openrouter
    """
    if not provider:
        return provider
    # colon syntax หรือ bare "openrouter" → pass through ไม่แตะ
    if provider.startswith("openrouter:") or provider == "openrouter":
        return provider
    # ลอง exact match ก่อน
    normalized = _PROVIDER_ALIASES.get(provider)
    if normalized:
        return normalized
    # ลอง lowercase
    normalized = _PROVIDER_ALIASES.get(provider.lower())
    if normalized:
        return normalized
    # ลอง strip/replace
    cleaned = provider.lower().strip().replace("-", "_").replace(" ", "_")
    normalized = _PROVIDER_ALIASES.get(cleaned)
    if normalized:
        return normalized
    # ไม่เจอ → คืนตัวเดิม (ให้ validate ทีหลัง)
    return provider


DAILY_TARGET_ENTRIES = 3
QUOTA_CONFIDENCE_LADDER = (0.60, 0.63, 0.67)
QUOTA_POSITION_LADDER_THB = (1000, 1000, 1000)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def _current_quota_slot() -> int:
    hour = get_thai_time().hour
    if hour < 12:
        return 1
    if hour < 18:
        return 2
    return 3


def build_execution_quota_from_portfolio(
    portfolio: Optional[Dict[str, Any]],
    *,
    session_gate: Optional[Dict[str, Any]] = None,
    source: str = "database",
) -> Dict[str, Any]:
    """
    Build execution quota only after runtime portfolio/session context is known.

    The data orchestrator must stay market-data only; quota depends on persisted
    portfolio counters and optional SessionGate context from the service layer.
    """
    portfolio = portfolio if isinstance(portfolio, dict) else {}
    session_gate = session_gate if isinstance(session_gate, dict) else {}

    trades_today = max(0, _safe_int(portfolio.get("trades_today", 0)))
    trades_this_session = max(0, _safe_int(portfolio.get("trades_this_session", 0)))
    entries_remaining = max(0, DAILY_TARGET_ENTRIES - trades_today)
    quota_met = trades_today >= DAILY_TARGET_ENTRIES

    current_slot = _current_quota_slot()
    min_entries_by_now = max(0, current_slot - 1)
    next_slot_index = min(trades_today, DAILY_TARGET_ENTRIES - 1)
    recommended_position = (
        0 if quota_met else QUOTA_POSITION_LADDER_THB[next_slot_index]
    )

    quota = {
        "source": source,
        "computed_at": get_thai_time().isoformat(),
        "portfolio_updated_at": portfolio.get("updated_at"),
        "daily_target_entries": DAILY_TARGET_ENTRIES,
        "entries_done": trades_today,
        "entries_done_today": trades_today,
        "entries_remaining": entries_remaining,
        "quota_met": quota_met,
        "trades_today": trades_today,
        "trades_this_session": trades_this_session,
        "trades_this_session_source": portfolio.get("trades_this_session_source"),
        "current_slot": current_slot,
        "min_entries_by_now": min_entries_by_now,
        "required_confidence_for_next_buy": QUOTA_CONFIDENCE_LADDER[next_slot_index],
        "recommended_next_position_thb": recommended_position,
    }

    if session_gate:
        quota.update({
            "session_id": session_gate.get("session_id"),
            "quota_group_id": session_gate.get("quota_group_id"),
            "session_start_iso": session_gate.get("session_start_iso"),
            "minutes_to_session_end": session_gate.get("minutes_to_session_end"),
            "session_quota_urgent": bool(session_gate.get("quota_urgent", False)),
            "emergency_mode": session_gate.get("emergency_mode"),
        })

    return quota

    


# ─────────────────────────────────────────────
# Analysis Service
# ─────────────────────────────────────────────


class AnalysisService:
    """
    Main analysis service for trading signals

    Responsibilities:
    ✅ Input validation + provider normalization
    ✅ Data fetching (via orchestrator)
    ✅ LLM orchestration (ReAct loop)
    ✅ Weighted voting across intervals
    ✅ Retry logic with exponential backoff
    ✅ Database persistence (runs + llm_logs)
    """

    def __init__(
        self,
        skill_registry,
        role_registry,
        data_orchestrator,
        persistence=None,
        discord_notifier: DiscordNotifier = None,
        telegram_notifier: TelegramNotifier = None,
    ):
        self.skill_registry    = skill_registry
        self.role_registry     = role_registry
        self.data_orchestrator = data_orchestrator
        self.persistence       = persistence
        self.discord_notifier  = discord_notifier
        self.telegram_notifier = telegram_notifier
        self.max_retries       = SERVICE_CONFIG["max_retries"]
        sys_logger.info(f"AnalysisService initialized (max_retries={self.max_retries})")
        self.risk_manager = RiskManager()
        sys_logger.info("RiskManager initialized as singleton")


    def run_analysis(
        self,
        provider: str,
        period: str,
        intervals: List[str],
        *,
        bypass_session_gate: bool = False,
    ) -> Dict:
        """
        Run analysis for a single interval (multi-interval voting removed)

        intervals รับ list แต่ใช้แค่ตัวแรก (เพื่อ backward compat กับ caller)

        Returns:
            {
                "status": "success" | "error",
                "data": {
                    "market_state": {...},
                    "interval_results": { interval: result }
                },
                "voting_result": {           # passthrough — ไม่มี multi-vote แล้ว
                    "final_signal":       str,
                    "weighted_confidence": float,
                    "voting_breakdown":   {},
                    "interval_details":   []
                },
                "run_id": int,
                "llm_log_ids": [int],
                "attempt": int,
                "market_open": bool
            }
        """
        # ── Normalize provider name (fix: gemini_2.5_flash → gemini) ──────
        original_provider = provider
        provider = _normalize_provider(provider)
        if provider != original_provider:
            sys_logger.info(
                f"Provider normalized: '{original_provider}' → '{provider}'"
            )

        # ── Input validation ───────────────────────────────────────────────
        validation_error = self._validate_inputs(provider, period, intervals)
        if validation_error:
            sys_logger.error(f"Validation failed: {validation_error}")
            return {
                "status":     "error",
                "error":      validation_error,
                "error_type": "validation",
                "attempt":    0,
            }
            
        # ═══════════════════════════════════════════
        # GATE-1 │ services.py → run_analysis() หลัง normalize provider
        # ═══════════════════════════════════════════
        # print("\n" + "="*60)
        # print("GATE-1 │ VALIDATE INPUT")
        # print(f"  provider   = {provider!r}")
        # print(f"  period     = {period!r}")
        # print(f"  intervals  = {intervals}")
        # print(f"  bypass_gate= {bypass_session_gate}")
        # print("="*60 + "\n")

        # ── Market hours check (warn only) ─────────────────────────────────
        market_open = is_thailand_market_open()
        if not market_open:
            sys_logger.warning(
                "Thailand gold market is closed (weekend/holiday) — running analysis anyway"
            )
        
        # ── [NEW] 1. ดึงความทรงจำจากความเจ็บปวด (Reflective Memory) ──
        recent_trades = []
        # print(recent_trades)
        if self.persistence:
                try:
                    # ใช้ get_trade_history แทน get_recent_runs เพื่อดึง PnL จริง
                    trade_history = self.persistence.get_trade_history(limit=5)

                    # เอาแค่ 3 ไม้ล่าสุด
                    for t in trade_history[:3]:
                        dt_str = str(t.get("executed_at", ""))
                        time_str = dt_str.split("T")[1][:5] if "T" in dt_str else dt_str[-8:-3]
                        
                        # เช็คสถานะ PnL (ถ้าเป็นไม้ BUY, PnL จะเป็น None ใน DB ของคุณ)
                        pnl_val = t.get("pnl_thb")
                        if pnl_val is not None:
                            status_mark = "❌ LOSS" if pnl_val < 0 else "✅ WIN"
                            pnl_str = f"{pnl_val:+.2f}"
                        else:
                            status_mark = "⏳ ENTRY"
                            pnl_str = "0.00"

                        # พยายามดึง rationale ถ้าไม่มีให้ใช้ note
                        reason_str = t.get("rationale") or t.get("note") or "N/A"
                        # ตัดคำให้สั้นลงไม่เปลือง Token
                        if len(reason_str) > 100: reason_str = reason_str[:100] + "..."
                        
                        recent_trades.append({
                            "time": time_str or "Recent",
                            "action": t.get("action", "UNKNOWN"),
                            "status": status_mark,
                            "pnl_thb": pnl_str,
                            "reason": reason_str
                        })
                            
                    # กลับด้านเพื่อให้ไม้ล่าสุดอยู่ท้ายสุด
                    recent_trades.reverse()
                    sys_logger.info(f"Loaded {len(recent_trades)} executed trades for Reflective Memory.")
                except Exception as e:
                    sys_logger.warning(f"Failed to load recent trades memory: {e}")
            # ─────────────────────────────────────────────────────────

        # ── Retry loop ─────────────────────────────────────────────────────
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            try:
                sys_logger.info(
                    f"Starting analysis (Attempt {attempt}/{self.max_retries}) "
                    f"provider={provider}, period={period}, intervals={intervals}"
                )

                # Step 2a: Fetch market data
                _PERIOD_TO_DAYS = {
                    "1d": 1, "3d": 3, "5d": 5, "7d": 7, "14d": 14,
                    "1mo": 30, "2mo": 60, "3mo": 90,
                }
                interval = intervals[0]   # ← define ก่อน (Step 2b)
                sys_logger.info(f"Fetching market data (period={period}, interval={interval})...")
                market_state = self.data_orchestrator.run(
                    history_days=_PERIOD_TO_DAYS.get(period, 90), 
                    interval=interval, 
                    save_to_file=True,
                )

                if not market_state or "market_data" not in market_state:
                    raise ValueError("Failed to fetch market data")

                sys_logger.info("Market data fetched successfully")
                
                sys_logger.info("Starting Async Pre-fetch for Tools...")
                # ถ้าไฟล์นี้รันอยู่ใน async function อยู่แล้ว ใช้ await ได้เลย
                # แต่ถ้าไฟล์นี้เป็นฟังก์ชันธรรมดา (sync) ต้องใช้ asyncio.run() ครอบ
                try:
                    pre_fetched_data = asyncio.run(pre_fetch_market_data(session_context={})) 
                    
                    # ยัดข้อมูลที่ดึงมาล่วงหน้าลงใน state 
                    # PromptBuilder จะเห็น key นี้แล้วสวิตช์เป็นโหมด Fast Track อัตโนมัติ
                    market_state["pre_fetched_tools"] = pre_fetched_data
                    
                    sys_logger.info("Pre-fetch completed successfully")
                except Exception as e:
                    sys_logger.error(f"Pre-fetch failed, continuing with normal loop: {e}")
                    # ถ้าพังก็ไม่เป็นไร เพราะถ้าไม่มี key "pre_fetched_tools" 
                    # ReAct Loop จะทำงาน 3 Iterations ตามปกติ (Fallback ที่ปลอดภัย)

                market_state["recent_trades"] = recent_trades

                # Attach runtime portfolio to market state from DB/defaults.
                portfolio = None
                portfolio_source = "default_portfolio"

                if self.persistence:
                    portfolio = self.persistence.get_portfolio()
                    if portfolio:
                        portfolio_source = "database"

                if not portfolio:
                    from ui.core.config import DEFAULT_PORTFOLIO
                    portfolio = DEFAULT_PORTFOLIO.copy()
                else:
                    portfolio = dict(portfolio)

                market_state["portfolio"] = portfolio

                # ── Dynamic PnL Update: Recalculate using latest market price ──
                try:
                    gold_grams = float(portfolio.get("gold_grams", 0.0))
                    if gold_grams > 0:
                        # ใช้ราคา "รับซื้อ (Buy Price)" เพราะเป็นราคาที่เราจะได้เงินจริงถ้าขายตอนนี้
                        thai_gold = market_state.get("market_data", {}).get("thai_gold_thb", {})
                        current_buy_price_baht = float(thai_gold.get("buy_price_thb", 0))
                        
                        if current_buy_price_baht > 0:
                            price_per_gram = current_buy_price_baht / 15.244
                            cost_basis_per_gram = float(portfolio.get("cost_basis_thb", 0))
                            
                            new_current_value = gold_grams * price_per_gram
                            new_pnl = new_current_value - (gold_grams * cost_basis_per_gram)
                            
                            # Update the portfolio dict that goes into market_state
                            portfolio["current_value_thb"] = round(new_current_value, 2)
                            portfolio["unrealized_pnl"] = round(new_pnl, 2)
                            sys_logger.info(
                                f"Dynamic PnL Updated: Price={price_per_gram:.2f}/g, "
                                f"Value={new_current_value:.2f}, PnL={new_pnl:+.2f}"
                            )
                except Exception as pnl_err:
                    sys_logger.warning(f"Failed to update dynamic PnL: {pnl_err}")

                # ===== Compact Portfolio Summary =====
                cash = float(portfolio.get("cash_balance", 0.0))

                gold = float(portfolio.get("gold_grams", 0.0))
                cost = float(portfolio.get("cost_basis_thb", 0.0))
                pnl = float(portfolio.get("unrealized_pnl", 0.0))

                holding = gold > 0.0001
                profit = pnl > 0.0
                pnl_pct = round((pnl / cost) * 100, 2) if cost > 0 else 0.0

                can_trade = cash >= 1000.0

                if cash < 1000:
                    mode = "blocked"
                elif cash < 1100:
                    mode = "critical"
                elif cash < 1250:
                    mode = "defensive"
                else:
                    mode = "normal"

                bias = "manage" if holding else "entry"

                market_state["portfolio_summary"] = {
                    "holding": holding,
                    "pnl_pct": pnl_pct,
                    "profit": profit,
                    "cash": round(cash, 2),
                    "can_trade": can_trade,
                    "mode": mode,
                    "bias": bias
                }

                market_state["execution_quota"] = build_execution_quota_from_portfolio(
                    portfolio,
                    source=portfolio_source,
                )

                sys_logger.info(
                    "Portfolio/quota merged into market state "
                    "(source=%s, entries_done=%s, remaining=%s)",
                    portfolio_source,
                    market_state["execution_quota"].get("entries_done"),
                    market_state["execution_quota"].get("entries_remaining"),
                )

                # 🎯 [MTF Phase 2] Classify Market Regime from trend_analysis
                try:
                    trend_analysis = market_state.get("trend_analysis", {})
                    market_state["market_regime"] = self._detect_market_regime(trend_analysis)
                    sys_logger.info(f"[MTF] Market Regime detected: {market_state['market_regime']}")
                except Exception as _regime_err:
                    sys_logger.warning(f"[MTF] Market regime detection failed: {_regime_err}")
                    market_state["market_regime"] = "UNKNOWN"

                # 🎯 สกัด DataFrame ออกจาก state เพื่อไม่ให้ระบบ Database พังตอนเซฟ
                ohlcv_df = market_state.pop("_raw_ohlcv", None)

                # Step 2c: Run analysis — single interval only
                interval_result = self._run_single_interval(
                    provider=provider,
                    market_state=market_state,
                    interval=interval,
                    ohlcv_df=ohlcv_df, # 🎯 ส่งต่อไปให้ Agent
                    bypass_session_gate=bypass_session_gate,
                )
                interval_results = {interval: interval_result}

                # Extract llm log
                llm_logs_pending: List[dict] = [_extract_llm_log(interval_result, interval)]

                sys_logger.info("Interval analysis complete")

                # Step 2d: Build voting_result passthrough (no multi-vote)
                voting_result = {
                    "final_signal":        interval_result.get("signal", "HOLD"),
                    "weighted_confidence": interval_result.get("confidence", 0.0),
                    "voting_breakdown":    {},
                    "interval_details":    [{
                        "interval":   interval,
                        "signal":     interval_result.get("signal", "HOLD"),
                        "confidence": round(interval_result.get("confidence", 0.0), 3),
                        "weight":     1.0,
                    }],
                    "rationale": interval_result.get("rationale", ""),  # ← เพิ่มบรรทัดนี้
                }

                sys_logger.info(
                    f"Analysis complete: "
                    f"final_signal={voting_result['final_signal']}, "
                    f"confidence={voting_result['weighted_confidence']:.1%}"
                )

                # Step 2e: Provider label (แสดง fallback ถ้ามี)
                best_iv = interval   # single interval — ไม่ต้อง max()
                actual_provider = interval_result.get("provider_used", provider)
                provider_label  = (
                    f"{provider}→{actual_provider}" if actual_provider != provider
                    else provider
                )
                
                # Step 2f: Persist to DB (runs + llm_logs)
                run_id      = None
                llm_log_ids = []
                if self.persistence:
                    sys_logger.info("Saving run to database...")

                    # ── save_run (เรียกแค่ครั้งเดียว — ไม่มี @log_method บน db method) ──
                    run_id = self.persistence.save_run(
                        provider=provider_label,
                        result={
                            "signal":          voting_result["final_signal"],
                            "confidence":      voting_result["weighted_confidence"],
                            "voting_breakdown": voting_result["voting_breakdown"],
                            # ราคาจาก interval result (THB/gram)
                            "entry_price":     interval_result.get("entry_price"),
                            "stop_loss":       interval_result.get("stop_loss"),
                            "take_profit":     interval_result.get("take_profit"),
                            "react_trace":     interval_result.get("trace", []),
                            "iterations_used": interval_result.get("iterations_used", 0),
                            "tool_calls_used": interval_result.get("tool_calls_used", 0),
                        },
                        market_state=market_state,
                        interval_tf=interval,
                        period=period,
                    )
                    sys_logger.info(f"Run saved with ID: {run_id}")

                    # ── save llm_logs (กระบวนการคิดทั้งหมด) ─────────────────
                    llm_log_ids = self.persistence.save_llm_logs_batch(
                        run_id=run_id,
                        logs=llm_logs_pending,
                    )
                    sys_logger.info(
                        f"LLM logs saved: {len(llm_log_ids)} entries for run_id={run_id}"
                    )
                
                # ── Step 2g: Notify Discord  ──────────────
                if self.discord_notifier:  # Fixed here
                    sent = self.discord_notifier.notify( # Fixed here
                        voting_result    = voting_result,
                        interval_results = interval_results,
                        market_state     = market_state,
                        provider         = provider_label,
                        period           = period,
                        run_id = run_id,   # ยังไม่มี run_id ตอนนี้
                    )
                    if sent:
                        sys_logger.info("Discord notification sent ✅")
                    elif self.discord_notifier.last_error: # Fixed here
                        sys_logger.warning(
                            f"Discord notification failed: {self.discord_notifier.last_error}")
                
                # ── Step 2h: Notify Telegram  ──────────────        
                if self.telegram_notifier:
                    sent_telegram = self.telegram_notifier.notify(
                        voting_result=voting_result,
                        interval_results=interval_results,  
                        market_state=market_state,         
                        provider=provider_label,
                        period=period,
                        run_id=run_id
                    )
                    if sent_telegram:
                        sys_logger.info("Telegram notification sent ✅")
                    else:
                        sys_logger.warning("Telegram notification failed or disabled")

                return {
                    "status":      "success",
                    "market_open": market_open,
                    "data": {
                        "market_state":    market_state,
                        "interval_results":interval_results,
                    },
                    "voting_result": voting_result,
                    "run_id":        run_id,
                    "llm_log_ids":   llm_log_ids,
                    "attempt":       attempt,
                }

            except ValueError as e:
                sys_logger.error(f"Validation error: {e}")
                return {
                    "status":     "error",
                    "error":      str(e),
                    "error_type": "validation",
                    "attempt":    attempt,
                }

            except Exception as e:
                last_error = e
                sys_logger.warning(
                    f"Attempt {attempt} failed: {type(e).__name__}: {e}"
                )
                if attempt < self.max_retries:
                    wait_time = SERVICE_CONFIG["retry_delay"] ** attempt
                    sys_logger.info(
                        f"Retrying in {wait_time}s... "
                        f"(attempt {attempt + 1}/{self.max_retries})"
                    )
                    time.sleep(wait_time)
                continue

        sys_logger.error(f"Failed after {self.max_retries} attempts: {last_error}")
        return {
            "status":     "error",
            "error":      str(last_error),
            "error_type": "api_failure",
            "attempt":    self.max_retries,
        }

    def _run_single_interval(
        self, provider: str, market_state: dict, interval: str, *,bypass_session_gate: bool = False, ohlcv_df=None
    ) -> Dict:
        """Run analysis for single interval using ReAct loop with provider fallback chain"""
        t_start = time.time()
        try:
            from agent_core.core.session_gate import (
                attach_session_gate_to_market_state,
                resolve_session_gate,
            )
            from ui.core.config import (
                PROVIDER_FALLBACK_CHAIN,
                PROVIDER_DOMAIN,
                OPENROUTER_MODELS,
                get_openrouter_model,
            )
            from agent_core.llm.client import FallbackChainClient, GeminiClient

            # ── Gemini model variants ที่ระบุ model string โดยตรง ──────────
            # ใช้ GeminiClient แต่ override model — ไม่ผ่าน LLMClientFactory
            _GEMINI_VARIANTS: set[str] = {
                "gemini-3.1-flash-lite-preview",
                "gemini-2.5-flash-lite",
                "gemini-2.0-flash-lite",
            }

            OLLAMA_MODELS = [
                "qwen3.5:9b", "qwen2.5:7b", "qwen2.5:3b",
                "deepseek-r1:7b", "deepseek-r1:8b", "ollama",
            ]

            # openrouter colon syntax → map ไปยัง fallback chain ของตัวเอง
            # ถ้าไม่มีใน chain ให้ fallback เป็น [provider, "gemini", "mock"]
            chain_key      = "ollama" if provider in OLLAMA_MODELS else provider
            fallback_order = PROVIDER_FALLBACK_CHAIN.get(
                chain_key, [chain_key, "gemini", "mock"]
            )

            sys_logger.info(
                f"[{interval}] Building fallback chain: {' → '.join(fallback_order)}"
            )

            chain_clients: list[tuple] = []  # (name, client, domain)
            for p in fallback_order:
                try:
                    domain = PROVIDER_DOMAIN.get(p)  # None ถ้าไม่มีใน map

                    if p in _GEMINI_VARIANTS:
                        # สร้าง GeminiClient ด้วย model string โดยตรง
                        client = GeminiClient(model=p)
                        sys_logger.info(
                            f"  Creating GeminiClient (variant): model={p} domain={domain}"
                        )
                    elif p in OLLAMA_MODELS or (p == "ollama" and provider in OLLAMA_MODELS):
                        model_name = provider if provider != "ollama" else "qwen3.5:9b"
                        client = LLMClientFactory.create(
                            "ollama", model=model_name,
                            base_url="http://localhost:11434",
                            temperature=0.1,
                        )
                    # ✨ OpenRouter colon syntax: "openrouter:claude-haiku-3-5", "openrouter:gpt-5o-mini" ฯลฯ
                    elif p.startswith("openrouter:") or p == "openrouter":
                        api_key = os.environ.get("OPENROUTER_API_KEY")
                        if not api_key:
                            raise ValueError(f"OPENROUTER_API_KEY not set in .env")
                        client = LLMClientFactory.create(p, temperature=0.1)
                        sys_logger.info(
                            f"  Creating OpenRouter client: {p} "
                            f"(resolved={client.model}) domain={domain}"
                        )
                    # compat: old underscore names ที่ยังหลุดมา
                    elif p.startswith("openrouter_"):
                        model_config = get_openrouter_model(p)
                        if not model_config:
                            raise ValueError(f"Unknown OpenRouter model: {p}")
                        if not model_config.get("api_key"):
                            raise ValueError(f"OPENROUTER_API_KEY not set in .env for {p}")
                        sys_logger.info(
                            f"  Creating OpenRouter client (legacy): {p} "
                            f"(model={model_config['model_id']})"
                        )
                        client = LLMClientFactory.create(
                            "openrouter",
                            api_key=model_config["api_key"],
                            model=model_config["model_id"],
                            temperature=0.1,
                        )
                    else:
                        client = LLMClientFactory.create(p)
                    chain_clients.append((p, client, domain))
                    sys_logger.info(f"  ✅ Provider '{p}' ready (domain={domain})")
                except Exception as e:
                    sys_logger.warning(f"  ⚠️ Provider '{p}' skipped: {e}")

            if not chain_clients:
                raise ValueError(f"No providers available for chain: {fallback_order}")

            llm_client = FallbackChainClient(chain_clients)

            if not llm_client.is_available():
                raise ValueError(
                    f"No provider in fallback chain available: {fallback_order}"
                )
            
            market_state["interval"] = interval
            gate_res = resolve_session_gate(force_bypass=bypass_session_gate)
            
            _portfolio_for_gate = market_state.get("portfolio", {})
            _trades_this_session, _trades_this_session_source = (
                self._resolve_session_trade_count(_portfolio_for_gate, gate_res)
            )
            if isinstance(_portfolio_for_gate, dict):
                _portfolio_for_gate["trades_this_session"] = _trades_this_session
                _portfolio_for_gate["trades_this_session_source"] = (
                    _trades_this_session_source
                )
            _gold_grams_for_gate = float(
                (_portfolio_for_gate.get("gold_grams", 0.0) or 0.0)
                if isinstance(_portfolio_for_gate, dict)
                else 0.0
            )
            # พิมพ์ออก Console โดยตรงเพื่อให้ตรวจสอบได้ง่าย
            print(
                f"\n📊 [SESSION CHECK] Trades in this session: "
                f"{_trades_this_session} ({_trades_this_session_source})"
            )
            sys_logger.info(
                "[Session Quota] Resolved trades_this_session=%s source=%s "
                "session_start=%s",
                _trades_this_session,
                _trades_this_session_source,
                getattr(gate_res, "session_start_iso", None),
            )
            attach_session_gate_to_market_state(
                market_state,
                gate_res,
                trades_this_session=_trades_this_session,
                gold_grams=_gold_grams_for_gate,
            )
            _quota_source = (
                market_state.get("execution_quota", {}).get("source")
                or "database"
            )
            market_state["execution_quota"] = build_execution_quota_from_portfolio(
                market_state.get("portfolio", {}),
                session_gate=market_state.get("session_gate", {}),
                source=_quota_source,
            )
            sys_logger.info(
                "[ExecutionQuota] Finalized after SessionGate: source=%s "
                "entries_done=%s trades_this_session=%s session=%s",
                _quota_source,
                market_state["execution_quota"].get("entries_done"),
                market_state["execution_quota"].get("trades_this_session"),
                market_state["execution_quota"].get("session_id"),
            )
            
            # ═══════════════════════════════════════════
            # GATE-2 │ services.py → หลัง data_orchestrator.run()
            # ═══════════════════════════════════════════
            # import json
            # print("\n" + "="*60)
            # print("GATE-2 │ MARKET STATE RAW")
            # print(json.dumps(market_state, indent=2, ensure_ascii=False, default=str))
            # print("="*60 + "\n")
            
            if gate_res.apply_gate:
                sys_logger.info(
                    f"[{interval}] Session gate: session_id={gate_res.session_id} "
                    f"mode={gate_res.llm_mode} urgent={gate_res.quota_urgent} "
                    f"mins_to_end={gate_res.minutes_to_session_end}"
                )
            else:
                sys_logger.info(
                    f"[{interval}] Session gate skipped "
                    f"(outside session window or bypass_session_gate={bypass_session_gate})"
                )
                
            # quota_urgent → ไม่วน ReAct/tool loop: fast path ใน react.py (max_tool_calls=0)
            # = merge prompt (build_final_decision) → LLM ครั้งเดียว → output
            quota_urgent_fast = bool(
                gate_res.apply_gate and getattr(gate_res, "quota_urgent", False)
            )
            if quota_urgent_fast:
                sys_logger.info(
                    f"[{interval}] quota_urgent=True — LLM fast path only (no ReAct tool loop)"
                )
            
            _ts_str = (
                market_state.get("market_data", {})
                .get("spot_price_usd", {})
                .get("timestamp", "")
            )
            
            try:
                _ts = datetime.fromisoformat(_ts_str)
                market_state["time"] = _ts.strftime("%H:%M")
                market_state["date"] = _ts.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                now = datetime.now()
                market_state["time"] = now.strftime("%H:%M")
                market_state["date"] = now.strftime("%Y-%m-%d")
                
                
            # ─── ATR Conversion: USD/oz → THB/baht_weight ───────────────
            try:
                _ti        = market_state.get("technical_indicators", {})
                _atr_node  = _ti.get("atr", {})
                _atr_usd   = float(_atr_node.get("value", 0))
                _usd_thb   = float(
                    market_state.get("market_data", {})
                    .get("forex", {}).get("usd_thb", 0.0)
                )
                _spot      = float(
                    market_state.get("market_data", {})
                    .get("spot_price_usd", {}).get("price_usd_per_oz", 0)
                )

                # Guard: ข้อมูลพร้อม?
                if _atr_usd <= 0 or _usd_thb <= 0:
                    raise ValueError(
                        f"ATR conversion skipped - atr_usd={_atr_usd}, usd_thb={_usd_thb}"
                    )

                # Stale check: ATR < 0.1% ของราคา = ข้อมูล stale มาก
                if _spot > 0 and (_atr_usd / _spot) < 0.001:
                    sys_logger.warning(
                        f"[{interval}] ATR unreliable (ratio={_atr_usd/_spot:.4%}) "
                        f"- market likely closed or stale data"
                    )

                _atr_thb = (_atr_usd * _usd_thb / 31.1035) * 15.244

                # Mutation ที่ document ชัดเจน
                _atr_node["value"]     = round(_atr_thb, 2)
                _atr_node["unit"]      = "THB_PER_BAHT_WEIGHT"
                _atr_node["value_usd"] = round(_atr_usd, 4)

                sys_logger.info(
                    f"[{interval}] ATR: {_atr_usd:.4f} USD/oz "
                    f"-> {_atr_thb:.2f} THB/baht_weight (usd_thb={_usd_thb:.4f})"
                )

                # ═══════════════════════════════════════════
                # GATE-3 │ services.py → หลัง ATR conversion
                # ═══════════════════════════════════════════
                # print("\n" + "="*60)
                # print("GATE-3 │ ATR CONVERSION")
                # print(f"  _atr_usd            = {_atr_usd}")
                # print(f"  _usd_thb            = {_usd_thb}")
                # print(f"  _atr_thb_per_baht   = {_atr_thb_per_baht}")
                # print(f"  _spot               = {_spot}")
                # print(f"  atr/spot ratio      = {_atr_usd/_spot if _spot else 'DIV/0'}")
                # print("="*60 + "\n")

            except Exception as _atr_err:
                sys_logger.warning(
                    f"[{interval}] ATR conversion failed: {_atr_err} "
                    "- value remains in USD"
                )
                # Explicit fallback: set unit ให้ตรงกับความจริง
                _atr_node = market_state.get("technical_indicators", {}).get("atr", {})
                if "unit" not in _atr_node:
                    _atr_node["unit"] = "USD_PER_OZ"
                if "value_usd" not in _atr_node:
                    _atr_node["value_usd"] = _atr_node.get("value", 0)

            # ReAct orchestration
            # ── [MTF Phase 3] Auto-select AIRole based on detected market_regime ──
            _regime = str(market_state.get("market_regime", "UNKNOWN")).upper()
            _REGIME_TO_ROLE = {
                "UPTREND":   AIRole.AGGRESSIVE_BULLISH,
                "SIDEWAYS":  AIRole.RANGE_BOUND_SNIPER,
                "DOWNTREND": AIRole.DEFENSIVE_SCAVENGER,
            }
            _session_gate = market_state.get("session_gate", {}) or {}
            _emergency_mode = _session_gate.get("emergency_mode")
            if _emergency_mode == "forced_buy":
                selected_role = AIRole.AGGRESSIVE_BULLISH
                sys_logger.warning(
                    "[EmergencySession] forced_buy -> Role=%s (%s)",
                    selected_role.value,
                    _session_gate.get("emergency_reason"),
                )
            elif _emergency_mode == "forced_sell":
                selected_role = AIRole.DEFENSIVE_SCAVENGER
                sys_logger.warning(
                    "[EmergencySession] forced_sell -> Role=%s (%s)",
                    selected_role.value,
                    _session_gate.get("emergency_reason"),
                )
            else:
                selected_role = _REGIME_TO_ROLE.get(_regime, AIRole.ANALYST)
                sys_logger.info(f"[MTF] Regime={_regime} → Role={selected_role.value}")

            prompt_builder = PromptBuilder(self.role_registry, selected_role)
            if quota_urgent_fast:
                # fast path: ไม่ใช้ tool loop → readiness check ไม่มีผล
                react_config = ReactConfig(max_iterations=1, max_tool_calls=0)
            else:
                # [P1] inject ReadinessConfig — required_indicators เปลี่ยนได้โดยไม่แตะ checker
                react_config = ReactConfig(
                    max_iterations=3,
                    max_tool_calls=5,
                    readiness=ReadinessConfig(
                        required_indicators=["rsi", "macd", "trend", "force_react_loop"],
                        require_htf=True,
                    ),
                )
                
            # print('TOOL REGISTY')
            # print(TOOL_REGISTRY)
            react_orchestrator = ReactOrchestrator(
                llm_client=llm_client,
                prompt_builder=prompt_builder,
                tool_registry=TOOL_REGISTRY,
                config=react_config,
                risk_manager=self.risk_manager,
            )
            
            ## ═══════════════════════════════════════════
            # GATE-4 IN │ services.py → ก่อน react_orchestrator.run()
            # ═══════════════════════════════════════════
            
            current_session = gate_res.session_id if gate_res.apply_gate else "Morning"
            is_market_open = gate_res.apply_gate

            # 2. สร้าง Predictor
            predictor = XGBoostPredictor(
                repo_id="athiphatss/Xgboost_HSH965_gold_trading_signal",
                filename="feature_columns.json"
            )

            # 3. เตรียม features_dict
            features_dict = {
                "xauusd_open": market_state.get("market_data", {}).get("ohlcv", {}).get("open", 0.0),
                "xauusd_high": market_state.get("market_data", {}).get("ohlcv", {}).get("high", 0.0),
                "xauusd_low": market_state.get("market_data", {}).get("ohlcv", {}).get("low", 0.0),
                "xauusd_close": market_state.get("market_data", {}).get("ohlcv", {}).get("close", 0.0),
                "hour_sin": np.sin(2 * np.pi * datetime.now().hour / 24),
                "hour_cos": np.cos(2 * np.pi * datetime.now().hour / 24),
                "day_of_week": datetime.now().weekday(),
            }

            # 4. รัน Predictor เพื่อเอา XGBoost Signal
            xgb_out = predictor.predict(features_dict, session=current_session)
            # print(xgb_out)
            
            # --- [NEW] 5. คำนวณ Dynamic Weights ---
            # ดึงทิศทางจาก 3 แหล่ง
            xgb_dir = str(getattr(xgb_out, "signal", "HOLD")).upper()
            
            news_score = market_state.get("news", {}).get("sentiment_score", 0.0)
            news_dir = "BUY" if news_score > 0.5 else "SELL" if news_score < -0.5 else "HOLD"
            
            tech_trend = market_state.get("technical_indicators", {}).get("trend", {}).get("trend", "").lower()
            tech_dir = "BUY" if "up" in tech_trend else "SELL" if "down" in tech_trend else "HOLD"

            # กำหนดน้ำหนักตาม Session
            if is_market_open and current_session == "Evening":
                w_xgb, w_news, w_tech = 0.35, 0.45, 0.20
            elif current_session == "Morning":
                w_xgb, w_news, w_tech = 0.55, 0.15, 0.30
            else:
                w_xgb, w_news, w_tech = 0.50, 0.20, 0.30

            # คำนวณคะแนน
            bull_score, bear_score = 0.0, 0.0
            
            if xgb_dir == "BUY": bull_score += w_xgb
            elif xgb_dir == "SELL": bear_score += w_xgb
            
            if news_dir == "BUY": bull_score += w_news
            elif news_dir == "SELL": bear_score += w_news
            
            if tech_dir == "BUY": bull_score += w_tech
            elif tech_dir == "SELL": bear_score += w_tech

            # สรุปผล
            if bull_score > bear_score:
                final_dir, base_conf = "BUY", bull_score
            elif bear_score > bull_score:
                final_dir, base_conf = "SELL", bear_score
            else:
                # ถ้าคะแนนเท่ากัน ให้ใช้ค่าเฉลี่ยของน้ำหนักที่เหลืออยู่ แทนการล็อค 0.5
                final_dir, base_conf = "HOLD", (bull_score + bear_score) / 2 if (bull_score + bear_score) > 0 else 0.35

            # ยัดใส่ market_state ให้ PromptBuilder เอาไปใช้
            market_state["dynamic_weights"] = {
                "session": current_session,
                "xgb_w": w_xgb,
                "news_w": w_news,
                "tech_w": w_tech,
                "direction": final_dir,
                "base_confidence": round(base_conf, 2)
            }
            
            slim_state = self.data_orchestrator.pack(market_state)

            _portfolio_trades = (
                market_state.get("portfolio", {}).get("trades_this_session")
            )
            _session_gate = market_state.get("session_gate", {}) or {}
            _execution_quota = market_state.get("execution_quota", {}) or {}
            _slim_session_gate = slim_state.get("session_gate", {}) or {}
            _slim_execution_quota = slim_state.get("execution_quota", {}) or {}
            _session_gate_present = bool(market_state.get("session_gate"))
            _slim_session_gate_present = bool(slim_state.get("session_gate"))
            _session_gate_trades = (
                _session_gate.get("trades_this_session")
                if _session_gate_present
                else _portfolio_trades
            )
            _slim_session_gate_trades = (
                _slim_session_gate.get("trades_this_session")
                if _slim_session_gate_present
                else _portfolio_trades
            )
            _pre_llm_state_check = {
                "portfolio.trades_this_session": _portfolio_trades,
                "session_gate.present": _session_gate_present,
                "session_gate.apply_gate": _session_gate.get("apply_gate", False),
                "session_gate.trades_this_session": _session_gate_trades,
                "execution_quota.trades_this_session": _execution_quota.get("trades_this_session"),
                "session_gate.emergency_mode": _session_gate.get("emergency_mode"),
                "execution_quota.source": _execution_quota.get("source"),
                "slim_state.session_gate.present": _slim_session_gate_present,
                "slim_state.session_gate.trades_this_session": _slim_session_gate_trades,
                "slim_state.execution_quota.trades_this_session": _slim_execution_quota.get("trades_this_session"),
                "slim_state.session_gate.emergency_mode": _slim_session_gate.get("emergency_mode"),
                "slim_state.execution_quota.source": _slim_execution_quota.get("source"),
                "aligned": (
                    _portfolio_trades
                    == _session_gate_trades
                    == _execution_quota.get("trades_this_session")
                    == _slim_session_gate_trades
                    == _slim_execution_quota.get("trades_this_session")
                ),
            }
            sys_logger.info(
                "[PreLLM StateCheck] %s",
                json.dumps(_pre_llm_state_check, ensure_ascii=False, default=str),
            )
            
            react_result = react_orchestrator.run(
                market_state=slim_state,
                ohlcv_df=ohlcv_df
            )

            # react_result = react_orchestrator.run(market_state)
            
            # ═══════════════════════════════════════════
            # GATE-4 OUT │ services.py → หลัง react_orchestrator.run()
            # ═══════════════════════════════════════════
            # print("\n" + "="*60)
            # print("GATE-4 OUT │ REACT RESULT")
            # print(json.dumps(react_result, indent=2, ensure_ascii=False, default=str))
            # print("="*60 + "\n") 
            
            elapsed_ms   = int((time.time() - t_start) * 1000)

            used_provider = llm_client.active_provider
            fallback_log  = llm_client.errors

            if fallback_log:
                sys_logger.warning(
                    f"[{interval}] Fallback occurred — used '{used_provider}' "
                    f"after {len(fallback_log)} failure(s): "
                    + "; ".join(e["provider"] for e in fallback_log)
                )
            else:
                sys_logger.info(f"[{interval}] Used primary provider '{used_provider}'")

            # ─── Guard: ถ้า react_result ไม่ใช่ dict ให้ wrap ───
            if not isinstance(react_result, dict):
                sys_logger.warning(
                    f"[{interval}] react_result is {type(react_result).__name__}, expected dict — wrapping"
                )
                react_result = {}

            decision = react_result.get("final_decision", {})

            # ─── Guard: ถ้า final_decision เป็น JSON string ให้ parse ───
            if isinstance(decision, str):
                try:
                    decision = json.loads(decision)
                    sys_logger.warning(f"[{interval}] final_decision was a JSON string — parsed OK")
                except (json.JSONDecodeError, TypeError):
                    sys_logger.error(f"[{interval}] final_decision string cannot be parsed: {decision!r}")
                    decision = {}

            # ─── Inject time/date ────────────────────────────────────────
            from datetime import datetime as _dt
            try:
                _ts = _dt.fromisoformat(_ts_str)
                market_state["time"] = _ts.strftime("%H:%M")
                market_state["date"] = _ts.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                _now = _dt.now()
                market_state["time"] = _now.strftime("%H:%M")
                market_state["date"] = _now.strftime("%Y-%m-%d")

            final_decision =  decision

            return {
                "signal":          final_decision.get("signal", "HOLD"),
                "confidence":      final_decision.get("confidence", 0.0),
                "reasoning":       final_decision.get("rationale", ""),
                "rationale":       final_decision.get("rationale", ""),
                "entry_price":     final_decision.get("entry_price"),
                "stop_loss":       final_decision.get("stop_loss"),
                "take_profit":     final_decision.get("take_profit"),
                "rejection_reason": final_decision.get("rejection_reason"),
                # metadata เดิมคงไว้
                "trace":           react_result.get("react_trace", []),
                "provider_used":   used_provider,
                "fallback_log":    fallback_log,
                "is_fallback":     bool(fallback_log),
                "fallback_from":   fallback_log[0]["provider"] if fallback_log else None,
                "elapsed_ms":      elapsed_ms,
                "token_input":     react_result.get("token_input"),
                "token_output":    react_result.get("token_output"),
                "token_total":     react_result.get("token_total"),
                "iterations_used": react_result.get("iterations_used", 0),
                "tool_calls_used": react_result.get("tool_calls_used", 0),
                "full_prompt":     react_result.get("prompt_text"),
                "full_response":   react_result.get("response_raw"),
            }

        except Exception as e:
            elapsed_ms = int((time.time() - t_start) * 1000)
            
            import traceback
            sys_logger.error(f"FULL TRACEBACK:\n{traceback.format_exc()}")
    
            sys_logger.error(
                f"Error analyzing interval {interval}: {type(e).__name__}: {e}"
            )
            return {
                "signal":          "HOLD",
                "confidence":      0.0,
                "reasoning":       f"Analysis failed: {str(e)}",
                "rationale":       f"Analysis failed: {str(e)}",
                "entry_price":     None,
                "stop_loss":       None,
                "take_profit":     None,
                "trace":           [],
                "provider_used":   "none",
                "fallback_log":    [],
                "is_fallback":     False,
                "fallback_from":   None,
                "elapsed_ms":      elapsed_ms,
                "token_input":     None,
                "token_output":    None,
                "token_total":     None,
                "iterations_used": 0,
                "tool_calls_used": 0,
                "full_prompt":     None,
                "full_response":   None,
            }

    def _validate_inputs(
        self, provider: str, period: str, intervals: List[str]
    ) -> Optional[str]:
        """Validate input parameters. Return error message if invalid, None if OK"""
        from ui.core.config import validate_provider, validate_period, validate_intervals

        if not validate_provider(provider):
            return f"Invalid provider: {provider}"

        if not validate_period(period):
            return f"Invalid period: {period}"

        if not intervals:
            return "At least one interval must be selected"

        if not validate_intervals(intervals):
            return f"Invalid intervals: {intervals}"

        return None

    def _resolve_session_trade_count(self, portfolio: dict, gate_res) -> tuple[int, str]:
        """
        Resolve trades_this_session from trade_log for the active session.

        portfolio.trades_this_session is treated as a fallback only. A NULL value
        is never allowed to imply "zero trades" while a DB session can be counted.
        """
        if not getattr(gate_res, "apply_gate", False):
            return 0, "outside_session"

        session_start_iso = getattr(gate_res, "session_start_iso", None)
        if (
            self.persistence
            and session_start_iso
            and hasattr(self.persistence, "get_trades_count_since")
        ):
            try:
                count = max(
                    0,
                    int(self.persistence.get_trades_count_since(session_start_iso) or 0),
                )
                if hasattr(self.persistence, "update_trades_this_session"):
                    try:
                        self.persistence.update_trades_this_session(count)
                    except Exception as sync_exc:
                        sys_logger.warning(
                            "[Session Quota] Could not sync "
                            "portfolio.trades_this_session=%s: %s",
                            count,
                            sync_exc,
                        )
                return count, "trade_log"
            except Exception as exc:
                sys_logger.warning(
                    "[Session Quota] Could not count trades from trade_log "
                    "since %s: %s",
                    session_start_iso,
                    exc,
                )

        raw_count = portfolio.get("trades_this_session") if isinstance(portfolio, dict) else None
        if raw_count is None:
            sys_logger.warning(
                "[Session Quota] portfolio.trades_this_session is NULL and "
                "trade_log count is unavailable; using explicit 0 fallback"
            )
        return max(0, _safe_int(raw_count, 0)), "portfolio_fallback"

    @staticmethod
    def _detect_market_regime(trend_analysis: dict) -> str:
        """
        [MTF Phase 2] จำแนก Market Regime จากข้อมูล EMA trend ของ 15m และ 30m

        Logic:
          - UPTREND:   ทั้ง 15m และ 30m สถานะ 'bullish'
          - DOWNTREND: ทั้ง 15m และ 30m สถานะ 'bearish'
          - SIDEWAYS:  สัญญาณขัดกัน หรือไม่มีข้อมูลเพียงพอ

        Returns:
            str: "UPTREND" | "DOWNTREND" | "SIDEWAYS" | "UNKNOWN"
        """
        if not trend_analysis:
            return "UNKNOWN"

        tf_15m = trend_analysis.get("15m", {})
        tf_30m = trend_analysis.get("30m", {})

        status_15m = str(tf_15m.get("status", "")).lower()
        status_30m = str(tf_30m.get("status", "")).lower()

        # ถ้ามีข้อมูลแค่ timeframe เดียว ให้ใช้ timeframe นั้นตัดสิน
        if status_15m and not status_30m:
            if status_15m == "bullish":
                return "UPTREND"
            elif status_15m == "bearish":
                return "DOWNTREND"
            return "SIDEWAYS"

        if status_30m and not status_15m:
            if status_30m == "bullish":
                return "UPTREND"
            elif status_30m == "bearish":
                return "DOWNTREND"
            return "SIDEWAYS"

        # ทั้งคู่มีข้อมูล — ต้องสอดคล้องกัน (agree)
        if status_15m == "bullish" and status_30m == "bullish":
            return "UPTREND"
        elif status_15m == "bearish" and status_30m == "bearish":
            return "DOWNTREND"
        else:
            # สัญญาณขัดกัน (15m bullish แต่ 30m bearish หรือกลับกัน) = ไซด์เวย์
            return "SIDEWAYS"


# ─────────────────────────────────────────────
# LLM Log Extractor (helper)
# ─────────────────────────────────────────────

def _extract_llm_log(interval_result: dict, interval: str) -> dict:
    """
    สกัด llm_log data จาก interval_result
    สำหรับบันทึกลง llm_logs table
    """
    fallback_log  = interval_result.get("fallback_log", [])
    is_fallback   = bool(fallback_log)
    fallback_from = fallback_log[0]["provider"] if fallback_log else None

    return {
        "interval_tf":     interval,
        "step_type":       "THOUGHT_FINAL",
        "iteration":       interval_result.get("iterations_used", 0),
        "provider":        interval_result.get("provider_used", ""),
        "signal":          interval_result.get("signal", "HOLD"),
        "confidence":      interval_result.get("confidence", 0.0),
        "rationale":       interval_result.get("rationale", interval_result.get("reasoning", "")),
        "entry_price":     interval_result.get("entry_price"),   # THB/gram
        "stop_loss":       interval_result.get("stop_loss"),
        "take_profit":     interval_result.get("take_profit"),
        "trace_json":      interval_result.get("trace", []),
        "token_input":     interval_result.get("token_input"),
        "token_output":    interval_result.get("token_output"),
        "token_total":     interval_result.get("token_total"),
        "elapsed_ms":      interval_result.get("elapsed_ms"),
        "iterations_used": interval_result.get("iterations_used", 0),
        "tool_calls_used": interval_result.get("tool_calls_used", 0),
        "is_fallback":     is_fallback,
        "fallback_from":   fallback_from,
        # จะมีข้อมูลเมื่อ react.py expose ออกมา
        "full_prompt":     interval_result.get("full_prompt"),
        "full_response":   interval_result.get("full_response"),
    }


# ─────────────────────────────────────────────
# Portfolio Service
# ─────────────────────────────────────────────


class PortfolioService:
    """Portfolio CRUD operations and validation"""

    def __init__(self, db):
        self.db = db
        sys_logger.info("PortfolioService initialized")

    def save_portfolio(
        self,
        cash: float,
        gold_grams: float,
        cost_basis: float,
        current_value: float,
        pnl: float,
        trades_today: int,
    ) -> Dict:
        try:
            portfolio_data = {
                "cash_balance":      float(cash),
                "gold_grams":        float(gold_grams),
                "cost_basis_thb":    float(cost_basis),
                "current_value_thb": float(current_value),
                "unrealized_pnl":    float(pnl),
                "trades_today":      int(trades_today),
                "updated_at":        datetime.now(timezone.utc).isoformat(),
            }

            is_valid, error_msg = validate_portfolio_update(None, portfolio_data)
            if not is_valid:
                return {
                    "status":  "error",
                    "message": f"Validation failed: {error_msg}",
                    "error":   error_msg,
                }

            self.db.save_portfolio(portfolio_data)
            sys_logger.info(
                f"Portfolio saved: cash=฿{cash}, gold={gold_grams}g, pnl=฿{pnl}"
            )

            return {
                "status":  "success",
                "message": "✅ Portfolio saved successfully",
                "data":    portfolio_data,
            }

        except Exception as e:
            sys_logger.error(f"Error saving portfolio: {type(e).__name__}: {e}")
            return {
                "status":  "error",
                "message": f"Failed to save: {e}",
                "error":   str(e),
            }

    def load_portfolio(self) -> Dict:
        try:
            portfolio = self.db.get_portfolio()
            if not portfolio:
                portfolio = DEFAULT_PORTFOLIO.copy()
                sys_logger.info("Portfolio loaded from defaults (DB was empty)")
            else:
                sys_logger.info(
                    f"Portfolio loaded: cash=฿{portfolio.get('cash_balance', 0)}, "
                    f"gold={portfolio.get('gold_grams', 0)}g"
                )
            return {"status": "success", "data": portfolio}

        except Exception as e:
            sys_logger.error(f"Error loading portfolio: {type(e).__name__}: {e}")
            return {
                "status": "error",
                "data":   DEFAULT_PORTFOLIO.copy(),
                "error":  str(e),
            }


# ─────────────────────────────────────────────
# History Service
# ─────────────────────────────────────────────


class HistoryService:
    """Run history, statistics, and LLM log retrieval"""

    def __init__(self, db):
        self.db = db
        sys_logger.info("HistoryService initialized")

    def get_recent_runs(self, limit: int = 50) -> List[Dict]:
        try:
            runs = self.db.get_recent_runs(limit=limit)
            sys_logger.info(f"Fetched {len(runs)} recent runs")
            return runs
        except Exception as e:
            sys_logger.error(f"Error fetching history: {type(e).__name__}: {e}")
            return []

    def get_statistics(self) -> Dict:
        try:
            stats = self.db.get_signal_stats()
            sys_logger.info(
                f"Stats: total={stats.get('total')}, "
                f"buy={stats.get('buy_count')}, sell={stats.get('sell_count')}"
            )
            return stats
        except Exception as e:
            sys_logger.error(f"Error computing stats: {type(e).__name__}: {e}")
            return {
                "total": 0, "buy_count": 0, "sell_count": 0,
                "hold_count": 0, "avg_confidence": 0.0, "avg_price": 0.0,
            }

    def get_run_detail(self, run_id: int) -> Dict:
        try:
            if hasattr(self.db, "get_run_by_id"):
                run = self.db.get_run_by_id(run_id)
            else:
                recent = self.db.get_recent_runs(limit=1000)
                run = next((r for r in recent if r.get("id") == run_id), None)

            if not run:
                sys_logger.warning(f"Run {run_id} not found")
                return {"status": "error", "message": f"Run #{run_id} not found"}

            sys_logger.info(f"Loaded run detail: #{run_id}")
            return {"status": "success", "data": run}

        except Exception as e:
            sys_logger.error(f"Error loading run detail: {type(e).__name__}: {e}")
            return {"status": "error", "message": str(e)}

    def get_llm_logs(self, run_id: int) -> List[Dict]:
        """ดึง LLM thinking logs ของ run_id หนึ่งๆ"""
        try:
            logs = self.db.get_llm_logs_for_run(run_id)
            sys_logger.info(f"Fetched {len(logs)} llm_logs for run_id={run_id}")
            return logs
        except Exception as e:
            sys_logger.error(f"Error fetching llm_logs: {type(e).__name__}: {e}")
            return []

    def get_recent_llm_logs(self, limit: int = 20) -> List[Dict]:
        """ดึง LLM thinking logs ล่าสุด (ข้ามรอบ)"""
        try:
            logs = self.db.get_recent_llm_logs(limit=limit)
            sys_logger.info(f"Fetched {len(logs)} recent llm_logs")
            return logs
        except Exception as e:
            sys_logger.error(f"Error fetching recent llm_logs: {type(e).__name__}: {e}")
            return []
    
    def get_llm_logs_for_run(self, run_id: int) -> list:
        return self.db.get_llm_logs_for_run(run_id)


# ─────────────────────────────────────────────
# Service Initialization
# ─────────────────────────────────────────────


def init_services(skill_registry, role_registry, data_orchestrator, db):
    """Initialize all services with dependency injection"""
 
    # สร้าง notifier instances
    discord_notifier = DiscordNotifier()
    sys_logger.info(
        f"DiscordNotifier initialized — "
        f"enabled={discord_notifier.enabled}, "
        f"notify_hold={discord_notifier.notify_hold}, "
        f"webhook_set={bool(discord_notifier.webhook_url)}"
    )

    telegram_notifier = TelegramNotifier()
    sys_logger.info(
        f"TelegramNotifier initialized — "
        f"enabled={telegram_notifier.enabled}, "
        f"token_set={bool(telegram_notifier.token)}"
    )
 
    analysis_service = AnalysisService(
        skill_registry    = skill_registry,
        role_registry     = role_registry,
        data_orchestrator = data_orchestrator,
        persistence       = db,
        discord_notifier  = discord_notifier,    # ← INJECT DISCORD
        telegram_notifier = telegram_notifier,   # ← INJECT TELEGRAM
    )
    portfolio_service = PortfolioService(db)
    history_service   = HistoryService(db)
 
    sys_logger.info("All services initialized successfully")
 
    return {
        "analysis":  analysis_service,
        "portfolio": portfolio_service,
        "history":   history_service,
        "discord_notifier":  discord_notifier,
        "telegram_notifier": telegram_notifier,
    }
