"""
tools/fetch_news.py — Tool: ดึงข่าวทองคำ (ENHANCED - MERGED VERSION - ASYNC)
ใช้ NewsFetcher (FinBERT sentiment + RSS) แล้วจัดรูปแบบสำหรับ LLM

NEW: รองรับการทำงานแบบ Asynchronous เต็มรูปแบบ (to_dict_async, fetch_category_async)
"""

import asyncio
import logging
from typing import Optional
import httpx  # ← เพิ่ม httpx สำหรับส่งเข้า fetch_category_async

from data_engine.newsfetcher import GoldNewsFetcher

logger = logging.getLogger(__name__)

TOOL_NAME = "fetch_news"
TOOL_DESCRIPTION = (
    "ดึงข่าวทองคำล่าสุดจาก RSS feeds พร้อม sentiment analysis (FinBERT) "
    "แยกตาม category และสรุป overall sentiment score "
    "[MERGED] สนับสนุน category_filter สำหรับ deep dive analysis (Async Version)"
)

_news_fetcher_cache: dict[int, GoldNewsFetcher] = {}


async def fetch_news(
    max_per_category: int = 5,
    category_filter: Optional[str] = None,
    detail_level: str = "summary",
) -> dict:
    """
    Enhanced news fetcher supporting BOTH general fetch AND deep category analysis
    
    * อัปเกรดเป็น Async: ใช้ await กับฟังก์ชันของ GoldNewsFetcher เพื่อไม่บล็อก Event Loop *

    Args:
        max_per_category: จำนวนข่าวสูงสุดต่อ category (default 5)
        category_filter: (Optional) Filter to single category for deep dive
                        Example: "fed_policy", "gold_price", "usd_thb"
                        If None, returns summary across all categories
        detail_level: "summary" (all categories, brief) or "deep" (single category, detailed)
                     Ignored if category_filter is None

    Returns:
        dict: ผลลัพธ์ข้อมูลข่าว
    """
    logger.info(
        f"[fetch_news] Fetching news ASYNC (max_per_category={max_per_category}, "
        f"category_filter={category_filter}, detail_level={detail_level})..."
    )

    if max_per_category not in _news_fetcher_cache:
        _news_fetcher_cache[max_per_category] = GoldNewsFetcher(
            max_per_category=max_per_category
        )
    fetcher = _news_fetcher_cache[max_per_category]

    # ─────────────────────────────────────────────────────────────
    # 1. Fetch general news (summary + by_category) - แบบ Async
    # ─────────────────────────────────────────────────────────────
    try:
        # ใช้ to_dict_async() แทน to_dict()
        raw = await fetcher.to_dict_async()
    except Exception as e:
        logger.error(f"[fetch_news] NewsFetcher failed: {e}")
        return {
            "summary": {
                "total_articles": 0,
                "overall_sentiment": 0.0,
                "errors": [str(e)],
            },
            "by_category": {},
            "error": str(e),
        }

    result = {
        "summary": {
            "total_articles": raw.get("total_articles", 0),
            "token_estimate": raw.get("token_estimate", 0),
            "overall_sentiment": raw.get("overall_sentiment", 0.0),
            "fetched_at": raw.get("fetched_at", ""),
            "errors": raw.get("errors", []),
        },
        "by_category": raw.get("by_category", {}),
        "error": None,
    }

    # ─────────────────────────────────────────────────────────────
    # 2. Deep dive into single category (if requested) - แบบ Async
    # ─────────────────────────────────────────────────────────────
    if category_filter and detail_level == "deep":
        logger.info(f"[fetch_news] Deep dive into category ASYNC: {category_filter}")
        try:
            loop = asyncio.get_event_loop()
            
            # สร้าง AsyncClient แบบชั่วคราวเพื่อส่งให้ fetch_category_async
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                # เรียกใช้ fetch_category_async
                articles = await fetcher.fetch_category_async(category_filter, client, loop)

            deep_news = {
                "category": category_filter,
                "count": len(articles),
                "articles": [
                    {
                        "title": a.title,
                        "source": a.source,
                        "impact_level": a.impact_level,
                        "sentiment": getattr(a, "sentiment_score", None), # แก้เป็น sentiment_score ตามคลาส
                        "published_at": getattr(a, "published_at", None),
                    }
                    for a in articles
                ],
            }

            result["deep_news"] = deep_news
            logger.info(
                f"[fetch_news] ✅ Deep news fetched ASYNC — {len(articles)} articles in {category_filter}"
            )

        except Exception as e:
            logger.error(f"[fetch_news] Deep news fetch failed for {category_filter}: {e}")
            result["deep_news_error"] = str(e)
            result["error"] = str(e)
            
    elif category_filter and detail_level != "deep":
        logger.debug(
            f"[fetch_news] category_filter={category_filter} provided but "
            f"detail_level={detail_level} (not 'deep') — skipping deep dive"
        )

    logger.info(
        f"[fetch_news] ✅ Done — {result['summary']['total_articles']} articles, "
        f"sentiment={result['summary']['overall_sentiment']:.3f}"
    )

    return result