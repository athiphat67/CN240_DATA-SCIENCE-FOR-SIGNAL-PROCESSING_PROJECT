"""
tools/tool_registry.py — Registry สำหรับ LLM Agent
รวม tools ไว้ที่เดียว แยกส่วน Internal (Orchestrator) และ Public (LLM)

Usage:
    from data_engine.tools.tool_registry import call_tool, list_tools, AVAILABLE_TOOLS_INFO

    # Orchestrator เรียกได้ (Internal) — ไม่ผ่าน scorer
    result = call_tool("fetch_price", interval="5m", history_days=30)

    # LLM เรียกได้ (Public) — ไม่ผ่าน scorer (single call เดิม)
    result = call_tool("detect_swing_low", interval="15m", history_days=3)

    # ─── NEW: เรียก tools พร้อม scoring ในครั้งเดียว ───────────────
    from data_engine.tools.tool_registry import execute_with_scoring

    report = execute_with_scoring([
        ("check_upcoming_economic_calendar", {"hours_ahead": 24}),
        ("detect_breakout_confirmation",     {"zone_top": 3250, "zone_bottom": 3200, "interval": "15m"}),
    ])

    if report.should_proceed:
        llm_context = [ts.tool_name for ts in report.tool_scores]  # ส่งต่อ LLM ได้เลย
    else:
        print(report.recommendations)   # ดูว่าต้อง call tool เพิ่มอะไร
"""
import logging
import asyncio
from typing import Any

from data_engine.tools.fetch_price      import fetch_price
from data_engine.tools.fetch_indicators import fetch_indicators
# เปลี่ยนมา import แบบ async และตั้งชื่อ alias
from data_engine.tools.fetch_news       import fetch_news as fetch_news_async
from data_engine.tools.schema_validator import validate_market_state

from data_engine.analysis_tools import TOOL_REGISTRY as ANALYSIS_TOOL_REGISTRY
from data_engine.analysis_tools import AVAILABLE_TOOLS_INFO as ANALYSIS_TOOLS_INFO
from data_engine.tools.tool_result_scorer import ToolResult, ToolResultScorer, ScoreReport

from data_engine.analysis_tools.fundamental_tools import (
    check_upcoming_economic_calendar as _calendar_async,
    get_intermarket_correlation as _intermarket_async
)

logger = logging.getLogger(__name__)

_scorer = ToolResultScorer()

def fetch_news_sync(max_per_category: int = 5, category_filter: str = None, detail_level: str = "summary") -> dict:
    """
    ตัวครอบ (Wrapper) ให้ระบบ Sync เก่า (เช่น engine.py, services.py) 
    สามารถเรียกใช้ fetch_news ที่เป็น Async ได้โดยไม่พัง
    """
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()
            
        return asyncio.run(fetch_news_async(
            max_per_category=max_per_category,
            category_filter=category_filter,
            detail_level=detail_level
        ))
    except Exception as e:
        return {"error": f"Failed to run async fetch_news: {e}"}

INTERNAL_TOOLS: dict[str, Any] = {
    "fetch_price": fetch_price,
    "fetch_indicators": fetch_indicators,
    "fetch_news": fetch_news_sync, # ตรงนี้จะไม่ Error แดงๆ แล้วครับ!
}

# สร้างสะพานเชื่อมให้ ปฏิทินเศรษฐกิจ
def check_upcoming_economic_calendar_sync(hours_ahead: int = 24):
    return asyncio.run(_calendar_async(hours_ahead=hours_ahead))

# สร้างสะพานเชื่อมให้ Intermarket
def get_intermarket_correlation_sync():
    return asyncio.run(_intermarket_async())

# 3. LLM Tools (เครื่องมือวิเคราะห์จำเพาะ ที่อนุญาตให้ LLM ใช้ใน ReAct Loop)
LLM_TOOLS = {
    **ANALYSIS_TOOL_REGISTRY, # แตกของเก่าที่มีอยู่แล้วออกมาวาง
    "check_upcoming_economic_calendar": check_upcoming_economic_calendar_sync, # ใส่ตัว Sync ที่เราเพิ่งสร้าง
    "get_intermarket_correlation": get_intermarket_correlation_sync, # ใส่ตัว Sync ที่เราเพิ่งสร้าง
}

# 4. TOOL_REGISTRY (รวมทั้งหมด เพื่อให้ call_tool หรือไฟล์เก่าดึงไปใช้ได้ ไม่พัง)
TOOL_REGISTRY = {**INTERNAL_TOOLS, **LLM_TOOLS}

