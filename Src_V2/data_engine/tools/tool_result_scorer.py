from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ToolResult:
    """Wrapper สำหรับผลลัพธ์จาก tool call หนึ่งครั้ง"""
    tool_name: str                                          # ชื่อ function เป๊ะๆ
    output: dict                                            # dict ที่ tool return มาตรงๆ
    params: dict                                            # params ที่ใช้ call (สำหรับ recommendation)
    called_at: datetime = field(default_factory=datetime.utcnow)
    weight: float = 1.0                                     # ความสำคัญของ tool นี้ใน context ปัจจุบัน


@dataclass
class ToolScore:
    """คะแนนและเหตุผลของ tool หนึ่งตัว"""
    tool_name: str
    score: float                                            # 0.0 – 1.0
    reason: str                                             # อธิบายว่าทำไมได้คะแนนนี้
    weight: float
    weighted_score: float                                   # score * weight (คำนวณให้แล้ว)


@dataclass
class Recommendation:
    """คำแนะนำให้ call tool เพิ่ม"""
    source_tool: str                                        # tool ที่ score ต่ำ (เหตุผลที่แนะนำ)
    recommended_tool: str                                   # tool ที่ควร call เพิ่ม
    suggested_params: dict                                  # params ที่แนะนำ (อ้างอิงจาก source params)
    reason: str


@dataclass
class ScoreReport:
    """ผลลัพธ์รวมของ ToolResultScorer"""
    tool_scores: list[ToolScore]
    avg_score: float
    should_proceed: bool                                    # True ถ้า avg >= 0.6 AND ไม่มี hard_block
    hard_block: bool                                        # True ถ้ามี tool ส่ง is_safe_to_trade=False
    hard_block_reason: str                                  # อธิบาย hard_block (ว่างถ้า hard_block=False)
    recommendations: list[Recommendation]                  # ว่างถ้า should_proceed = True
    summary: str                                            # สรุปสั้นๆ สำหรับ log


# ─────────────────────────────────────────────────────────────────────────────
# Scorer
# ─────────────────────────────────────────────────────────────────────────────

PROCEED_THRESHOLD = 0.6
FLOOR_SCORE = 0.2       # score ขั้นต่ำสำหรับ result ที่ไม่มี signal (ไม่ใช่ error)


