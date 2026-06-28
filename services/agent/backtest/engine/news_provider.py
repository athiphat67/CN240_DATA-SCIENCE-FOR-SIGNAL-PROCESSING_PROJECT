from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import Optional
from datetime import timedelta

import pandas as pd

logger = logging.getLogger(__name__)

NewsDict = dict

_NEUTRAL: NewsDict = {
    "overall_sentiment":     0.0,
    "news_count":            0,
    "top_headlines_summary": "No news data available.",
}


class NewsProvider(ABC):
    @abstractmethod
    def get(self, candle_ts: pd.Timestamp) -> NewsDict: ...

    @property
    def source_name(self) -> str:
        return self.__class__.__name__


class NullNewsProvider(NewsProvider):
    """Return neutral (0.0) เสมอ — LLM จะพึ่ง technical indicators อย่างเดียว"""

    def __init__(self, log: bool = True):
        if log:
            logger.info("NullNewsProvider: sentiment=0.0 for all candles")

    def get(self, candle_ts: pd.Timestamp) -> NewsDict:
        return dict(_NEUTRAL)


class CSVNewsProvider(NewsProvider):
    def __init__(self, csv_path: str, window_hours: int = 24):
        """
        window_hours: กรอบเวลาสำหรับตัดสินว่าข่าวนี้ "สดใหม่" หรือ "เป็นแค่ Context เก่า"
        """
        try:
            self.df = pd.read_csv(csv_path, encoding='utf-8-sig')
            print(self.df.columns.tolist())
            self.df['Date_Thai'] = pd.to_datetime(self.df['Date_Thai'])
            # ดึงรายชื่อ Category ทั้งหมดที่มีในไฟล์
            self.categories = self.df['Category'].unique() if not self.df.empty else []
        except Exception as e:
            logger.error(f"Failed to load CSV: {e}")
            self.df = pd.DataFrame()
            self.categories = []
            
        self.window_hours = window_hours

    def get(self, candle_timestamp) -> dict:
        if self.df.empty:
            return {"news_count": 0, "latest_news": ["No news data available."]}
            
        try:
            if isinstance(candle_timestamp, str):
                candle_time = pd.to_datetime(candle_timestamp)
            else:
                candle_time = candle_timestamp

            if candle_time.tzinfo is not None:
                candle_time = candle_time.tz_localize(None)

            news_items_temp = []
            recent_count = 0
            
            # 1. วนลูปดึงข่าวล่าสุด "ของแต่ละ Category"
            for cat in self.categories:
                mask = (self.df['Category'] == cat) & (self.df['Date_Thai'] <= candle_time)
                cat_df = self.df[mask]
                
                if cat_df.empty:
                    continue # หมวดนี้ยังไม่มีข่าวเกิดขึ้นเลย ณ เวลานี้ ข้ามไป
                    
                # ดึงแถวที่เวลาใกล้แท่งเทียนที่สุด 1 แถว
                latest_row = cat_df.sort_values(by='Date_Thai', ascending=False).iloc[0]
                time_diff = candle_time - latest_row['Date_Thai']
                total_hours = int(time_diff.total_seconds() // 3600)
                
                news_items_temp.append({
                    'cat': cat,
                    'row': latest_row,
                    'time_diff': time_diff,
                    'total_hours': total_hours
                })
                
            # 2. จัดเรียงข่าว เอาข่าวที่ "สดใหม่ที่สุด" ขึ้นก่อนเสมอ
            news_items_temp.sort(key=lambda x: x['time_diff'])
            
            formatted_news = []
            for item in news_items_temp:
                total_hours = item['total_hours']
                minutes_ago = int((item['time_diff'].total_seconds() % 3600) // 60)
                days_ago = total_hours // 24
                
                # ทำ Format เวลาสวยๆ
                if days_ago > 0:
                    time_str = f"{days_ago}d {total_hours % 24}h ago"
                elif total_hours > 0:
                    time_str = f"{total_hours}h {minutes_ago}m ago"
                else:
                    time_str = f"{minutes_ago}m ago"
                    
                impact = str(item['row']['Impact']).upper()
                title = str(item['row']['Title'])
                cat = item['cat']
                
                # 3. แยกข่าวใหม่ กับข่าวเก่า (Fallback)
                if total_hours <= self.window_hours:
                    news_str = f"[{cat}] [{time_str}] [{impact}] {title}"
                    recent_count += 1
                else:
                    news_str = f"[{cat}] [{time_str}] [{impact}] {title} (Old Context)"
                    
                formatted_news.append(news_str)

            # แจ้งเตือน LLM ถ้าย้อนกลับไป 24 ชม. แล้วไม่มีข่าวสดใหม่เลย
            if recent_count == 0 and formatted_news:
                formatted_news.insert(0, "⚠️ No recent macro news in the past 24h. Focus primarily on Technicals. Below are old contexts:")

            return {
                "news_count": recent_count,  # นับเฉพาะข่าวใหม่
                "latest_news": formatted_news
            }
            
        except Exception as e:
            logger.error(f"Error filtering news for {candle_timestamp}: {e}")
            return {"news_count": 0, "latest_news": ["Error fetching news."]}


class LiveNewsProvider(NewsProvider):
    """
    ดึง sentiment จาก GoldNewsFetcher production
    ถ้า import ไม่ได้ → fallback neutral อัตโนมัติ
    """

    def __init__(self, cache_minutes: int = 30):
        self._cache_minutes = cache_minutes
        self._fetcher       = None
        self._cached:    Optional[NewsDict]     = None
        self._cached_ts: Optional[pd.Timestamp] = None

        try:
            from data_engine.newsfetcher import GoldNewsFetcher
            self._fetcher = GoldNewsFetcher()
            logger.info(f"✓ LiveNewsProvider ready (cache={cache_minutes}min)")
        except ImportError:
            logger.warning("LiveNewsProvider: GoldNewsFetcher not found → neutral fallback")

    def get(self, candle_ts: pd.Timestamp) -> NewsDict:
        if self._fetcher is None:
            return dict(_NEUTRAL)
        if self._cached and self._cached_ts:
            age = abs((pd.Timestamp.now(tz="UTC") - self._cached_ts).total_seconds())
            if age < self._cache_minutes * 60:
                return dict(self._cached)
        try:
            raw = self._fetcher.fetch_news_sentiment()
            result: NewsDict = {
                "overall_sentiment":     float(raw.get("overall_sentiment", 0.0)),
                "news_count":            int(raw.get("news_count", 0)),
                "top_headlines_summary": str(raw.get("top_headlines_summary", ""))[:300],
            }
            self._cached    = result
            self._cached_ts = pd.Timestamp.now(tz="UTC")
            return dict(result)
        except Exception as e:
            logger.error(f"LiveNewsProvider.get() error: {e}")
            return dict(_NEUTRAL)

    @property
    def source_name(self) -> str:
        ok = self._fetcher is not None
        return f"LiveNewsProvider({'active' if ok else 'fallback-neutral'})"


def create_news_provider(
    mode: str = "null",
    csv_path: str = "",
    window_hours: int = 4,
    live_cache_minutes: int = 30,
) -> NewsProvider:
    """
    Factory สร้าง NewsProvider
    mode: "null" | "csv" | "live"
    """
    mode = mode.lower().strip()
    if mode == "null":
        return NullNewsProvider()
    elif mode == "csv":
        if not csv_path:
            logger.warning("create_news_provider: mode=csv ไม่มี csv_path → NullNewsProvider")
            return NullNewsProvider(log=False)
        return CSVNewsProvider(csv_path, window_hours)
    elif mode == "live":
        return LiveNewsProvider(live_cache_minutes)
    else:
        logger.warning(f"create_news_provider: unknown mode '{mode}' → NullNewsProvider")
        return NullNewsProvider(log=False)


def _to_utc(ts: pd.Timestamp) -> pd.Timestamp:
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
