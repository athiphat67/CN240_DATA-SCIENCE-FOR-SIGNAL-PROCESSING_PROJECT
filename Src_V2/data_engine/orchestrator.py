import json
import asyncio
import logging
import os
import time
from pathlib import Path

import pandas as pd
import requests

from data_engine.thailand_timestamp import get_thai_time
from data_engine.tools.schema_validator import validate_market_state
from data_engine.tools.fetch_indicators import fetch_indicators
from data_engine.tools.fetch_news import fetch_news as fetch_news_async

logger = logging.getLogger(__name__)

_WEEKEND_WARN = "Market is closed (Weekend) - Price data might be stale."
_WEEKEND_INSTRUCTION = (
    "Market is closed. Weigh news sentiment higher than short-term indicators."
)

MTS_HISTORY_URL = "https://tradingview.mtsgold.co.th/mgb/history"
MTS_SYMBOL = "GLD965"
MTS_CURRENCY = "THB"
MTS_DEFAULT_CANDLE_COUNT = 200
MTS_DEFAULT_SPREAD_THB = 100.0

INTERVAL_TO_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
}

INTERVAL_TO_MTS_RESOLUTION = {
    "1m": "1",
    "5m": "5",
    "15m": "15",
    "30m": "30",
    "1h": "60",
    "4h": "240",
    "1d": "1D",
}


def fetch_news_sync(max_per_category: int = 5) -> dict:
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import nest_asyncio
            nest_asyncio.apply()

        return asyncio.run(fetch_news_async(max_per_category=max_per_category))
    except Exception as exc:
        return {"error": f"Failed to run async fetch_news: {exc}"}