# 5. คู่มือสำหรับ LLM (ดึงมาเฉพาะฝั่ง Analysis)
AVAILABLE_TOOLS_INFO = ANALYSIS_TOOLS_INFO


# ─────────────────────────────────────────────────────────────────────────────
# ฟังก์ชันเดิม — ไม่เปลี่ยนแปลง (Backward Compatible)
# ─────────────────────────────────────────────────────────────────────────────

def call_tool(tool_name: str, **kwargs: Any) -> dict:
    """
    เรียก tool จาก TOOL_REGISTRY (Orchestrator และ LLM เรียกผ่านที่นี่)
    คืน dict ตรงๆ ไม่ผ่าน scorer — เหมือนเดิมทุกอย่าง
    """
    if tool_name not in TOOL_REGISTRY:
        available = list(TOOL_REGISTRY.keys())
        raise KeyError(f"Tool '{tool_name}' not found. Available: {available}")

    logger.info(f"[ToolRegistry] Calling '{tool_name}' with params={list(kwargs.keys())}")

    tool_target = TOOL_REGISTRY[tool_name]

    # Smart Check: รองรับทั้ง Dictionary ที่มี "fn" และ Function ตรงๆ
    if isinstance(tool_target, dict) and "fn" in tool_target:
        return tool_target["fn"](**kwargs)
    else:
        return tool_target(**kwargs)


def list_tools() -> list[dict]:
    """
    คืน list ของ tools ไปประทับใน Prompt
    **คืนค่าเฉพาะ LLM_TOOLS เท่านั้น (ซ่อน Internal Tools)**
    """
    tools_list = []
    for name, meta in LLM_TOOLS.items():
        if isinstance(meta, dict) and "description" in meta:
            tools_list.append({
                "name": name,
                "description": meta["description"],
                "parameters": meta.get("parameters", {}),
            })
        else:
            # Fallback ป้องกัน list_tools() พัง
            tools_list.append({
                "name": name,
                "description": f"Advanced Analysis Tool: {name}",
                "parameters": {},
            })
    return tools_list


# ─────────────────────────────────────────────────────────────────────────────
# NEW — ฟังก์ชันเสริม สำหรับ Scoring Pipeline
# ─────────────────────────────────────────────────────────────────────────────

def call_tool_as_result(
    tool_name: str,
    weight: float = 1.0,
    **kwargs: Any,
) -> ToolResult:
    """
    เรียก tool เดียว แล้วห่อผลลัพธ์เป็น ToolResult ทันที

    ใช้เมื่อต้องการ call tool ทีละตัวแต่ยังอยากรวม score ทีหลัง
    Internal Tools (fetch_price ฯลฯ) ก็เรียกได้ แต่ scorer จะ skip ถ้าชื่อไม่รู้จัก

    Args:
        tool_name: ชื่อ tool ใน TOOL_REGISTRY
        weight:    ความสำคัญของ tool นี้ใน context ปัจจุบัน (default 1.0)
        **kwargs:  params ส่งต่อให้ tool ตรงๆ

    Returns:
        ToolResult พร้อม output และ params ที่ใช้ call
    """
    output = call_tool(tool_name, **kwargs)
    return ToolResult(
        tool_name=tool_name,
        output=output,
        params=dict(kwargs),
        weight=weight,
    )


def _call_safe(
    tool_name: str,
    params: dict,
    weight: float,
) -> ToolResult:
    """
    Internal helper: call tool เดียวพร้อม error handling ครบวงจร
    ใช้แทน try/except ซ้ำๆ ใน execute_with_scoring เพื่อลด code duplication

    คืน ToolResult เสมอ — ถ้า tool crash จะสร้าง ToolResult(status=error)
    แทนที่จะ raise exception ให้ caller จัดการเอง
    """
    try:
        return call_tool_as_result(tool_name, weight=weight, **params)
    except KeyError as e:
        logger.warning(f"[_call_safe] Tool ไม่พบ: {e}")
        raise   # re-raise KeyError ให้ caller skip ได้ถูกต้อง
    except Exception as e:
        logger.error(f"[_call_safe] '{tool_name}' error: {e}")
        return ToolResult(
            tool_name=tool_name,
            output={"status": "error", "message": str(e)},
            params=params,
            weight=weight,
        )


