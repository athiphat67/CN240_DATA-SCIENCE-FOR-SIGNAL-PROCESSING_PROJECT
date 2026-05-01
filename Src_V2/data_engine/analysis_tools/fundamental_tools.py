import io
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import httpx
import asyncio

import pandas as pd
import requests

logger = logging.getLogger(__name__)


# ─── News Relevance Helper ──────────────────────────────────────────────────

# คำสำคัญต่อ category สำหรับตรวจ relevance ของแต่ละบทความ
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "gold_price":        ["gold", "xau", "bullion", "precious metal", "spot gold"],
    "usd_thb":           ["usd", "thb", "baht", "dollar", "thai baht", "usd/thb"],
    "fed_policy":        ["fed", "fomc", "federal reserve", "interest rate", "powell", "rate hike", "rate cut"],
    "inflation":         ["inflation", "cpi", "pce", "price index", "deflation", "consumer price"],
    "geopolitics":       ["war", "conflict", "sanction", "geopolitic", "tension", "ukraine", "middle east", "israel"],
    "dollar_index":      ["dxy", "dollar index", "usd index", "dollar strength", "dollar weakness"],
    "thai_economy":      ["thailand", "thai economy", "bot", "bank of thailand", "set index", "thai gdp"],
    "thai_gold_market":  ["ทอง", "ราคาทอง", "สมาคมค้าทองคำ", "gold association", "thai gold"],
}


def _compute_news_relevance(articles: list[dict], category: str) -> float:
    """
    คำนวณ relevance_score (0.0–1.0) จากสัดส่วนบทความที่มีคำสำคัญของ category

    Logic:
        - นับบทความที่ title หรือ summary มีคำสำคัญ ≥ 1 คำ
        - score = matched / total  (0.0 ถ้าไม่มีบทความ)
        - ถ้าไม่รู้จัก category → คืน 0.5 เป็น neutral fallback
    """
    if not articles:
        return 0.0

    keywords = _CATEGORY_KEYWORDS.get(category)
    if not keywords:
        return 0.5  # category ใหม่ที่ยังไม่มี keywords → neutral

    matched = 0
    for article in articles:
        text = " ".join([
            str(article.get("title", "")),
            str(article.get("summary", "")),
            str(article.get("description", "")),
        ]).lower()
        if any(kw in text for kw in keywords):
            matched += 1

    return round(matched / len(articles), 3)


async def get_deep_news_by_category(category: str) -> dict:
    """
    🔄 WRAPPER: ดึงข่าวเจาะลึกตามหมวดหมู่ (Backward compatible)

    THIS IS NOW A WRAPPER that calls merged fetch_news() from data_engine/tools

    Categories ที่รองรับ: "gold_price", "usd_thb", "fed_policy", "inflation",
    "geopolitics", "dollar_index", "thai_economy", "thai_gold_market"

    ✅ Maintains the same input/output as before
    ✅ But now uses shared merged fetch_news() underneath
    """
    logger.info(f"🔍 [TOOL] get_deep_news_by_category: {category}")

    # ─────────────────────────────────────────────────────────────
    # Import merged fetch_news from data_engine
    # ─────────────────────────────────────────────────────────────
    try:
        from data_engine.tools.fetch_news import fetch_news as fetch_news_merged
    except ImportError:
        logger.error("[TOOL] Failed to import merged fetch_news from data_engine.tools")
        return {
            "status": "error",
            "message": "Could not load news fetcher - import failed",
        }

    # ─────────────────────────────────────────────────────────────
    # Call merged fetch_news with deep dive parameters
    # ─────────────────────────────────────────────────────────────
    try:
        result = await fetch_news_merged(
            max_per_category=5, category_filter=category, detail_level="deep"
        )

        # ─────────────────────────────────────────────────────────────
        # Transform result to maintain backward compatibility
        # ─────────────────────────────────────────────────────────────
        if "deep_news" in result and result.get("error") is None:
            articles = result["deep_news"].get("articles", [])
            count    = result["deep_news"].get("count", 0)
            return {
                "status": "success",
                "category": category,
                "articles": articles,
                "count": count,
                "relevance_score": _compute_news_relevance(articles, category),
            }
        elif "deep_news_error" in result:
            return {
                "status": "error",
                "message": result.get("deep_news_error", "Unknown error"),
            }
        else:
            # Fallback if structure is different
            return {
                "status": "success",
                "category": category,
                "articles": [],
                "count": 0,
                "note": "No articles found for this category",
            }

    except Exception as e:
        logger.error(f"Error in get_deep_news_by_category: {e}")
        return {"status": "error", "message": str(e)}


