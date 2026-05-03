"""
prompt.py — Part C: Prompt System
Builds PromptPackage objects for the ReAct loop.

[FIX v2.1]
  - build_final_decision() ใช้ system prompt เต็มจาก roles.json
  - _format_market_state() เพิ่ม timestamp ให้ LLM ใช้ตรวจ time-based exit rule

[FIX v2.2]
  - build_thought() เพิ่ม iteration-aware guidance:
      Iteration 1 → บังคับ CALL_TOOL ห้าม FINAL_DECISION
      Iteration 2 → แนะนำ tool เพิ่มหรือตัดสินใจได้
      Iteration 3+ → บังคับ FINAL_DECISION ทันที
  - ลบ OUTPUT FORMAT ซ้ำออกจาก user prompt (ให้ system prompt จัดการ)

[FIX v2.5]
  - แก้ NameError: TZ_BKK → self.TZ_BKK ใน _parse_to_bkk_minutes()
  - ลบ PnL hardcode thresholds ออกจาก _format_market_state()
      → pnl_status อ่านจาก portfolio["risk_status"] ที่ risk.py inject มา
      → PromptBuilder ไม่มี TP/SL constants ใดๆ อีกต่อไป
  - sync MIN_BUY_CASH = 1000 (no fee)
  - can_buy logic แยก case: insufficient cash vs already holding
  - build_final_decision: position_size_thb 1000 

[P10 — Async Tool Execution / Parallel Tool Calls]
  - build_thought() เพิ่ม action "CALL_TOOLS" (plural) ใน action_guidance ทุก iteration
      iteration 1 → แนะนำ CALL_TOOLS เป็น preferred path (เรียก 2 tool พร้อมกันได้)
                    ยังคง CALL_TOOL (single) ไว้เป็น fallback format
      iteration 2 → เพิ่ม option C: CALL_TOOLS ถ้ายังต้องการ tool เพิ่มหลายตัว
      iteration 3+ → บังคับ FINAL_DECISION เหมือนเดิม (ไม่เพิ่ม CALL_TOOLS)
  - format CALL_TOOLS: {"action": "CALL_TOOLS", "thought": "...", "tools": [...]}

[XGB — XGBoost Signal Integration]
  - _format_market_state() เพิ่ม XGBoost Pre-Analysis block
      → อ่านจาก market_state["xgb_signal"] (string จาก SignalAggregator)
      → ส่งทุก iteration (ราคาไม่เปลี่ยน แต่ signal สำคัญ)
      → ถ้าไม่มี key นี้ → ไม่แสดงอะไร (backward compatible)
  - วิธี inject:
      market_state["xgb_signal"] = aggregator.aggregate_to_prompt(xgb_out, news_sig)
"""

import json
from enum import Enum
from typing import Optional
from dataclasses import dataclass
import textwrap
from datetime import datetime, timezone, timedelta

from data_engine.tools.tool_registry import list_tools
# ─────────────────────────────────────────────
# Core data transfer object
# ─────────────────────────────────────────────


@dataclass
class PromptPackage:
    """Container ที่ส่งระหว่าง PromptBuilder → LLMClient"""

    system: str
    user: str
    step_label: str = "THOUGHT"
    thinking_mode: Optional[str] = None


# ─────────────────────────────────────────────
# Role enum
# ─────────────────────────────────────────────


class AIRole(Enum):
    ANALYST             = "analyst"
    AGGRESSIVE_BULLISH  = "aggressive_bullish"   # [MTF] Uptrend — Trend Following Scalper
    RANGE_BOUND_SNIPER  = "range_bound_sniper"   # [MTF] Sideways — Mean Reversion Sniper
    DEFENSIVE_SCAVENGER = "defensive_scavenger"  # [MTF] Downtrend — Capital Preservation


# ─────────────────────────────────────────────
# Skill
# ─────────────────────────────────────────────


@dataclass
class Skill:
    name: str
    description: str
    tools: list
    constraints: Optional[dict] = None

    def to_prompt_text(self) -> str:
        tools_str = ", ".join(self.tools) if self.tools else "none"
        return f"- {self.name}: {self.description}\n  Tools: {tools_str}"


