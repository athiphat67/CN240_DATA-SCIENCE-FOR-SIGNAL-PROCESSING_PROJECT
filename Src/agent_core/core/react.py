"""
react.py — Part B: ReAct Orchestration Loop
Thought → Action → Observation → ... → FINAL_DECISION

v2: แก้ไขให้รองรับ LLMResponse จาก client.py
    - บันทึก prompt_text, response_raw, token_input/output/total, model
      ลงใน react_trace ทุก step เพื่อ LLM Log UI

v2.1 (fixes):
    - [FIX #1] extract_json: ตรวจ _parse_error ก่อนส่งเข้า _build_decision — log warning ทุกครั้ง
    - [FIX #2] RiskManager รับผ่าน __init__ (dependency injection) แทน hardcode
    - [FIX #3] _aggregate_trace: แยก token count กับ prompt/response ให้ถูกต้อง
                ใช้ elif "FINAL" เพื่อกัน overwrite ซ้ำ และไม่นับ token จาก FINAL ซ้ำ
    - [FIX #4] extract_json: หา JSON ที่มี key "action" หรือ "signal" ก่อน แทน match แรกที่เจอ

[P2 — Pydantic Output Validation]
    - เพิ่ม _lenient_loads(): รองรับ trailing comma จาก LLM
    - เพิ่ม _extract_json_objects(): balanced-brace scanner รองรับ nested JSON ทุกชั้น
    - เพิ่ม AgentDecision: Pydantic model validate + normalise output
      - clamp confidence 0–1
      - normalise signal uppercase
      - degrade CALL_TOOL-without-tool_name → FINAL_DECISION/HOLD
      - parse_failed flag สำหรับ safe loop control
    - เพิ่ม parse_agent_response(): แทน extract_json()+_build_decision() ทุก call site
    - extract_json() + _check_parse_error() เก็บไว้ (backward compat)

[P10 — Async Tool Execution]
    - เพิ่ม _execute_tools_parallel(): asyncio.gather + to_thread สำหรับ run หลาย tool พร้อมกัน
      - Exception ต่อ tool แปลงเป็น ToolResult(status="error") — ไม่ crash loop
    - AgentDecision เพิ่ม action "CALL_TOOLS" (plural) + field tools: list[dict]
      - model_validator: CALL_TOOLS ที่ไม่มี tools list → degrade → CALL_TOOL (ถ้ามี tool_name) หรือ HOLD
    - run() loop เพิ่ม branch elif action == "CALL_TOOLS":
      - trim tool_requests ตาม remaining budget ก่อน execute
      - asyncio.run() เพื่อ bridge sync→async (safe สำหรับ non-async caller)
      - log observation แต่ละ tool แยก entry ใน react_trace

[P1 — State Readiness Check]
    - เพิ่ม ReadinessConfig: inject required_indicators จากภายนอก (ไม่ hardcode ใน class)
    - ReactConfig เพิ่ม field readiness: ReadinessConfig
    - เพิ่ม StateReadinessChecker: ตรวจ technical_indicators + htf coverage
      - _TI_PRIMARY_KEYS: map indicator → primary value key
      - is_ready() คืน True ถ้าข้อมูลครบ → skip tool loop ประหยัด 1 LLM call
    - ReactOrchestrator.__init__: สร้าง StateReadinessChecker จาก config.readiness
    - run() full loop: เพิ่ม readiness skip block ก่อน while loop
"""

import asyncio
import os
from datetime import datetime 
import json
import logging
import re
import inspect
from typing import Optional
from dataclasses import dataclass, field
from .risk import RiskManager

# ── P2: Pydantic imports ─────────────────────────────────────────
from pydantic import BaseModel, field_validator, model_validator, ValidationError
from typing import Literal

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Config (ต้องอยู่ก่อน ReactState)
# ─────────────────────────────────────────────


# ── [P1] ReadinessConfig — inject ได้จากภายนอก ──────────────────
@dataclass
class ReadinessConfig:
    """
    Config สำหรับ StateReadinessChecker
    Strategy / ReactConfig inject required_indicators มาได้โดยไม่แตะ checker

    Example:
        ReadinessConfig(required_indicators=["rsi", "macd", "trend", "bollinger"])
        ReadinessConfig(require_htf=False)   # ไม่บังคับ htf_trend tool
    """
    required_indicators: list = field(
        default_factory=lambda: ["rsi", "macd", "trend"]
    )
    require_htf: bool = True  # False = ไม่บังคับ htf_trend tool


@dataclass
class ReactConfig:
    """Config สำหรับ ReAct loop"""

    max_iterations: int = 5
    max_tool_calls: int = 10  # 0 = ไม่ใช้ tool (data pre-loaded)
    timeout_seconds: Optional[int] = None  # TODO: enforce at orchestration level
    # [P1] inject ReadinessConfig ผ่าน ReactConfig — Strategy เปลี่ยนได้โดยไม่แตะ checker
    readiness: ReadinessConfig = field(default_factory=ReadinessConfig)


# ─────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────


@dataclass
class ToolResult:
    """Result จากการ execute tool"""

    tool_name: str
    status: str  # "success" | "error"
    data: dict
    error: Optional[str] = None