async def check_upcoming_economic_calendar(hours_ahead: int = 24) -> dict:
    """
    เช็คปฏิทินเศรษฐกิจ (Economic Calendar) ล่วงหน้าจาก ForexFactory JSON
    เพื่อหา "ข่าวกล่องแดง" (High Impact) เช่น Non-Farm (NFP), CPI, การประชุม FOMC
    เหตุผลที่ LLM ควรใช้: หากใกล้เวลาข่าวออก เอเจนต์ควรหลีกเลี่ยงการเข้าเทรด หรือตัดสินใจปิดออเดอร์เพื่อลดความเสี่ยง

    ตย. output
    {
        "status": "success",
        "source": "forexfactory_json",
        "risk_level": "critical",
        "hours_checked": 24,
        "high_impact_usd_count": 2,
        "events": [
            {
                "title": "Non-Farm Employment Change",
                "country": "USD",
                "impact": "High",
                "datetime_utc": "2024-07-05T12:30:00+00:00",
                "hours_until": 1.5,
                "forecast": "180K",
                "previous": "175K"
            }
        ],
        "interpretation": "🔴 CRITICAL: NFP ออกอีก 1.5 ชม. → ห้ามเปิดออเดอร์ใหม่!"
    }
    ═══════════════════════════════════════════════════════════════════
    """
    logger.info(
        f"📅 [TOOL] check_upcoming_economic_calendar: ดูข่าวล่วงหน้า {hours_ahead} ชม..."
    )

    # ── Step 1: FETCH JSON ─────────────────────────────────────────
    FF_JSON_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

    try:
        # 🚀 เปลี่ยนจากการใช้ requests.get เป็น httpx.AsyncClient
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                FF_JSON_URL,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            resp.raise_for_status()
            events_raw = resp.json()
            logger.debug(f"📥 ForexFactory JSON: ดึงข้อมูลสำเร็จ {len(events_raw)} ข่าว")
            
    except Exception as e:
        logger.warning(f"⚠️ ForexFactory JSON fetch failed: {e}")
        return {
            "status": "error",
            "message": f"ไม่สามารถดึงปฏิทินเศรษฐกิจจาก ForexFactory ได้: {e}",
        }

    if not events_raw:
        return {
            "status": "success",
            "risk_level": "low",
            "hours_checked": hours_ahead,
            "high_impact_usd_count": 0,
            "events": [],
            "interpretation": "ไม่พบข่าวเศรษฐกิจในปฏิทินสัปดาห์นี้",
        }

    # ── Step 2: PARSE + CONVERT TIMEZONE ───────────────────────────
    # JSON "date" field มาเป็น ISO-8601 พร้อม offset เช่น "2024-07-05T08:30:00-04:00"
    # datetime.fromisoformat() รับรู้ offset แล้วแปลง → UTC ได้ทันที
    now_utc = datetime.now(timezone.utc)
    cutoff_utc = now_utc + timedelta(hours=hours_ahead)
    GOLD_RELEVANT_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "CNY", "CHF"}

    parsed_events = []

    for ev in events_raw:
        # ── กรองสกุลเงินก่อน (ลดงาน parse ที่ไม่จำเป็น) ──
        country = ev.get("country", "")
        if country not in GOLD_RELEVANT_CURRENCIES:
            continue

        date_str = ev.get("date", "")
        time_str = ev.get("time", "")
        impact = ev.get("impact", "")
        is_tentative = time_str in ("All Day", "Tentative", "")

        # ── แปลง ISO-8601 → UTC datetime ──
        try:
            dt_aware = datetime.fromisoformat(date_str)
            dt_utc = dt_aware.astimezone(timezone.utc)
        except (ValueError, TypeError):
            continue

        # ── Tentative: เก็บเฉพาะ High USD (อาจสำคัญแม้ไม่มีเวลาแน่ชัด) ──
        if is_tentative:
            if impact == "High" and country == "USD":
                parsed_events.append(
                    {
                        "title": ev.get("title", ""),
                        "country": country,
                        "impact": impact,
                        "datetime_utc": None,
                        "hours_until": None,
                        "forecast": ev.get("forecast", ""),
                        "previous": ev.get("previous", ""),
                        "is_tentative": True,
                    }
                )
            continue

        # ── กรองตามเวลา: เฉพาะ events ภายใน window ──
        if dt_utc < now_utc or dt_utc > cutoff_utc:
            continue

        hours_until = round((dt_utc - now_utc).total_seconds() / 3600, 1)

        parsed_events.append(
            {
                "title": ev.get("title", ""),
                "country": country,
                "impact": impact,
                "datetime_utc": dt_utc.isoformat(),
                "hours_until": hours_until,
                "forecast": ev.get("forecast", ""),
                "previous": ev.get("previous", ""),
                "is_tentative": False,
            }
        )

    # ── Step 3: CLASSIFY RISK ──────────────────────────────────────
    # แยกข่าวตามระดับ impact แล้วประเมิน risk
    #
    # critical: ข่าว High USD ≤ 2 ชม. → ห้ามเทรด!
    # high:     ข่าว High USD ใน window → ระวัง ลด position
    # medium:   ข่าว Medium หรือ High สกุลอื่น → เทรดได้แต่ระวัง
    # low:      ไม่มีข่าวสำคัญ → เทรดได้ปกติ
    high_usd = [
        ev
        for ev in parsed_events
        if ev["impact"] == "High" and ev["country"] == "USD" and not ev["is_tentative"]
    ]
    high_other = [
        ev for ev in parsed_events if ev["impact"] == "High" and ev["country"] != "USD"
    ]
    medium_all = [ev for ev in parsed_events if ev["impact"] == "Medium"]

    risk_level = "low"
    if high_usd:
        imminent = [
            ev
            for ev in high_usd
            if ev.get("hours_until") is not None and ev["hours_until"] <= 2.0
        ]
        if imminent:
            risk_level = "critical"
        else:
            risk_level = "high"
    elif high_other or medium_all:
        risk_level = "medium"

    # ── เรียง events ตามเวลา (ใกล้สุดก่อน) ──
    parsed_events.sort(key=lambda x: x.get("hours_until") or 999)

    # ── Step 4: INTERPRETATION ─────────────────────────────────────
    interpretation = _interpret_calendar(
        risk_level, high_usd, high_other, medium_all, hours_ahead
    )

    # ── Step 3b: MAP risk_level → trade guidance ──────────────────
    _TRADE_GUIDANCE = {
        "critical": (False, "avoid",   "ห้ามเปิดออเดอร์ใหม่ — ข่าว High Impact ใกล้ออก"),
        "high":     (False, "reduce",  "ลด position / งด open trade ใหม่"),
        "medium":   (True,  "caution", "เทรดได้แต่ระวัง volatility"),
        "low":      (True,  "proceed", "ไม่มีข่าวสำคัญ — เทรดตาม technical ได้เลย"),
    }
    is_safe_to_trade, trade_action, trade_note = _TRADE_GUIDANCE.get(
        risk_level, (True, "proceed", "")
    )

    result = {
        "status": "success",
        "source": "forexfactory_json",
        "risk_level": risk_level,
        "is_safe_to_trade": is_safe_to_trade,   # False → scorer/orchestrator ควรหยุด
        "trade_action": trade_action,            # "avoid" | "reduce" | "caution" | "proceed"
        "trade_note": trade_note,
        "hours_checked": hours_ahead,
        "high_impact_usd_count": len(high_usd),
        "high_impact_other_count": len(high_other),
        "medium_impact_count": len(medium_all),
        "total_relevant_events": len(parsed_events),
        "events": parsed_events[:15],  # จำกัด 15 events ป้องกัน prompt ยาวเกิน
        "interpretation": interpretation,
    }

    logger.info(
        f"✅ Calendar: risk={risk_level} | "
        f"High USD: {len(high_usd)}, High other: {len(high_other)}, "
        f"Medium: {len(medium_all)} | window={hours_ahead}h"
    )
    return result


