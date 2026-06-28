# data_engine/tools/pre_fetch.py

import asyncio
import logging
from typing import Any

# Technical Tools (ใช้ Pandas -> ต้องห่อด้วย to_thread)
from data_engine.analysis_tools.technical_tools import (
    get_htf_trend,
    get_support_resistance_zones,
)

# Fundamental Tools (อัปเกรดเป็น Async แล้ว -> เรียกใช้งานได้ตรงๆ)
from data_engine.analysis_tools.fundamental_tools import (
    check_upcoming_economic_calendar,
    get_deep_news_by_category
)

logger = logging.getLogger(__name__)

def _safe_tool_result(result: Any, tool_name: str) -> dict:
    if isinstance(result, Exception):
        logger.error(f"[PRE-FETCH] ❌ Tool '{tool_name}' failed: {str(result)}")
        return {"status": "error", "message": str(result)}
    if isinstance(result, dict):
        return result
    return {"status": "success", "data": result}

async def pre_fetch_market_data(session_context: dict = None) -> dict:
    logger.info("🚀 [PRE-FETCH] Start fetching core tools concurrently...")

    # 1. CPU-Bound Tasks (กราฟ/Pandas) -> ห่อด้วย to_thread
    task_trend = asyncio.to_thread(
        get_htf_trend, timeframe="1h", history_days=1
    )
    task_sr = asyncio.to_thread(
        get_support_resistance_zones, interval="15m", history_days=1
    )
    
    # 2. I/O-Bound Tasks (ข่าว/API) -> เป็น Native Async แล้ว เรียกได้เลย!
    task_calendar = check_upcoming_economic_calendar(hours_ahead=4)
    task_news = get_deep_news_by_category(category="fed_policy") 

    # 3. รันพร้อมกันทั้งหมด (ทะลวงขีดจำกัดความเร็ว)
    results = await asyncio.gather(
        task_trend, 
        task_sr, 
        task_calendar, 
        task_news, 
        return_exceptions=True
    )

    pre_fetched_tools = {
        "get_htf_trend": _safe_tool_result(results[0], "get_htf_trend"),
        "get_support_resistance_zones": _safe_tool_result(results[1], "get_support_resistance_zones"),
        "check_upcoming_economic_calendar": _safe_tool_result(results[2], "check_upcoming_economic_calendar"),
        "get_deep_news_by_category": _safe_tool_result(results[3], "get_deep_news_by_category")
    }

    logger.info("✅ [PRE-FETCH] Done in God-Tier Mode!")
    return pre_fetched_tools