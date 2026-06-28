"""
backtest/engine/portfolio.py  — Scalping Edition v3.0
══════════════════════════════════════════════════════════════════════
[PATCH v3.0 — สอดคล้องกับ Scalping Strategy]

ปัญหาเดิม:
  - DEFAULT_CASH = 1,500 THB แต่ position = 1,400 THB
    → เหลือ cash 97 THB หลังซื้อ → ซื้อซ้ำไม่ได้เลย (กระสุน 1 นัด)
  - can_buy() เช็ค >= BUST_THRESHOLD (1,000) ซึ่งไม่เคยเป็นจริง
    เพราะหลังซื้อ 1,400 cash เหลือแค่ 97 < 1,000 → bust ทันที

แก้ไข:
  [A] DEFAULT_POSITION_THB = 1,000 (ลดจาก 1,400)
      → เหลือ cash ~497 THB → พอซื้อรอบที่ 2 ได้ (ถ้าขายแล้ว)
      → round-trip cost ~0.93% ยังสมเหตุสมผล
  [B] BUST_THRESHOLD = 500 (ลดจาก 1,000)
      → threshold ต่ำกว่า position → ไม่ bust ทันทีหลังซื้อ
  [C] can_buy() เช็ค cash >= DEFAULT_POSITION_THB + MIN_FEE_BUFFER
      → ชัดเจนกว่า bust_threshold
  [D] execute_buy() รับ position_thb จาก caller (ไม่ hardcode)
      → risk.py เป็นคนกำหนด — portfolio แค่รัน

Trading Constants (ไม่เปลี่ยน):
  SPREAD_PER_BAHT    = 120 THB / 1 บาทน้ำหนัก
  COMMISSION_BUY_THB =   3 THB (SCB EASY)
  COMMISSION_SELL_THB=   0 THB (ฮั่วเซ่งเฮงออกให้)
  GOLD_GRAM_PER_BAHT = 15.244 g
══════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────
GOLD_GRAM_PER_BAHT   = 15.244
SPREAD_PER_BAHT      = 0   # THB / 1 บาทน้ำหนัก (ข้อมูลจริงฮั่วเซ่งเฮง ออม NOW)
COMMISSION_BUY_THB   = 0      # THB (SCB EASY)
COMMISSION_SELL_THB  = 0.0      # THB (ฟรี — ฮั่วเซ่งเฮงออกให้)
COMMISSION_THB       = COMMISSION_BUY_THB  # backward compat alias

# [PATCH v3.0] ปรับ capital constants ให้ scalping หมุนได้หลายรอบ
DEFAULT_CASH          = 1500  # ทุนเริ่มต้น (ไม่เปลี่ยน)
DEFAULT_POSITION_THB  = 1_250.0  # [PATCH] ลดจาก 1,400 → 1,000 ต่อไม้
                                  # เหลือ ~497 THB buffer หลังซื้อ
MIN_FEE_BUFFER        = 0    # buffer ขั้นต่ำสำหรับค่าธรรมเนียม
BUST_THRESHOLD        = 1000.0    # [PATCH] ลดจาก 1,000 → 500 (ต่ำกว่า position)
WIN_THRESHOLD         = 1_500.0  # equity เป้าหมาย

# backward compat alias — ใช้ใน _add_validation() ของ run_main_backtest.py
SPREAD_THB = SPREAD_PER_BAHT


def _calc_spread(position_thb: float, price_per_baht: float) -> float:
    """
    คำนวณ spread จริงตาม position size และราคา (1 ขา)

    ตัวอย่าง @ ราคา 71,950 THB/บาท:
      position=1,000 → baht_weight=0.01390 → spread=1.67 THB
      position=1,400 → baht_weight=0.01946 → spread=2.34 THB
    """
    if price_per_baht <= 0:
        return 0.0
    baht_weight = position_thb / price_per_baht
    return baht_weight * SPREAD_PER_BAHT


def _calc_spread_from_grams(gold_grams: float, price_per_baht: float) -> float:
    """คำนวณ spread จาก gold_grams ที่ถือ (ใช้ตอน SELL)"""
    if price_per_baht <= 0:
        return 0.0
    baht_weight = gold_grams / GOLD_GRAM_PER_BAHT
    return baht_weight * SPREAD_PER_BAHT


# ══════════════════════════════════════════════════════════════════
# Exception
# ══════════════════════════════════════════════════════════════════


class PortfolioBustException(Exception):
    """Raised เมื่อ portfolio total value < bust_threshold"""

    def __init__(self, equity: float, threshold: float = BUST_THRESHOLD,
                 timestamp: str = ""):
        self.equity    = equity
        self.threshold = threshold
        self.timestamp = timestamp
        super().__init__(
            f"🔴 PORTFOLIO BUST: equity={equity:.2f} THB "
            f"< threshold={threshold:.0f} THB"
            + (f" at {timestamp}" if timestamp else "")
        )


# ══════════════════════════════════════════════════════════════════
# Trade Record
# ══════════════════════════════════════════════════════════════════


@dataclass
class ClosedTrade:
    """1 รอบการเทรดที่ปิดแล้ว (BUY → SELL)"""
    entry_price:  float
    exit_price:   float
    gold_grams:   float
    entry_time:   str
    exit_time:    str
    position_thb: float
    gross_pnl:    float
    cost_thb:     float
    pnl_thb:      float
    is_win:       bool = field(init=False)

    def __post_init__(self):
        self.is_win = self.pnl_thb > 0

    def to_dict(self) -> dict:
        return {
            "entry_time":   self.entry_time,
            "exit_time":    self.exit_time,
            "entry_price":  round(self.entry_price, 2),
            "exit_price":   round(self.exit_price, 2),
            "gold_grams":   round(self.gold_grams, 4),
            "position_thb": round(self.position_thb, 2),
            "gross_pnl":    round(self.gross_pnl, 2),
            "cost_thb":     round(self.cost_thb, 2),
            "pnl_thb":      round(self.pnl_thb, 2),
            "is_win":       self.is_win,
        }


@dataclass
class _OpenTrade:
    entry_price:       float
    gold_grams:        float
    entry_time:        str
    position_thb:      float
    cost_at_entry:     float
    take_profit_price: float = 0.0
    stop_loss_price:   float = 0.0


# ══════════════════════════════════════════════════════════════════
# SimPortfolio v3.0
# ══════════════════════════════════════════════════════════════════


@dataclass
class SimPortfolio:
    """
    Simulated portfolio พร้อม bust detection และ trade logging
    [v3.0] ปรับ position size และ bust threshold สำหรับ scalping
    """
    initial_cash:   float = DEFAULT_CASH
    bust_threshold: float = BUST_THRESHOLD
    win_threshold:  float = WIN_THRESHOLD

    cash_balance:   float = field(init=False)
    gold_grams:     float = field(init=False, default=0.0)
    cost_basis_thb: float = field(init=False, default=0.0)
    trades_today:   int   = field(init=False, default=0)
    _last_date:     str   = field(init=False, default="")

    closed_trades:  List[ClosedTrade]    = field(init=False, default_factory=list)
    _open_trade:    Optional[_OpenTrade] = field(init=False, default=None)

    bust_flag:   bool            = field(init=False, default=False)
    bust_at:     Optional[str]   = field(init=False, default=None)
    bust_equity: Optional[float] = field(init=False, default=None)

    def __post_init__(self):
        self.cash_balance = self.initial_cash

    def reset_daily(self, date_str: str):
        if date_str != self._last_date:
            self.trades_today = 0
            self._last_date   = date_str

    def set_open_tp_sl(self, take_profit: float, stop_loss: float):
        """บันทึก TP/SL price หลังจาก execute_buy สำเร็จ"""
        if self._open_trade is not None:
            self._open_trade.take_profit_price = float(take_profit or 0.0)
            self._open_trade.stop_loss_price   = float(stop_loss  or 0.0)
            logger.debug(
                f"  TP/SL set: TP={self._open_trade.take_profit_price:,.0f} "
                f"SL={self._open_trade.stop_loss_price:,.0f}"
            )
    def update_trailing_stop(self, current_buy_price: float, trailing_distance_thb: float = 150.0) -> bool:
        """
        [NEW] ฟังก์ชันขยับ Stop Loss ตามราคาที่พุ่งขึ้น (Trailing Stop Loss)
        คืนค่า True ถ้ามีการขยับ SL, คืนค่า False ถ้าไม่มีการขยับ
        """
        if self._open_trade is None:
            return False

        current_sl = self._open_trade.stop_loss_price

        # ถ้าไม่ได้ตั้ง SL ไว้แต่แรกให้ข้ามไป
        if current_sl <= 0:
            return False

        # คำนวณจุดตัดขาดทุนใหม่ (ราคารับซื้อปัจจุบัน - ระยะห่างที่ยอมรับได้)
        potential_new_sl = current_buy_price - trailing_distance_thb

        # 🚨 กฎเหล็ก: เลื่อนขึ้นได้อย่างเดียว ห้ามเลื่อนลง
        if potential_new_sl > current_sl:
            self._open_trade.stop_loss_price = potential_new_sl
            logger.info(
                f"🚀 [Trailing Stop] ราคาพุ่งมาที่ ฿{current_buy_price:,.0f} | "
                f"เลื่อน SL ขึ้นเป็น ฿{potential_new_sl:,.0f} (Lock-in Profit!)"
            )
            return True

        return False

    def check_auto_exit(self, current_buy_price: float) -> Optional[str]:
        """
        [NEW] ตรวจสอบว่าราคาปัจจุบันชน TP หรือ SL หรือไม่ (คืนค่าสาเหตุ)
        """
        if self._open_trade is None:
            return None

        tp = self._open_trade.take_profit_price
        sl = self._open_trade.stop_loss_price

        # เช็ค SL ก่อนเพื่อป้องกันความเสี่ยงสูงสุด
        if sl > 0 and current_buy_price <= sl:
            logger.warning(f"🛑 [AUTO-EXIT DETECTED] ราคา ฿{current_buy_price:,.0f} ชน Stop Loss ที่ ฿{sl:,.0f}!")
            return "SL"

        # เช็ค TP
        if tp > 0 and current_buy_price >= tp:
            logger.info(f"🎯 [AUTO-EXIT DETECTED] ราคา ฿{current_buy_price:,.0f} ชน Take Profit ที่ ฿{tp:,.0f}!")
            return "TP"

        return None

    def can_buy(self) -> bool:
        """
        [PATCH v3.0] เช็ค cash เพียงพอสำหรับ position + fee buffer
        ไม่ใช้ bust_threshold เป็น lower bound อีกต่อไป
        (bust_threshold=500 < DEFAULT_POSITION_THB=1000 → logic เดิมพัง)
        """
        min_needed = DEFAULT_POSITION_THB + MIN_FEE_BUFFER
        return self.cash_balance >= min_needed and self.gold_grams <= 1e-4

    def can_sell(self) -> bool:
        return self.gold_grams > 1e-4

    def execute_buy(
        self,
        price_thb_per_baht: float,
        position_thb: float,
        timestamp: str = "",
        hsh_sell: float = 0.0,
    ) -> bool:
        """
        ซื้อทอง — spread คำนวณ proportional ต่อบาทน้ำหนัก

        [PATCH v3.0] position_thb มาจาก risk.py (1,000 THB default)
        portfolio ไม่ hardcode — รับค่าจาก caller เสมอ

        Cost breakdown @ 71,950 THB/บาท, position=1,000:
          spread buy  = 1.67 THB
          commission  = 3.00 THB
          total cost  = 4.67 THB
          cash after  = 1,500 - 1,000 - 4.67 = 495.33 THB  ← มีเงินเหลือ!
          round-trip  = 1.67 + 1.67 + 3 = 6.34 THB (0.63%)
        """
        exec_price = hsh_sell if hsh_sell > 0 else price_thb_per_baht

        if hsh_sell > 0:
            spread_cost = 0.0
        else:
            spread_cost = _calc_spread(position_thb, exec_price)

        trade_cost = spread_cost + COMMISSION_BUY_THB 
        total_cost = position_thb + trade_cost

        # Cost warning: แจ้งเตือนถ้าต้นทุนไป-กลับ > 1.5%
        round_trip_cost_est = (spread_cost * 2) + COMMISSION_BUY_THB
        if position_thb > 0:
            cost_pct = (round_trip_cost_est / position_thb) * 100
            if cost_pct > 1.5:
                logger.warning(
                    f"⚠️ COST WARNING [{timestamp}]: ลงทุน {position_thb:.0f} THB "
                    f"ต้นทุนไป-กลับ {round_trip_cost_est:.2f} THB ({cost_pct:.2f}%)"
                )

        if self.cash_balance < total_cost:
            logger.debug(
                f"  BUY skipped: cash={self.cash_balance:.2f} < "
                f"need={total_cost:.2f} (pos={position_thb:.0f} + cost={trade_cost:.2f})"
            )
            return False

        grams = (position_thb / exec_price) * GOLD_GRAM_PER_BAHT
        self.cash_balance   -= total_cost
        self.gold_grams     += grams
        self.cost_basis_thb  = exec_price
        self.trades_today   += 1

        self._open_trade = _OpenTrade(
            entry_price=exec_price,
            gold_grams=grams,
            entry_time=timestamp,
            position_thb=position_thb,
            cost_at_entry=trade_cost,
        )
        
        if self.cash_balance < total_cost:
            self.last_trade_status = "REJECTED_CASH" # บอก AI ว่าทำไมเทรดไม่ได้
            return False

        logger.debug(
            f"  BUY: {grams:.4f}g @ {exec_price:,.0f} | "
            f"spread={spread_cost:.2f} comm={COMMISSION_BUY_THB} | "
            f"cash_after={self.cash_balance:.2f}"
        )
        self._check_bust(exec_price, timestamp)
        self.last_trade_status = "SUCCESS"
        return True

    def execute_sell(
        self,
        price_thb_per_baht: float,
        timestamp: str = "",
        hsh_buy: float = 0.0,
    ) -> bool:
        """ขายทองทั้งหมด — spread proportional, SELL commission = 0"""
        if not self.can_sell():
            return False

        exec_price = hsh_buy if hsh_buy > 0 else price_thb_per_baht

        if hsh_buy > 0:
            spread_cost = 0.0
        else:
            spread_cost = _calc_spread_from_grams(self.gold_grams, exec_price)

        trade_cost   = spread_cost + COMMISSION_SELL_THB
        proceeds     = (self.gold_grams / GOLD_GRAM_PER_BAHT) * exec_price
        net_proceeds = proceeds - trade_cost
        self.cash_balance += net_proceeds
        self.trades_today += 1

        if self._open_trade:
            ot = self._open_trade
            gross_pnl        = (ot.gold_grams / GOLD_GRAM_PER_BAHT) * (exec_price - ot.entry_price)
            total_cost_trade = ot.cost_at_entry + trade_cost
            net_pnl          = gross_pnl - total_cost_trade

            self.closed_trades.append(ClosedTrade(
                entry_price=ot.entry_price,
                exit_price=exec_price,
                gold_grams=ot.gold_grams,
                entry_time=ot.entry_time,
                exit_time=timestamp,
                position_thb=ot.position_thb,
                gross_pnl=gross_pnl,
                cost_thb=total_cost_trade,
                pnl_thb=net_pnl,
            ))
            logger.debug(
                f"  SELL: {ot.gold_grams:.4f}g @ {exec_price:,.0f} | "
                f"spread={spread_cost:.2f} comm={COMMISSION_SELL_THB} (ฟรี) | "
                f"gross={gross_pnl:+.2f} net={net_pnl:+.2f} | "
                f"cash_after={self.cash_balance:.2f}"
            )

        self.gold_grams     = 0.0
        self.cost_basis_thb = 0.0
        self._open_trade    = None

        self._check_bust(price_thb_per_baht, timestamp)
        return True

    def _check_bust(self, price: float, timestamp: str = ""):
        tv = self.total_value(price)
        if tv < self.bust_threshold:
            self.bust_flag   = True
            self.bust_at     = timestamp
            self.bust_equity = round(tv, 2)
            raise PortfolioBustException(tv, self.bust_threshold, timestamp)

    def current_value(self, price: float) -> float:
        return (self.gold_grams / GOLD_GRAM_PER_BAHT) * price

    def unrealized_pnl(self, price: float) -> float:
        if self.gold_grams <= 1e-4:
            return 0.0
        return self.current_value(price) - (
            (self.gold_grams / GOLD_GRAM_PER_BAHT) * self.cost_basis_thb
        )

    def total_value(self, price: float) -> float:
        return self.cash_balance + self.current_value(price)

    def total_return_pct(self, price: float) -> float:
        if self.initial_cash <= 0:
            return 0.0
        return (self.total_value(price) - self.initial_cash) / self.initial_cash * 100

    def is_winner(self, price: float) -> bool:
        return self.total_value(price) > self.win_threshold

    def to_market_state_dict(self, price: float) -> dict:
        min_needed = DEFAULT_POSITION_THB + MIN_FEE_BUFFER
        can_buy = (
            f"YES (cash={self.cash_balance:.0f})"
            if self.can_buy()
            else (
                f"NO (already holding gold)"
                if self.gold_grams > 1e-4
                else f"NO (cash={self.cash_balance:.0f} < {min_needed:.0f} needed)"
            )
        )
        can_sell = (
            f"YES ({self.gold_grams:.4f}g)"
            if self.can_sell()
            else "NO (no gold held)"
        )
        unrealized = self.unrealized_pnl(price)
        tp_price = self._open_trade.take_profit_price if self._open_trade else 0.0
        sl_price = self._open_trade.stop_loss_price   if self._open_trade else 0.0
        return {
            "cash_balance":      round(self.cash_balance, 2),
            "gold_grams":        round(self.gold_grams, 4),
            "cost_basis_thb":    round(self.cost_basis_thb, 2),
            "current_value_thb": round(self.current_value(price), 2),
            "unrealized_pnl":    round(unrealized, 2),
            "trades_today":      self.trades_today,
            "can_buy":           can_buy,
            "can_sell":          can_sell,
            "take_profit_price": round(tp_price, 2),
            "stop_loss_price":   round(sl_price, 2),
        }

    def summary(self, current_price: float) -> dict:
        return {
            "initial_cash_thb":    round(self.initial_cash, 2),
            "final_cash_thb":      round(self.cash_balance, 2),
            "final_gold_grams":    round(self.gold_grams, 4),
            "final_total_value":   round(self.total_value(current_price), 2),
            "total_return_pct":    round(self.total_return_pct(current_price), 2),
            "is_winner":           self.is_winner(current_price),
            "bust_flag":           self.bust_flag,
            "bust_at":             self.bust_at,
            "bust_equity":         self.bust_equity,
            "total_closed_trades": len(self.closed_trades),
        }


# ── Self-test ─────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG, format="%(message)s")
    print("=" * 60)
    print("SimPortfolio v3.0 — Scalping Self Test")
    print("=" * 60)

    price = 71_950.0

    p = SimPortfolio()
    print(f"\nInitial cash: {p.cash_balance:.2f} THB")
    print(f"can_buy()   : {p.can_buy()} (need >= {DEFAULT_POSITION_THB + MIN_FEE_BUFFER:.0f})")

    # ── BUY ──────────────────────────────────────────────────────
    ok = p.execute_buy(price, DEFAULT_POSITION_THB, "2026-04-05 10:00")
    assert ok, "BUY ควรสำเร็จ"

    bw            = DEFAULT_POSITION_THB / price
    spread_buy    = bw * SPREAD_PER_BAHT
    expected_cost = spread_buy + COMMISSION_BUY_THB
    expected_cash = DEFAULT_CASH - DEFAULT_POSITION_THB - expected_cost

    print(f"\nAfter BUY {DEFAULT_POSITION_THB:.0f} THB @ {price:,.0f}:")
    print(f"  baht_weight   = {bw:.6f}")
    print(f"  spread buy    = {spread_buy:.2f} THB")
    print(f"  commission    = {COMMISSION_BUY_THB} THB")
    print(f"  cash_after    = {p.cash_balance:.2f} THB  (expected ~{expected_cash:.2f})")
    print(f"  can_buy again = {p.can_buy()}  ← ถือทองอยู่ ต้องเป็น False")

    assert abs(p.cash_balance - expected_cash) < 0.01
    assert not p.can_buy(), "ถือทองอยู่ ต้อง can_buy=False"

    # ── SELL (break-even + small profit) ─────────────────────────
    # break-even = round-trip cost / baht_weight
    # round-trip = spread_buy + spread_sell + commission_buy
    round_trip = (spread_buy * 2) + COMMISSION_BUY_THB
    breakeven_move = round_trip / bw
    sell_price = price + breakeven_move + 50  # +50 THB กำไรเพิ่ม

    p.execute_sell(sell_price, "2026-04-05 10:30")
    t = p.closed_trades[0]

    print(f"\nAfter SELL @ {sell_price:,.0f} (+{sell_price - price:.0f} THB/บาท):")
    print(f"  break-even move = {breakeven_move:.0f} THB/บาท")
    print(f"  gross_pnl  = {t.gross_pnl:+.2f} THB")
    print(f"  cost_thb   = {t.cost_thb:.2f} THB  (spread×2 + commission BUY only)")
    print(f"  net_pnl    = {t.pnl_thb:+.2f} THB")
    print(f"  is_win     = {t.is_win}")
    print(f"  cash_after = {p.cash_balance:.2f} THB")
    print(f"  can_buy    = {p.can_buy()}  ← ขายแล้ว cash กลับมา ควร True")

    assert t.is_win, f"ควร win ที่ +{sell_price - price:.0f} THB move (break-even={breakeven_move:.0f})"
    assert p.can_buy(), "หลัง SELL ต้อง can_buy=True"

    print(f"\n✓ Position sizing v3.0 ถูกต้อง!")
    print(f"  Position    : {DEFAULT_POSITION_THB:.0f} THB (ลดจาก 1,400)")
    print(f"  Cash buffer : {p.cash_balance:.2f} THB หลังซื้อ (เดิมเหลือแค่ 97 THB)")
    print(f"  Round-trip  : {round_trip:.2f} THB ({round_trip/DEFAULT_POSITION_THB*100:.2f}% of position)")
    print(f"  Break-even  : {breakeven_move:.0f} THB/บาทน้ำหนัก move")