# ─── Calendar Helper Functions ─────────────────────────────────────────────


def _interpret_calendar(
    risk_level: str,
    high_usd: list,
    high_other: list,
    medium_all: list,
    hours_ahead: int,
) -> str:
    """
    สร้างข้อความสรุปปฏิทินเศรษฐกิจสำหรับ LLM

    Logic:
      - critical → เตือนอย่างแรงว่าห้ามเทรด
      - high     → แนะนำให้ลด position / ไม่เปิดออเดอร์ใหม่
      - medium   → เทรดได้แต่ระวังสวิง
      - low      → ปลอดภัย เทรดตาม technical ได้เลย
    """
    parts = []

    if risk_level == "critical":
        # หาข่าวที่ใกล้ที่สุด
        nearest = min(
            (ev for ev in high_usd if ev.get("hours_until") is not None),
            key=lambda x: x["hours_until"],
            default=None,
        )
        if nearest:
            parts.append(
                f"🔴 CRITICAL: {nearest['title']} (USD High Impact) "
                f"ออกอีก {nearest['hours_until']:.1f} ชม. → ห้ามเปิดออเดอร์ใหม่! "
                "ถ้าถือทองอยู่ ควรพิจารณาปิดก่อนข่าวออก"
            )
        else:
            parts.append("🔴 CRITICAL: มีข่าว High Impact USD ใกล้จะออก → ห้ามเทรด!")

    elif risk_level == "high":
        titles = [ev["title"] for ev in high_usd[:3]]
        parts.append(
            f"🟠 HIGH RISK: มีข่าว USD High Impact {len(high_usd)} รายการ "
            f"({', '.join(titles)}) ภายใน {hours_ahead} ชม. → "
            "ไม่ควรเปิดออเดอร์ใหม่ หรือเปิดด้วย position เล็กลง"
        )

    elif risk_level == "medium":
        count = len(high_other) + len(medium_all)
        parts.append(
            f"🟡 MEDIUM RISK: มีข่าว Medium/High impact {count} รายการ → "
            "เทรดได้แต่ระวัง volatility spike ช่วงข่าวออก"
        )

    else:
        parts.append(
            f"🟢 LOW RISK: ไม่มีข่าวสำคัญใน {hours_ahead} ชม. ข้างหน้า → "
            "เทรดตาม technical signal ได้ตามปกติ"
        )

    return " | ".join(parts)