class GoldTradingOrchestrator:
    def __init__(
        self, history_days=90, interval="5m", max_news_per_cat=5, output_dir=None
    ):
        self.history_days = history_days
        self.interval = interval
        self.max_news_per_cat = max_news_per_cat
        self.output_dir = Path(output_dir) if output_dir else Path("./output")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.mts_spread_thb = float(
            os.getenv("MTS_DERIVED_SPREAD_THB", MTS_DEFAULT_SPREAD_THB)
        )

    def _fetch_mts_ohlcv(
        self, interval: str, countback: int = MTS_DEFAULT_CANDLE_COUNT
    ) -> tuple[pd.DataFrame, dict]:
        resolution = INTERVAL_TO_MTS_RESOLUTION.get(interval, interval)
        interval_seconds = INTERVAL_TO_SECONDS.get(interval, 300)
        end_ts = int(time.time())
        start_ts = end_ts - (interval_seconds * countback * 3)
        now_thai = get_thai_time()
        quality = {
            "source": "MTS_API",
            "status": "error",
            "timestamp": now_thai.isoformat(),
            "age_seconds": None,
            "stale": True,
            "fallback": False,
            "symbol": MTS_SYMBOL,
            "resolution": resolution,
            "warnings": [],
        }

        try:
            response = requests.get(
                MTS_HISTORY_URL,
                params={
                    "symbol": MTS_SYMBOL,
                    "resolution": resolution,
                    "from": start_ts,
                    "to": end_ts,
                    "countback": countback,
                    "currencyCode": MTS_CURRENCY,
                },
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.exceptions.RequestException as exc:
            quality["warnings"].append(f"MTS HTTP error: {exc}")
            logger.error("MTS OHLCV HTTP error: %s", exc)
            return pd.DataFrame(), quality
        except ValueError as exc:
            quality["warnings"].append(f"MTS JSON decode error: {exc}")
            logger.error("MTS OHLCV JSON decode error: %s", exc)
            return pd.DataFrame(), quality

        status = payload.get("s")
        if status == "no_data":
            quality["status"] = "no_data"
            quality["warnings"].append("MTS returned no_data; market may be closed.")
            logger.warning("MTS returned no_data.")
            return pd.DataFrame(), quality
        if status != "ok":
            quality["warnings"].append(f"MTS unexpected status: {status}")
            logger.error("MTS OHLCV unexpected status '%s': %s", status, payload)
            return pd.DataFrame(), quality

        try:
            times = payload.get("t") or []
            opens = payload.get("o") or []
            highs = payload.get("h") or []
            lows = payload.get("l") or []
            closes = payload.get("c") or []
            volumes = payload.get("v") or [0] * len(times)
            row_count = min(
                len(times), len(opens), len(highs), len(lows), len(closes), len(volumes)
            )
            if row_count == 0:
                quality["warnings"].append("MTS status ok but OHLCV arrays are empty.")
                return pd.DataFrame(), quality

            index = pd.to_datetime(times[:row_count], unit="s", utc=True).tz_convert(
                "Asia/Bangkok"
            )
            df = pd.DataFrame(
                {
                    "open": pd.to_numeric(opens[:row_count], errors="coerce"),
                    "high": pd.to_numeric(highs[:row_count], errors="coerce"),
                    "low": pd.to_numeric(lows[:row_count], errors="coerce"),
                    "close": pd.to_numeric(closes[:row_count], errors="coerce"),
                    "volume": pd.to_numeric(
                        pd.Series(volumes[:row_count]), errors="coerce"
                    ).fillna(0),
                },
                index=index,
            )
            df.index.name = "datetime"
            df = df.dropna(subset=["open", "high", "low", "close"])
            df = df[
                (df["open"] > 0)
                & (df["high"] >= df["low"])
                & (df["low"] > 0)
                & (df["close"] > 0)
            ]
            if df.empty:
                quality["warnings"].append("MTS OHLCV validation removed all rows.")
                return pd.DataFrame(), quality

            last_ts = df.index[-1]
            age_seconds = max(
                0.0,
                (pd.Timestamp.now(tz="Asia/Bangkok") - last_ts).total_seconds(),
            )
            stale_limit = max(interval_seconds * 2, 180)
            stale = age_seconds > stale_limit
            quality.update(
                {
                    "status": "stale" if stale else "ok",
                    "timestamp": last_ts.isoformat(),
                    "age_seconds": round(age_seconds, 2),
                    "stale": stale,
                    "fallback": False,
                    "row_count": int(len(df)),
                }
            )
            if stale:
                quality["warnings"].append(
                    f"MTS latest candle age {age_seconds:.0f}s exceeds {stale_limit}s."
                )
            return df, quality
        except Exception as exc:
            quality["warnings"].append(f"MTS OHLCV parse error: {exc}")
            logger.error("MTS OHLCV parse error: %s", exc)
            return pd.DataFrame(), quality
        
    def _parse_mts_udf_payload(self, payload: dict) -> pd.DataFrame:
        if payload.get("s") != "ok":
            raise ValueError(f"MTS status not ok: {payload.get('s')}")

        required = ["t", "o", "h", "l", "c"]
        for k in required:
            if k not in payload or not payload[k]:
                raise ValueError(f"MTS payload missing/empty key: {k}")

        n = min(len(payload["t"]), len(payload["o"]), len(payload["h"]), len(payload["l"]), len(payload["c"]))

        df = pd.DataFrame({
            "datetime": pd.to_datetime(payload["t"][:n], unit="s", utc=True).tz_convert("Asia/Bangkok"),
            "open": pd.to_numeric(pd.Series(payload["o"][:n]), errors="coerce"),
            "high": pd.to_numeric(pd.Series(payload["h"][:n]), errors="coerce"),
            "low": pd.to_numeric(pd.Series(payload["l"][:n]), errors="coerce"),
            "close": pd.to_numeric(pd.Series(payload["c"][:n]), errors="coerce"),
        })
    
        if "v" in payload and payload["v"]:
            df["volume"] = pd.to_numeric(pd.Series(payload["v"][:n]), errors="coerce").fillna(0.0)
        else:
            df["volume"] = 0.0
    
        df = df.dropna(subset=["open", "high", "low", "close"])
        df = df.set_index("datetime").sort_index()
    
        if len(df) < 50:
            raise ValueError(f"Not enough MTS candles: {len(df)}/50")

        return df    

    def _derive_mts_quote(self, ohlcv_df: pd.DataFrame, quality: dict) -> dict:
        if ohlcv_df is None or ohlcv_df.empty:
            return {
                "source": "MTS_API",
                "sell_price_thb": 0.0,
                "buy_price_thb": 0.0,
                "mid_price_thb": 0.0,
                "spread_thb": round(self.mts_spread_thb, 2),
                "timestamp": quality.get("timestamp", get_thai_time().isoformat()),
            }

        mid = float(ohlcv_df["close"].iloc[-1])
        half_spread = self.mts_spread_thb / 2.0
        return {
            "source": "MTS_API",
            "sell_price_thb": round(mid + half_spread, 2),
            "buy_price_thb": round(mid - half_spread, 2),
            "mid_price_thb": round(mid, 2),
            "spread_thb": round(self.mts_spread_thb, 2),
            "timestamp": quality.get("timestamp", ohlcv_df.index[-1].isoformat()),
        }

    def _recent_price_action(self, ohlcv_df: pd.DataFrame) -> list[dict]:
        if ohlcv_df is None or ohlcv_df.empty:
            return []

        recent = []
        for idx, row in ohlcv_df.tail(5).iterrows():
            recent.append(
                {
                    "datetime": idx.isoformat(),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": int(row["volume"]) if pd.notna(row["volume"]) else 0,
                }
            )
        return recent

    def run(
        self, save_to_file=True, history_days=None, interval=None, recent_trades=None
    ) -> dict:
        effective_days = history_days or self.history_days
        effective_interval = interval or self.interval

        ohlcv_df, mts_quality = self._fetch_mts_ohlcv(effective_interval)
        price_trend = self._compute_price_trend(ohlcv_df)
        ind_result = fetch_indicators(
            ohlcv_df=ohlcv_df,
            interval=effective_interval,
            usd_thb=None,
        )
        news_result = fetch_news_sync(max_per_category=self.max_news_per_cat)

        payload = self._assemble_payload(
            ind_result,
            news_result,
            effective_days,
            effective_interval,
            mts_quality=mts_quality,
            ohlcv_df=ohlcv_df,
            price_trend=price_trend,
            recent_trades=recent_trades,
        )

        schema_errors = validate_market_state(payload)
        if schema_errors:
            logger.error("Schema errors: %s", schema_errors)

        if save_to_file:
            self._save(payload)

        payload["_raw_ohlcv"] = ohlcv_df
        return payload

    def _compute_price_trend(self, ohlcv_df: pd.DataFrame) -> dict:
        price_trend: dict = {}
        if ohlcv_df is None or ohlcv_df.empty or len(ohlcv_df) < 2:
            return price_trend

        try:
            closes = ohlcv_df["close"].dropna()
            c_now = float(closes.iloc[-1])
            c_prev = float(closes.iloc[-2])
            price_trend["current_close_thb"] = round(c_now, 2)
            price_trend["prev_close_thb"] = round(c_prev, 2)
            price_trend["change_pct"] = (
                round(((c_now - c_prev) / c_prev) * 100, 2) if c_prev != 0 else 0.0
            )
            if len(closes) >= 6:
                c_5p = float(closes.iloc[-6])
                price_trend["5p_change_pct"] = (
                    round(((c_now - c_5p) / c_5p) * 100, 2) if c_5p != 0 else 0.0
                )
            if len(closes) >= 11:
                window10 = closes.tail(10)
                price_trend["10p_range_high"] = round(float(window10.max()), 2)
                price_trend["10p_range_low"] = round(float(window10.min()), 2)
        except Exception as exc:
            logger.error("Price trend calc error: %s", exc)
            price_trend = {"change_pct": 0.0}

        return price_trend

    def _assemble_payload(
        self,
        ind,
        news,
        history_days,
        interval=None,
        mts_quality=None,
        ohlcv_df=None,
        price_trend=None,
        recent_trades=None,
    ) -> dict:
        ind_d = ind.get("indicators", {})
        dq = ind.get("data_quality", {})
        news_s = news.get("summary")
        if news_s is None:
            news_s = {
                "total_articles": news.get("total_articles", 0),
                "overall_sentiment": news.get("overall_sentiment", 0.0),
                "fetched_at": news.get("fetched_at", ""),
                "errors": news.get("errors", []),
            }

        now_thai = get_thai_time().isoformat()
        effective_interval = interval or self.interval
        mts_quality = mts_quality or {}
        warnings = list(dq.get("warnings", [])) + list(mts_quality.get("warnings", []))
        if dq.get("is_weekend"):
            if _WEEKEND_WARN not in warnings:
                warnings.append(_WEEKEND_WARN)
            dq.setdefault("llm_instruction", _WEEKEND_INSTRUCTION)

        data_quality = {
            **dq,
            **mts_quality,
            "warnings": warnings,
        }
        data_quality.setdefault("quality_score", "good")
        if data_quality.get("status") != "ok":
            data_quality["quality_score"] = "degraded"
        data_quality.setdefault("is_weekend", get_thai_time().weekday() >= 5)
        data_quality.setdefault("llm_instruction", "Use standard technical analysis.")

        macd_d = ind_d.get("macd", {})
        if macd_d and "signal" not in macd_d:
            macd_d["signal"] = macd_d.get("crossover", "neutral")

        thai = self._derive_mts_quote(ohlcv_df, data_quality)
        sell = float(thai.get("sell_price_thb", 0) or 0)
        buy = float(thai.get("buy_price_thb", 0) or 0)
        mid = float(thai.get("mid_price_thb", 0) or 0)
        spread_thb = round(max(0.0, sell - buy), 2) if sell and buy else 0.0
        effective_spread = spread_thb

        trend_change_pct = abs(float((price_trend or {}).get("change_pct", 0.0) or 0.0))
        expected_move_thb = (
            round(mid * (trend_change_pct / 100.0), 2) if mid > 0 else 0.0
        )
        edge_score = (
            round((expected_move_thb / effective_spread), 4)
            if effective_spread > 0
            else 0.0
        )

        by_cat = news.get("by_category", {})
        latest_news = []
        if "top_5_key_headlines" in by_cat:
            latest_news = by_cat.get("top_5_key_headlines", [])
        else:
            for cat_name, cat_data in by_cat.items():
                if isinstance(cat_data, str):
                    continue
                articles = (
                    cat_data
                    if isinstance(cat_data, list)
                    else cat_data.get("articles", [])
                )
                for article in articles[:2]:
                    title = article.get("title", "") if isinstance(article, dict) else str(article)
                    if title:
                        latest_news.append(f"[{cat_name}] {title}")
        latest_news = latest_news[:10]

        portfolio = {}
        trades_today = int(portfolio.get("trades_today", 0) or 0)
        daily_target_entries = 3
        remaining_entries = max(0, daily_target_entries - trades_today)
        now_hour = get_thai_time().hour
        current_slot = min(3, max(1, (now_hour // 8) + 1)) if now_hour < 18 else 3
        min_entries_by_now = max(0, current_slot - 1)
        slot_conf_ladder = [0.62, 0.66, 0.70]
        slot_pos_ladder = [1000, 1000, 1000]
        next_slot_index = min(trades_today, daily_target_entries - 1)

        return {
            "meta": {
                "agent": "gold-trading-agent",
                "version": "1.3.0",
                "generated_at": now_thai,
                "history_days": history_days,
                "interval": effective_interval,
                "data_mode": "live",
            },
            "data_quality": data_quality,
            "data_sources": {
                "price": "MTS_API",
                "thai_gold": "MTS_API",
                "ohlcv": "MTS_API",
                "forex": "not_used_mts_only",
            },
            "market_data": {
                "spot_price_usd": {"source": "not_used_mts_only"},
                "forex": {"usd_thb": 0.0, "source": "not_used_mts_only"},
                "thai_gold_thb": thai,
                "spread_coverage": {
                    "spread_thb": spread_thb,
                    "effective_spread": effective_spread,
                    "expected_move_thb": expected_move_thb,
                    "expected_move": expected_move_thb,
                    "edge_score": edge_score,
                    "move_method": "MTS_mid_candle_pct",
                },
                "recent_price_action": self._recent_price_action(ohlcv_df),
                "price_trend": price_trend or {},
            },
            "technical_indicators": ind_d,
            "news": {
                "summary": news_s,
                "by_category": by_cat,
                "latest_news": latest_news,
                "news_count": len(latest_news),
            },
            "portfolio": portfolio,
            "execution_quota": {
                "daily_target_entries": daily_target_entries,
                "entries_done": trades_today,
                "entries_remaining": remaining_entries,
                "quota_met": trades_today >= daily_target_entries,
                "current_slot": current_slot,
                "min_entries_by_now": min_entries_by_now,
                "required_confidence_for_next_buy": slot_conf_ladder[next_slot_index],
                "recommended_next_position_thb": slot_pos_ladder[next_slot_index],
            },
            "recent_trades": recent_trades or [],
            "interval": effective_interval,
            "timestamp": now_thai,
        }

    def pack(self, full_state: dict) -> dict:
        slim = {}
        for key in [
            "meta",
            "interval",
            "timestamp",
            "time",
            "date",
            "session_gate",
            "execution_quota",
            "portfolio",
            "portfolio_summary",
            "backtest_directive",
            "recent_trades",
        ]:
            if key in full_state:
                slim[key] = full_state[key]

        slim["data_quality"] = full_state.get("data_quality", {})
        slim["technical_indicators"] = full_state.get("technical_indicators", {})
        md = full_state.get("market_data", {})
        slim["market_data"] = {
            "spot_price_usd": md.get("spot_price_usd", {}),
            "forex": md.get("forex", {}),
            "thai_gold_thb": md.get("thai_gold_thb", {}),
            "spread_coverage": md.get("spread_coverage", {}),
            "price_trend": md.get("price_trend", {}),
        }
        news = full_state.get("news", {})
        slim["news"] = {
            "latest_news": news.get("latest_news", []),
            "news_count": news.get("news_count", 0),
        }
        return slim

    def _save(self, payload: dict):
        ts = get_thai_time().strftime("%Y%m%d_%H%M%S")
        for fp in [
            self.output_dir / f"payload_{ts}.json",
            self.output_dir / "latest.json",
        ]:
            with open(fp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
            logger.info("Saved: %s", fp)
