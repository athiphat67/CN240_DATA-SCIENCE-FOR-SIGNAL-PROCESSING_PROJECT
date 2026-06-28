# newsfetcher.py — Gold Trading Agent · Phase 2.2 (Async Refactor: httpx + asyncio)
# การเปลี่ยนแปลงหลัก:
#   - เพิ่ม score_sentiment_batch_async  → ใช้ httpx.AsyncClient + asyncio.sleep
#   - เพิ่ม _fetch_rss_async             → ใช้ httpx.AsyncClient แทน requests.get
#   - เพิ่ม fetch_category_async         → await RSS + yfinance (run_in_executor)
#   - เพิ่ม fetch_all_async              → asyncio.gather แทน ThreadPoolExecutor
#   - เพิ่ม to_dict_async                → async entry point หลัก
#   - คง sync version ทุกตัวไว้เพื่อ backward compatibility

from __future__ import annotations

import asyncio
import logging
import concurrent.futures
import json
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Optional
import httpx          # ← NEW: สำหรับ async HTTP calls
import requests       # ← KEEP: backward compatibility (sync path)
import feedparser
import os
import time
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# กำหนด Timezone ประเทศไทย (UTC+7)
from data_engine.thailand_timestamp import get_thai_time, to_thai_time

load_dotenv()

# ─── [A] Tokenizer Setup (tiktoken) ──────────────────────────────────────────
try:
    import tiktoken
    _tokenizer = tiktoken.get_encoding("cl100k_base")
    HAS_TIKTOKEN = True
except ImportError:
    HAS_TIKTOKEN = False
    _tokenizer = None
    logger.warning("tiktoken ไม่ได้ติดตั้ง — จะใช้การประมาณการ Token แบบพื้นฐาน")

# ─── [B] Sentiment: FinBERT via Hugging Face API ─────────────────────────────
FINBERT_MODEL = "ProsusAI/finbert"
HF_API_URL = f"https://router.huggingface.co/hf-inference/models/{FINBERT_MODEL}"
HF_TOKEN = os.getenv("HF_TOKEN")

if not HF_TOKEN:
    print("Warning: ไม่พบ HF_TOKEN กรุณาตรวจสอบไฟล์ .env หรือการตั้งค่า Environment Variable")

# ─── [B-1] Sentiment: Sync version (เดิม — คงไว้เพื่อ backward compatibility) ───
def score_sentiment_batch(texts: list[str], retries: int = 3) -> list[float]:
    """ประเมิน Sentiment ผ่าน Hugging Face Free API (Synchronous — เดิม)"""
    if not texts:
        return []
    if not HF_TOKEN:
        logger.warning("ไม่ได้ตั้งค่า HF_TOKEN จะข้ามการประเมิน Sentiment (คืนค่า 0.0)")
        return [0.0] * len(texts)

    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    scores = []
    logger.info(f"กำลังประเมิน Sentiment ทีละข่าวจำนวน {len(texts)} ข่าว ผ่าน HF API...")

    logger.info("กำลังตรวจสอบสถานะโมเดล FinBERT (Warming up)...")
    for i, text in enumerate(texts):
        payload = {"inputs": text[:512]}
        text_score = 0.0

        for attempt in range(retries):
            try:
                requests.post(HF_API_URL, headers=headers, json={"inputs": "warmup"}, timeout=10)
                logger.info(f"  [ข่าว {i + 1}] กำลังส่งไปประเมิน (Attempt {attempt + 1}/3)...")
                response = requests.post(HF_API_URL, headers=headers, json=payload, timeout=25)

                if response.status_code == 429:
                    logger.warning(f"  [ข่าว {i + 1}] ติด Rate Limit รอ 10 วินาที... (ครั้งที่ {attempt + 1})")
                    time.sleep(10)
                    continue

                if response.status_code == 503 and "estimated_time" in response.json():
                    wait_time = response.json().get("estimated_time", 10)
                    logger.info(f"  [ข่าว {i + 1}] โมเดลกำลังโหลด รอ {wait_time} วินาที...")
                    time.sleep(wait_time)
                    continue

                response.raise_for_status()
                results = response.json()

                if isinstance(results, list) and len(results) > 0:
                    res = results[0] if isinstance(results[0], list) else results
                    if isinstance(res, list) and len(res) > 0:
                        best_label = max(res, key=lambda x: x.get("score", 0))
                        label = best_label.get("label", "")
                        conf = best_label.get("score", 0.0)

                        if label == "positive":
                            text_score = round(conf, 4)
                        elif label == "negative":
                            text_score = -round(conf, 4)
                break
            except requests.exceptions.Timeout:
                logger.error(f"  [ข่าว {i + 1}] Error: HF API ตอบสนองช้าเกินไป (Timeout)")
                time.sleep(5)
            except Exception as e:
                logger.warning(f"  [ข่าว {i + 1}] HF API Error อื่นๆ: {e}")
                time.sleep(2)

        time.sleep(0.5)
        scores.append(text_score)

    return scores


