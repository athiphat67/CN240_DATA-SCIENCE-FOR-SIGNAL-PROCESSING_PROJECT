import json
import logging
import time
from pathlib import Path
import pandas as pd
import requests
from data_engine.tools.tool_registry import call_tool
from data_engine.tools.schema_validator import validate_market_state
from data_engine.tools.interceptor_manager import start_interceptor_background
from data_engine.thailand_timestamp import get_thai_time

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
_WEEKEND_WARN = "Market is closed (Weekend) — Price data might be stale."
_WEEKEND_INSTRUCTION = (
    "Market is closed. Weigh news sentiment higher than short-term indicators."
)


class GoldTradingOrchestrator:
    def __init__(
        self, history_days=90, interval="5m", max_news_per_cat=5, output_dir=None
    ):
        start_interceptor_background()

        self.history_days = history_days
        self.interval = interval
        self.max_news_per_cat = max_news_per_cat
        self.output_dir = Path(output_dir) if output_dir else Path("./output")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _fetch_mts_latest_price(self):
        """
        Fetch the latest 1-minute close price for GLD965 from the MTS Gold
        TradingView UDF history endpoint.

        Returns:
            float | None: Latest close price in THB, or None if the market is
            closed (status "no_data") or any error occurs.
        """
        end_ts = int(time.time())
        start_ts = end_ts - 3600  # 1 hour window to guarantee >=1 candle

        url = (
            "https://tradingview.mtsgold.co.th/mgb/history"
            f"?symbol=GLD965&resolution=1&from={start_ts}&to={end_ts}"
            "&countback=1&currencyCode=THB"
        )

        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            payload = resp.json()
        except requests.exceptions.RequestException as e:
            logger.error("MTS latest price HTTP error: %s", e)
            return None
        except ValueError as e:
            logger.error("MTS latest price JSON decode error: %s", e)
            return None

        status = payload.get("s")

        if status == "ok":
            closes = payload.get("c") or []
            if not closes:
                logger.warning("MTS response status 'ok' but 'c' array is empty.")
                return None
            try:
                return float(closes[-1])
            except (TypeError, ValueError) as e:
                logger.error("MTS latest price could not cast close to float: %s", e)
                return None

        if status == "no_data":
            logger.warning("MTS returned 'no_data' — market likely closed.")
            return None

        logger.error("MTS latest price unexpected status '%s': %s", status, payload)
        return None

    def run(self, save_to_file=True, history_days=None, interval=None, recent_trades=None) -> dict:
        effective_days = history_days or self.history_days
        effective_interval = interval or self.interval

        # ── Step 1: fetch_price (ซึ่งข้างในเรียก fetch_all ที่เราทำ Stitching ไว้แล้ว) ──
        price_result = call_tool(
            "fetch_price", history_days=effective_days, interval=effective_interval
        )

        ohlcv_df = price_result.get("ohlcv_df")
        
        if ohlcv_df is not None and not ohlcv_df.empty:
            try:
                if ohlcv_df.index.tz is None:
                    # ไม่มี tz -> สมมติ UTC (yfinance ส่งมาแบบนี้) แล้ว convert
                    ohlcv_df = ohlcv_df.copy()  # ป้องกัน mutation ของ cache
                    ohlcv_df.index = (
                        ohlcv_df.index
                        .tz_localize("UTC")
                        .tz_convert("Asia/Bangkok")
                    )
                elif str(ohlcv_df.index.tz) != "Asia/Bangkok":
                    # มี tz อื่น -> convert ตรงๆ
                    ohlcv_df = ohlcv_df.copy()
                    ohlcv_df.index = ohlcv_df.index.tz_convert("Asia/Bangkok")
                # ถ้าเป็น Asia/Bangkok แล้ว -> skip (ไม่ต้องทำอะไร)
            except Exception as _tz_err:
                logger.warning(
                    f"[Orchestrator] OHLCV timezone conversion failed: {_tz_err} "
                    "- using original index"
                )
                
        if ohlcv_df is not None and not ohlcv_df.empty:
            try:
                import pandas as pd
                # logger.info("\n" + "="*50)
                # logger.info(f"📊 DEBUG OHLCV DATA (Interval: {effective_interval})")
                # logger.info("="*50)
                
                # 1. ปริ้น 5 แท่งล่าสุด (ดูแค่ O H L C ให้ดูง่ายๆ)
                # logger.info(f"Last 5 Candles:\n{ohlcv_df[['open', 'high', 'low', 'close']].tail(5)}\n")
                
                # 2. คำนวณความต่างของเวลา (Delay)
                last_candle_open = ohlcv_df.index[-1]
                
                # บวกเวลาของ 1 แท่งเข้าไป (เช่น 15 นาที) เพื่อหาเวลาปิดแท่ง
                interval_minutes = int(effective_interval.replace('m', '')) if 'm' in effective_interval else 60
                last_candle_close = last_candle_open + pd.Timedelta(minutes=interval_minutes)
                
                current_time = pd.Timestamp.now(tz="Asia/Bangkok")
                
                # คำนวณ Delay จากเวลาที่แท่ง "ควรจะปิด"
                delay_mins = (current_time - last_candle_close).total_seconds() / 60
                
                logger.info(f"🕒 Last Candle Open   : {last_candle_open}")
                logger.info(f"⏱️ Current System Time: {current_time.strftime('%Y-%m-%d %H:%M:%S%z')}")
                
                if delay_mins > 0:
                    logger.warning(f"⚠️ Data Lag Detected : {delay_mins:.2f} minutes past candle close")
                else:
                    logger.info(f"✅ Data is Real-time  : We are {-delay_mins:.2f} minutes before candle close")
                
            except Exception as e:
                logger.error(f"[Debug] Failed to print OHLCV: {e}")

        # ── Step 2: Price Trend Calculation (ใช้ข้อมูลที่ปะชุนแล้ว) ──
        price_trend: dict = {}
        if ohlcv_df is not None and not ohlcv_df.empty and len(ohlcv_df) >= 2:
            try:
                closes = ohlcv_df["close"].dropna()
                c_now = float(closes.iloc[-1])
                c_prev = float(closes.iloc[-2])

                price_trend["current_close_usd"] = round(c_now, 2)
                price_trend["prev_close_usd"] = round(c_prev, 2)
                
                # คำนวณ % การเปลี่ยนแปลงของแท่งล่าสุด (15m)
                # เราใช้ชื่อ key ว่า 'change_pct' กลางๆ เพื่อให้ดึงง่าย
                if c_prev != 0:
                    price_trend["change_pct"] = round(((c_now - c_prev) / c_prev) * 100, 2)
                else:
                    price_trend["change_pct"] = 0.0

                # เก็บข้อมูลย้อนหลัง 5 และ 10 แท่ง (Periods)
                if len(closes) >= 6:
                    c_5p = float(closes.iloc[-6])
                    price_trend["5p_change_pct"] = round(((c_now - c_5p) / c_5p) * 100, 2)
                
                if len(closes) >= 11:
                    window10 = closes.tail(10)
                    price_trend["10p_range_high"] = round(float(window10.max()), 2)
                    price_trend["10p_range_low"] = round(float(window10.min()), 2)

            except Exception as _pt_err:
                logger.error(f"🚨 Price Trend Calc Error: {_pt_err}")
                price_trend = {"change_pct": 0.0} # Fallback
                
        # ── Step 3: fetch_indicators (ส่ง ohlcv_df ที่ปะราคาล่าสุดแล้วเข้าไปคำนวณ) ──
        # จุดนี้สำคัญมาก: RSI, MACD, BB จะคำนวณจากราคาล่าสุดทันที
        ind_result = call_tool(
            "fetch_indicators", ohlcv_df=ohlcv_df, interval=effective_interval
        )

        # ── Step 3.5: MTF Trend Analysis (15m + 30m) ──────────────────────────────
        # [Phase 1] ดึง OHLCV ของ 30m แยกต่างหาก แล้วคำนวณ EMA 20/50 เพื่อหา Regime
        trend_analysis: dict = {}
        try:
            from data_engine.indicators import TechnicalIndicators

            # ── 15m trend (ใช้ข้อมูลที่ดึงมาแล้ว) ──
            tf_data = {}
            if ohlcv_df is not None and not ohlcv_df.empty and len(ohlcv_df) >= 50:
                ti_15m = TechnicalIndicators(ohlcv_df)
                t15 = ti_15m.trend()
                latest_close_15m = float(ohlcv_df["close"].iloc[-1])
                tf_data["15m"] = {
                    "ema_20": t15.ema_20,
                    "ema_50": t15.ema_50,
                    "status": "bullish" if latest_close_15m > t15.ema_50 else "bearish",
                }
                logger.info(
                    f"[MTF] 15m → EMA20={t15.ema_20:.2f} EMA50={t15.ema_50:.2f} "
                    f"Close={latest_close_15m:.2f} Status={tf_data['15m']['status']}"
                )

            # ── 30m trend (ดึง OHLCV ใหม่ถ้า effective_interval ไม่ใช่ 30m) ──
            if effective_interval != "30m":
                try:
                    from data_engine.ohlcv_fetcher import OHLCVFetcher
                    fetcher_30m = OHLCVFetcher()
                    ohlcv_30m = fetcher_30m.fetch_historical_ohlcv(
                        days=min(effective_days, 60),
                        interval="30m",
                        use_cache=True,
                    )
                    if ohlcv_30m is not None and not ohlcv_30m.empty and len(ohlcv_30m) >= 50:
                        ti_30m = TechnicalIndicators(ohlcv_30m)
                        t30 = ti_30m.trend()
                        latest_close_30m = float(ohlcv_30m["close"].iloc[-1])
                        tf_data["30m"] = {
                            "ema_20": t30.ema_20,
                            "ema_50": t30.ema_50,
                            "status": "bullish" if latest_close_30m > t30.ema_50 else "bearish",
                        }
                        logger.info(
                            f"[MTF] 30m → EMA20={t30.ema_20:.2f} EMA50={t30.ema_50:.2f} "
                            f"Close={latest_close_30m:.2f} Status={tf_data['30m']['status']}"
                        )
                    else:
                        logger.warning("[MTF] 30m OHLCV insufficient data (<50 candles)")
                except Exception as e_30m:
                    logger.warning(f"[MTF] Failed to fetch 30m data: {e_30m}")
            else:
                # ถ้า effective_interval == "30m" ใช้ข้อมูลที่มีอยู่แล้ว
                if ohlcv_df is not None and not ohlcv_df.empty and len(ohlcv_df) >= 50:
                    ti_30m = TechnicalIndicators(ohlcv_df)
                    t30 = ti_30m.trend()
                    latest_close_30m = float(ohlcv_df["close"].iloc[-1])
                    tf_data["30m"] = {
                        "ema_20": t30.ema_20,
                        "ema_50": t30.ema_50,
                        "status": "bullish" if latest_close_30m > t30.ema_50 else "bearish",
                    }

            trend_analysis = tf_data
        except Exception as e_mtf:
            logger.warning(f"[MTF] Trend analysis failed — skipping: {e_mtf}")

        # ── Step 4: fetch_news & Assemble ──
        news_result = call_tool("fetch_news", max_per_category=self.max_news_per_cat)

        payload = self._assemble_payload(
            price_result,
            ind_result,
            news_result,
            effective_days,
            effective_interval,
            price_trend=price_trend,
            trend_analysis=trend_analysis,
        )

        schema_errors = validate_market_state(payload)
        if schema_errors:
            logger.error(f"🚨 Schema errors: {schema_errors}")

        if save_to_file:
            self._save(payload)

        payload["_raw_ohlcv"] = ohlcv_df
        return payload

    def _assemble_payload(self, price, ind, news, history_days, interval=None, price_trend=None, recent_trades=None, trend_analysis=None) -> dict:
        spot = price.get("spot_price_usd", {})
        thai = price.get("thai_gold_thb", {})
        ind_d = ind.get("indicators", {})
        dq = ind.get("data_quality", {})
        news_s = news.get("summary")
        if news_s is None:
            news_s = {
                "total_articles": news.get("total_articles", 0),
                "overall_sentiment": news.get("overall_sentiment", 0.0),
                "fetched_at": news.get("fetched_at", ""),
                "errors": news.get("errors", [])
            }
            
        now_thai = get_thai_time().isoformat()

        # [FIX B1] _weekend_warn อยู่ใน if block → NameError เมื่อ is_weekend=False
        # แก้: ใช้ constant ระดับ module และครอบทั้ง block ไว้ใน if
        if dq.get("is_weekend"):
            warnings = dq.setdefault("warnings", [])
            if _WEEKEND_WARN not in warnings:  # dedup
                warnings.append(_WEEKEND_WARN)
            dq.setdefault("llm_instruction", _WEEKEND_INSTRUCTION)

        # ── Normalize technical_indicators ──────────────────────────────────────
        macd_d = ind_d.get("macd", {})
        trend_d = ind_d.get("trend", {})
        if macd_d and "signal" not in macd_d:
            macd_d["signal"] = macd_d.get("crossover", "neutral")
        # if trend_d and "trend_signal" not in trend_d:
        #     trend_d["trend_signal"] = trend_d.get("trend", "neutral")
        # TODO: trend_signal reserved for future multi-signal aggregation

        # ── Primary price source: MTS API → fallback to Interceptor ────────────
        mts_price = self._fetch_mts_latest_price()
        if mts_price is not None:
            thai["sell_price_thb"] = float(mts_price)
            dq["source"] = "MTS_API"
            logger.info(f"[Orchestrator] Primary price source: MTS_API ({mts_price})")
        else:
            dq["source"] = "INTERCEPTOR_FALLBACK"
            logger.warning(
                "[Orchestrator] MTS API returned None — falling back to "
                f"Interceptor price ({thai.get('sell_price_thb')})"
            )

        # ── thai_gold_thb: เพิ่ม mid_price + timestamp ─────────────────────────
        sell = thai.get("sell_price_thb", 0)
        buy = thai.get("buy_price_thb", 0)
        thai.setdefault(
            "mid_price_thb", round((sell + buy) / 2, 2) if sell and buy else 0
        )
        thai.setdefault("timestamp", thai.get("timestamp", now_thai))
        # [FIX v11-B] spread = sell - buy (positive)
        # thai["sell_price_thb"] = ราคาที่ร้านขาย = คุณจ่าย = สูงกว่า (71,104)
        # thai["buy_price_thb"]  = ราคาที่ร้านซื้อ = คุณได้รับ = ต่ำกว่า (71,080)
        # spread = sell - buy = 71,104 - 71,080 = +24 THB ✅
        # [v2 comment ผิด: "buy - sell (positive)" จริงๆ ได้ -24 ทำให้ edge_score = 0 ตลอด]
        spread_thb = round(max(0.0, float(sell) - float(buy)), 2) if sell and buy else 0.0
        effective_spread = spread_thb

        # [FIX v11] ATR-based expected_move — แก้ bug ที่ใช้ single-candle % change
        # ❌ เดิม: ref_price × 0.01% = ~7 THB → edge=0.07 (ต่ำเกินจริงในช่วง low-volatility candle)
        # ✅ ใหม่: ATR สะท้อน volatility จริงของ session → ~111 THB → edge=1.18 ผ่าน threshold
        trend_change_pct = abs(float((price_trend or {}).get("change_pct", 0.0) or 0.0))
        ref_price = float(thai.get("mid_price_thb") or buy or 0.0)
        atr_thb = float((ind_d or {}).get("atr", {}).get("value", 0) or 0)

        if atr_thb > 0:
            expected_move_thb = round(atr_thb, 2)
            _move_method = "ATR"
        elif ref_price > 0 and trend_change_pct > 0:
            expected_move_thb = round(ref_price * (trend_change_pct / 100.0), 2)
            _move_method = "candle_pct_fallback"
        else:
            expected_move_thb = 0.0
            _move_method = "zero"

        edge_score = round((expected_move_thb / effective_spread), 4) if effective_spread > 0 else 0.0
        logger.info(
            "[EdgeScore] method=%s atr=%.0f candle_pct=%.4f%% expected_move=%.2f THB "
            "spread=%.2f THB edge=%.4f",
            _move_method, atr_thb, trend_change_pct, expected_move_thb, effective_spread, edge_score,
        )

        # ── forex: [FIX B5] รับ source จาก fetch_price ด้วย ──────────────────
        forex_data = price.get("forex", {})
        usd_thb_val = forex_data.get("usd_thb", 0.0)
        _src = (
            forex_data.get("source")
            or forex_data.get("usd_thb_source")
            or forex_data.get("provider")
            or price.get("data_sources", {}).get("forex")
            or "unknown"
        )
        forex = {
            "usd_thb": float(usd_thb_val),
            "source": _src,
        }

        # ── Transform news ───────────────────────────────────────────────────────
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
                for a in articles[:2]:
                    title = a.get("title", "") if isinstance(a, dict) else str(a)
                    if title:
                        latest_news.append(f"[{cat_name}] {title}")

        latest_news = latest_news[:10]

        effective_interval = interval or self.interval
        daily_target_entries = 3  # [FIX v2] 6→3 rounds/day
        
        # [v12] 3 slots: early=0.60, mid=0.63, late=0.67 (ลด ~3% ต่อ slot)

        return {
            "meta": {
                "agent": "gold-trading-agent",
                "version": "1.3.0",
                "generated_at": now_thai,
                "history_days": history_days,
                "interval": effective_interval,  # [FIX B2]
                "data_mode": "live",
            },
            "data_quality": dq,
            "data_sources": price.get("data_sources", {}),
            "market_data": {
                "spot_price_usd": spot,
                "forex": forex,
                "thai_gold_thb": thai,
                "spread_coverage": {
                    "spread_thb": spread_thb,
                    "effective_spread": effective_spread,
                    "expected_move_thb": expected_move_thb,
                    "expected_move": expected_move_thb,
                    "edge_score": edge_score,
                    "move_method": _move_method,   # [FIX v11] ATR | candle_pct_fallback | zero
                    "atr_thb": atr_thb,            # [FIX v11] raw ATR value used
                },
                "recent_price_action": price.get("recent_price_action", []),
                "price_trend": price_trend or {},
            },
            "technical_indicators": ind_d,
            "news": {
                "summary": news_s,
                "by_category": by_cat,
                "latest_news": latest_news,
                "news_count": len(latest_news),
            },
            "trend_analysis": trend_analysis or {},   # [MTF Phase 1] 15m+30m EMA trend
            "interval": effective_interval,  # [FIX B2]
            "timestamp": now_thai,
        }

    def pack(self, full_state: dict) -> dict:
        """
        [Phase 5] สกัดเฉพาะ "essential state" สำหรับส่งเข้า LLM
        เพื่อลด Token ขนาดมหึมา และบังคับให้ LLM เรียกใช้ Tools มากขึ้น
        """
        slim = {}

        # 1. คัดลอก Key ระดับบนที่สำคัญ
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
            "dynamic_weights",
            "xgb_signal",
            "trend_analysis",    # [MTF Phase 1] 15m+30m regime data
            "market_regime",     # [MTF Phase 2] classified regime label
        ]:
            if key in full_state:
                slim[key] = full_state[key]

        slim["data_quality"] = full_state.get("data_quality", {})
        slim["technical_indicators"] = full_state.get("technical_indicators", {})

        # 2. หั่นไขมัน Market Data (ตัด Array แท่งเทียน 5 แท่งล่าสุดออก)
        md = full_state.get("market_data", {})
        slim["market_data"] = {
            "spot_price_usd": md.get("spot_price_usd", {}),
            "forex": md.get("forex", {}),
            "thai_gold_thb": md.get("thai_gold_thb", {}),
            "spread_coverage": md.get("spread_coverage", {}),
            "price_trend": md.get("price_trend", {}),
        }

        # 3. หั่นไขมัน News (เอาแค่พาดหัว ไม่เอา Summary และเนื้อหาเต็ม)
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
            logger.info(f"Saved: {fp}")