@dataclass
class ReactState:
    """Mutable state ตลอด loop"""

    market_state: dict
    tool_results: list  # list[ToolResult]
    iteration: int = 0
    tool_call_count: int = 0
    react_trace: list = field(default_factory=list)


# ─────────────────────────────────────────────
# [P2] JSON Extraction Helpers
# ─────────────────────────────────────────────


def _lenient_loads(text: str) -> dict:
    """
    json.loads + strip trailing commas
    รองรับ LLM output ที่ใส่ trailing comma เช่น {"confidence": 0.8,}

    ลำดับ: strict json.loads → strip trailing comma → raise JSONDecodeError
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # strip trailing comma ก่อน } หรือ ]
        cleaned = re.sub(r",\s*([}\]])", r"\1", text)
        return json.loads(cleaned)  # ถ้าพังอีกรอบ ให้ caller จัดการ


def _extract_json_objects(text: str) -> list:
    """
    Balanced-brace scanner — handle nested JSON ทุกชั้น
    แทน regex r"{[^{}]*...}" ที่จำกัดแค่ 1–2 ชั้น

    คืน list[dict] ของทุก JSON object ที่ parse ได้ใน text
    """
    results: list = []
    i = 0
    n = len(text)

    while i < n:
        if text[i] != "{":
            i += 1
            continue

        depth = 0
        in_string = False
        escape_next = False
        start = i

        for j in range(i, n):
            ch = text[j]

            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue

            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start: j + 1]
                    try:
                        obj = _lenient_loads(candidate)
                        if isinstance(obj, dict):
                            results.append(obj)
                    except (json.JSONDecodeError, ValueError):
                        pass
                    i = j + 1
                    break
        else:
            break  # ไม่เจอ closing brace — หยุด scan

    return results


# ─────────────────────────────────────────────
# [P2] AgentDecision — Pydantic model
# ─────────────────────────────────────────────


class AgentDecision(BaseModel):
    """
    Validated LLM output จาก ReAct agent

    Fields:
        action           — "CALL_TOOL" | "CALL_TOOLS" | "FINAL_DECISION"
        signal           — "BUY" | "SELL" | "HOLD" (FINAL_DECISION only)
        confidence       — 0.0–1.0 (clamped)
        tool_name        — ชื่อ tool (CALL_TOOL only)
        tool_args        — args ส่งไปยัง tool (CALL_TOOL only)
        tools            — list[{tool_name, tool_args}] (CALL_TOOLS only) [P10]
        rationale        — เหตุผล (FINAL_DECISION)
        thought          — เหตุผล (CALL_TOOL / CALL_TOOLS / alternative key)
        position_size_thb — ขนาด position (FINAL_DECISION)
        parse_failed     — True ถ้า parse/validation ล้มเหลว (ไม่ได้มาจาก LLM)
    """
    action: Literal["CALL_TOOL", "CALL_TOOLS", "FINAL_DECISION"] = "FINAL_DECISION"
    analysis: Optional[dict] = None
    execution_check: Optional[dict] = None
    signal: Optional[Literal["BUY", "SELL", "HOLD"]] = "HOLD"
    confidence: Optional[float] = 0.0
    tool_name: Optional[str] = None
    tool_args: Optional[dict] = None
    tools: Optional[list] = None          # [P10] list[{tool_name: str, tool_args: dict}]
    rationale: Optional[str] = None
    thought: Optional[str] = None
    position_size_thb: Optional[float] = None
    parse_failed: bool = False  # internal flag — ไม่ได้มาจาก LLM

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, v):
        if v is None:
            return 0.0
        return round(max(0.0, min(1.0, float(v))), 4)

    @field_validator("signal", mode="before")
    @classmethod
    def normalise_signal(cls, v):
        if isinstance(v, str):
            return v.upper()
        return v

    @model_validator(mode="before")
    @classmethod
    def infer_action(cls, values):
        """ถ้า LLM ตอบแค่ signal โดยไม่มี action → infer เป็น FINAL_DECISION"""
        if isinstance(values, dict):
            # normalize alias keys from heterogeneous model outputs
            if "tools_args" in values and "tool_args" not in values:
                values["tool_args"] = values.get("tools_args")
            if "args" in values and "tool_args" not in values:
                values["tool_args"] = values.get("args")

            raw_tools = values.get("tools")
            if isinstance(raw_tools, list):
                fixed = []
                for req in raw_tools:
                    if not isinstance(req, dict):
                        continue
                    req2 = dict(req)
                    if "tools_args" in req2 and "tool_args" not in req2:
                        req2["tool_args"] = req2.get("tools_args")
                    if "args" in req2 and "tool_args" not in req2:
                        req2["tool_args"] = req2.get("args")
                    fixed.append(req2)
                values["tools"] = fixed

            if "action" not in values and "signal" in values:
                values["action"] = "FINAL_DECISION"
        return values

    @model_validator(mode="after")
    def check_action_consistency(self):
        """
        Degrade CALL_TOOL ที่ไม่มี tool_name → FINAL_DECISION/HOLD
        Degrade CALL_TOOLS ที่ไม่มี tools list:
          - มี tool_name fallback → CALL_TOOL
          - ไม่มีอะไรเลย → FINAL_DECISION/HOLD
        เพื่อป้องกัน tool loop ค้างอยู่
        """
        if self.action == "FINAL_DECISION" and self.signal is None:
            self.signal = "HOLD"
        if self.signal == "HOLD" and (self.confidence or 0.0) > 0.64:
            # HOLD confidence เพดานต่ำไว้เพื่อ consistency กับ calibration
            self.confidence = 0.64

        # [P10] CALL_TOOLS degrade
        if self.action == "CALL_TOOLS":
            if not self.tools:
                if self.tool_name:
                    logger.warning(
                        "AgentDecision: CALL_TOOLS without tools list "
                        "but tool_name present — degrading to CALL_TOOL"
                    )
                    self.action = "CALL_TOOL"
                else:
                    logger.warning(
                        "AgentDecision: CALL_TOOLS without tools list — "
                        "degrading to FINAL_DECISION/HOLD"
                    )
                    self.action = "FINAL_DECISION"
                    self.signal = "HOLD"

        if self.action == "CALL_TOOL" and not self.tool_name:
            logger.warning(
                "AgentDecision: CALL_TOOL without tool_name — "
                "degrading to FINAL_DECISION/HOLD"
            )
            self.action = "FINAL_DECISION"
            self.signal = "HOLD"
        return self

    def to_decision_dict(self) -> dict:
        """
        แปลงเป็น dict format ที่ RiskManager.evaluate() คาดหวัง
        แทน _build_decision()
        """
        return {
            "action":      self.action,
            "signal":      self.signal or "HOLD",
            "confidence":  self.confidence or 0.0,
            "position_size_thb": self.position_size_thb,
            "analysis":    self.analysis or {},
            "execution_check": self.execution_check or {},
            "entry_price": None,
            "stop_loss":   None,
            "take_profit": None,
            "rationale":   self.rationale or self.thought or "",
        }


def parse_agent_response(raw: str, context: str = "") -> AgentDecision:
    """
    Parse + validate LLM response → AgentDecision
    แทน extract_json() + _check_parse_error() + _build_decision() ทุก call site

    Fallback chain:
      1. strip markdown fences
      2. balanced-brace scan → candidates[]
      3. เลือก candidate ที่มี "action" / "signal" key ก่อน
      4. Pydantic validate (clamp, normalise, consistency check)
      5. safe HOLD + parse_failed=True ถ้าทุกขั้นล้มเหลว

    ไม่ raise exception — คืน AgentDecision เสมอ
    """
    _SAFE_HOLD = AgentDecision(
        action="FINAL_DECISION",
        signal="HOLD",
        confidence=0.0,
        rationale=f"parse/validation failed [{context}]",
        parse_failed=True,
    )

    if not raw or not raw.strip():
        logger.warning("parse_agent_response [%s]: empty response", context)
        return _SAFE_HOLD

    # strip markdown fences
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())

    candidates = _extract_json_objects(cleaned)

    # เลือก candidate ที่มี "action" หรือ "signal" ก่อน
    best: Optional[dict] = next(
        (c for c in candidates if "action" in c or "signal" in c),
        candidates[0] if candidates else None,
    )

    if best is None:
        logger.warning(
            "parse_agent_response [%s]: no JSON found. raw=%r",
            context, raw[:200],
        )
        return _SAFE_HOLD

    try:
        return AgentDecision(**best)
    except ValidationError as exc:
        logger.warning(
            "parse_agent_response [%s]: ValidationError — %s. raw=%r",
            context, exc, raw[:200],
        )
        return _SAFE_HOLD


# ─────────────────────────────────────────────
# [P2] Legacy helpers — เก็บไว้เพื่อ backward compat
# (ไม่ถูกใช้ใน run() แล้ว แต่ยังมี caller อื่นที่อาจ import)
# ─────────────────────────────────────────────


def extract_json(raw: str) -> dict:
    """
    Parse JSON จาก LLM response อย่างปลอดภัย
    [LEGACY] — ใช้ parse_agent_response() แทนใน run()

    [FIX #4] ลำดับการหา JSON:
      1. หา JSON object ที่มี key "action" หรือ "signal"
      2. fallback: JSON object แรกที่เจอ
      3. fallback: parse ทั้ง string
      4. คืน _parse_error dict พร้อม raw สำหรับ debug
    """
    if not raw or not raw.strip():
        return {"_parse_error": True, "_raw": ""}

    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned.strip())

    candidates = []
    for m in re.finditer(r"\{.*?\}", cleaned, re.DOTALL):
        try:
            obj = json.loads(m.group())
            candidates.append(obj)
        except json.JSONDecodeError:
            pass

    for obj in candidates:
        if "action" in obj or "signal" in obj:
            return obj

    if candidates:
        return candidates[0]

    try:
        result = json.loads(cleaned)
        if not isinstance(result, dict):
            logger.warning(
                f"extract_json: json.loads returned {type(result).__name__} "
                f"(value={repr(result)[:100]}) — treating as parse error"
            )
            return {"_parse_error": True, "_raw": raw[:500], "_parsed_value": result}
        return result
    except json.JSONDecodeError:
        return {"_parse_error": True, "_raw": raw[:500]}


def _check_parse_error(parsed: dict, context: str = "") -> bool:
    """
    [LEGACY] ตรวจ parse error และ log warning
    Return True ถ้ามี error (caller ควร fallback)
    """
    if parsed.get("_parse_error"):
        raw_preview = parsed.get("_raw", "")[:200]
        logger.warning(
            f"LLM response parse failed{' at ' + context if context else ''} — "
            f"falling back to HOLD. Raw preview: {repr(raw_preview)}"
        )
        return True
    return False


# ─────────────────────────────────────────────
# [P1] StateReadinessChecker
# ─────────────────────────────────────────────


class StateReadinessChecker:
    """
    ตรวจว่า market_state + tool_results มีข้อมูลพอสำหรับ FINAL_DECISION
    โดยไม่ต้อง call tool เพิ่ม → ประหยัด 1 LLM call ต่อรอบ

    "พร้อม" = technical_indicators ครบตาม required_indicators
              AND (htf_covered หรือ require_htf=False)

    required_indicators inject ได้จาก ReadinessConfig
    → Strategy เปลี่ยน indicators ได้โดยไม่แตะ class นี้
    """

    # map indicator name → primary value keys (ตรวจตามลำดับ, หยุดเมื่อเจอค่าที่ดี)
    _TI_PRIMARY_KEYS: dict = {
        "rsi":        ["value"],
        "macd":       ["macd_line", "histogram"],
        "trend":      ["trend", "ema_20"],
        "bollinger":  ["upper", "lower"],
        "atr":        ["value"],
        "stochastic": ["k", "d"],
    }

    def __init__(self, config: Optional[ReadinessConfig] = None):
        self._cfg = config or ReadinessConfig()

    def is_ready(self, market_state: dict, tool_results: list) -> bool:
        ti_ok  = self._check_technical_indicators(market_state)
        htf_ok = self._check_htf_covered(market_state, tool_results)
        ready  = ti_ok and htf_ok

        logger.debug(
            "[StateReadinessChecker] required=%s ti_ok=%s htf_ok=%s → skip_loop=%s",
            self._cfg.required_indicators, ti_ok, htf_ok, ready,
        )
        return ready

    def _check_technical_indicators(self, market_state: dict) -> bool:
        ti = market_state.get("technical_indicators", {})
        if not ti:
            return False

        for ind in self._cfg.required_indicators:
            section = ti.get(ind)
            if not section or not isinstance(section, dict):
                logger.debug("[StateReadinessChecker] missing section: %s", ind)
                return False

            # หา primary key ตาม _TI_PRIMARY_KEYS หรือ fallback ใช้ key แรกของ section
            primary_keys = self._TI_PRIMARY_KEYS.get(ind, list(section.keys())[:1])
            found_valid = False
            for pk in primary_keys:
                val = section.get(pk)
                if val not in (None, "N/A", ""):
                    found_valid = True
                    break

            if not found_valid:
                logger.debug(
                    "[StateReadinessChecker] indicator '%s' has no valid value "
                    "(checked keys=%s)", ind, primary_keys
                )
                return False

        return True

    def _check_htf_covered(self, market_state: dict, tool_results: list) -> bool:
        if not self._cfg.require_htf:
            return True

        # ตรวจ tool_results — htf tool ถูก call ไปแล้วหรือยัง
        for tr in tool_results:
            if (
                "htf" in getattr(tr, "tool_name", "").lower()
                and getattr(tr, "status", "") == "success"
            ):
                return True

        # fallback — ดู trend section ว่ามี ema ครบไหม (data pre-loaded)
        trend = market_state.get("technical_indicators", {}).get("trend", {})
        return bool(
            trend.get("trend") not in (None, "N/A", "")
            and trend.get("ema_20") not in (None, "N/A", "")
            and trend.get("ema_50") not in (None, "N/A", "")
        )


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────


def _make_llm_log(
    step: str,
    iteration: int,
    llm_resp,  # LLMResponse object จาก client.py
    parsed: dict,
    note: str = "",
) -> dict:
    """
    Helper: สร้าง trace entry พร้อม LLM metadata ครบถ้วน

    Args:
        llm_resp: LLMResponse instance (หรือ None ถ้า fallback)
        parsed:   dict จาก AgentDecision.model_dump() หรือ legacy dict
    """
    entry = {
        "step": step,
        "iteration": iteration,
        "response": parsed,
        "prompt_text":  getattr(llm_resp, "prompt_text", "") if llm_resp else "",
        "response_raw": getattr(llm_resp, "text", "") if llm_resp else "",
        "token_input":  getattr(llm_resp, "token_input", 0) if llm_resp else 0,
        "token_output": getattr(llm_resp, "token_output", 0) if llm_resp else 0,
        "token_total":  getattr(llm_resp, "token_total", 0) if llm_resp else 0,
        "model":        getattr(llm_resp, "model", "") if llm_resp else "",
        "provider":     getattr(llm_resp, "provider", "") if llm_resp else "",
    }
    if note:
        entry["note"] = note
    return entry


# ─────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────

class ReactOrchestrator:
    """
    ReAct loop: Thought → Action → Observation → repeat → FINAL_DECISION

    Fully dependency-injected:
      llm_client     — Part A (LLMClient) — ต้องรองรับ LLMResponse return
      prompt_builder — Part C (PromptBuilder)
      tool_registry  — dict[str, Callable]
      config         — ReactConfig (รวม ReadinessConfig สำหรับ P1)
      risk_manager   — RiskManager (optional, สร้าง default ถ้าไม่ส่งมา)
    """

    def __init__(
        self,
        llm_client,
        prompt_builder,
        tool_registry: dict,
        config: ReactConfig,
        risk_manager: Optional[RiskManager] = None,
    ):
        self.llm = llm_client
        self.prompt_builder = prompt_builder
        self.tools = tool_registry
        self.config = config

        if risk_manager is None:
            logger.warning(
                "RiskManager not injected — using default params "
                "(atr_multiplier=2.0, risk_reward_ratio=1.5). "
                "Consider passing risk_manager explicitly."
            )
            self.risk_manager = RiskManager(atr_multiplier=1.0, risk_reward_ratio=1.0)
        else:
            self.risk_manager = risk_manager

        # [P1] สร้าง StateReadinessChecker จาก config.readiness
        self._readiness_checker = StateReadinessChecker(config.readiness)

    # ── Entry point ─────────────────────────────

    def run(
        self,
        market_state: dict,
        initial_observation: Optional[ToolResult] = None,
        ohlcv_df=None,
    ) -> dict:
        """
        Run ReAct loop.
        """

        # # ── [ADDED] Helper สำหรับ Save Log ลงไฟล์ ──────────────────────────
        # def _save_to_trace_log(result_dict: dict):
        #     try:
        #         os.makedirs("logs", exist_ok=True)
        #         log_filepath = "logs/logs/llm_trace.log"
                
        #         def _format_for_readability(obj):
        #             if isinstance(obj, dict):
        #                 return {k: _format_for_readability(v) for k, v in obj.items()}
        #             elif isinstance(obj, list):
        #                 return [_format_for_readability(v) for v in obj]
        #             elif isinstance(obj, str) and '\n' in obj:
        #                 return obj.split('\n') # แตกบรรทัดยาวๆ ออกเป็นบรรทัดย่อยใน List
        #             return obj
                
        #         timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        #         log_entry = {
        #             "timestamp": timestamp,
        #             "market_state_timestamp": market_state.get("timestamp", "N/A"),
        #             "final_decision": result_dict.get("final_decision"),
        #             "react_trace": result_dict.get("react_trace"),
        #             "summary": {
        #                 "iterations": result_dict.get("iterations_used"),
        #                 "tool_calls": result_dict.get("tool_calls_used"),
        #             }
        #         }
                
        #         readable_log_entry = _format_for_readability(log_entry)
                
        #         with open(log_filepath, "a", encoding="utf-8") as f:
        #             f.write(f"\n{'='*80}\n")
        #             f.write(f"[{timestamp}] ReAct Execution Trace\n")
        #             f.write(f"{'-'*80}\n")
        #             # default=str เพื่อป้องกัน Error กรณีมี Datetime object หลุดเข้าไป
        #             f.write(json.dumps(readable_log_entry, indent=2, ensure_ascii=False, default=str))
        #             f.write("\n")
        #     except Exception as e:
        #         logger.error(f"[ReAct] Failed to write trace log: {e}")
        # # ──────────────────────────────────────────────────────────────

        # ── Fast path: no tools → single LLM call ───────────────
        if self.config.max_tool_calls == 0:
            prompt = self.prompt_builder.build_final_decision(market_state, [])

            logger.debug("[ReAct] fast_path prompt_len=%d", len(prompt.user))
            llm_resp = self.llm.call(prompt)
            logger.debug("[ReAct] fast_path response=%s", llm_resp.text[:200])

            # [P2] parse_agent_response แทน extract_json + _check_parse_error + _build_decision
            decision_obj = parse_agent_response(llm_resp.text, context="fast_path")
            llm_decision = decision_obj.to_decision_dict()

            adjusted_decision = self.risk_manager.evaluate(
                llm_decision=llm_decision,
                market_state=market_state,
            )

            trace = [_make_llm_log(
                "THOUGHT_FINAL", 1, llm_resp,
                decision_obj.model_dump(exclude={"parse_failed"}),
            )]
            
            result = {
                "final_decision":  adjusted_decision,
                "react_trace":     trace,
                "iterations_used": 1,
                "tool_calls_used": 0,
                **self._aggregate_trace(trace),
            }
            # _save_to_trace_log(result) # [ADDED] Save Log
            return result

        # ── Full ReAct loop ──────────────────────────────────────
        state = ReactState(
            market_state=market_state,
            tool_results=[initial_observation] if initial_observation else [],
        )
        
        # เช็คว่ามีข้อมูล Pre-fetch หรือไม่
        has_pre_fetched = "pre_fetched_tools" in market_state

        # ── [P1] Readiness Check — skip tool loop ถ้าข้อมูลพร้อมแล้ว ──
        if not has_pre_fetched and self._readiness_checker.is_ready(market_state, state.tool_results):
            logger.info(
                "[ReAct] StateReadinessChecker: data sufficient — skipping tool loop"
            )
            prompt   = self.prompt_builder.build_final_decision(
                market_state, state.tool_results
            )
            llm_resp     = self.llm.call(prompt)
            decision_obj = parse_agent_response(
                llm_resp.text, context="readiness_skip"
            )
            adjusted = self.risk_manager.evaluate(
                llm_decision=decision_obj.to_decision_dict(),
                market_state=market_state,
            )
            trace = [_make_llm_log(
                "THOUGHT_FINAL", 1, llm_resp,
                decision_obj.model_dump(exclude={"parse_failed"}),
                note="readiness_skip",
            )]
            
            result = {
                "final_decision":  adjusted,
                "react_trace":     trace,
                "iterations_used": 1,
                "tool_calls_used": 0,
                **self._aggregate_trace(trace),
            }
            # _save_to_trace_log(result) # [ADDED] Save Log
            return result

        final_decision = None

        while state.iteration < self.config.max_iterations:
            state.iteration += 1

            # ── THOUGHT ────────────────────────────────────────
            prompt = self.prompt_builder.build_thought(
                state.market_state,
                state.tool_results,
                state.iteration,
            )

            print(f"\n{'=' * 20} [DEBUG: (IN While loop) PROMPT BEFORE AI] {'=' * 20}")
            print(f"SYSTEM: {prompt.system[:200]}...")
            print(f"USER:\n{prompt.user}")
            print(f"{'=' * 60}\n")

            logger.debug("[ReAct] iter=%d prompt_len=%d", state.iteration, len(prompt.user))
            llm_resp = self.llm.call(prompt)
            logger.debug("[ReAct] iter=%d response=%s", state.iteration, llm_resp.text[:200])

            # [P2] parse + validate
            thought_obj = parse_agent_response(
                llm_resp.text, context=f"iteration_{state.iteration}"
            )

            state.react_trace.append(
                _make_llm_log(
                    f"THOUGHT_{state.iteration}",
                    state.iteration,
                    llm_resp,
                    thought_obj.model_dump(exclude={"parse_failed"}),
                    note="parse_error — fallback to HOLD" if thought_obj.parse_failed else "",
                )
            )

            # [P2] parse_failed → fallback ทันที (แทน _check_parse_error + break เดิม)
            if thought_obj.parse_failed:
                final_decision = self._fallback_decision("LLM response parse failed")
                break

            action = thought_obj.action

            # ── ACTION: FINAL_DECISION ──────────────────────────
            if action == "FINAL_DECISION":
                final_decision = thought_obj.to_decision_dict()
                break

            # ── ACTION: CALL_TOOL ───────────────────────────────
            elif action == "CALL_TOOL":
                if state.tool_call_count >= self.config.max_tool_calls:
                    # Max tool calls ถึงแล้ว → force final decision
                    final_prompt = self.prompt_builder.build_final_decision(
                        state.market_state,
                        state.tool_results,
                    )

                    logger.debug(
                        "[ReAct] forced_final (max_tool_calls) prompt_len=%d",
                        len(final_prompt.user),
                    )
                    llm_resp_fin = self.llm.call(final_prompt)
                    logger.debug(
                        "[ReAct] forced_final response=%s", llm_resp_fin.text[:200]
                    )

                    # [P2]
                    final_obj    = parse_agent_response(
                        llm_resp_fin.text, context="forced_final_max_tool_calls"
                    )
                    final_decision = final_obj.to_decision_dict()

                    state.react_trace.append(
                        _make_llm_log(
                            "THOUGHT_FINAL",
                            state.iteration,
                            llm_resp_fin,
                            final_obj.model_dump(exclude={"parse_failed"}),
                            note="forced — max_tool_calls reached",
                        )
                    )
                    break

                tool_name = thought_obj.tool_name or ""
                tool_args = thought_obj.tool_args or {}

                base_interval = market_state.get("interval", "5m")
                observation = self._execute_tool(
                    tool_name,
                    tool_args,
                    ohlcv_df=ohlcv_df,
                    base_interval=base_interval,
                )

                state.tool_results = state.tool_results + [observation]
                state.tool_call_count += 1

                state.react_trace.append(
                    {
                        "step":       "TOOL_EXECUTION",
                        "iteration":  state.iteration,
                        "tool_name":  tool_name,
                        "observation": {
                            "status": observation.status,
                            "data":   observation.data,
                            "error":  observation.error,
                        },
                        "prompt_text":  "",
                        "response_raw": "",
                        "token_input":  0,
                        "token_output": 0,
                        "token_total":  0,
                        "model":        "",
                        "provider":     "",
                    }
                )
                continue

            # ── ACTION: CALL_TOOLS (parallel) [P10] ────────────────
            elif action == "CALL_TOOLS":
                tool_requests = thought_obj.tools or []
                if not tool_requests:
                    logger.warning(
                        "[ReAct] CALL_TOOLS: empty tools list at iteration %d — "
                        "falling back to HOLD", state.iteration
                    )
                    final_decision = self._fallback_decision("CALL_TOOLS: empty tools list")
                    break

                # ตรวจ budget — trim ถ้า tools เกิน remaining quota
                remaining = self.config.max_tool_calls - state.tool_call_count
                if len(tool_requests) > remaining:
                    logger.warning(
                        "[P10] CALL_TOOLS: requested %d tools but only %d budget left — trimming",
                        len(tool_requests), remaining,
                    )
                    tool_requests = tool_requests[:remaining]

                base_interval = market_state.get("interval", "5m")

                logger.info(
                    "[P10] CALL_TOOLS: running %d tools in parallel: %s",
                    len(tool_requests),
                    [r.get("tool_name") for r in tool_requests],
                )

                # asyncio.run() เพื่อ bridge sync→async (safe สำหรับ non-async caller)
                observations = asyncio.run(
                    self._execute_tools_parallel(tool_requests, ohlcv_df, base_interval)
                )

                state.tool_results = state.tool_results + observations
                state.tool_call_count += len(observations)

                # log แต่ละ tool แยก entry ใน react_trace
                for obs in observations:
                    state.react_trace.append(
                        {
                            "step":       "TOOL_EXECUTION",
                            "iteration":  state.iteration,
                            "tool_name":  obs.tool_name,
                            "observation": {
                                "status": obs.status,
                                "data":   obs.data,
                                "error":  obs.error,
                            },
                            "prompt_text":  "",
                            "response_raw": "",
                            "token_input":  0,
                            "token_output": 0,
                            "token_total":  0,
                            "model":        "",
                            "provider":     "",
                        }
                    )
                continue

            # ── UNKNOWN ACTION ──────────────────────────────────
            else:
                logger.warning(
                    f"Unknown action '{action}' at iteration {state.iteration} — "
                    "falling back to HOLD"
                )
                state.react_trace.append(
                    {
                        "step":         "UNKNOWN_ACTION",
                        "iteration":    state.iteration,
                        "raw":          thought_obj.model_dump(),
                        "prompt_text":  getattr(llm_resp, "prompt_text", ""),
                        "response_raw": getattr(llm_resp, "text", ""),
                        "token_input":  getattr(llm_resp, "token_input", 0),
                        "token_output": getattr(llm_resp, "token_output", 0),
                        "token_total":  getattr(llm_resp, "token_total", 0),
                        "model":        getattr(llm_resp, "model", ""),
                        "provider":     getattr(llm_resp, "provider", ""),
                        "note":         f"unknown action: '{action}'",
                    }
                )
                final_decision = self._fallback_decision(f"unknown action: '{action}'")
                break

        # ── Max iterations reached ──────────────────────────────
        if final_decision is None:
            final_prompt = self.prompt_builder.build_final_decision(
                state.market_state,
                state.tool_results,
            )
            llm_resp_fin = self.llm.call(final_prompt)

            # [P2]
            final_obj      = parse_agent_response(
                llm_resp_fin.text, context="forced_final_max_iterations"
            )
            final_decision = final_obj.to_decision_dict()

            state.react_trace.append(
                _make_llm_log(
                    "THOUGHT_FINAL",
                    state.iteration,
                    llm_resp_fin,
                    final_obj.model_dump(exclude={"parse_failed"}),
                    note="forced — max_iterations reached",
                )
            )

        adjusted_decision = self.risk_manager.evaluate(
            llm_decision=final_decision,
            market_state=market_state,
        )

        result = {
            "final_decision":  adjusted_decision,
            "react_trace":     state.react_trace,
            "iterations_used": state.iteration,
            "tool_calls_used": state.tool_call_count,
            **self._aggregate_trace(state.react_trace),
        }
        
        # _save_to_trace_log(result) # [ADDED] Save Log
        return result

    @staticmethod
    def _aggregate_trace(trace: list) -> dict:
        """
        สกัด top-level LLM metadata จาก trace entries
        เพื่อให้ services.py → _run_single_interval ดึงได้โดยตรง

        - prompt_text / response_raw : มาจาก THOUGHT_FINAL step ล่าสุด
        - token_input/output/total   : รวมทุก LLM step (ไม่รวม TOOL_EXECUTION)

        [FIX #3] ใช้ elif "FINAL" เพื่อกัน overwrite ซ้ำกรณี edge case
        """
        token_input  = 0
        token_output = 0
        token_total  = 0
        prompt_text  = ""
        response_raw = ""

        for entry in trace:
            step = entry.get("step", "")

            if step == "TOOL_EXECUTION":
                continue

            token_input  += entry.get("token_input", 0) or 0
            token_output += entry.get("token_output", 0) or 0
            token_total  += entry.get("token_total", 0) or 0

            if "FINAL" in step:
                prompt_text  = entry.get("prompt_text", "") or ""
                response_raw = entry.get("response_raw", "") or ""

        return {
            "prompt_text":  prompt_text,
            "response_raw": response_raw,
            "token_input":  token_input or None,
            "token_output": token_output or None,
            "token_total":  token_total or None,
        }

    # ── Private helpers ─────────────────────────

    async def _execute_tools_parallel(
        self,
        tool_requests: list[dict],
        ohlcv_df=None,
        base_interval: str = "5m",
    ) -> list[ToolResult]:
        """
        [P10] Run tool list แบบ parallel
        - ถ้าเป็น sync tool: ใช้ asyncio.to_thread เพื่อไม่ให้ block event loop
        - ถ้าเป็น async tool: เรียกโดยตรง (เป็น coroutine) แล้วเก็บเข้า tasks
        """
        tasks = []
        
        for req in tool_requests:
            name = req.get("tool_name", "")
            # ดึง target tool จาก dictionary ที่เก็บ tools ไว้
            target = self.tools.get(name, {})
            
            # ตรวจสอบว่า target เป็น dict และมี key 'fn' หรือไม่ (ตาม logic ในรูป)
            fn = target.get("fn") if isinstance(target, dict) else None

            # ✅ ตรวจสอบว่าเป็น async function หรือไม่
            if fn and asyncio.iscoroutinefunction(fn):
                # ถ้าเป็น async -> เรียก wrapper ที่เป็น async โดยตรง
                tasks.append(self._execute_tool_async(req, ohlcv_df, base_interval))
            else:
                # ถ้าเป็น sync -> wrap ด้วย to_thread เพื่อรันใน thread แยก
                tasks.append(asyncio.to_thread(
                    self._execute_tool,
                    name,
                    req.get("tool_args", {}),
                    ohlcv_df,
                    base_interval,
                ))

        # รันทุก tasks พร้อมกัน
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        clean: list[ToolResult] = []
        for req, res in zip(tool_requests, raw_results):
            if isinstance(res, Exception):
                tool_name = req.get("tool_name", "unknown")
                logger.error(
                    "[P10] Parallel tool '%s' raised exception: %s", tool_name, res
                )
                clean.append(ToolResult(
                    tool_name=tool_name,
                    status="error",
                    data={},
                    error=str(res),
                ))
            else:
                clean.append(res)
                
        return clean

    async def _execute_tool_async(self, req, ohlcv_df, base_interval):
        """Wrapper สำหรับเรียกใช้งาน async tools (ตามรูปภาพด้านล่าง)"""
        tool_name = req.get("tool_name", "")
        tool_args = req.get("tool_args", {}).copy()
        
        # หมายเหตุ: ในโค้ดจริง คุณอาจต้องมีการ inject ohlcv_df เข้าไปใน tool_args 
        # เหมือนที่ทำใน _execute_tool (sync) ก่อนจะเรียกใช้งาน
        
        try:
            # เรียกใช้งาน tool function ที่เป็น async ด้วย await
            result = await self.tools[tool_name]["fn"](**tool_args)
            return ToolResult(tool_name=tool_name, status="success", data=result)
        except Exception as exc:
            return ToolResult(
                tool_name=tool_name, 
                status="error", 
                data={}, 
                error=str(exc)
            )

    def _execute_tool(
        self, tool_name: str, tool_args: dict,
        ohlcv_df=None, base_interval=None,
    ) -> ToolResult:
        if tool_name not in self.tools:
            logger.warning(f"Tool '{tool_name}' not found in registry")
            return ToolResult(
                tool_name=tool_name, status="error", data={},
                error=f"Tool '{tool_name}' not found",
            )

        target = self.tools[tool_name]
        fn = target["fn"] if isinstance(target, dict) and "fn" in target else target

        exec_args = tool_args.copy()

        try:
            sig = inspect.signature(fn)
            if ohlcv_df is not None and "ohlcv_df" in sig.parameters:
                requested_interval = exec_args.get("interval", base_interval)
                if requested_interval == base_interval:
                    exec_args["ohlcv_df"] = ohlcv_df
                    logger.info(
                        f"💉 [Smart Injection] ส่ง DataFrame ที่มีอยู่เข้า "
                        f"'{tool_name}' สำเร็จ (ข้ามการดึง API ซ้ำ)"
                    )
        except Exception as e:
            logger.warning(f"Signature check failed for {tool_name}: {e}")

        try:
            result = fn(**exec_args)
            return ToolResult(tool_name=tool_name, status="success", data=result)
        except Exception as exc:
            logger.error(f"Tool '{tool_name}' execution failed: {exc}")
            return ToolResult(
                tool_name=tool_name, status="error", data={}, error=str(exc)
            )

    @staticmethod
    def _build_decision(parsed: dict) -> dict:
        """
        [LEGACY] Normalise LLM output → final_decision dict
        ใช้ AgentDecision.to_decision_dict() แทนใน run()
        """
        return {
            "signal":      parsed.get("signal", "HOLD"),
            "confidence":  float(parsed.get("confidence", 0.0)),
            "entry_price": parsed.get("entry_price"),
            "stop_loss":   parsed.get("stop_loss"),
            "take_profit": parsed.get("take_profit"),
            "rationale":   parsed.get("rationale", parsed.get("thought", "")),
        }

    @staticmethod
    def _fallback_decision(reason: str = "") -> dict:
        return {
            "signal":      "HOLD",
            "confidence":  0.0,
            "entry_price": None,
            "stop_loss":   None,
            "take_profit": None,
            "rationale":   f"Fallback HOLD — {reason}",
        }