# ─── [B-2] Sentiment: Async version (NEW) ────────────────────────────────────
def _parse_hf_response(results: list) -> float:
    """Helper แยก logic การแปลง HF response → float score (ใช้ร่วมกันทั้ง sync/async)"""
    if not (isinstance(results, list) and len(results) > 0):
        return 0.0
    res = results[0] if isinstance(results[0], list) else results
    if not (isinstance(res, list) and len(res) > 0):
        return 0.0
    best_label = max(res, key=lambda x: x.get("score", 0))
    label = best_label.get("label", "")
    conf = best_label.get("score", 0.0)
    if label == "positive":
        return round(conf, 4)
    elif label == "negative":
        return -round(conf, 4)
    return 0.0


async def score_sentiment_batch_async(
    texts: list[str],
    retries: int = 3,
    concurrency: int = 5,
) -> list[float]:
    """
    ประเมิน Sentiment ผ่าน Hugging Face API แบบ Asynchronous (NEW)

    ใช้ httpx.AsyncClient + asyncio.Semaphore เพื่อ:
    - ส่ง request พร้อมกันได้สูงสุด `concurrency` คำขอในเวลาเดียวกัน
    - ไม่บล็อก Event Loop ระหว่างรอ I/O
    - asyncio.sleep แทน time.sleep เพื่อไม่หยุด Event Loop
    """
    if not texts:
        return []
    if not HF_TOKEN:
        logger.warning("ไม่ได้ตั้งค่า HF_TOKEN จะข้ามการประเมิน Sentiment (คืนค่า 0.0)")
        return [0.0] * len(texts)

    headers = {"Authorization": f"Bearer {HF_TOKEN}"}
    # Semaphore จำกัดจำนวน concurrent request ไม่ให้โดน rate limit
    sem = asyncio.Semaphore(concurrency)

    async def _score_one(idx: int, text: str) -> tuple[int, float]:
        """ประเมิน Sentiment ของ text เดี่ยว — คืนค่า (index, score) เพื่อรักษาลำดับ"""
        payload = {"inputs": text[:512]}
        score = 0.0

        async with sem:
            async with httpx.AsyncClient(timeout=25.0) as client:
                # Warmup request เพื่อ wake โมเดล (ส่งพร้อมกับ request จริง)
                try:
                    await client.post(HF_API_URL, headers=headers, json={"inputs": "warmup"})
                except Exception:
                    pass  # warmup ล้มเหลวไม่เป็นไร

                for attempt in range(retries):
                    try:
                        logger.info(f"  [ข่าว {idx + 1}] async sentiment (Attempt {attempt + 1}/{retries})...")
                        response = await client.post(HF_API_URL, headers=headers, json=payload)

                        if response.status_code == 429:
                            logger.warning(f"  [ข่าว {idx + 1}] Rate Limit — รอ 10s (async)")
                            await asyncio.sleep(10)
                            continue

                        if response.status_code == 503:
                            body = response.json()
                            if "estimated_time" in body:
                                wait_time = body.get("estimated_time", 10)
                                logger.info(f"  [ข่าว {idx + 1}] โมเดลกำลังโหลด รอ {wait_time}s (async)")
                                await asyncio.sleep(float(wait_time))
                                continue

                        response.raise_for_status()
                        score = _parse_hf_response(response.json())
                        break

                    except httpx.TimeoutException:
                        logger.error(f"  [ข่าว {idx + 1}] httpx Timeout — รอ 5s แล้วลองใหม่")
                        await asyncio.sleep(5)
                    except Exception as e:
                        logger.warning(f"  [ข่าว {idx + 1}] HF API Error: {e}")
                        await asyncio.sleep(2)

        return idx, score

    logger.info(f"[Async] กำลังประเมิน Sentiment {len(texts)} ข่าว (concurrency={concurrency})...")

    # รัน _score_one ทุก text พร้อมกัน (จำกัดด้วย Semaphore)
    tasks = [_score_one(i, text) for i, text in enumerate(texts)]
    results_unordered = await asyncio.gather(*tasks)

    # เรียงลำดับกลับตาม index เดิม
    results_unordered.sort(key=lambda x: x[0])
    return [score for _, score in results_unordered]


