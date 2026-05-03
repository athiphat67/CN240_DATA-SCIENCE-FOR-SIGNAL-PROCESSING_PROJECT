import logging
import os
import copy
import threading
import time
from typing import Any, Optional

import pandas as pd

from data_engine.indicators import TechnicalIndicators
from data_engine.thailand_timestamp import THAI_TZ, get_thai_time

logger = logging.getLogger(__name__)

SOURCE_NAME = "supabase_hsh_ig"
MIN_CANDLES = 50
DEFAULT_LIMIT = 10000
DEFAULT_MAX_STALE_SECONDS = 259200
DEFAULT_PAGE_SIZE = 1000
DEFAULT_CACHE_TTL_SECONDS = 15


class HshSupabaseMarketDataProvider:
    """Build Watcher-compatible market_state from HSH and IG Supabase tables."""

    _cache: dict[tuple, tuple[float, dict]] = {}
    _inflight: dict[tuple, threading.Event] = {}
    _cache_lock = threading.Lock()
    _client_lock = threading.Lock()
    _cacheable_statuses = {"ok", "stale", "insufficient_data"}

    def __init__(
        self,
        limit: int = DEFAULT_LIMIT,
        max_stale_seconds: Optional[int] = None,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if page_size <= 0:
            raise ValueError("page_size must be positive")
        self.limit = limit
        self.page_size = page_size
        self.max_stale_seconds = (
            max_stale_seconds
            if max_stale_seconds is not None
            else self._read_max_stale_seconds()
        )
        self.cache_ttl_seconds = self._read_cache_ttl_seconds()

    def build_market_state(self, interval: str = "5m") -> dict:
        cache_key = (
            str(interval),
            int(self.limit),
            int(self.max_stale_seconds),
            int(self.page_size),
        )
        cached = self._get_cached_market_state(cache_key)
        if cached is not None:
            logger.info("[HSHSupabase] cache_hit=True interval=%s", interval)
            return cached

        event = self._claim_cache_fetch(cache_key)
        if event is not None:
            event.wait()
            cached = self._get_cached_market_state(cache_key)
            if cached is not None:
                logger.info("[HSHSupabase] cache_hit=True interval=%s", interval)
                return cached

            # The first fetch failed with a non-cacheable fatal error. This caller
            # may try once rather than making duplicate concurrent requests.
            event = self._claim_cache_fetch(cache_key)
            if event is not None:
                event.wait()
                cached = self._get_cached_market_state(cache_key)
                if cached is not None:
                    logger.info("[HSHSupabase] cache_hit=True interval=%s", interval)
                    return cached

        logger.info("[HSHSupabase] cache_hit=False interval=%s", interval)
        try:
            market_state = self._build_market_state_uncached(interval=interval)
            status = (market_state.get("data_quality") or {}).get("status")
            if status in self._cacheable_statuses:
                self._store_cached_market_state(cache_key, market_state)
            return self._copy_market_state(market_state)
        finally:
            self._release_cache_fetch(cache_key)

    def _build_market_state_uncached(self, interval: str = "5m") -> dict:
        warnings: list[str] = []

        try:
            hsh_rows, ig_rows = self._fetch_rows()
            hsh_df = self._clean_hsh_rows(hsh_rows)
            ig_df = self._clean_ig_rows(ig_rows)

            if hsh_df.empty:
                return self._error_state(
                    "No usable rows in gold_prices_hsh",
                    row_count_hsh=0,
                    row_count_ig=len(ig_df),
                )
            if ig_df.empty:
                return self._error_state(
                    "No usable rows in gold_prices_ig",
                    row_count_hsh=len(hsh_df),
                    row_count_ig=0,
                )

            merged_df = self._align_hsh_ig(hsh_df, ig_df)
            ohlcv_df = self._build_ohlcv(hsh_df, interval=interval)

            latest_hsh = hsh_df.iloc[-1]
            latest_ig = ig_df.iloc[-1]
            latest_hsh_ts = latest_hsh["timestamp"]
            latest_ig_ts = latest_ig["timestamp"]

            age_seconds = max(
                0.0,
                (get_thai_time() - latest_hsh_ts).total_seconds(),
            )
            stale = age_seconds > self.max_stale_seconds

            status = "ok"
            quality_score = "good"
            if len(ohlcv_df) < MIN_CANDLES:
                status = "insufficient_data"
                quality_score = "bad"
                warnings.append(
                    f"Only {len(ohlcv_df)} OHLCV candles available; need {MIN_CANDLES}."
                )
            if stale:
                status = "stale"
                quality_score = "degraded"
                warnings.append(
                    f"Latest HSH row age {age_seconds:.1f}s exceeds "
                    f"HSH_MAX_STALE_SECONDS={self.max_stale_seconds}."
                )

            indicators_dict: dict[str, Any] = {}
            if len(ohlcv_df) >= MIN_CANDLES:
                indicators_dict = TechnicalIndicators(
                    ohlcv_df,
                    usd_thb=self._to_float(latest_ig.get("usd_thb")),
                    price_unit="THB_PER_BAHT_GOLD",
                ).to_dict(interval=interval)
                indicators_dict.pop("data_quality", None)
                indicators_dict["price_unit"] = "THB_PER_BAHT_GOLD"

            spread_thb = self._to_float(latest_hsh["spread_thb"])
            atr_thb = self._to_float(
                (indicators_dict.get("atr", {}) or {}).get("value")
            )
            mid_price = self._to_float(latest_hsh["mid_price_thb"])
            price_trend = self._build_price_trend(ohlcv_df)
            expected_move = atr_thb or (
                mid_price * abs(self._to_float(price_trend.get("change_pct"))) / 100.0
                if mid_price
                else 0.0
            )

            market_state = {
                "meta": {
                    "agent": "gold-trading-agent",
                    "version": "hsh-supabase-v1",
                    "generated_at": get_thai_time().isoformat(),
                    "interval": interval,
                    "data_mode": "live",
                },
                "market_data": {
                    "source": SOURCE_NAME,
                    "thai_gold_thb": {
                        "sell_price_thb": self._to_float(latest_hsh["ask_96"]),
                        "buy_price_thb": self._to_float(latest_hsh["bid_96"]),
                        "mid_price_thb": self._to_float(latest_hsh["mid_price_thb"]),
                        "spread_thb": spread_thb,
                        "unit": "THB_PER_BAHT_GOLD",
                        "source": "gold_prices_hsh",
                        "timestamp": latest_hsh_ts.isoformat(),
                    },
                    "spot_price_usd": {
                        "price_usd_per_oz": self._to_float(latest_ig["spot_price"]),
                        "source": "gold_prices_ig",
                        "timestamp": latest_ig_ts.isoformat(),
                    },
                    "forex": {
                        "usd_thb": self._to_float(latest_ig["usd_thb"]),
                        "source": "gold_prices_ig",
                        "timestamp": latest_ig_ts.isoformat(),
                    },
                    "candles": self._candles_to_records(ohlcv_df),
                    "spread_coverage": {
                        "spread_thb": spread_thb,
                        "effective_spread": spread_thb,
                        "expected_move_thb": round(expected_move, 2),
                        "expected_move": round(expected_move, 2),
                        "edge_score": round(expected_move / spread_thb, 4)
                        if spread_thb > 0
                        else 0.0,
                        "move_method": "ATR" if atr_thb > 0 else "candle_pct_fallback",
                        "atr_thb": atr_thb,
                    },
                    "recent_price_action": self._candles_to_records(ohlcv_df.tail(5)),
                    "price_trend": price_trend,
                },
                "technical_indicators": indicators_dict,
                "data_quality": {
                    "source": SOURCE_NAME,
                    "status": status,
                    "quality_score": quality_score,
                    "row_count_hsh": len(hsh_df),
                    "row_count_ig": len(ig_df),
                    "row_count_ohlcv": len(ohlcv_df),
                    "row_count_aligned": len(merged_df),
                    "timestamp": latest_hsh_ts.isoformat(),
                    "age_seconds": round(age_seconds, 2),
                    "stale": stale,
                    "fallback": False,
                    "warnings": warnings,
                    "is_weekend": get_thai_time().weekday() >= 5,
                },
                "data_sources": {
                    "price": "gold_prices_ig",
                    "thai_gold": "gold_prices_hsh",
                    "forex": "gold_prices_ig",
                },
                "trend_analysis": {},
                "interval": interval,
                "timestamp": latest_hsh_ts.isoformat(),
                "_raw_ohlcv": ohlcv_df,
            }

            logger.info(
                "[HSHSupabase] source=%s hsh_rows=%s ig_rows=%s ohlcv_rows=%s "
                "latest_ask_96=%s latest_bid_96=%s latest_mid=%s "
                "latest_spot_price=%s usd_thb=%s age_seconds=%.2f stale=%s",
                SOURCE_NAME,
                len(hsh_df),
                len(ig_df),
                len(ohlcv_df),
                market_state["market_data"]["thai_gold_thb"]["sell_price_thb"],
                market_state["market_data"]["thai_gold_thb"]["buy_price_thb"],
                market_state["market_data"]["thai_gold_thb"]["mid_price_thb"],
                market_state["market_data"]["spot_price_usd"]["price_usd_per_oz"],
                market_state["market_data"]["forex"]["usd_thb"],
                age_seconds,
                stale,
            )
            return market_state

        except Exception as exc:
            logger.error("[HSHSupabase] Failed to build market_state: %s", exc)
            return self._error_state(str(exc))

    def _fetch_rows(self) -> tuple[list[dict], list[dict]]:
        url = os.environ.get("SUPABASE_URL_INPUT") or os.environ.get("SUPABASE_URL")
        key = (
            os.environ.get("SUPABASE_KEY_INPUT")
            or os.environ.get("KEY_DB_IN")
            or os.environ.get("SUPABASE_KEY")
        )
        if not url:
            raise ValueError(
                "Missing required env var SUPABASE_URL_INPUT or SUPABASE_URL"
            )
        if not key:
            raise ValueError(
                "Missing required env var SUPABASE_KEY_INPUT, KEY_DB_IN, or SUPABASE_KEY"
            )

        try:
            from supabase import Client, create_client
        except ImportError as exc:
            raise RuntimeError(
                "supabase package is required for MARKET_DATA_SOURCE=supabase_hsh_ig"
            ) from exc

        db_in: Client = create_client(url, key)
        with self._client_lock:
            self._db_in = db_in
            try:
                hsh_rows = self._fetch_table_paginated(
                    "gold_prices_hsh",
                    "timestamp, ask_96, bid_96",
                    max_rows=self.limit,
                    page_size=self.page_size,
                )
                ig_rows = self._fetch_table_paginated(
                    "gold_prices_ig",
                    "timestamp, spot_price, usd_thb",
                    max_rows=self.limit,
                    page_size=self.page_size,
                )
            finally:
                if hasattr(self, "_db_in"):
                    delattr(self, "_db_in")

        if not hsh_rows:
            raise ValueError("No data returned from Supabase table gold_prices_hsh")
        if not ig_rows:
            raise ValueError("No data returned from Supabase table gold_prices_ig")

        return list(hsh_rows), list(ig_rows)

    def _fetch_table_paginated(
        self,
        table_name: str,
        columns: str,
        order_col: str = "timestamp",
        max_rows: int = DEFAULT_LIMIT,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> list[dict]:
        db_in = getattr(self, "_db_in", None)
        if db_in is None:
            raise RuntimeError("_fetch_table_paginated requires an active Supabase client")

        rows: list[dict] = []
        page_count = 0
        start = 0
        while len(rows) < max_rows:
            end = min(start + page_size - 1, max_rows - 1)
            response = (
                db_in.table(table_name)
                .select(columns)
                .order(order_col, desc=True)
                .range(start, end)
                .execute()
            )
            page_rows = list(response.data or [])
            if not page_rows:
                break
            rows.extend(page_rows)
            page_count += 1
            if len(page_rows) < page_size:
                break
            start += page_size

        capped_rows = rows[:max_rows]
        logger.info(
            "[HSHSupabase] table=%s requested_rows=%s fetched_rows=%s page_count=%s",
            table_name,
            max_rows,
            len(capped_rows),
            page_count,
        )
        return capped_rows

    def _clean_hsh_rows(self, rows: list[dict]) -> pd.DataFrame:
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df["timestamp"] = self._parse_timestamp_series(df["timestamp"])
        for col in ("ask_96", "bid_96"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["timestamp", "ask_96", "bid_96"])
        df = df[(df["ask_96"] > 0) & (df["bid_96"] > 0)]
        df = df[df["ask_96"] >= df["bid_96"]]
        df["sell_price_thb"] = df["ask_96"]
        df["buy_price_thb"] = df["bid_96"]
        df["mid_price_thb"] = (df["ask_96"] + df["bid_96"]) / 2.0
        df["spread_thb"] = df["ask_96"] - df["bid_96"]
        return (
            df.sort_values("timestamp")
            .drop_duplicates(subset=["timestamp"], keep="last")
            .reset_index(drop=True)
        )

    def _clean_ig_rows(self, rows: list[dict]) -> pd.DataFrame:
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df["timestamp"] = self._parse_timestamp_series(df["timestamp"])
        for col in ("spot_price", "usd_thb"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["timestamp", "spot_price", "usd_thb"])
        df = df[(df["spot_price"] > 0) & (df["usd_thb"] > 0)]
        return (
            df.sort_values("timestamp")
            .drop_duplicates(subset=["timestamp"], keep="last")
            .reset_index(drop=True)
        )

    def _parse_timestamp_series(self, series: pd.Series) -> pd.Series:
        return series.apply(self._parse_timestamp_value)

    def _parse_timestamp_value(self, value: Any) -> pd.Timestamp:
        if pd.isna(value):
            return pd.NaT
        ts = pd.to_datetime(value, errors="coerce")
        if pd.isna(ts):
            return pd.NaT
        if ts.tzinfo is None:
            return ts.tz_localize(THAI_TZ, nonexistent="shift_forward")
        return ts.tz_convert(THAI_TZ)

    def _align_hsh_ig(self, hsh_df: pd.DataFrame, ig_df: pd.DataFrame) -> pd.DataFrame:
        return pd.merge_asof(
            hsh_df.sort_values("timestamp"),
            ig_df.sort_values("timestamp"),
            on="timestamp",
            direction="nearest",
            suffixes=("", "_ig"),
        )

    def _build_ohlcv(self, hsh_df: pd.DataFrame, interval: str) -> pd.DataFrame:
        rule = self._interval_to_pandas_rule(interval)
        ticks = hsh_df[["timestamp", "mid_price_thb"]].copy()
        ticks = ticks.set_index("timestamp").sort_index()
        ohlcv = ticks["mid_price_thb"].resample(rule).agg(
            open="first",
            high="max",
            low="min",
            close="last",
            volume="count",
        )
        ohlcv = ohlcv.dropna(subset=["open", "high", "low", "close"])
        ohlcv["volume"] = ohlcv["volume"].fillna(0).astype(int)
        ohlcv = ohlcv.tail(self.limit)
        ohlcv.index.name = "timestamp"
        return ohlcv

    def _build_price_trend(self, ohlcv_df: pd.DataFrame) -> dict:
        if ohlcv_df is None or len(ohlcv_df) < 2:
            return {}
        closes = ohlcv_df["close"].dropna()
        if len(closes) < 2:
            return {}
        current = self._to_float(closes.iloc[-1])
        previous = self._to_float(closes.iloc[-2])
        change_pct = ((current - previous) / previous * 100.0) if previous else 0.0
        return {
            "current_close_thb": round(current, 2),
            "prev_close_thb": round(previous, 2),
            "change_pct": round(change_pct, 4),
        }

    def _candles_to_records(self, ohlcv_df: pd.DataFrame) -> list[dict]:
        if ohlcv_df is None or ohlcv_df.empty:
            return []
        records = []
        for idx, row in ohlcv_df.reset_index().iterrows():
            timestamp = row["timestamp"]
            records.append(
                {
                    "timestamp": timestamp.isoformat()
                    if hasattr(timestamp, "isoformat")
                    else str(timestamp),
                    "open": self._to_float(row["open"]),
                    "high": self._to_float(row["high"]),
                    "low": self._to_float(row["low"]),
                    "close": self._to_float(row["close"]),
                    "volume": int(row["volume"]) if pd.notna(row["volume"]) else 0,
                }
            )
        return records

    def _error_state(
        self,
        message: str,
        *,
        row_count_hsh: int = 0,
        row_count_ig: int = 0,
    ) -> dict:
        now = get_thai_time().isoformat()
        return {
            "market_data": {
                "source": SOURCE_NAME,
                "thai_gold_thb": {},
                "spot_price_usd": {},
                "forex": {},
                "candles": [],
            },
            "technical_indicators": {},
            "data_quality": {
                "source": SOURCE_NAME,
                "status": "error",
                "quality_score": "bad",
                "row_count_hsh": row_count_hsh,
                "row_count_ig": row_count_ig,
                "row_count_ohlcv": 0,
                "timestamp": now,
                "age_seconds": None,
                "stale": True,
                "fallback": False,
                "warnings": [message],
            },
            "interval": "",
            "timestamp": now,
            "_raw_ohlcv": pd.DataFrame(),
        }

    def _interval_to_pandas_rule(self, interval: str) -> str:
        normalized = str(interval).strip().lower()
        mapping = {
            "1m": "1min",
            "5m": "5min",
            "15m": "15min",
            "30m": "30min",
            "1h": "1h",
            "60m": "60min",
        }
        if normalized not in mapping:
            raise ValueError(f"Unsupported HSH Supabase interval: {interval}")
        return mapping[normalized]

    def _read_max_stale_seconds(self) -> int:
        raw = os.environ.get("HSH_MAX_STALE_SECONDS")
        if raw is None:
            return DEFAULT_MAX_STALE_SECONDS
        try:
            value = int(raw)
        except ValueError as exc:
            raise ValueError("HSH_MAX_STALE_SECONDS must be an integer") from exc
        if value <= 0:
            raise ValueError("HSH_MAX_STALE_SECONDS must be positive")
        return value

    def _read_cache_ttl_seconds(self) -> float:
        raw = os.environ.get("HSH_PROVIDER_CACHE_TTL_SECONDS")
        if raw is None:
            return float(DEFAULT_CACHE_TTL_SECONDS)
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError("HSH_PROVIDER_CACHE_TTL_SECONDS must be numeric") from exc
        if value < 0:
            raise ValueError("HSH_PROVIDER_CACHE_TTL_SECONDS must be non-negative")
        return value

    def _get_cached_market_state(self, cache_key: tuple) -> Optional[dict]:
        if self.cache_ttl_seconds <= 0:
            return None
        now = time.monotonic()
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached is None:
                return None
            expires_at, market_state = cached
            if expires_at <= now:
                self._cache.pop(cache_key, None)
                return None
            return self._copy_market_state(market_state)

    def _store_cached_market_state(self, cache_key: tuple, market_state: dict) -> None:
        if self.cache_ttl_seconds <= 0:
            return
        expires_at = time.monotonic() + self.cache_ttl_seconds
        with self._cache_lock:
            self._cache[cache_key] = (expires_at, self._copy_market_state(market_state))

    def _claim_cache_fetch(self, cache_key: tuple) -> Optional[threading.Event]:
        if self.cache_ttl_seconds <= 0:
            return None
        with self._cache_lock:
            event = self._inflight.get(cache_key)
            if event is not None:
                return event
            self._inflight[cache_key] = threading.Event()
            return None

    def _release_cache_fetch(self, cache_key: tuple) -> None:
        if self.cache_ttl_seconds <= 0:
            return
        with self._cache_lock:
            event = self._inflight.pop(cache_key, None)
            if event is not None:
                event.set()

    def _copy_market_state(self, market_state: dict) -> dict:
        raw_ohlcv = market_state.get("_raw_ohlcv")
        copied = copy.deepcopy(
            {key: value for key, value in market_state.items() if key != "_raw_ohlcv"}
        )
        if isinstance(raw_ohlcv, pd.DataFrame):
            copied["_raw_ohlcv"] = raw_ohlcv.copy()
        else:
            copied["_raw_ohlcv"] = copy.deepcopy(raw_ohlcv)
        return copied

    def _to_float(self, value: Any) -> float:
        try:
            if pd.isna(value):
                return 0.0
            return float(value)
        except (TypeError, ValueError):
            return 0.0