async def get_intermarket_correlation() -> dict:
    """
    ตรวจสอบความสัมพันธ์ข้ามตลาด (Intermarket Analysis)
    ดึงข้อมูลดัชนีดอลลาร์ (DXY) และผลตอบแทนพันธบัตรรัฐบาลสหรัฐอายุ 10 ปี (US10Y)
    เหตุผลที่ LLM ควรใช้: ทองคำมักวิ่งสวนทางกับ DXY และ US10Y ถ้าราคาทองขึ้นแต่ DXY ก็ขึ้นด้วย แสดงว่ามีความผิดปกติ

    ตย. output
    {
        "status": "success",
        "gold": {"price_usd": 3230.50, "change_1d_pct": +0.45, "change_5d_pct": +1.2},
        "dxy": {"value": 104.32, "change_1d_pct": +0.18, "change_5d_pct": -0.5},
        "us10y": {"yield_pct": 4.35, "change_1d_pct": -0.12},
        "correlation_20d": {"gold_vs_dxy": -0.52, "gold_vs_us10y": -0.38},
        "correlation_regime": {"gold_dxy": "normal_inverse", "gold_us10y": "normal_inverse"},
        "divergences": [{"pair": "gold_vs_DXY", "status": "bearish_warning", "note": "..."}],
        "interpretation": "⚠️ Gold ↑+0.45% + DXY ↑+0.18% → ผิดปกติ ทองอาจกลับลง"
    }
    ═══════════════════════════════════════════════════════════════════
    """
    logger.info("🌐 [TOOL] get_intermarket_correlation: ดึงข้อมูล DXY + US10Y...")

    # ── Step 1: FETCH DATA ─────────────────────────────────────────
    # ดึงราคาย้อนหลัง 20 วัน เพื่อคำนวณ correlation ที่มีนัยสำคัญ
    # ใช้ period="1mo" เผื่อวันหยุดตลาด จะได้ข้อมูลจริง ≥ 20 แท่ง
    try:
        import yfinance as yf
    except ImportError:
        return {"status": "error", "message": "yfinance not installed"}

    tickers = {"gold": "GC=F", "dxy": "DX-Y.NYB", "us10y": "^TNX"}
    
    # 🚀 สร้างฟังก์ชันย่อยสำหรับการดึง yfinance เพื่อโยนเข้า Thread
    def _fetch_all_yf():
        temp_dfs = {}
        for key, symbol in tickers.items():
            try:
                ticker_obj = yf.Ticker(symbol)
                df = ticker_obj.history(period="1mo")
                if not df.empty and len(df) >= 5:
                    temp_dfs[key] = df
            except Exception:
                pass
        return temp_dfs

    # 🚀 เรียกใช้ yfinance ผ่าน to_thread (เพื่อให้มันไม่บล็อกระบบ)
    dfs = await asyncio.to_thread(_fetch_all_yf)
    
    for key, symbol in tickers.items():
        try:
            ticker_obj = yf.Ticker(symbol)
            df = ticker_obj.history(period="1mo")
            if df.empty or len(df) < 5:
                logger.warning(f"⚠️ {key} ({symbol}): ข้อมูลไม่เพียงพอ ({len(df)} rows)")
                continue
            dfs[key] = df
            logger.debug(f"✅ {key}: {len(df)} rows, last={df.index[-1].date()}")
        except Exception as e:
            logger.warning(f"⚠️ {key} ({symbol}) fetch failed: {e}")

    # ── ต้องมีอย่างน้อย Gold + 1 ตัวอื่น ────────────────────────
    if "gold" not in dfs:
        print('นี้จ้า error')
        return {
            "status": "error",
            "message": "ไม่สามารถดึงราคาทองคำ (GC=F) ได้",
        }
    if "dxy" not in dfs and "us10y" not in dfs:
        return {
            "status": "error",
            "message": "ไม่สามารถดึง DXY หรือ US10Y ได้เลย",
        }

    # ── Step 2: COMPUTE % CHANGE ───────────────────────────────────
    # คำนวณ % change วันล่าสุด (1d) และย้อนหลัง 5 วัน (5d)
    # ใช้ราคาปิด (Close) เป็นตัวแทน
    def _pct_changes(df: pd.DataFrame) -> dict:
        """คำนวณ % change 1d และ 5d จาก DataFrame"""
        closes = df["Close"].dropna()
        if len(closes) < 2:
            return {"latest": None, "pct_1d": None, "pct_5d": None}

        latest = float(closes.iloc[-1])
        prev = float(closes.iloc[-2])
        pct_1d = round((latest - prev) / prev * 100, 3)

        pct_5d = None
        if len(closes) >= 6:
            five_ago = float(closes.iloc[-6])
            pct_5d = round((latest - five_ago) / five_ago * 100, 3)

        return {"latest": round(latest, 4), "pct_1d": pct_1d, "pct_5d": pct_5d}

    gold_chg = _pct_changes(dfs["gold"])
    dxy_chg = _pct_changes(dfs["dxy"]) if "dxy" in dfs else {}
    us10y_chg = _pct_changes(dfs["us10y"]) if "us10y" in dfs else {}

    # ── Step 3: CORRELATION MATRIX (20 วัน) ────────────────────────
    # ใช้ daily % return แทนราคาดิบ เพราะราคาดิบมี scale ต่างกัน
    # Pearson correlation ของ % return บอก co-movement ได้ดีกว่า
    gold_returns = dfs["gold"]["Close"].pct_change().dropna()

    cor_gold_dxy = None
    cor_gold_us10y = None

    if "dxy" in dfs:
        dxy_returns = dfs["dxy"]["Close"].pct_change().dropna()
        # align วันให้ตรงกัน (บางวัน DXY อาจหยุดแต่ทองเปิด)
        aligned = pd.concat([gold_returns, dxy_returns], axis=1, join="inner")
        aligned.columns = ["gold", "dxy"]
        if len(aligned) >= 10:
            cor_gold_dxy = round(float(aligned["gold"].corr(aligned["dxy"])), 3)
            logger.debug(f"Correlation Gold-DXY (20d): {cor_gold_dxy}")

    if "us10y" in dfs:
        us10y_returns = dfs["us10y"]["Close"].pct_change().dropna()
        aligned = pd.concat([gold_returns, us10y_returns], axis=1, join="inner")
        aligned.columns = ["gold", "us10y"]
        if len(aligned) >= 10:
            cor_gold_us10y = round(float(aligned["gold"].corr(aligned["us10y"])), 3)
            logger.debug(f"Correlation Gold-US10Y (20d): {cor_gold_us10y}")

    # ── Step 4: DETECT DIVERGENCE ──────────────────────────────────
    # ตรวจว่าทองกับ DXY/US10Y วิ่งทิศเดียวกันไหม (ผิดปกติ)
    #
    # หลักการ:
    #   ปกติ: Gold ↑ + DXY ↓ (สวนทาง)     → "normal"
    #   ผิดปกติ: Gold ↑ + DXY ↑ (ทิศเดียว) → "bearish_warning" ทองอาจจะกลับลง
    #   ผิดปกติ: Gold ↓ + DXY ↓ (ทิศเดียว) → "bullish_warning" ทองอาจจะกลับขึ้น

    divergences = []

    def _detect_div(
        gold_pct: float | None,
        other_pct: float | None,
        other_name: str,
    ) -> dict | None:
        """ตรวจ divergence ระหว่าง Gold กับ asset อื่น"""
        if gold_pct is None or other_pct is None:
            return None
        # threshold: ≥ 0.1% ถือว่าเคลื่อนไหวจริง (กรอง noise)
        if abs(gold_pct) < 0.1 and abs(other_pct) < 0.1:
            return {"pair": f"gold_vs_{other_name}", "status": "flat", "note": "ทั้งคู่นิ่ง"}

        same_direction = (gold_pct > 0 and other_pct > 0) or (
            gold_pct < 0 and other_pct < 0
        )

        if same_direction:
            # ทิศเดียวกัน = ผิดปกติ
            if gold_pct > 0:
                return {
                    "pair": f"gold_vs_{other_name}",
                    "status": "bearish_warning",
                    "note": f"Gold ↑{gold_pct:+.2f}% + {other_name} ↑{other_pct:+.2f}% → ผิดปกติ ทองอาจกลับลง",
                }
            else:
                return {
                    "pair": f"gold_vs_{other_name}",
                    "status": "bullish_warning",
                    "note": f"Gold ↓{gold_pct:+.2f}% + {other_name} ↓{other_pct:+.2f}% → ผิดปกติ ทองอาจกลับขึ้น",
                }
        else:
            # สวนทาง = ปกติ
            return {
                "pair": f"gold_vs_{other_name}",
                "status": "normal",
                "note": f"Gold {gold_pct:+.2f}% vs {other_name} {other_pct:+.2f}% → ปกติ (สวนทาง)",
            }

    # ตรวจ Gold vs DXY
    if dxy_chg:
        div = _detect_div(gold_chg.get("pct_1d"), dxy_chg.get("pct_1d"), "DXY")
        if div:
            divergences.append(div)

    # ตรวจ Gold vs US10Y
    if us10y_chg:
        div = _detect_div(gold_chg.get("pct_1d"), us10y_chg.get("pct_1d"), "US10Y")
        if div:
            divergences.append(div)

    # ── Correlation regime ─────────────────────────────────────────
    # ถ้า correlation 20 วัน เป็นบวก (> +0.3) = สภาวะ macro ผิดปกติ
    cor_regime_dxy = None
    if cor_gold_dxy is not None:
        if cor_gold_dxy > 0.3:
            cor_regime_dxy = "abnormal_positive"
        elif cor_gold_dxy < -0.3:
            cor_regime_dxy = "normal_inverse"
        else:
            cor_regime_dxy = "weak_or_transitioning"

    cor_regime_us10y = None
    if cor_gold_us10y is not None:
        if cor_gold_us10y > 0.3:
            cor_regime_us10y = "abnormal_positive"
        elif cor_gold_us10y < -0.3:
            cor_regime_us10y = "normal_inverse"
        else:
            cor_regime_us10y = "weak_or_transitioning"

    # ── Step 5: INTERPRETATION ─────────────────────────────────────
    # สร้างข้อความสรุปสำหรับ LLM ใช้ประกอบการตัดสินใจ
    interpretation = _interpret_intermarket(
        divergences, cor_gold_dxy, cor_gold_us10y, cor_regime_dxy, cor_regime_us10y
    )

    data_date = str(dfs["gold"].index[-1].date())

    result = {
        "status": "success",
        "source": "yfinance",
        "data_date": data_date,
        # ── ราคาและ % change ──
        "gold": {
            "price_usd": gold_chg.get("latest"),
            "change_1d_pct": gold_chg.get("pct_1d"),
            "change_5d_pct": gold_chg.get("pct_5d"),
        },
        "dxy": {
            "value": dxy_chg.get("latest"),
            "change_1d_pct": dxy_chg.get("pct_1d"),
            "change_5d_pct": dxy_chg.get("pct_5d"),
        }
        if dxy_chg
        else None,
        "us10y": {
            "yield_pct": us10y_chg.get("latest"),
            "change_1d_pct": us10y_chg.get("pct_1d"),
            "change_5d_pct": us10y_chg.get("pct_5d"),
        }
        if us10y_chg
        else None,
        # ── Correlation 20 วัน ──
        "correlation_20d": {
            "gold_vs_dxy": cor_gold_dxy,
            "gold_vs_us10y": cor_gold_us10y,
        },
        # ── Regime ──
        "correlation_regime": {
            "gold_dxy": cor_regime_dxy,
            "gold_us10y": cor_regime_us10y,
        },
        # ── Divergence signals ──
        "divergences": divergences,
        # ── สรุปสำหรับ LLM ──
        "interpretation": interpretation,
    }

    logger.info(
        f"✅ Intermarket: Gold {gold_chg.get('pct_1d', 'N/A'):+}% | "
        f"DXY {dxy_chg.get('pct_1d', 'N/A')} | "
        f"US10Y {us10y_chg.get('pct_1d', 'N/A')} | "
        f"cor_dxy={cor_gold_dxy} regime={cor_regime_dxy}"
    )
    return result