# ─── [C] Category → Sources Mapping ─────────────────────────────────────────
NEWS_CATEGORIES: dict[str, dict] = {
    "gold_price": {
        "label": "ราคาทองคำโลก", "impact": "direct", "tickers": ["GC=F", "GLD", "IAU"],
        "rss": ["https://www.kitco.com/rss/kitconews.xml", "https://www.investing.com/rss/news_301.rss"],
        "keywords": ["gold", "xau", "bullion", "comex", "spot gold", "precious metal"],
    },
    "usd_thb": {
        "label": "ค่าเงิน USD/THB", "impact": "direct", "tickers": ["THB=X", "USDTHB=X"],
        "rss": ["https://www.fxstreet.com/rss/news"],
        "keywords": ["thai baht", "thb", "usd/thb", "bank of thailand", "bot rate", "bangkok"],
    },
    "fed_policy": {
        "label": "นโยบายดอกเบี้ย Fed", "impact": "high", "tickers": ["^TNX", "^IRX", "TLT"],
        "rss": ["https://feeds.feedburner.com/reuters/businessNews", "https://www.fxstreet.com/rss/news"],
        "keywords": ["fed", "federal reserve", "fomc", "rate hike", "rate cut", "powell", "interest rate", "monetary policy"],
    },
    "inflation": {
        "label": "เงินเฟ้อ / CPI", "impact": "high", "tickers": ["TIP", "RINF"],
        "rss": ["https://feeds.feedburner.com/reuters/businessNews"],
        "keywords": ["inflation", "cpi", "pce", "consumer price", "core inflation", "deflation"],
    },
    "geopolitics": {
        "label": "ภูมิรัฐศาสตร์ / Safe Haven", "impact": "high", "tickers": ["GC=F", "SLV", "^VIX"],
        "rss": ["https://www.kitco.com/rss/kitconews.xml", "https://feeds.feedburner.com/reuters/worldNews"],
        "keywords": ["war", "conflict", "sanction", "geopolitic", "russia", "ukraine", "china", "middle east", "safe haven", "tension"],
    },
    "dollar_index": {
        "label": "ดัชนีค่าเงินดอลลาร์ (DXY)", "impact": "medium", "tickers": ["DX-Y.NYB", "UUP"],
        "rss": ["https://www.fxstreet.com/rss/news"],
        "keywords": ["dxy", "dollar index", "usd", "us dollar", "greenback", "dollar strength"],
    },
    "thai_economy": {
        "label": "เศรษฐกิจไทย / ตลาดหุ้นไทย", "impact": "medium", "tickers": ["EWY", "THD", "SET.BK"],
        "rss": ["https://www.bangkokpost.com/rss/data/business.xml"],
        "keywords": ["thailand", "thai economy", "set index", "boi", "gdp thai", "thai baht", "thai government"],
    },
    "thai_gold_market": {
        "label": "ตลาดทองไทย", "impact": "direct", "tickers": ["GC=F", "SGOL"],
        "rss": ["https://www.kitco.com/rss/kitconews.xml", "https://www.bangkokpost.com/rss/data/business.xml"],
        "keywords": ["gold", "thai gold", "ausiris", "hua seng heng", "gold shop", "ygold"],
    },
}
IMPACT_PRIORITY: dict[str, int] = {"direct": 0, "high": 1, "medium": 2}