class SkillRegistry:
    def __init__(self):
        self.skills: dict = {}

    def register(self, skill: Skill) -> None:
        self.skills[skill.name] = skill

    def get(self, name: str) -> Optional[Skill]:
        return self.skills.get(name)

    def get_tools_for_skills(self, skill_names: list) -> list:
        tools = set()
        for name in skill_names:
            skill = self.get(name)
            if skill:
                tools.update(skill.tools)
        return sorted(tools)

    def load_from_json(self, filepath: str) -> None:
        with open(filepath, 'r', encoding="utf-8") as f:
            data = json.load(f)
        for sd in data.get("skills", []):
            self.register(
                Skill(
                    name=sd["name"],
                    description=sd["description"],
                    tools=sd.get("tools", []),
                    constraints=sd.get("constraints"),
                )
            )


# ─────────────────────────────────────────────
# Role
# ─────────────────────────────────────────────


@dataclass
class RoleDefinition:
    name: AIRole
    title: str
    system_prompt_template: str          # legacy / fallback (single string)
    available_skills: list
    confidence_threshold: float = 0.58
    max_position_thb: int = 1000
    system_prompt_static: str = ""       # cacheable — rules, conditions, format
    system_prompt_dynamic_template: str = ""  # injected per-call — market context

    def get_system_prompt(self, context: dict) -> str:
        """Fix v2.6: ดึงจาก system_prompt_static ก่อน ถ้าไม่มีค่อย fallback"""
        base_prompt = self.system_prompt_static or self.system_prompt_template
        for key, value in context.items():
            base_prompt = base_prompt.replace(f"{{{key}}}", str(value))
        return base_prompt

    def render_dynamic(self, directive: str, session_gate: dict, market_state: dict) -> str:
        """Render dynamic context block สำหรับ build_messages()"""
        tpl = self.system_prompt_dynamic_template
        if not tpl:
            return ""
        return tpl.format(
            directive=directive or "NONE",
            session_gate=session_gate or {},
            market_state=market_state,
        )


class RoleRegistry:
    def __init__(self, skill_registry: SkillRegistry):
        self.roles: dict = {}
        self.skills = skill_registry

    def register(self, role_def: RoleDefinition) -> None:
        self.roles[role_def.name] = role_def

    def get(self, role: AIRole) -> Optional[RoleDefinition]:
        return self.roles.get(role)

    def load_from_json(self, filepath: str) -> None:
        with open(filepath, 'r', encoding="utf-8") as f:
            data = json.load(f)
        for rd in data.get("roles", []):
            role_enum = AIRole(rd["name"])
            # รองรับทั้ง format เก่า (system_prompt) และใหม่ (system_prompt_static)
            legacy_prompt = rd.get("system_prompt_template", rd.get("system_prompt", ""))
            self.register(
                RoleDefinition(
                    name=role_enum,
                    title=rd["title"],
                    system_prompt_template=legacy_prompt,
                    available_skills=rd["available_skills"],
                    confidence_threshold=rd.get("confidence_threshold", 0.58),
                    max_position_thb=rd.get("max_position_thb", 1000),
                    system_prompt_static=rd.get("system_prompt_static", legacy_prompt),
                    system_prompt_dynamic_template=rd.get("system_prompt_dynamic_template", ""),
                )
            )


# ─────────────────────────────────────────────
# PromptBuilder
# ─────────────────────────────────────────────