def _interpret_intermarket(
    divergences: list,
    cor_dxy: float | None,
    cor_us10y: float | None,
    regime_dxy: str | None,
    regime_us10y: str | None,
) -> str:
    """
    สร้างข้อความสรุป intermarket analysis สำหรับ LLM

    Logic:
      - ถ้ามี divergence (bearish/bullish warning) → เตือน LLM
      - ถ้า correlation regime เป็น abnormal_positive → เตือน macro ผิดปกติ
      - ถ้าทุกอย่างปกติ → บอกว่า intermarket สนับสนุนเทรนด์ปัจจุบัน
    """
    parts = []

    # ── รวม divergence warnings ──
    warnings = [
        d for d in divergences if d["status"] in ("bearish_warning", "bullish_warning")
    ]
    normals = [d for d in divergences if d["status"] == "normal"]

    for w in warnings:
        parts.append(f"⚠️ {w['note']}")

    # ── Correlation regime warnings ──
    if regime_dxy == "abnormal_positive":
        parts.append(
            f"Correlation Gold-DXY = {cor_dxy:+.2f} (บวกผิดปกติ) → "
            "ระวัง macro shift อาจเกิด reversal"
        )
    if regime_us10y == "abnormal_positive":
        parts.append(
            f"Correlation Gold-US10Y = {cor_us10y:+.2f} (บวกผิดปกติ) → "
            "yield กับทองวิ่งทิศเดียวกัน สภาวะ risk-off"
        )

    # ── ถ้าปกติทั้งหมด ──
    if not parts:
        if normals:
            parts.append(
                "Intermarket ปกติ: Gold สวนทาง DXY/US10Y ตามทฤษฎี → สนับสนุนเทรนด์ปัจจุบัน"
            )
        else:
            parts.append("ข้อมูล Intermarket ไม่เพียงพอสำหรับวิเคราะห์")

    return " | ".join(parts)


