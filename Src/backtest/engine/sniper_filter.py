"""
engine/sniper_filter.py  — Sniper Pre-filter v1.0
══════════════════════════════════════════════════════════════════════
หน้าที่: คัดกรองแท่งเทียนก่อนส่งให้ LLM

หลักการ Hybrid Pipeline:
  ❌ เดิม: ทุกแท่งเทียน → LLM (แพง / ช้า / AI งง)
  ✅ ใหม่: ทุกแท่งเทียน → SniperFilter → เฉพาะที่ผ่านกรอง → LLM

กฎการกรอง (ต้องผ่าน **ทุกข้อ** จึงจะ call LLM):
  [1] Session Quota  — ยังไม่ BUY ในเซสชั่นนี้ (max 1 BUY entry/session)
  [2] Dip Setup      — มีสัญญาณย่อตัว (RSI / BB / Price Pullback)
  [3] Trend Filter   — HTF trend ไม่ขัดแย้งชัดเจน (EMA20 vs EMA50)
  [4] Spread Cover   — ATR คาดว่าจะชนะ Spread ได้ (edge > 0)
  [5] SELL Pass      — ถ้าถือทองอยู่ ให้ผ่านกรองเสมอ (SELL/EXIT ห้ามบล็อก)

Return: SniperResult (dataclass) บอกว่า should_call_llm=True/False + reason
══════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# 🌟[FIX] กำหนดค่าคงที่แทน Magic Number
DEFAULT_POSITION_THB = 1000.0

# ══════════════════════════════════════════════════════════════════
# Config — ปรับได้ตามผล Backtest
# ══════════════════════════════════════════════════════════════════

@dataclass
class SniperConfig:
    # ── [1] Session Quota ──────────────────────────────────────────
    max_buy_per_session: int = 1

    # ── [2] Dip Setup ──────────────────────────────────────────────
    rsi_dip_threshold: float = 45.0
    bb_band_pct: float = 0.005
    pullback_pct: float = 0.002
    min_dip_conditions: int = 1

    # ──[3] Trend Filter ───────────────────────────────────────────
    enable_trend_filter: bool = True
    allow_neutral_trend: bool = True
    ema_neutral_pct: float = 0.003

    # ── [4] Spread Cover ───────────────────────────────────────────
    spread_cover_multiplier: float = 1.0
    default_spread_thb: float = 200.0

    # ── [5] SELL Always Pass ───────────────────────────────────────
    sell_always_pass: bool = True

    # ── [6] Master Merged Label ────────────────────────────────────
    use_master_label: bool = True
    buy_score_threshold: float = 0.0
    require_master_label: bool = False

    # ── [8] Min Expected Profit ────────────────────────────────────
    min_expected_profit_thb: float = 1.5
    expected_rr_ratio: float = 2.0
    expected_position_thb: float = 0.0

    # ── Cluster Dedup ──────────────────────────────────────────────
    cluster_dedup_mode: str = "middle"   # "off" | "first" | "middle" | "session"
    cluster_gap_bars: int = 3

    # ── Debug ──────────────────────────────────────────────────────
    verbose: bool = False


# ══════════════════════════════════════════════════════════════════
# Result
# ══════════════════════════════════════════════════════════════════

@dataclass
class SniperResult:
    should_call_llm: bool
    reason: str               
    dip_score: int = 0        
    checks: Dict[str, bool] = field(default_factory=dict)

    @property
    def label(self) -> str:
        return "🎯 PASS" if self.should_call_llm else "⏭ SKIP"


# ══════════════════════════════════════════════════════════════════
# SniperFilter
# ══════════════════════════════════════════════════════════════════

class SniperFilter:
    def __init__(self, config: Optional[SniperConfig] = None):
        self.cfg = config or SniperConfig()
        self._session_buy_count: Dict[str, int] = {}  

        # ── Cluster Dedup State ───────────────────────────────────────
        self._cluster_bar_index: int = 0          
        self._cluster_start_bar: int = -999       
        self._cluster_end_bar: int = -999         
        self._cluster_fired_bar: int = -999       
        self._cluster_session: Optional[str] = None  

    # ── Public API ───────────────────────────────────────────────

    def check(
        self,
        row: pd.Series,
        gold_grams: float,
        session_id: Optional[str],
        date_str: str,
    ) -> SniperResult:
        cfg = self.cfg

        self._cluster_bar_index += 1
        cur_bar = self._cluster_bar_index

        if cfg.cluster_dedup_mode != "off" and cfg.use_master_label:
            _tb_pre = float(row.get("target_buy", -1.0))
            if _tb_pre == 1.0:
                _gap = cur_bar - self._cluster_end_bar
                if _gap > cfg.cluster_gap_bars:
                    self._cluster_start_bar = cur_bar
                    self._cluster_fired_bar = -999
                    if cfg.cluster_dedup_mode == "session":
                        self._cluster_session = None
                self._cluster_end_bar = cur_bar

        if cfg.sell_always_pass and gold_grams > 1e-4:
            return SniperResult(
                should_call_llm=True,
                reason="SELL_PASS: holding gold → always evaluate exit",
                dip_score=0,
                checks={"sell_always_pass": True},
            )

        if cfg.require_master_label:
            target_buy = float(row.get("target_buy", -1.0))
            buy_score  = float(row.get("buy_score",  -1.0))
            label_pass = (target_buy == 1.0) and (buy_score >= cfg.buy_score_threshold)
            if not label_pass:
                reason = (
                    f"NO_LABEL: target_buy={target_buy} buy_score={buy_score:.3f} "
                    f"(need target_buy=1 & score≥{cfg.buy_score_threshold})"
                )
                if cfg.verbose:
                    logger.debug(f"  ⏭ SniperFilter {reason}")
                return SniperResult(
                    should_call_llm=False,
                    reason=reason,
                    dip_score=0,
                    checks={"master_label": False},
                )

        quota_key = f"{date_str}|{session_id or 'UNKNOWN'}"
        buys_this_session = self._session_buy_count.get(quota_key, 0)
        quota_ok = buys_this_session < cfg.max_buy_per_session

        if not quota_ok:
            return SniperResult(
                should_call_llm=False,
                reason=f"QUOTA: session {session_id} already has {buys_this_session} BUY entry",
                checks={"quota": False},
            )

        if cfg.cluster_dedup_mode != "off" and cfg.use_master_label:
            target_buy_val = float(row.get("target_buy", -1.0))
            is_label_1 = (target_buy_val == 1.0)

            if is_label_1:
                should_fire = self._should_fire_cluster(
                    cur_bar, session_id, cfg.cluster_dedup_mode
                )

                if not should_fire:
                    reason = (
                        f"CLUSTER_SKIP: mode={cfg.cluster_dedup_mode} | "
                        f"cluster_start={self._cluster_start_bar} cur={cur_bar} "
                        f"fired_at={self._cluster_fired_bar}"
                    )
                    if cfg.verbose:
                        logger.debug(f"  ⏭ SniperFilter {reason}")
                    return SniperResult(
                        should_call_llm=False,
                        reason=reason,
                        dip_score=0,
                        checks={"cluster_dedup": False},
                    )
                self._cluster_fired_bar = cur_bar
                if cfg.cluster_dedup_mode == "session":
                    self._cluster_session = session_id

        if cfg.min_expected_profit_thb > 0:
            profit_ok, profit_detail = self._check_min_profit(row)
            if not profit_ok:
                reason = f"LOW_PROFIT: {profit_detail}"
                if cfg.verbose:
                    logger.debug(f"  ⏭ SniperFilter {reason}")
                return SniperResult(
                    should_call_llm=False,
                    reason=reason,
                    dip_score=0,
                    checks={"min_profit": False},
                )

        dip_flags, dip_details = self._check_dip(row)
        dip_score = sum(dip_flags.values())
        dip_ok = dip_score >= cfg.min_dip_conditions

        trend_ok, trend_detail = self._check_trend(row)
        spread_ok, spread_detail = self._check_spread(row)

        checks = {
            "quota":  quota_ok,
            "dip":    dip_ok,
            "trend":  trend_ok,
            "spread": spread_ok,
            **dip_flags,
        }

        all_pass = dip_ok and trend_ok and spread_ok

        if all_pass:
            reason = (
                f"PASS: dip_score={dip_score} | {dip_details} | "
                f"trend={trend_detail} | spread={spread_detail}"
            )
        else:
            fails =[]
            if not dip_ok:
                fails.append(f"NO_DIP(score={dip_score}/{cfg.min_dip_conditions}: {dip_details})")
            if not trend_ok:
                fails.append(f"TREND_BLOCK({trend_detail})")
            if not spread_ok:
                fails.append(f"SPREAD_WEAK({spread_detail})")
            reason = "SKIP: " + " | ".join(fails)

        if cfg.verbose:
            icon = "🎯" if all_pass else "⏭"
            logger.debug(f"  {icon} SniperFilter {reason}")

        return SniperResult(
            should_call_llm=all_pass,
            reason=reason,
            dip_score=dip_score,
            checks=checks,
        )

    def record_buy(self, date_str: str, session_id: Optional[str]):
        quota_key = f"{date_str}|{session_id or 'UNKNOWN'}"
        self._session_buy_count[quota_key] = self._session_buy_count.get(quota_key, 0) + 1
        logger.debug(f"  📌 SniperFilter: recorded BUY for {quota_key} "
                     f"(total={self._session_buy_count[quota_key]})")

    def reset(self):
        self._session_buy_count.clear()
        self._cluster_bar_index = 0
        self._cluster_start_bar = -999
        self._cluster_end_bar = -999
        self._cluster_fired_bar = -999
        self._cluster_session = None

    def stats(self) -> dict:
        return dict(self._session_buy_count)

    def diagnose(self, df: "pd.DataFrame", session_col: str = "session_id", date_col: str = "date_str") -> dict:
        # 🌟 [FIX] ลบ import pandas as _pd ที่ซ้ำซ้อนออก ใช้ pd ตัวบนได้เลย
        total = len(df)
        label_1 = int((df.get("target_buy", pd.Series(dtype=float)) == 1.0).sum()) if "target_buy" in df.columns else 0
        label_0 = total - label_1

        temp = SniperFilter(SniperConfig(
            cluster_dedup_mode=self.cfg.cluster_dedup_mode,
            cluster_gap_bars=self.cfg.cluster_gap_bars,
            use_master_label=self.cfg.use_master_label,
            require_master_label=False,   
            min_dip_conditions=0,
            enable_trend_filter=False,
            spread_cover_multiplier=0.0,
            max_buy_per_session=9999,
            sell_always_pass=False,
        ))

        cluster_pass = 0
        cluster_skip = 0
        for _, row in df.iterrows():
            tb = float(row.get("target_buy", 0.0))
            if tb != 1.0:
                temp._cluster_bar_index += 1
                continue
            r = temp.check(
                row,
                gold_grams=0.0,
                session_id=str(row.get(session_col, "UNK")),
                date_str=str(row.get(date_col, "2000-01-01")),
            )
            if r.should_call_llm:
                cluster_pass += 1
            else:
                cluster_skip += 1

        return {
            "total_bars":      total,
            "label_1_bars":    label_1,
            "label_0_bars":    label_0,
            "label_1_pct":     f"{label_1/total*100:.1f}%" if total else "N/A",
            "cluster_mode":    self.cfg.cluster_dedup_mode,
            "cluster_gap":     self.cfg.cluster_gap_bars,
            "cluster_pass":    cluster_pass,
            "cluster_skip":    cluster_skip,
            "pass_rate":       f"{cluster_pass/label_1*100:.1f}%" if label_1 else "N/A",
            "note": "cluster_pass = จำนวนแท่งที่จะผ่านถึง LLM หลัง dedup",
        }

    # ── Internal checks ───────────────────────────────────────────

    def _should_fire_cluster(
        self,
        cur_bar: int,
        session_id: Optional[str],
        mode: str,
    ) -> bool:
        if self._cluster_fired_bar >= self._cluster_start_bar:
            return False

        if mode == "first":
            return cur_bar == self._cluster_start_bar

        elif mode == "middle":
            bars_into_cluster = cur_bar - self._cluster_start_bar
            half_gap = self.cfg.cluster_gap_bars // 2  
            return bars_into_cluster >= half_gap or cur_bar == self._cluster_start_bar

        elif mode == "session":
            return self._cluster_session != session_id

        return True

    def _check_min_profit(self, row: pd.Series):
        cfg = self.cfg

        buy_price  = float(row.get("Mock_HSH_Buy_Close", 0.0))
        sell_price = float(row.get("Mock_HSH_Sell_Close", buy_price))
        atr        = float(row.get("atr", 0.0))

        if buy_price <= 0 or atr <= 0:
            return True, "NO_PRICE_OR_ATR"

        spread_per_unit = max(0.0, buy_price - sell_price)
        if spread_per_unit <= 0:
            spread_per_unit = cfg.default_spread_thb

        # 🌟 [FIX] ใช้ค่าคงที่ DEFAULT_POSITION_THB แทน Magic Number 900.0
        pos_thb = cfg.expected_position_thb if cfg.expected_position_thb > 0 else DEFAULT_POSITION_THB

        units = pos_thb / buy_price
        net_move_per_unit = (atr * cfg.expected_rr_ratio) - spread_per_unit
        profit_est = units * net_move_per_unit

        ok = profit_est >= cfg.min_expected_profit_thb
        detail = (
            f"est_profit={profit_est:.2f} THB "
            f"(units={units:.5f} × net_move={net_move_per_unit:.0f}) "
            f"[ATR={atr:.0f}×RR{cfg.expected_rr_ratio:.1f} − spread={spread_per_unit:.0f}] "
            f"vs min={cfg.min_expected_profit_thb:.1f}"
        )
        return ok, detail

    def _check_dip(self, row: pd.Series):
        cfg = self.cfg
        flags = {}

        rsi = float(row.get("rsi", 50.0))
        flags["dip_rsi"] = rsi < cfg.rsi_dip_threshold

        price = float(row.get("Mock_HSH_Sell_Close", row.get("close_thai", 0.0)))
        bb_lower = float(row.get("bb_lower", 0.0))
        if bb_lower > 0 and price > 0:
            gap_pct = (price - bb_lower) / price
            flags["dip_bb"] = gap_pct <= cfg.bb_band_pct
        else:
            flags["dip_bb"] = False

        recent_high = float(row.get("Mock_HSH_Sell_High", row.get("high_thai", 0.0)))
        if recent_high <= 0:
            recent_high = float(row.get("ema_20", 0.0))

        if recent_high > 0 and price > 0:
            pullback = (recent_high - price) / recent_high
            flags["dip_pullback"] = pullback >= cfg.pullback_pct
        else:
            flags["dip_pullback"] = False

        if cfg.use_master_label:
            target_buy = float(row.get("target_buy", -1.0))
            buy_score  = float(row.get("buy_score",  -1.0))
            if target_buy >= 0:  
                label_pass = (target_buy == 1.0) and (buy_score >= cfg.buy_score_threshold)
                flags["dip_master_label"] = label_pass

        details = (
            f"RSI={rsi:.1f}({'✓' if flags['dip_rsi'] else '✗'}) | "
            f"BB_gap={'✓' if flags['dip_bb'] else '✗'} | "
            f"Pullback={'✓' if flags['dip_pullback'] else '✗'}"
            + (f" | Label={'✓' if flags.get('dip_master_label') else '✗'}"
               if "dip_master_label" in flags else "")
        )
        return flags, details

    def _check_trend(self, row: pd.Series):
        cfg = self.cfg

        if not cfg.enable_trend_filter:
            return True, "TREND_OFF"

        ema20 = float(row.get("ema_20", 0.0))
        ema50 = float(row.get("ema_50", 0.0))

        if ema20 <= 0 or ema50 <= 0:
            return True, "NO_EMA_DATA"

        gap_pct = (ema20 - ema50) / ema50

        if gap_pct > cfg.ema_neutral_pct:
            return True, f"UPTREND(EMA20={ema20:.0f}>EMA50={ema50:.0f})"
        elif abs(gap_pct) <= cfg.ema_neutral_pct:
            if cfg.allow_neutral_trend:
                return True, f"NEUTRAL(gap={gap_pct*100:.2f}%)"
            else:
                return False, f"NEUTRAL_BLOCKED(gap={gap_pct*100:.2f}%)"
        else:
            return False, f"DOWNTREND(EMA20={ema20:.0f}<EMA50={ema50:.0f})"

    def _check_spread(self, row: pd.Series):
        cfg = self.cfg

        atr = float(row.get("atr", 0.0))
        if atr <= 0:
            return True, "NO_ATR"

        buy_price = float(row.get("Mock_HSH_Buy_Close", 0.0))
        sell_price = float(row.get("Mock_HSH_Sell_Close", 0.0))
        if buy_price > 0 and sell_price > 0 and sell_price > buy_price:
            spread = sell_price - buy_price
        else:
            spread = cfg.default_spread_thb

        min_atr_needed = spread * cfg.spread_cover_multiplier
        ok = atr >= min_atr_needed

        return ok, f"ATR={atr:.0f} vs spread*{cfg.spread_cover_multiplier:.1f}={min_atr_needed:.0f}"