class ToolResultScorer:
    """
    ประเมินคุณภาพของ ToolResult แต่ละตัวก่อนส่งเข้า LLM context

    Usage:
        results = [
            ToolResult("detect_breakout_confirmation", output={...}, params={...}),
            ToolResult("check_upcoming_economic_calendar", output={...}, params={...}, weight=1.5),
        ]
        report = ToolResultScorer().score(results)
        if report.should_proceed:
            # ส่ง results เข้า LLM ได้เลย
        else:
            # ดู report.recommendations แล้ว call tool เพิ่ม
    """

    # ─── Recommendation Map ───────────────────────────────────────────────────

    _RECOMMENDATION_MAP: dict[str, list[str]] = {
        "detect_breakout_confirmation":   ["get_support_resistance_zones", "check_bb_rsi_combo"],
        "check_bb_rsi_combo":             ["detect_rsi_divergence", "calculate_ema_distance"],
        "detect_rsi_divergence":          ["calculate_ema_distance"],          # ลบ check_bb_rsi_combo ออก (circular)
        "calculate_ema_distance":         ["get_htf_trend", "check_spot_thb_alignment"],
        "get_support_resistance_zones":   ["detect_breakout_confirmation"],
        "get_htf_trend":                  ["check_spot_thb_alignment"],
        "check_spot_thb_alignment":       ["get_htf_trend"],
        "check_upcoming_economic_calendar": ["get_intermarket_correlation"],
        "get_deep_news_by_category":      [],               # handled specially (retry + new category)
        "get_intermarket_correlation":    ["check_upcoming_economic_calendar", "get_deep_news_by_category"],
    }

    # ─── Public API ───────────────────────────────────────────────────────────

    def score(self, results: list[ToolResult]) -> ScoreReport:
        """
        รับ list ของ ToolResult แล้วคืน ScoreReport พร้อม recommendations
        """
        if not results:
            return ScoreReport(
                tool_scores=[],
                avg_score=0.0,
                should_proceed=False,
                hard_block=False,
                hard_block_reason="",
                recommendations=[],
                summary="ไม่มี tool results ส่งมา",
            )

        tool_scores: list[ToolScore] = []
        for tr in results:
            score, reason = self._dispatch(tr)
            weighted = round(score * tr.weight, 4)
            tool_scores.append(ToolScore(
                tool_name=tr.tool_name,
                score=score,
                reason=reason,
                weight=tr.weight,
                weighted_score=weighted,
            ))

        # weighted average
        total_weight = sum(ts.weight for ts in tool_scores)
        avg_score = round(
            sum(ts.weighted_score for ts in tool_scores) / total_weight, 4
        ) if total_weight > 0 else 0.0

        # ── Hard Block: tool บอกว่า is_safe_to_trade=False → หยุดทันที ──────
        # ตรวจก่อน should_proceed เสมอ เพราะ data quality สูง ≠ ควรเทรด
        hard_block = False
        hard_block_reason = ""
        for tr in results:
            if tr.output.get("is_safe_to_trade") is False:
                hard_block = True
                action = tr.output.get("trade_action", "avoid")
                note   = tr.output.get("trade_note", "")
                hard_block_reason = (
                    f"[{tr.tool_name}] trade_action={action}"
                    + (f" — {note}" if note else "")
                )
                break

        should_proceed = (avg_score >= PROCEED_THRESHOLD) and not hard_block

        recommendations: list[Recommendation] = []
        if not should_proceed:
            for tr, ts in zip(results, tool_scores):
                if ts.score < PROCEED_THRESHOLD:
                    recs = self._build_recommendations(tr, results)   # ← ส่ง results ทั้งหมด
                    recommendations.extend(recs)

        summary = self._build_summary(tool_scores, avg_score, should_proceed, hard_block)
        logger.info(f"[ToolResultScorer] {summary}")

        return ScoreReport(
            tool_scores=tool_scores,
            avg_score=avg_score,
            should_proceed=should_proceed,
            hard_block=hard_block,
            hard_block_reason=hard_block_reason,
            recommendations=recommendations,
            summary=summary,
        )

    # ─── Dispatch ─────────────────────────────────────────────────────────────

    def _dispatch(self, tr: ToolResult) -> tuple[float, str]:
        """เลือก scorer ที่ถูกต้องตาม tool_name"""
        scorer_map = {
            "detect_breakout_confirmation":     self._score_breakout_confirmation,
            "check_bb_rsi_combo":               self._score_bb_rsi_combo,
            "detect_rsi_divergence":            self._score_rsi_divergence,
            "calculate_ema_distance":           self._score_ema_distance,
            "get_support_resistance_zones":     self._score_support_resistance,
            "get_htf_trend":                    self._score_htf_trend,
            "check_spot_thb_alignment":         self._score_spot_thb_alignment,
            "check_upcoming_economic_calendar": self._score_economic_calendar,
            "get_deep_news_by_category":        self._score_deep_news,
            "get_intermarket_correlation":      self._score_intermarket_correlation,
        }
        fn = scorer_map.get(tr.tool_name)
        if fn is None:
            logger.warning(f"[ToolResultScorer] ไม่รู้จัก tool '{tr.tool_name}' ใช้ generic scorer")
            return self._score_generic(tr.output)
        return fn(tr.output)

    # ─── Generic (fallback) ───────────────────────────────────────────────────

    def _score_generic(self, output: dict) -> tuple[float, str]:
        if output.get("status") == "error":
            return 0.0, f"Tool error: {output.get('message', 'unknown')}"
        return FLOOR_SCORE, "Tool ไม่รู้จัก — ให้ floor score"

    # ─── Technical Tools ──────────────────────────────────────────────────────

    def _score_breakout_confirmation(self, output: dict) -> tuple[float, str]:
        if output.get("status") == "error":
            return 0.0, f"Error: {output.get('message')}"

        confirmed = output.get("is_confirmed_breakout", False)
        if not confirmed:
            return FLOOR_SCORE, "ไม่มี breakout confirmation"

        body_strength = output.get("details", {}).get("body_strength_pct", 0.0)
        score = 0.85
        reason = f"Breakout confirmed | body_strength={body_strength:.1f}%"

        if body_strength >= 70.0:
            score += 0.10
            reason += " → body แข็งแกร่งมาก (+0.10)"

        return min(score, 1.0), reason

    def _score_bb_rsi_combo(self, output: dict) -> tuple[float, str]:
        if output.get("status") == "error":
            return 0.0, f"Error: {output.get('message')}"

        if output.get("combo_detected", False):
            return 0.85, "BB+RSI+MACD combo detected — oversold signal ชัดเจน"
        return FLOOR_SCORE, "ไม่ครบ combo conditions"

    def _score_rsi_divergence(self, output: dict) -> tuple[float, str]:
        if output.get("status") == "error":
            return 0.0, f"Error: {output.get('message')}"

        if output.get("divergence_detected", False):
            data = output.get("data", {})
            return 0.85, (
                f"Bullish RSI divergence detected | "
                f"Low1={data.get('Low1')} RSI1={data.get('RSI1')} → "
                f"Low2={data.get('Low2')} RSI2={data.get('RSI2')}"
            )
        return FLOOR_SCORE, f"ไม่พบ divergence: {output.get('logic', '')}"

    def _score_ema_distance(self, output: dict) -> tuple[float, str]:
        if output.get("status") == "error":
            return 0.0, f"Error: {output.get('message')}"

        overextended = output.get("is_overextended", False)
        distance = abs(output.get("distance_atr_ratio", 0.0))

        if not overextended:
            return FLOOR_SCORE, f"ราคาใกล้ EMA20 — distance={distance:.2f} ATR"

        score = 0.75
        reason = f"Price overextended จาก EMA20 | distance={distance:.2f} ATR"
        if distance >= 7.0:
            score += 0.15
            reason += " → ไกลมาก (+0.15)"

        return min(score, 1.0), reason

    def _score_support_resistance(self, output: dict) -> tuple[float, str]:
        if output.get("status") == "error":
            return 0.0, f"Error: {output.get('message')}"

        zones: list[dict] = output.get("zones", [])
        current_price: float = output.get("current_price", 0.0)
        atr: float = output.get("adaptive_metrics", {}).get("atr_used", 0.0)

        if not zones:
            return FLOOR_SCORE, "ไม่พบ S/R zone เลย"

        # หา zone ที่ราคาอยู่ภายใน 1 ATR
        nearby_zones = []
        for z in zones:
            top = z.get("top", 0.0)
            bottom = z.get("bottom", 0.0)
            if atr > 0:
                if (bottom - atr) <= current_price <= (top + atr):
                    nearby_zones.append(z)
            else:
                # fallback ถ้าไม่มี ATR: ใช้ 0.5% ของราคา
                tolerance = current_price * 0.005
                if (bottom - tolerance) <= current_price <= (top + tolerance):
                    nearby_zones.append(z)

        if not nearby_zones:
            return 0.4, f"มี {len(zones)} zones แต่ราคาไม่ใกล้ zone ใดเลย"

        best = max(nearby_zones, key=lambda z: {"High": 3, "Medium": 2, "Low": 1}.get(z.get("strength", "Low"), 1))
        strength = best.get("strength", "Low")

        score_map = {"Low": 0.6, "Medium": 0.75, "High": 0.9}
        score = score_map.get(strength, 0.6)
        reason = (
            f"ราคาใกล้ {len(nearby_zones)} zone | "
            f"strongest={strength} ({best.get('bottom')}–{best.get('top')})"
        )
        return score, reason

    def _score_htf_trend(self, output: dict) -> tuple[float, str]:
        if output.get("status") == "error":
            return 0.0, f"Error: {output.get('message')}"

        trend = output.get("trend", "")
        distance_pct = abs(output.get("distance_from_ema_pct", 0.0))

        if trend not in ("Bullish", "Bearish"):
            return FLOOR_SCORE, f"Trend ไม่ชัดเจน: {trend}"

        if distance_pct >= 1.5:
            return 0.75, f"HTF trend {trend} | ห่าง EMA200 {distance_pct:.2f}% — ชัดเจน"
        return 0.6, f"HTF trend {trend} ใกล้ EMA200 ({distance_pct:.2f}%) — อาจ consolidate แต่ทิศชัด"

    def _score_spot_thb_alignment(self, output: dict) -> tuple[float, str]:
        if output.get("status") == "error":
            return 0.0, f"Error: {output.get('message')}"

        alignment = output.get("alignment", "")
        if alignment in ("Strong Bullish", "Strong Bearish"):
            details = output.get("details", {})
            return 0.85, (
                f"Alignment ชัดเจน: {alignment} | "
                f"spot={details.get('spot_pct_change')}% "
                f"thb={details.get('thb_pct_change')}%"
            )
        return 0.3, f"Alignment: {alignment} — ทิศทางสวนกัน ไม่มี strong signal"

    # ─── Fundamental Tools ────────────────────────────────────────────────────

    def _score_economic_calendar(self, output: dict) -> tuple[float, str]:
        if output.get("status") == "error":
            return 0.0, f"Error: {output.get('message')}"

        risk_map = {
            "critical": (1.0, "🔴 CRITICAL risk — มีข่าวใหญ่ใกล้ออก"),
            "high":     (0.8, "🟠 HIGH risk — ควรระวัง"),
            "medium":   (0.5, "🟡 MEDIUM risk — มีข่าว medium impact"),
            "low":      (FLOOR_SCORE, "🟢 LOW risk — ไม่มีข่าวสำคัญ"),
        }
        risk_level = output.get("risk_level", "low")
        score, reason = risk_map.get(risk_level, (FLOOR_SCORE, f"Unknown risk level: {risk_level}"))
        return score, reason

    def _score_deep_news(self, output: dict) -> tuple[float, str]:
        if output.get("status") == "error":
            return 0.0, f"Error: {output.get('message')}"

        count           = output.get("count", 0)
        relevance_score = output.get("relevance_score")   # 0.0–1.0 จาก tool (อาจไม่มีถ้า tool เก่า)

        if count == 0:
            return FLOOR_SCORE, "ไม่พบบทความเลย"

        # base score จาก count
        if count <= 2:
            base = 0.5
            count_label = f"พบ {count} บทความ — น้อย"
        elif count <= 4:
            base = 0.7
            count_label = f"พบ {count} บทความ — พอใช้"
        else:
            base = 0.85
            count_label = f"พบ {count} บทความ — ครบถ้วน"

        # ถ้ามี relevance_score → ปรับ base ตาม quality จริง
        if relevance_score is not None:
            # weighted blend: 60% count-based + 40% relevance
            blended = round(base * 0.6 + relevance_score * 0.4, 4)
            reason = (
                f"{count_label} | relevance={relevance_score:.2f} → score={blended:.2f}"
            )
            return min(blended, 1.0), reason

        # fallback ถ้าไม่มี relevance_score (tool เก่า)
        return base, count_label

    def _score_intermarket_correlation(self, output: dict) -> tuple[float, str]:
        if output.get("status") == "error":
            return 0.0, f"Error: {output.get('message')}"

        divergences: list[dict] = output.get("divergences", [])
        warnings = [d for d in divergences if d.get("status") in ("bearish_warning", "bullish_warning")]
        flat_or_normal = all(d.get("status") in ("normal", "flat") for d in divergences)

        if len(warnings) >= 2:
            return 1.0, f"มี divergence warning ทั้ง {len(warnings)} pairs — signal แข็งมาก"
        if len(warnings) == 1:
            w = warnings[0]
            return 0.75, f"มี divergence warning: {w.get('pair')} ({w.get('status')}) — {w.get('note', '')}"
        if flat_or_normal and divergences:
            statuses = [d.get("status") for d in divergences]
            if all(s == "flat" for s in statuses):
                return FLOOR_SCORE, "ทุก pair flat — ตลาดนิ่งมาก"
            return 0.3, "ทุก pair normal inverse — ไม่มีความผิดปกติ"
        return FLOOR_SCORE, "ไม่มีข้อมูล divergence"

    # ─── Recommendation Builder ───────────────────────────────────────────────

    def _build_recommendations(
        self,
        tr: ToolResult,
        results: list[ToolResult],          # ← รับ results แทน already_called set
    ) -> list[Recommendation]:
        recs: list[Recommendation] = []

        # ── already_called: tool_name ระดับทั่วไป (ไม่นับ params) ───────────
        already_called: set[str] = {r.tool_name for r in results}

        # กรณีพิเศษ: get_deep_news_by_category → track ระดับ category (params)
        if tr.tool_name == "get_deep_news_by_category":
            tried_categories: set[str] = {
                r.params.get("category", "")
                for r in results
                if r.tool_name == "get_deep_news_by_category"
            }
            all_categories = [
                "gold_price", "usd_thb", "fed_policy", "inflation",
                "geopolitics", "dollar_index", "thai_economy", "thai_gold_market",
            ]
            for cat in all_categories:
                if cat not in tried_categories:
                    recs.append(Recommendation(
                        source_tool=tr.tool_name,
                        recommended_tool="get_deep_news_by_category",
                        suggested_params={"category": cat},
                        reason=f"ลอง category ถัดไปที่ยังไม่ได้ call: '{cat}'",
                    ))
                    break   # แนะนำครั้งละ 1 category ไม่ flood
            return recs

        # กรณีทั่วไป
        suggested_tools = self._RECOMMENDATION_MAP.get(tr.tool_name, [])
        for suggested in suggested_tools:
            if suggested in already_called:
                continue

            inherited_params: dict[str, Any] = {}
            for key in ("interval", "history_days", "timeframe"):
                if key in tr.params:
                    inherited_params[key] = tr.params[key]

            recs.append(Recommendation(
                source_tool=tr.tool_name,
                recommended_tool=suggested,
                suggested_params=inherited_params,
                reason=f"'{tr.tool_name}' score ต่ำ → เพิ่มข้อมูลด้วย '{suggested}'",
            ))
            already_called.add(suggested)   # กัน duplicate ภายใน loop นี้

        return recs

    # ─── Summary Builder ──────────────────────────────────────────────────────

    def _build_summary(
        self,
        tool_scores: list[ToolScore],
        avg_score: float,
        should_proceed: bool,
        hard_block: bool = False,
    ) -> str:
        if hard_block:
            status = "🚫 HARD BLOCK"
        elif should_proceed:
            status = "✅ PROCEED"
        else:
            status = "🔄 NEED MORE TOOLS"
        scores_str = " | ".join(
            f"{ts.tool_name}={ts.score:.2f}(x{ts.weight})" for ts in tool_scores
        )
        return f"{status} | avg={avg_score:.3f} | {scores_str}"