# def check_fed_speakers_schedule() -> dict:
#     """
#     ตรวจสอบตารางการให้สัมภาษณ์ของคณะกรรมการธนาคารกลางสหรัฐ (Fed Speakers) ประจำวัน
#     เหตุผลที่ LLM ควรใช้: คำพูดหลุดกรอบ (Hawkish/Dovish) นอกตาราง มักทำให้ทองคำสวิงรุนแรงโดยไม่มีกราฟเตือนล่วงหน้า
#     """
#     return {"status": "not_implemented", "message": "รอการพัฒนาเพิ่มเติม"}


# def get_institutional_positioning() -> dict:
#     """
#     ดึงข้อมูล COT Report (Commitments of Traders) ที่ออกรายสัปดาห์
#     ดูว่ากองทุนและสถาบันใหญ่ๆ มีสถานะ Net Long หรือ Net Short ทองคำอยู่เท่าไหร่
#     เหตุผลที่ LLM ควรใช้: ใช้ประเมินเทรนด์ระยะกลาง-ยาว เพื่อดูว่าตลาดมีมุมมอง (Bias) ไปทางไหน
#     """
#     return {"status": "not_implemented", "message": "รอการพัฒนาเพิ่มเติม"}


# ─── Gold ETF Flow Constants ────────────────────────────────────────────────
SPDR_XLSX_URL = (
    "https://api.spdrgoldshares.com/api/v1/historical-archive"
    "?product=gld&exchange=NYSE&lang=en"
)
_CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache"
_GLD_CACHE_FILE = _CACHE_DIR / "gld_spdr_archive.xlsx"
_GLD_CACHE_MAX_AGE = 12 * 3600  # 12 ชั่วโมง
_TROY_OZ_PER_TONNE = 32_150.7


# ═════════════════════════════════════════════════════════════════════════════
# get_gold_etf_flow — SPDR Gold Trust (GLD) Institutional Flow Tracker
# ═════════════════════════════════════════════════════════════════════════════


def get_gold_etf_flow() -> dict:
    """
    ดึงข้อมูล Gold ETF Flow จาก SPDR Gold Trust (GLD)
    Primary: SPDR Historical XLSX → ดูการเปลี่ยนแปลง Ounces in Trust (institutional flow จริง)
    Fallback: yfinance GLD → ดู Volume anomaly

    LLM ใช้ประกอบการตัดสินใจ:
    - Ounces เพิ่ม (inflow) → สถาบันสะสมทอง = Bullish
    - Ounces ลด (outflow) → สถาบันเทขาย = Bearish
    - Volume spike > 2x avg → สถาบันกำลังเคลื่อนไหว
    ตย. Output
    {
        "status": "success",
        "source": "spdr_xlsx",
        "ounces_in_trust": 28500000.0,
        "ounces_change_1d": 45000.0,
        "tonnes_in_trust": 886.45,
        "tonnes_change_1d": 1.40,
        "flow_direction": "inflow",
        "institutional_signal": "accumulating",
        "interpretation": "สถาบันเพิ่มทอง 1.40 ตัน (Bullish signal) | 5 วันย้อนหลัง: สะสม 3.20 ตัน"
    }
    """
    logger.info("🏦 [TOOL] get_gold_etf_flow: ดึงข้อมูล GLD ETF Flow...")

    # ── Layer 1: SPDR XLSX (Primary — institutional flow จริง) ──
    spdr_result = _fetch_spdr_holdings()
    if spdr_result is not None:
        return spdr_result

    # ── Layer 2: yfinance GLD (Fallback — volume anomaly) ──
    yf_result = _fetch_yfinance_gld()
    if yf_result is not None:
        return yf_result

    return {
        "status": "error",
        "message": "ไม่สามารถดึงข้อมูล Gold ETF ได้จากทุกแหล่ง (SPDR + yfinance)",
    }


# ─── Layer 1: SPDR XLSX ─────────────────────────────────────────────────────