# ─── Dataclasses ──────────────────────────────────────────────────────────────
@dataclass
class NewsArticle:
    title: str
    url: str
    source: str
    published_at: str
    ticker: str
    category: str
    impact_level: str
    sentiment_score: float = 0.0

    def estimated_tokens(self) -> int:
        text = f"{self.title} {self.source} {self.published_at} {self.url}"
        if HAS_TIKTOKEN:
            base_tokens = len(_tokenizer.encode(text, disallowed_special=()))
            return int(base_tokens * 1.10)
        else:
            return max(1, len(text) // 4)

@dataclass
class NewsFetchResult:
    fetched_at: str
    total_articles: int
    token_estimate: int
    overall_sentiment: float = 0.0
    by_category: dict = field(default_factory=dict)
    errors: list = field(default_factory=list)


# ─── GoldNewsFetcher ──────────────────────────────────────────────────────────
class GoldNewsFetcher:
    def __init__(
        self,
        max_per_category: int = 5,
        max_total_articles: int = 30,
        token_budget: int = 3_000,
        target_date: Optional[str] = None,
        lookback_days: int = 3,
    ):
        self.max_per_category = max_per_category
        self.max_total_articles = max_total_articles
        self.token_budget = token_budget
        self.lookback_days = lookback_days
        self.target_date = target_date or get_thai_time().strftime("%Y-%m-%d")

    # ── helper ──────────────────────────────────────────────────────────────────
    def _is_recent(self, thai_dt) -> bool:
        """ยอมรับข่าวย้อนหลัง lookback_days วัน (default 3 วัน รองรับ weekend)"""
        from datetime import timedelta
        now = get_thai_time()
        cutoff = (now - timedelta(days=self.lookback_days)).strftime("%Y-%m-%d")
        article_date = thai_dt.strftime("%Y-%m-%d")
        return cutoff <= article_date <= self.target_date

    # ── yfinance (sync เดิม — yfinance ยังไม่มี async API) ───────────────────
    def _fetch_yfinance_raw(self, ticker_symbol: str) -> list[dict]:
        try:
            import yfinance as yf
            ticker = yf.Ticker(ticker_symbol)
            if hasattr(ticker, "get_news"):
                try:
                    news = ticker.get_news(count=self.max_per_category * 2) or []
                    if news: return news
                except Exception: pass
            return ticker.news or []
        except Exception as e:
            logger.warning(f"yfinance [{ticker_symbol}]: {e}")
            return []

    def _parse_yfinance(self, raw: dict, ticker: str, category: str) -> Optional[NewsArticle]:
        content = raw.get("content") or {}
        title = (raw.get("title") or content.get("title") or "").strip()
        if not title: return None

        url = (raw.get("link") or raw.get("url") or content.get("canonicalUrl", {}).get("url") or content.get("clickThroughUrl", {}).get("url") or "")
        if not url.startswith("http"): return None

        source = (raw.get("publisher") or content.get("provider", {}).get("displayName") or "unknown")
        raw_pub = (raw.get("providerPublishTime") or content.get("providerPublishTime") or content.get("pubDate") or raw.get("pubDate"))

        if not raw_pub: return None

        try:
            thai_dt = to_thai_time(raw_pub)
            if not self._is_recent(thai_dt): return None
            pub_str = thai_dt.isoformat()
        except Exception:
            return None

        return NewsArticle(title=title, url=url, source=source, published_at=pub_str, ticker=ticker, category=category, impact_level=NEWS_CATEGORIES[category]["impact"])

    # ── RSS: Sync version (เดิม) ──────────────────────────────────────────────
    def _fetch_rss(self, feed_url: str, keywords: list[str], category: str) -> list[NewsArticle]:
        articles: list[NewsArticle] = []
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = requests.get(feed_url, headers=headers, timeout=10)
            feed = feedparser.parse(resp.content)

            if feed.bozo and not feed.entries: return []

            for entry in feed.entries:
                title = (getattr(entry, "title", "") or "").strip()
                url = getattr(entry, "link", "") or ""
                if not title or not url.startswith("http"): continue

                if keywords and not any(kw in title.lower() for kw in keywords): continue

                pub_str = ""
                raw_pub = getattr(entry, "published", None) or getattr(entry, "updated", None)
                if raw_pub:
                    try:
                        thai_dt = to_thai_time(raw_pub)
                        if not self._is_recent(thai_dt): continue
                        pub_str = thai_dt.isoformat()
                    except Exception:
                        pass

                if not pub_str:
                    continue

                source = getattr(feed.feed, "title", None) or feed_url.split("/")[2]
                articles.append(NewsArticle(title=title, url=url, source=source, published_at=pub_str, ticker="rss", category=category, impact_level=NEWS_CATEGORIES[category]["impact"]))
        except Exception as e:
            logger.warning(f"RSS fetch error [{feed_url}]: {e}")
        return articles

    # ── RSS: Async version (NEW) ──────────────────────────────────────────────
    async def _fetch_rss_async(
        self,
        feed_url: str,
        keywords: list[str],
        category: str,
        client: httpx.AsyncClient,
    ) -> list[NewsArticle]:
        """
        ดึง RSS Feed แบบ Asynchronous โดยใช้ httpx.AsyncClient ที่รับมาจากภายนอก
        (share client เดียวกันทั้ง fetch_category_async เพื่อ reuse connection pool)
        """
        articles: list[NewsArticle] = []
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            response = await client.get(feed_url, headers=headers)
            # feedparser รับ bytes ได้โดยตรง — ไม่ต้อง decode
            feed = feedparser.parse(response.content)

            if feed.bozo and not feed.entries:
                return []

            for entry in feed.entries:
                title = (getattr(entry, "title", "") or "").strip()
                url = getattr(entry, "link", "") or ""
                if not title or not url.startswith("http"):
                    continue

                if keywords and not any(kw in title.lower() for kw in keywords):
                    continue

                pub_str = ""
                raw_pub = getattr(entry, "published", None) or getattr(entry, "updated", None)
                if raw_pub:
                    try:
                        thai_dt = to_thai_time(raw_pub)
                        if not self._is_recent(thai_dt):
                            continue
                        pub_str = thai_dt.isoformat()
                    except Exception:
                        pass

                if not pub_str:
                    continue

                source = getattr(feed.feed, "title", None) or feed_url.split("/")[2]
                articles.append(NewsArticle(
                    title=title, url=url, source=source, published_at=pub_str,
                    ticker="rss", category=category,
                    impact_level=NEWS_CATEGORIES[category]["impact"],
                ))

        except httpx.TimeoutException:
            logger.warning(f"RSS async timeout [{feed_url}]")
        except Exception as e:
            logger.warning(f"RSS async fetch error [{feed_url}]: {e}")

        return articles

    # ── fetch_category: Sync version (เดิม) ──────────────────────────────────
    def fetch_category(self, category: str) -> list[NewsArticle]:
        cat = NEWS_CATEGORIES[category]
        seen_urls: set[str] = set()
        results: list[NewsArticle] = []

        for symbol in cat["tickers"]:
            for raw in self._fetch_yfinance_raw(symbol):
                article = self._parse_yfinance(raw, symbol, category)
                if not article or article.url in seen_urls: continue
                if category == "usd_thb":
                    thai_kws = ["thai", "baht", "thb", "bangkok", "bot"]
                    if not any(k in article.title.lower() for k in thai_kws): continue
                results.append(article)
                seen_urls.add(article.url)

        if len(results) < self.max_per_category:
            keywords = cat.get("keywords", [])
            for feed_url in cat.get("rss", []):
                for article in self._fetch_rss(feed_url, keywords, category):
                    if article.url not in seen_urls:
                        results.append(article)
                        seen_urls.add(article.url)

        results.sort(key=lambda a: a.published_at, reverse=True)
        return results[: self.max_per_category]

    # ── fetch_category: Async version (NEW) ──────────────────────────────────
    async def fetch_category_async(
        self,
        category: str,
        client: httpx.AsyncClient,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> list[NewsArticle]:
        """
        ดึงข่าว 1 category แบบ Asynchronous (NEW)

        - yfinance ยังเป็น sync → รันใน executor เพื่อไม่บล็อก Event Loop
        - RSS feeds → ใช้ _fetch_rss_async พร้อมกันทุก feed ด้วย asyncio.gather
        """
        cat = NEWS_CATEGORIES[category]
        seen_urls: set[str] = set()
        results: list[NewsArticle] = []

        if loop is None:
            loop = asyncio.get_event_loop()

        # [1] yfinance — รันใน ThreadPoolExecutor เพื่อหลีกเลี่ยงการบล็อก Event Loop
        yf_tasks = [
            loop.run_in_executor(None, self._fetch_yfinance_raw, symbol)
            for symbol in cat["tickers"]
        ]
        yf_results_list = await asyncio.gather(*yf_tasks, return_exceptions=True)

        for symbol, yf_raw_list in zip(cat["tickers"], yf_results_list):
            if isinstance(yf_raw_list, Exception):
                logger.warning(f"yfinance async [{symbol}]: {yf_raw_list}")
                continue
            for raw in yf_raw_list:
                article = self._parse_yfinance(raw, symbol, category)
                if not article or article.url in seen_urls:
                    continue
                if category == "usd_thb":
                    thai_kws = ["thai", "baht", "thb", "bangkok", "bot"]
                    if not any(k in article.title.lower() for k in thai_kws):
                        continue
                results.append(article)
                seen_urls.add(article.url)

        # [2] RSS Feeds — ดึงพร้อมกันทุก feed ด้วย asyncio.gather
        if len(results) < self.max_per_category:
            keywords = cat.get("keywords", [])
            rss_tasks = [
                self._fetch_rss_async(feed_url, keywords, category, client)
                for feed_url in cat.get("rss", [])
            ]
            rss_results_list = await asyncio.gather(*rss_tasks, return_exceptions=True)

            for rss_articles in rss_results_list:
                if isinstance(rss_articles, Exception):
                    logger.warning(f"RSS async gather error [{category}]: {rss_articles}")
                    continue
                for article in rss_articles:
                    if article.url not in seen_urls:
                        results.append(article)
                        seen_urls.add(article.url)

        results.sort(key=lambda a: a.published_at, reverse=True)
        return results[: self.max_per_category]

    # ── _apply_global_limit (เดิม — ใช้ร่วมกันทั้ง sync และ async path) ────────
    def _apply_global_limit(self, by_category: dict[str, list[NewsArticle]]) -> tuple[dict[str, list[NewsArticle]], int]:
        flat: list[tuple[int, str, str, NewsArticle]] = []
        for cat_key, articles in by_category.items():
            priority = IMPACT_PRIORITY.get(NEWS_CATEGORIES[cat_key]["impact"], 9)
            for article in articles:
                date_key = article.published_at or ""
                flat.append((priority, date_key, cat_key, article))

        flat.sort(key=lambda x: (x[1], -x[0]), reverse=True)
        selected: list[tuple[str, NewsArticle]] = []
        total_tokens = 0

        for priority, _date_key, cat_key, article in flat:
            if len(selected) >= self.max_total_articles: break
            est = article.estimated_tokens()
            if total_tokens + est > self.token_budget: continue
            selected.append((cat_key, article))
            total_tokens += est

        trimmed: dict[str, list[NewsArticle]] = {k: [] for k in by_category}
        for cat_key, article in selected: trimmed[cat_key].append(article)

        return trimmed, total_tokens

    # ── fetch_all: Sync version (เดิม) ───────────────────────────────────────
    def fetch_all(self) -> NewsFetchResult:
        logger.info(f"GoldNewsFetcher: fetching {len(NEWS_CATEGORIES)} categories...")

        by_category_raw: dict[str, list[NewsArticle]] = {}
        errors: list[str] = []

        def _fetch_single_category(cat_key: str) -> tuple[str, list[NewsArticle], str | None]:
            try: return cat_key, self.fetch_category(cat_key), None
            except Exception as e: return cat_key, [], str(e)

        max_threads = 2
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_threads) as executor:
            future_to_cat = {executor.submit(_fetch_single_category, cat_key): cat_key for cat_key in NEWS_CATEGORIES.keys()}
            for future in concurrent.futures.as_completed(future_to_cat):
                cat_key, articles, err = future.result()
                by_category_raw[cat_key] = articles
                if err:
                    errors.append(f"{cat_key}: {err}")
                    logger.error(f"  [{cat_key}] error: {err}")

        global_seen_urls = set()
        for cat_key, articles in by_category_raw.items():
            unique_articles = []
            for article in articles:
                if article.url not in global_seen_urls:
                    unique_articles.append(article)
                    global_seen_urls.add(article.url)
            by_category_raw[cat_key] = unique_articles

        by_category_trimmed, token_estimate = self._apply_global_limit(by_category_raw)

        surviving_articles: list[NewsArticle] = []
        for articles in by_category_trimmed.values(): surviving_articles.extend(articles)

        overall_sentiment = 0.0
        if surviving_articles:
            titles = [a.title for a in surviving_articles]
            scores = score_sentiment_batch(titles)

            impact_weights = {"direct": 1.5, "high": 1.2, "medium": 1.0}
            total_weight = 0.0
            weighted_score_sum = 0.0

            for article, score in zip(surviving_articles, scores):
                article.sentiment_score = score
                weight = impact_weights.get(article.impact_level, 1.0)
                weighted_score_sum += article.sentiment_score * weight
                total_weight += weight

            if total_weight > 0: overall_sentiment = round(weighted_score_sum / total_weight, 4)

        by_category_out: dict = {}
        total = 0
        for cat_key, articles in by_category_trimmed.items():
            cat_meta = NEWS_CATEGORIES[cat_key]
            by_category_out[cat_key] = {
                "label": cat_meta["label"],
                "impact": cat_meta["impact"],
                "tickers": cat_meta["tickers"],
                "count": len(articles),
                "articles": [asdict(a) for a in articles],
            }
            total += len(articles)

        return NewsFetchResult(
            fetched_at=get_thai_time().isoformat(), total_articles=total,
            token_estimate=token_estimate, overall_sentiment=overall_sentiment,
            by_category=by_category_out, errors=errors,
        )

    # ── fetch_all: Async version (NEW) ────────────────────────────────────────
    async def fetch_all_async(self) -> NewsFetchResult:
        """
        ดึงข่าวทุก Category แบบ Asynchronous (NEW)

        ใช้ asyncio.gather แทน ThreadPoolExecutor:
        - สร้าง httpx.AsyncClient ตัวเดียวแล้ว share ให้ทุก category (reuse connection pool)
        - ดึงทุก category พร้อมกันในครั้งเดียว
        - ใช้ score_sentiment_batch_async แทน score_sentiment_batch
        """
        logger.info(f"[Async] GoldNewsFetcher: fetching {len(NEWS_CATEGORIES)} categories concurrently...")

        errors: list[str] = []
        loop = asyncio.get_event_loop()

        # share httpx.AsyncClient เดียวทั้ง session (reuse TCP connection pool)
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            # [1] ดึงทุก category พร้อมกันใน asyncio.gather
            cat_keys = list(NEWS_CATEGORIES.keys())
            tasks = [
                self.fetch_category_async(cat_key, client, loop)
                for cat_key in cat_keys
            ]
            results_list = await asyncio.gather(*tasks, return_exceptions=True)

        # รวมผลลัพธ์
        by_category_raw: dict[str, list[NewsArticle]] = {}
        for cat_key, result in zip(cat_keys, results_list):
            if isinstance(result, Exception):
                by_category_raw[cat_key] = []
                errors.append(f"{cat_key}: {result}")
                logger.error(f"  [{cat_key}] async error: {result}")
            else:
                by_category_raw[cat_key] = result

        # [2] ลบ URL ซ้ำข้ามหมวดหมู่
        global_seen_urls: set[str] = set()
        for cat_key, articles in by_category_raw.items():
            unique_articles = []
            for article in articles:
                if article.url not in global_seen_urls:
                    unique_articles.append(article)
                    global_seen_urls.add(article.url)
            by_category_raw[cat_key] = unique_articles

        # [3] ตัดข่าวตาม global limit + token budget
        by_category_trimmed, token_estimate = self._apply_global_limit(by_category_raw)

        surviving_articles: list[NewsArticle] = []
        for articles in by_category_trimmed.values():
            surviving_articles.extend(articles)

        # [4] Sentiment แบบ async — ส่งทุก title พร้อมกัน
        overall_sentiment = 0.0
        if surviving_articles:
            titles = [a.title for a in surviving_articles]
            scores = await score_sentiment_batch_async(titles)

            impact_weights = {"direct": 1.5, "high": 1.2, "medium": 1.0}
            total_weight = 0.0
            weighted_score_sum = 0.0

            for article, score in zip(surviving_articles, scores):
                article.sentiment_score = score
                weight = impact_weights.get(article.impact_level, 1.0)
                weighted_score_sum += article.sentiment_score * weight
                total_weight += weight

            if total_weight > 0:
                overall_sentiment = round(weighted_score_sum / total_weight, 4)

        # [5] สร้าง output dict
        by_category_out: dict = {}
        total = 0
        for cat_key, articles in by_category_trimmed.items():
            cat_meta = NEWS_CATEGORIES[cat_key]
            by_category_out[cat_key] = {
                "label": cat_meta["label"],
                "impact": cat_meta["impact"],
                "tickers": cat_meta["tickers"],
                "count": len(articles),
                "articles": [asdict(a) for a in articles],
            }
            total += len(articles)

        return NewsFetchResult(
            fetched_at=get_thai_time().isoformat(),
            total_articles=total,
            token_estimate=token_estimate,
            overall_sentiment=overall_sentiment,
            by_category=by_category_out,
            errors=errors,
        )

    # ── to_dict: Sync version (เดิม — Smart Cache + Diet Payload) ─────────────
    def to_dict(self) -> dict:
        """รีเทิร์นข้อมูลแบบ Option B: ประหยัด Token (ตัดเนื้อหา) โหลดจาก Cache หากไม่ข้ามรอบเวลา"""
        cache_file = Path("news_cache.json")
        now = get_thai_time()

        cycle_hour = "00" if now.hour < 12 else "12"
        current_cycle = f"{now.strftime('%Y-%m-%d')}_{cycle_hour}"

        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                if cached_data.get("_cycle") == current_cycle:
                    logger.info(f"NewsFetcher [Cache Hit]: ใช้ข้อมูลข่าวเดิมของรอบ {current_cycle}")
                    return cached_data["data"]
            except Exception as e:
                logger.warning(f"NewsFetcher [Cache Error]: อ่านไฟล์ Cache ไม่สำเร็จ ({e}) กำลังดึงใหม่...")

        logger.info(f"NewsFetcher [Fetch New]: เริ่มดึงข่าวรอบใหม่ ({current_cycle})")
        raw_result = self.fetch_all()

        return self._build_diet_payload(raw_result, cache_file, current_cycle)

    # ── to_dict: Async version (NEW) ─────────────────────────────────────────
    async def to_dict_async(self) -> dict:
        """
        Async entry point หลัก — ใช้แทน to_dict() ใน async context (NEW)

        ตรรกะ Cache เหมือนกับ to_dict ทุกประการ
        แต่เรียก fetch_all_async แทน fetch_all เพื่อไม่บล็อก Event Loop
        """
        cache_file = Path("news_cache.json")
        now = get_thai_time()

        cycle_hour = "00" if now.hour < 12 else "12"
        current_cycle = f"{now.strftime('%Y-%m-%d')}_{cycle_hour}"

        # [1] ตรวจ Cache — อ่านไฟล์ใน executor เพื่อไม่บล็อก Event Loop
        loop = asyncio.get_event_loop()
        try:
            cached_data = await loop.run_in_executor(None, self._read_cache, cache_file)
            if cached_data and cached_data.get("_cycle") == current_cycle:
                logger.info(f"NewsFetcher [Async Cache Hit]: ใช้ข้อมูลข่าวเดิมของรอบ {current_cycle}")
                return cached_data["data"]
        except Exception as e:
            logger.warning(f"NewsFetcher [Async Cache Error]: {e} — กำลังดึงใหม่...")

        # [2] Cache miss → ดึงข้อมูลสดแบบ async
        logger.info(f"NewsFetcher [Async Fetch New]: เริ่มดึงข่าวรอบใหม่ ({current_cycle})")
        raw_result = await self.fetch_all_async()

        return self._build_diet_payload(raw_result, cache_file, current_cycle)

    # ── helper: อ่าน cache (แยกออกมาให้ run_in_executor เรียกได้) ─────────────
    @staticmethod
    def _read_cache(cache_file: Path) -> dict | None:
        if not cache_file.exists():
            return None
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    # ── helper: สร้าง Diet Payload + บันทึก Cache (ใช้ร่วมกัน sync/async) ──────
    def _build_diet_payload(
        self,
        raw_result: NewsFetchResult,
        cache_file: Path,
        current_cycle: str,
    ) -> dict:
        """แปลง NewsFetchResult → Diet Payload (Option B) และบันทึก Cache"""
        all_articles = []
        for cat_key, cat_data in raw_result.by_category.items():
            all_articles.extend(cat_data["articles"])

        all_articles.sort(key=lambda x: abs(x["sentiment_score"]), reverse=True)
        top_headlines = [
            f"[{a['category'].upper()}] {a['title']} (Sentiment: {a['sentiment_score']})"
            for a in all_articles[:5]
        ]

        diet_by_category = {}
        for cat_key, cat_data in raw_result.by_category.items():
            if cat_data["count"] > 0:
                cat_sent = sum(a["sentiment_score"] for a in cat_data["articles"]) / cat_data["count"]
                diet_by_category[cat_key] = {
                    "label": cat_data["label"],
                    "impact": cat_data["impact"],
                    "sentiment_avg": round(cat_sent, 4),
                    "article_count": cat_data["count"],
                }

        diet_payload = {
            "total_articles": raw_result.total_articles,
            "token_estimate": 150,
            "overall_sentiment": raw_result.overall_sentiment,
            "fetched_at": raw_result.fetched_at,
            "errors": raw_result.errors,
            "by_category": {
                "market_bias": "Bullish" if raw_result.overall_sentiment > 0.1 else ("Bearish" if raw_result.overall_sentiment < -0.1 else "Neutral"),
                "top_5_key_headlines": top_headlines,
                "category_summary": diet_by_category,
            },
        }

        if raw_result.total_articles > 0:
            cache_wrapper = {"_cycle": current_cycle, "data": diet_payload}
            try:
                with open(cache_file, "w", encoding="utf-8") as f:
                    json.dump(cache_wrapper, f, ensure_ascii=False, indent=2)
                logger.info("NewsFetcher [Cache Saved]: อัปเดตไฟล์ news_cache.json เรียบร้อยแล้ว")
            except Exception as e:
                logger.error(f"NewsFetcher [Cache Error]: เซฟไฟล์ Cache ไม่สำเร็จ ({e})")
        else:
            logger.warning("NewsFetcher [Skip Cache]: ไม่พบข่าวในรอบนี้ จะไม่บันทึกทับ Cache เดิม")

        return diet_payload


# ─── Quick test ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    async def _main():
        fetcher = GoldNewsFetcher()
        # ใช้ to_dict_async แทน to_dict เพื่อทดสอบ async path
        data = await fetcher.to_dict_async()

        print("\n--- START DIET JSON OUTPUT (OPTION B - ASYNC) ---")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        print("--- END JSON OUTPUT ---")

    asyncio.run(_main())