class PromptBuilder:
    """
    สร้าง PromptPackage สำหรับแต่ละ step ของ ReAct loop
    """

    def __init__(self, role_registry, current_role):
        self.roles = role_registry
        self.role = current_role
        self._cached_system: str | None = None
        self._cached_tools: list | None = None
        self.confidence_threshold = role_registry.get(current_role).confidence_threshold
        
    def _get_system(self) -> str:
        if self._cached_system is None:
            role_def = self._require_role()
            self._cached_system = (
                role_def.system_prompt_static
                or role_def.system_prompt_template
            )
        return self._cached_system
    
    def _get_tools(self) -> list:
        if self._cached_tools is None:
            role_def = self._require_role()
            self._cached_tools = self.roles.skills.get_tools_for_skills(
                role_def.available_skills
            )
        return self._cached_tools or []

    def build_messages(
        self,
        market_state: dict,
        history: list,
    ) -> list:
        """
        Fix v2.6: สร้าง payload แบบ List of Dicts เพื่อให้เข้ากับ OpenRouter / OpenAI Format 100%
        """
        role_def = self._require_role()
        max_pos = int(role_def.max_position_thb or 1000)

        static_text = role_def.system_prompt_static or role_def.system_prompt_template
        directive = market_state.get("backtest_directive", "")
        emergency_directive = self._build_emergency_directive(
            market_state.get("session_gate")
        )
        if emergency_directive:
            directive = (
                f"{directive}\n\nEMERGENCY SESSION DIRECTIVE\n{emergency_directive}"
            ).strip()
        dynamic_text = role_def.render_dynamic(
            directive=directive,
            session_gate=market_state.get("session_gate"),
            market_state={k: v for k, v in market_state.items()
                          if k not in ("backtest_directive", "session_gate")},
        )

        system_content = static_text + ("\n\n" + dynamic_text if dynamic_text else "")
        
        # คืนค่าเป็น List ที่มี role: system อยู่ด้านบนสุด
        return [{"role": "system", "content": system_content}] + history

    # ── public ──────────────────────────────────

    def build_thought(
        self,
        market_state: dict,
        tool_results: list,
        iteration: int,
    ) -> PromptPackage:
        role_def = self._require_role()
        tools_list = self._get_tools()
        system = self._get_system()
        
        has_pre_fetched = bool(market_state.get("pre_fetched_tools"))

        if iteration == 1 and has_pre_fetched:
            # 🚀 [FAST TRACK MODE] ถ้ามีข้อมูล Pre-fetch สั่งให้ออกออเดอร์ทันที (Single-Shot)
            action_guidance = textwrap.dedent(f"""
                ## YOUR TASK: FAST-TRACK FINAL_DECISION
                The backend has pre-fetched core tools. Review them in 'PRE-FETCHED TOOL RESULTS'.
                If data is sufficient, output FINAL_DECISION now using the TRIPLE-SCENARIO format.
                
                ── Option A (FAST TRACK): Final Decision ──
                {{
                  "action": "FINAL_DECISION",
                  "agent_reasoning": {{
                    "1_data_grounding": "...",
                    "2_market_hypothesis": "...",
                    "3_logical_constraints": "...",
                    "4_edge_gatekeeper": "...",
                    "5_weight_calibration": "..."
                  }},
                  "analysis": {{ "bull_case": "...", "bear_case": "...", "neutral_case": "..." }},
                  "execution_check": {{ "is_spread_covered": true|false, "is_profitable_to_sell": true|false|null }},
                  "signal": "BUY" | "SELL" | "HOLD",
                  "confidence": 0.0-1.0,
                  "position_size_thb": {max_pos} or null,
                  "rationale": "<Synthesis of Bull vs Bear. Max 30 words>"
                }}

                ── Option B (Fallback): Call Additional Tools ──
                {{
                  "action": "CALL_TOOLS",
                  "thought": "<why you need MORE tools>",
                  "tools": [{{"tool_name": "...", "tool_args": {{}}}}]
                }}
                
                CRITICAL: If signal is BUY, position_size_thb MUST be {max_pos}. If confidence < {self.confidence_threshold}, MUST be HOLD.
            """).strip()
        elif iteration == 1:
            action_guidance = (
                "## ITERATION 1 — Preferred: CALL_TOOLS (max 2 core tools, only if critical missing data).\n"
                "If market_state + prefetch are sufficient, you may output FINAL_DECISION."
            )
        elif iteration == 2:
            action_guidance = (
                "## ITERATION 2 — Choose: FINAL_DECISION (if enough data) or CALL_TOOLS (max 2, if critical gap)."
            )
        else:
            action_guidance = (
                f"## FINAL_DECISION mandatory – Triple scenario (bull/bear/neutral) then decision.\n"
                f"HOLD only if confidence<{self.confidence_threshold} or <2 conditions met."
            )

        if self._build_emergency_directive(market_state.get("session_gate")):
            action_guidance = (
                f"{action_guidance}\n\n"
                "EMERGENCY OVERRIDE: Follow the EMERGENCY SESSION DIRECTIVE in MARKET STATE "
                "before normal confidence, edge, or role preferences."
            )
        
        if iteration == 1 and not has_pre_fetched:
            tools_section = self._format_available_tools(verbose=True)
        else:
            tool_names_list = self._get_tools()
            _TOOL_NAMES = ", ".join(tool_names_list) if tool_names_list else "none"
            tools_section = f"### AVAILABLE TOOLS (names only)\n{_TOOL_NAMES}"

        user = textwrap.dedent(f"""
            ## Iteration {iteration}

            {tools_section}

            ### MARKET STATE
            {self._format_market_state(market_state, iteration=iteration)}

            ### PREVIOUS TOOL RESULTS
            {self._format_tool_results(tool_results)}

            {action_guidance}
        """).strip()
        
        return PromptPackage(
            system=system, user=user, step_label=f"THOUGHT_{iteration}", thinking_mode=None
        )

    def build_final_decision(
        self,
        market_state: dict,
        tool_results: list,
    ) -> PromptPackage:
        role_def = self._require_role()
        max_pos = int(role_def.max_position_thb or 1000)
        system = self._get_system()
        emergency_rule = ""
        if self._build_emergency_directive(market_state.get("session_gate")):
            emergency_rule = (
                "0. EMERGENCY OVERRIDE: Follow the EMERGENCY SESSION DIRECTIVE in MARKET STATE "
                "before normal confidence, edge, or role preferences.\n"
            )

        user = textwrap.dedent(f"""
            ### MARKET STATE
            {self._format_market_state(market_state)}

            ### ANALYSIS SO FAR
            {self._format_tool_results(tool_results)}

            ## FINAL VERDICT REQUIRED
            You must follow the strict reasoning framework before deciding. Inhibit your final signal until reasoning is fully written.

            {{
              "action": "FINAL_DECISION",
              "agent_reasoning": {{
                "1_data_grounding": "...",
                "2_market_hypothesis": "...",
                "3_logical_constraints": "...",
                "4_edge_gatekeeper": "...",
                "5_weight_calibration": "..."
              }},
              "analysis": {{ "bull_case": "...", "bear_case": "...", "neutral_case": "..." }},
              "execution_check": {{ "is_spread_covered": bool, "is_profitable_to_sell": bool }},
              "signal": "BUY" | "SELL" | "HOLD",
              "confidence": 0.0-1.0,
              "position_size_thb": {max_pos},
              "rationale": "..."
            }}

            CRITICAL RULES:
            {emergency_rule}
            1. If signal is BUY, position_size_thb MUST be {max_pos}.
            2. Default to HOLD ONLY if: (a) confidence < {self.confidence_threshold}, OR
               (b) fewer than 2 BUY/SELL conditions are met.
               A bearish intermarket signal alone is NOT sufficient to override
               a bullish technical setup with 3+ conditions met.
            3. Output ONLY valid JSON.
        """).strip()

        return PromptPackage(system=system, user=user, step_label="THOUGHT_FINAL")

    # ── private ─────────────────────────────────

    def _require_role(self) -> RoleDefinition:
        role_def = self.roles.get(self.role)
        if not role_def:
            raise ValueError(f"Role '{self.role}' not registered")
        return role_def

    @staticmethod
    def _build_emergency_directive(session_gate: dict | None) -> str:
        if not session_gate or not session_gate.get("apply_gate"):
            return ""

        mins_left = session_gate.get("minutes_to_session_end")
        if session_gate.get("is_emergency_sell"):
            return (
                f"URGENT: Session ends in {mins_left} mins. "
                "SELL ALL gold immediately. Profit/Loss is irrelevant. "
                "Market exit is mandatory."
            )
        if session_gate.get("is_emergency_buy"):
            return (
                f"URGENT: Session ends in {mins_left} mins. "
                "Zero trades completed. RELAX all technical gates. "
                "Find any reasonable support or momentum to ENTER now."
            )
        return ""

    def _format_available_tools(self, verbose: bool = False) -> str:
        """
        แสดงเฉพาะ tools ที่ role ปัจจุบันอนุญาต เพื่อลดการเรียก tool นอก policy
        """
        allowed = set(self._get_tools())
        if not allowed:
            return "### AVAILABLE TOOLS\n(none)"

        if not verbose:
            names = ", ".join(sorted(allowed))
            return f"### AVAILABLE TOOLS (names only)\n{names}"

        meta = {t.get("name"): t for t in list_tools()}
        lines = ["### AVAILABLE TOOLS"]
        for i, name in enumerate(sorted(allowed), start=1):
            desc = (meta.get(name, {}).get("description") or "").strip()
            if desc:
                lines.append(f"{i}. {name}: {desc}")
            else:
                lines.append(f"{i}. {name}")
        return "\n".join(lines)

    def _format_market_state(self, state: dict, iteration: int = 1) -> str:
        """Format market state for LLM — dynamically slims down in later iterations"""
        md   = state.get("market_data", {})
        ti   = state.get("technical_indicators", {})
        news_data = state.get("news", {})

        spot    = md.get("spot_price_usd", {}).get("price_usd_per_oz", "N/A")
        usd_thb = md.get("forex", {}).get("usd_thb", "N/A")
        thai    = md.get("thai_gold_thb", {})
        spread_cov = md.get("spread_coverage", {})
        sell_thb = thai.get("sell_price_thb", "N/A")
        buy_thb  = thai.get("buy_price_thb", "N/A")

        rsi   = ti.get("rsi", {})
        macd  = ti.get("macd", {})
        trend = ti.get("trend", {})
        bb    = ti.get("bollinger", {})
        atr   = ti.get("atr", {})

        timestamp_str = state.get("timestamp") or md.get("spot_price_usd", {}).get("timestamp", "")
        interval      = state.get("interval", "15m")

        time_part = ""
        if timestamp_str and timestamp_str != "N/A":
            try:
                if "T" in timestamp_str:
                    time_part = timestamp_str.split("T")[1][:5]
                else:
                    time_part = timestamp_str.split(" ")[1][:5]
            except Exception:
                time_part = str(timestamp_str)

        dead_zone_warning = ""
        if time_part:
            try:
                minutes = self._parse_to_bkk_minutes(timestamp_str)
                if minutes is not None:
                    if 90 <= minutes <= 119:
                        dead_zone_warning = "\n*** WARNING: Time 01:30–01:59 — Market closes at 02:00. SL3: SELL if holding gold! ***"
            except Exception:
                pass

        # ── 1. แกนหลัก (ส่งทุกรอบเพราะต้องใช้อ้างอิงราคา Real-time) ──
        lines =[
            f"Time: {timestamp_str} ({time_part}) | Int: {interval}{dead_zone_warning}",
            f"Gold: ${spot}/oz | USD/THB: {usd_thb} | THB/g: ฿{sell_thb} sell / ฿{buy_thb} buy",
            f"Spread: {spread_cov.get('spread_thb', 'N/A')} THB | Expected Move: {spread_cov.get('expected_move_thb', 'N/A')} THB | edge_score: {spread_cov.get('edge_score', 'N/A')}",
            f"RSI({rsi.get('period', 14)}): {rsi.get('value', 'N/A')} | MACD: {macd.get('macd_line', 'N/A')}/{macd.get('signal_line', 'N/A')} hist:{macd.get('histogram', 'N/A')}",
            f"Trend: EMA20={trend.get('ema_20', 'N/A')} EMA50={trend.get('ema_50', 'N/A')}[{trend.get('trend', 'N/A')}]",
            f"BB: up={bb.get('upper', 'N/A')} low={bb.get('lower', 'N/A')} | Close: ${ti.get('latest_close', 'N/A')} | ATR: {atr.get('value', 'N/A')} THB",
        ]

        emergency_directive = self._build_emergency_directive(state.get("session_gate"))
        if emergency_directive:
            lines += [
                "",
                "!!! EMERGENCY SESSION DIRECTIVE !!!",
                emergency_directive,
                "!!! END EMERGENCY SESSION DIRECTIVE !!!",
            ]

        # ── [MTF Phase 3] Market Regime Analysis (15m/30m) ──
        regime = state.get("market_regime", "UNKNOWN")
        trend_analysis = state.get("trend_analysis", {})

        _REGIME_INSTRUCTIONS = {
            "UPTREND": (
                "UPTREND \U0001f4c8 | Role: Aggressive Bullish Scalper\n"
                "  Strategy: Trend Following — Buy the momentum.\n"
                "  Entry BUY: On any pullback to RSI 40-50 or MACD hook-up. Also enter on strong momentum breakouts (RSI > 60 + expanding MACD hist).\n"
                "  Exit SELL: Let profits run. Use wider Trailing Stop. Consider holding until RSI > 75 or momentum clearly fades.\n"
                "  Confidence: Lower threshold — prioritize capturing the trend over perfection."
            ),
            "SIDEWAYS": (
                "SIDEWAYS \u27a1\ufe0f | Role: Range-Bound Sniper\n"
                "  Strategy: Mean Reversion — Buy low, sell median.\n"
                "  Entry BUY: ONLY at extreme lower boundary (Lower Bollinger Band) with RSI < 35 and a clear reversal hook.\n"
                "  Exit SELL: Take profit IMMEDIATELY at the midline (BB Middle). Do NOT hold expecting a breakout.\n"
                "  Confidence: Normal threshold — precision of entry matters most."
            ),
            "DOWNTREND": (
                "DOWNTREND \U0001f4c9 | Role: Defensive Scavenger\n"
                "  Strategy: Counter-Trend Rebound Only — Highest risk. Be very selective.\n"
                "  Entry BUY: ONLY on extreme capitulation: RSI < 25 OR clear Bullish Divergence on 15m.\n"
                "  Exit SELL: Take ANY small profit immediately. Do NOT hold. Cut losses without hesitation.\n"
                "  Confidence: Highest threshold required — capital preservation is priority #1."
            ),
            "UNKNOWN": (
                "UNKNOWN ❓ | Insufficient MTF data — apply default analyst rules.\n"
                "  Treat as SIDEWAYS and require normal confidence threshold."
            ),
        }

        regime_instruction = _REGIME_INSTRUCTIONS.get(regime, _REGIME_INSTRUCTIONS["UNKNOWN"])

        lines += ["", "── MARKET REGIME (15m/30m MTF Analysis) ──"]
        # แสดงรายละเอียด EMA ถ้ามี
        for tf, tf_data in trend_analysis.items():
            if isinstance(tf_data, dict):
                lines.append(
                    f"  {tf}: EMA20={tf_data.get('ema_20', 'N/A')} EMA50={tf_data.get('ema_50', 'N/A')} → {str(tf_data.get('status', 'N/A')).upper()}"
                )
        lines += [
            f"  ► Detected Regime: {regime}",
            f"  ► {regime_instruction}",
            "────────────────────────────────────────",
        ]

        # # ── [NEW] Dynamic Session Weights ──
        # dyn_weights = state.get("dynamic_weights")
        # if dyn_weights:
        #     lines +=[
        #         "",
        #         "── Dynamic Session Weights ──",
        #         f"Session: {dyn_weights.get('session')} (XGB: {dyn_weights.get('xgb_w')}, News: {dyn_weights.get('news_w')}, Tech: {dyn_weights.get('tech_w')})",
        #         f"Weighted Direction: {dyn_weights.get('direction')}",
        #         f"Base Confidence: {dyn_weights.get('base_confidence')}",
        #         "─────────────────────────────",
        #     ]


        # ── [XGB] XGBoost Pre-Analysis ──────────────────────────────────────
        # inject ก่อนส่งเข้า run():
        #   market_state["xgb_signal"] = aggregator.aggregate_to_prompt(xgb_out, news_sig)
        # backward compatible — ถ้าไม่มี key นี้ block นี้จะไม่แสดง
        # xgb_signal = state.get("xgb_signal")
        # if xgb_signal:
        #     lines += [
        #         "",
        #         "── XGBoost Pre-Analysis ──",
        #         *[f"  {ln}" for ln in xgb_signal.splitlines()],
        #         "── End XGBoost ──",
        #     ]
        # # ────────────────────────────────────────────────────────────────────

        portfolio = state.get("portfolio", {})
        quota = state.get("execution_quota", {})
        if quota:
            lines += [
                "",
                "── Daily Entry Quota ──",
                f"  Target entries/day: {quota.get('daily_target_entries', 3)}",
                f"  Entries done:       {quota.get('entries_done', 0)}",
                f"  Entries remaining:  {quota.get('entries_remaining', 0)}",
                f"  Quota met:          {quota.get('quota_met', False)}",
                f"  Current slot:       {quota.get('current_slot', 'N/A')} / 3",
                f"  Min entries by now: {quota.get('min_entries_by_now', 'N/A')}",
                f"  Next BUY min conf:  {quota.get('required_confidence_for_next_buy', 'N/A')}",
                f"  Next BUY size:      {quota.get('recommended_next_position_thb', 'N/A')} THB",
                "  Rule: prioritize capital safety first; if no valid edge, HOLD is allowed.",
                "── End Daily Entry Quota ──",
            ]

        if portfolio:
            cash      = portfolio.get("cash_balance", 0.0)
            gold_g    = portfolio.get("gold_grams", 0.0)
            pnl       = portfolio.get("unrealized_pnl", 0.0)
            trades_td = portfolio.get("trades_today", 0)
            cost      = portfolio.get("cost_basis_thb", 0.0)
            cur_val   = portfolio.get("current_value_thb", 0.0)

            MIN_BUY_CASH = 1000
            can_buy = (
                "YES" if (cash >= MIN_BUY_CASH and gold_g == 0)
                else f"NO — insufficient cash (฿{cash:.0f} < ฿{MIN_BUY_CASH})" if cash < MIN_BUY_CASH
                else "NO — already holding gold"
            )
            can_sell = f"YES ({gold_g:.4f}g held)" if gold_g > 0 else "NO — no gold held (short selling not supported)"

            pnl_status = portfolio.get("risk_status", "")
            pnl_tag = f"  ← {pnl_status} (You MUST NOT SELL if this is negative, unless SL is hit)" if pnl < 0 else "  ← PROFITABLE (Ready to SELL if momentum drops)"

            lines += [
                "",
                "── Portfolio ──",
                f"  Cash:           ฿{cash:,.2f}",
                f"  Gold:           {gold_g:.4f} g",
                f"  Cost basis:     ฿{cost:,.2f}",
                f"  Current value:  ฿{cur_val:,.2f}",
                f"  Unrealized PnL: ฿{pnl:,.2f}{pnl_tag}",
                f"  Trades today:   {trades_td}",
                f"  can_buy:  {can_buy}",
                f"  can_sell: {can_sell}",
                "── End Portfolio ──",
            ]
            
            
        recent_trades = state.get("recent_trades", [])
        
        print(f"DEBUG: Processing {len(recent_trades)} recent trades in PromptBuilder")
        
        
        if recent_trades:
            lines += ["", "── RECENT TRADE MEMORY (LEARN FROM MISTAKES) ──"]
            for t in recent_trades[-3:]:
                lines.append(f"  • {t.get('time')} | {t.get('action')} | Result: {t.get('status')} ({t.get('pnl_thb')} THB) | Reason: {t.get('reason')}")
            
            lines.append("  [CRITICAL RULE]: Review the memory. If the last trade was a LOSS, DO NOT use the exact same logic/setup again unless the market regime has clearly reversed.")
            lines.append("── End Trade Memory ──")

        directive = state.get("backtest_directive", "")
        if directive:
            lines += ["", "── DIRECTIVE ──", directive, "── End DIRECTIVE ──"]

        portfolio = state.get("portfolio", {})
        tp_price = portfolio.get("take_profit_price")
        sl_price = portfolio.get("stop_loss_price")
        # แก้ไขเป็นบล็อกป้องกัน Error:
        raw_gold = portfolio.get("gold_grams", 0.0)
        try:
            gold_g = float(raw_gold)
        except (ValueError, TypeError):
            gold_g = 0.0  # ถ้าแปลงเลขไม่ได้ ให้เซ็ตเป็น 0 ไว้ก่อน
        if gold_g > 0 and (tp_price or sl_price):
            lines += [
                "",
                f"── Active Position: {gold_g:.4f}g held ──",
                f"  TP={tp_price} / SL={sl_price} (system will auto-SELL when hit — do NOT pre-empt unless technical signal warrants early exit)",
                "──────────────────────────────────────",
            ]

        # ── 2. ส่วนเสริม (ส่งเฉพาะ Iteration 1 เพื่อประหยัด Token) ──
        if iteration == 1:
            lines.append("News Highlights:")
            latest_news = news_data.get("latest_news", [])
            news_count  = news_data.get("news_count", 0)
            if latest_news:
                for item in latest_news:
                    lines.append(f"  {item}")
                lines.append("  [INFO] News data is slimmed. Call 'get_deep_news_by_category' for deep-dive sentiment and details.")
            elif news_count == 0:
                lines.append("  [INFO] No significant macro news available. Focus entirely on technical setups.")

            sg = state.get("session_gate")
            if sg and sg.get("apply_gate"):
                notes = [f"  • {n}" for n in (sg.get("notes") or [])]
                context_instruction = (
                    "Emergency directive overrides normal market-evidence preferences."
                    if sg.get("emergency_mode")
                    else "Use as context only; do not override market evidence."
                )
                lines += [
                    "",
                    "── Session Context ──",
                    f"session: {sg.get('session_id')}",
                    f"mins_left: {sg.get('minutes_to_session_end')}",
                    f"mode: {sg.get('llm_mode')}",
                    f"emergency_mode: {sg.get('emergency_mode')}",
                    context_instruction,
                    *notes,
                    "── End Session Context ──",
                ]

            price_trend = md.get("price_trend", {})
            if price_trend:
                lines += [
                    "",
                    "── Price Trend ──",
                    f"  Current: ${price_trend.get('current_close_usd', 'N/A')} | Prev: ${price_trend.get('prev_close_usd', 'N/A')}",
                    f"  Daily chg: {price_trend.get('daily_change_pct', 'N/A')}%",
                ]
                if "5d_change_pct" in price_trend:
                    lines.append(f"  5d chg: {price_trend['5d_change_pct']}%")
                if "10d_change_pct" in price_trend:
                    lines.append(f"  10d chg: {price_trend['10d_change_pct']}%")
                if "10d_high" in price_trend:
                    lines.append(f"  10d range: ${price_trend['10d_low']} — ${price_trend['10d_high']}")
                lines.append("── End Price Trend ──")
                
            pre_fetched = state.get("pre_fetched_tools", {})
            if pre_fetched:
                lines += ["", "── PRE-FETCHED TOOL RESULTS ──"]
                lines.append("The backend has already executed these tools for you. DO NOT call them again unless necessary:")
                for tool_name, result in pre_fetched.items():
                    if isinstance(result, dict) and result.get("status") == "success":
                        data_str = str(result.get("data", result))
                        if len(data_str) > 1000: data_str = data_str[:1000] + "... [truncated]"
                        lines.append(f"  [{tool_name}] {data_str}")
                    else:
                        lines.append(f"  [{tool_name}] {result}")
                lines.append("── End Pre-fetched Tools ──")
        
        # ── 3. ซ่อนข้อมูลยืดเยื้อใน Iteration ถัดไป ──
        else:
            lines = [
                f"Timestamp: {timestamp_str} | Price: ฿{sell_thb} sell / ฿{buy_thb} buy | Close: ${ti.get('latest_close','N/A')}/oz",
            ]
            if directive:
                lines += ["── DIRECTIVE ──", directive, "────────────────"]
            if gold_g > 0 and (tp_price or sl_price):
                lines.append(f"Active position: {gold_g:.4f}g | TP={tp_price} SL={sl_price}")
            # # [XGB] ส่ง signal ซ้ำใน iteration ถัดไปด้วย เพราะ LLM ต้องใช้ใน reasoning
            # if xgb_signal:
            #     lines += [
            #         "── XGBoost Pre-Analysis (carry-forward) ──",
            #         *[f"  {ln}" for ln in xgb_signal.splitlines()],
            #         "── End XGBoost ──",
            #     ]
            lines.append("[Prices refreshed. All other market data unchanged from iteration 1 — use tool results below.]")

        return "\n".join(lines)

    def _format_tool_results(self, results: list) -> str:
        if not results:
            return "(No tool results yet)"
        parts = []
        for r in results:
            if hasattr(r, "tool_name"):
                parts.append(f"[{r.tool_name}] {r.status}: {r.data or r.error}")
            else:
                parts.append(str(r))
        return "\n".join(parts)
    
    TZ_BKK = timezone(timedelta(hours=7))

    def _parse_to_bkk_minutes(self, timestamp_str: str) -> int | None:
        """แปลง timestamp (UTC หรือ UTC+7) → นาทีนับจากเที่ยงคืน Bangkok time"""
        try:
            ts_str = timestamp_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=self.TZ_BKK)
            else:
                dt = dt.astimezone(self.TZ_BKK)
            return dt.hour * 60 + dt.minute
        except Exception:
            return None