def _fetch_spdr_holdings() -> dict | None:
    """ดาวน์โหลด SPDR Historical XLSX แล้ว parse ข้อมูล Ounces in Trust"""
    try:
        xlsx_bytes = None

        # ── ตรวจ cache ก่อน ──
        if _GLD_CACHE_FILE.exists():
            age = time.time() - _GLD_CACHE_FILE.stat().st_mtime
            if age < _GLD_CACHE_MAX_AGE:
                logger.info("📂 ใช้ SPDR XLSX จาก cache")
                xlsx_bytes = _GLD_CACHE_FILE.read_bytes()

        # ── ดาวน์โหลดใหม่ถ้าไม่มี cache ──
        if xlsx_bytes is None:
            logger.info("⬇️ กำลังดาวน์โหลด SPDR Historical XLSX...")
            resp = requests.get(
                SPDR_XLSX_URL,
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            resp.raise_for_status()
            xlsx_bytes = resp.content

            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            _GLD_CACHE_FILE.write_bytes(xlsx_bytes)
            logger.info(f"💾 บันทึก cache SPDR XLSX ({len(xlsx_bytes):,} bytes)")

        # ── Parse ──
        # ข้อมูลจริงอยู่ sheet 'US GLD Historical Archive' (sheet 0 = Disclaimer)
        df = pd.read_excel(
            io.BytesIO(xlsx_bytes),
            sheet_name="US GLD Historical Archive",
            engine="openpyxl",
        )
        return _parse_spdr_dataframe(df)

    except Exception as e:
        logger.warning(f"⚠️ SPDR XLSX failed: {e}")
        return None


def _find_column(df: pd.DataFrame, keywords: list[str]) -> str | None:
    """หา column name ที่มี keyword ทุกตัวอยู่ (case-insensitive)"""
    for col in df.columns:
        col_lower = str(col).lower()
        if all(kw.lower() in col_lower for kw in keywords):
            return col
    return None


def _parse_spdr_dataframe(df: pd.DataFrame) -> dict | None:
    """Parse SPDR XLSX DataFrame เพื่อหา holdings change"""
    try:
        # ── หา column ด้วย keyword matching (รองรับชื่อเปลี่ยน) ──
        # ※ ต้องใช้ ["total", "ounces"] ไม่ใช่ ["ounces"] อย่างเดียว
        #   เพราะ XLSX มี 'Ounces of Gold per Share' (~0.09) ด้วย
        #   เราต้องการ 'Total Ounces of Gold in the Trust' (~33M)
        date_col = _find_column(df, ["date"]) or df.columns[0]
        ounces_col = _find_column(df, ["total", "ounces"])
        tonnes_col = _find_column(df, ["tonnes"])
        volume_col = _find_column(df, ["volume"]) or _find_column(
            df, ["share", "volume"]
        )
        close_col = _find_column(df, ["closing"]) or _find_column(df, ["close"])
        nav_col = _find_column(df, ["total", "net", "asset"])

        if ounces_col is None:
            logger.warning("ไม่พบคอลัมน์ 'Ounces in Trust' ใน SPDR XLSX")
            logger.debug(f"Columns found: {list(df.columns)}")
            return None

        # ── ทำความสะอาดข้อมูล ──
        df[ounces_col] = pd.to_numeric(
            df[ounces_col].astype(str).str.replace(",", ""), errors="coerce"
        )
        df = df.dropna(subset=[ounces_col])

        if len(df) < 2:
            logger.warning("SPDR XLSX: ข้อมูลน้อยกว่า 2 แถว")
            return None

        # ── เปรียบเทียบวันล่าสุด vs วันก่อนหน้า ──
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        oz_today = float(latest[ounces_col])
        oz_prev = float(prev[ounces_col])
        oz_change = oz_today - oz_prev

        # ── Tonnes: ใช้จาก XLSX โดยตรง ถ้ามี (แม่นกว่าคำนวณเอง) ──
        if tonnes_col:
            df[tonnes_col] = pd.to_numeric(
                df[tonnes_col].astype(str).str.replace(",", ""), errors="coerce"
            )
            tonnes_today = (
                float(latest[tonnes_col])
                if pd.notna(latest[tonnes_col])
                else oz_today / _TROY_OZ_PER_TONNE
            )
            tonnes_prev = (
                float(prev[tonnes_col])
                if pd.notna(prev[tonnes_col])
                else oz_prev / _TROY_OZ_PER_TONNE
            )
            tonnes_change = tonnes_today - tonnes_prev
        else:
            tonnes_today = oz_today / _TROY_OZ_PER_TONNE
            tonnes_change = oz_change / _TROY_OZ_PER_TONNE

        # ── ดู Net change 5 วัน (ถ้ามีข้อมูลพอ) ──
        oz_5d_ago = float(df.iloc[-6][ounces_col]) if len(df) >= 6 else None
        oz_change_5d = (oz_today - oz_5d_ago) if oz_5d_ago else None
        tonnes_change_5d = (oz_change_5d / _TROY_OZ_PER_TONNE) if oz_change_5d else None

        # ── ประเมินทิศทาง ──
        if oz_change > 1000:
            flow_direction = "inflow"
            institutional_signal = "accumulating"
        elif oz_change < -1000:
            flow_direction = "outflow"
            institutional_signal = "distributing"
        else:
            flow_direction = "flat"
            institutional_signal = "neutral"

        # ── Volume (ถ้ามี) ──
        vol_today = None
        vol_avg_10d = None
        vol_ratio = None
        if volume_col:
            df[volume_col] = pd.to_numeric(
                df[volume_col].astype(str).str.replace(",", ""), errors="coerce"
            )
            vol_today = (
                int(latest[volume_col]) if pd.notna(latest[volume_col]) else None
            )
            if len(df) >= 10:
                vol_avg_10d = int(df[volume_col].tail(10).mean())
                if vol_avg_10d and vol_avg_10d > 0 and vol_today:
                    vol_ratio = round(vol_today / vol_avg_10d, 2)

        # ── GLD Close (ถ้ามี) ──
        gld_close = None
        if close_col:
            raw_close = pd.to_numeric(
                str(latest[close_col]).replace(",", ""), errors="coerce"
            )
            gld_close = round(float(raw_close), 2) if pd.notna(raw_close) else None

        # ── Date ──
        data_date = str(latest[date_col]) if pd.notna(latest[date_col]) else "unknown"

        result = {
            "status": "success",
            "source": "spdr_xlsx",
            "data_date": data_date,
            "ounces_in_trust": round(oz_today, 2),
            "ounces_change_1d": round(oz_change, 2),
            "ounces_change_5d": round(oz_change_5d, 2) if oz_change_5d else None,
            "tonnes_in_trust": round(tonnes_today, 2),
            "tonnes_change_1d": round(tonnes_change, 2),
            "tonnes_change_5d": round(tonnes_change_5d, 2)
            if tonnes_change_5d
            else None,
            "flow_direction": flow_direction,
            "institutional_signal": institutional_signal,
            "gld_close_usd": gld_close,
            "volume_today": vol_today,
            "volume_avg_10d": vol_avg_10d,
            "volume_ratio": vol_ratio,
            "interpretation": _interpret_flow(
                flow_direction, tonnes_change, tonnes_change_5d, vol_ratio
            ),
        }

        logger.info(
            f"✅ SPDR GLD: {flow_direction} {tonnes_change:+.2f}t (1d) | "
            f"Total: {tonnes_today:.1f}t | Signal: {institutional_signal}"
        )
        return result

    except Exception as e:
        logger.warning(f"SPDR parse error: {e}")
        return None


# ─── Layer 2: yfinance (Fallback) ───────────────────────────────────────────


def _fetch_yfinance_gld() -> dict | None:
    """Fallback: ดึง GLD volume + price จาก yfinance"""
    try:
        import yfinance as yf

        logger.info("📊 ใช้ yfinance GLD เป็น fallback...")
        ticker = yf.Ticker("GLD")
        df = ticker.history(period="15d")

        if df.empty or len(df) < 2:
            logger.warning("yfinance GLD: ข้อมูลไม่เพียงพอ")
            return None

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        vol_today = int(latest["Volume"])
        vol_avg_10d = (
            int(df["Volume"].tail(10).mean())
            if len(df) >= 10
            else int(df["Volume"].mean())
        )
        vol_ratio = round(vol_today / vol_avg_10d, 2) if vol_avg_10d > 0 else None

        price_change = float(latest["Close"] - prev["Close"])
        price_change_pct = round(price_change / float(prev["Close"]) * 100, 3)

        is_vol_anomaly = vol_ratio is not None and vol_ratio > 2.0

        if is_vol_anomaly and price_change > 0:
            flow_direction = "likely_inflow"
            institutional_signal = "likely_accumulating"
        elif is_vol_anomaly and price_change < 0:
            flow_direction = "likely_outflow"
            institutional_signal = "likely_distributing"
        else:
            flow_direction = "unclear"
            institutional_signal = "neutral"

        result = {
            "status": "success",
            "source": "yfinance_fallback",
            "data_date": str(df.index[-1].date()),
            "gld_close_usd": round(float(latest["Close"]), 2),
            "price_change_usd": round(price_change, 2),
            "price_change_pct": price_change_pct,
            "volume_today": vol_today,
            "volume_avg_10d": vol_avg_10d,
            "volume_ratio": vol_ratio,
            "volume_anomaly": is_vol_anomaly,
            "flow_direction": flow_direction,
            "institutional_signal": institutional_signal,
            "ounces_in_trust": None,
            "tonnes_change_1d": None,
            "interpretation": _interpret_flow_yf(
                flow_direction, price_change_pct, vol_ratio
            ),
        }

        logger.info(
            f"✅ yfinance GLD: ${latest['Close']:.2f} | "
            f"vol_ratio={vol_ratio} | signal={institutional_signal}"
        )
        return result

    except Exception as e:
        logger.warning(f"⚠️ yfinance GLD failed: {e}")
        return None


# ─── Interpretation helpers ─────────────────────────────────────────────────


def _interpret_flow(
    direction: str,
    tonnes_1d: float,
    tonnes_5d: float | None,
    vol_ratio: float | None,
) -> str:
    """สร้างข้อความสรุป institutional flow สำหรับ LLM"""
    parts = []

    if direction == "inflow":
        parts.append(f"สถาบันเพิ่มทอง {abs(tonnes_1d):.2f} ตัน (Bullish signal)")
    elif direction == "outflow":
        parts.append(f"สถาบันลดทอง {abs(tonnes_1d):.2f} ตัน (Bearish signal)")
    else:
        parts.append("Holdings ไม่เปลี่ยนแปลงอย่างมีนัยสำคัญ")

    if tonnes_5d is not None:
        trend = "สะสม" if tonnes_5d > 0 else "ลดลง"
        parts.append(f"5 วันย้อนหลัง: {trend} {abs(tonnes_5d):.2f} ตัน")

    if vol_ratio and vol_ratio > 2.0:
        parts.append(f"Volume สูงผิดปกติ {vol_ratio:.1f}x (institutional activity)")

    return " | ".join(parts)


def _interpret_flow_yf(
    direction: str,
    pct: float,
    vol_ratio: float | None,
) -> str:
    """สร้างข้อความสรุป (yfinance — ไม่มี holdings data)"""
    parts = []

    if direction == "likely_inflow":
        parts.append(f"GLD ขึ้น {pct:+.2f}% + Volume สูง → น่าจะมี inflow จากสถาบัน")
    elif direction == "likely_outflow":
        parts.append(f"GLD ลง {pct:+.2f}% + Volume สูง → น่าจะมี outflow จากสถาบัน")
    else:
        parts.append(f"GLD เปลี่ยน {pct:+.2f}% Volume ปกติ → ไม่มีสัญญาณพิเศษ")

    if vol_ratio:
        parts.append(f"Volume ratio: {vol_ratio:.1f}x")

    return " | ".join(parts)