def execute_with_scoring(
    tool_calls: list[tuple[str, dict]],
    weights: dict[str, float] | None = None,
    max_rounds: int = 3,
) -> ScoreReport:
    """
    เรียก tools หลายตัวพร้อมกัน → score → loop ถ้าคะแนนไม่ถึง 0.6

    Pipeline:
        1. Dedup tool_calls (tool_name, params) เพื่อกัน avg พอง
        2. Call tools ทุกตัวใน tool_calls
        3. ส่งผลทั้งหมดเข้า ToolResultScorer
        4. ถ้า avg score < 0.6 → call tools ที่ scorer แนะนำเพิ่ม
        5. วน loop ซ้ำจนกว่าจะผ่าน หรือครบ max_rounds
        6. คืน ScoreReport สุดท้าย (should_proceed + tool_scores + recommendations)

    Args:
        tool_calls:  list ของ (tool_name, params_dict) ที่จะ call รอบแรก
                     ตย. [("detect_breakout_confirmation", {"interval": "15m"})]
        weights:     dict ของ {tool_name: weight} สำหรับ tool ที่ต้องการให้น้ำหนักพิเศษ
                     ตย. {"check_upcoming_economic_calendar": 1.5}
                     tool ที่ไม่ระบุ weight จะได้ 1.0
        max_rounds:  จำนวนรอบ retry สูงสุด (default 3) ป้องกัน infinite loop

    Returns:
        ScoreReport ที่มี:
            - tool_scores:       คะแนนและเหตุผลของแต่ละ tool
            - avg_score:         weighted average ของทุก tool
            - should_proceed:    True ถ้าพร้อมส่งเข้า LLM
            - hard_block:        True ถ้า tool บอกว่า is_safe_to_trade=False
            - hard_block_reason: สาเหตุของ hard_block
            - recommendations:   tool ที่ควร call เพิ่ม (ว่างถ้า should_proceed=True)
            - summary:           สรุปสั้นๆ สำหรับ log
    """
    weights = weights or {}

    # ── Dedup: กัน (tool_name, params) ซ้ำที่จะทำให้ avg score พองเกินจริง ──
    seen: set[tuple] = set()
    deduped: list[tuple[str, dict]] = []
    for tool_name, params in tool_calls:
        key = (tool_name, tuple(sorted(params.items())))
        if key in seen:
            logger.warning(
                f"[execute_with_scoring] Duplicate tool_call ถูกข้าม: '{tool_name}' params={params}"
            )
            continue
        seen.add(key)
        deduped.append((tool_name, params))

    # ── Round 1: Call tools ชุดแรก ─────────────────────────────────────────
    results: list[ToolResult] = []
    for tool_name, params in deduped:
        try:
            w = weights.get(tool_name, 1.0)
            result = _call_safe(tool_name, params, w)
            results.append(result)
        except KeyError:
            pass  # _call_safe log แล้ว + re-raise KeyError → ข้ามไปเงียบๆ

    report = _scorer.score(results)
    logger.info(f"[execute_with_scoring] Round 1 — {report.summary}")

    # ── Retry Loop: ตาม recommendations จนกว่าผ่านหรือหมด rounds ──────────
    for round_num in range(2, max_rounds + 1):
        if report.should_proceed:
            break

        if not report.recommendations:
            logger.info(f"[execute_with_scoring] ไม่มี recommendations เหลือ — หยุดที่ round {round_num - 1}")
            break

        logger.info(f"[execute_with_scoring] Round {round_num} — call {len(report.recommendations)} tools เพิ่ม")

        for rec in report.recommendations:
            try:
                w = weights.get(rec.recommended_tool, 1.0)
                new_result = _call_safe(rec.recommended_tool, rec.suggested_params, w)
                results.append(new_result)
                logger.info(f"[execute_with_scoring] ✅ '{rec.recommended_tool}' called — reason: {rec.reason}")
            except KeyError:
                pass  # tool ไม่พบ — _call_safe log แล้ว

        report = _scorer.score(results)
        logger.info(f"[execute_with_scoring] Round {round_num} — {report.summary}")

    # ── Log สรุปผลสุดท้าย ──────────────────────────────────────────────────
    if report.hard_block:
        logger.warning(
            f"[execute_with_scoring] 🚫 HARD BLOCK — {report.hard_block_reason}"
        )
    elif report.should_proceed:
        logger.info(
            f"[execute_with_scoring] ✅ PROCEED — avg={report.avg_score:.3f} "
            f"| {len(results)} tools called"
        )
    else:
        logger.warning(
            f"[execute_with_scoring] ⚠️ LOW SCORE หลัง {max_rounds} rounds — "
            f"avg={report.avg_score:.3f} | proceed ต่อด้วย context ที่มีอยู่"
        )

    return report