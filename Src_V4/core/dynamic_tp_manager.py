from typing import Optional, Tuple
import logging

logger = logging.getLogger("trading")

class DynamicTPManager:
    def __init__(
        self,
        atr_multiplier: float = 1.5,
        breakeven_atr_mult: float = 1.0,
        score_drop_threshold: float = 0.15
    ):
        self.atr_mult = atr_multiplier
        self.be_mult = breakeven_atr_mult
        self.score_drop_thresh = score_drop_threshold
        
        self.is_active = False
        self.entry_ask: Optional[float] = None
        self.entry_score: Optional[float] = None
        self.sl_price: Optional[float] = None
        self.highest_bid: float = 0.0
        self._breakeven_locked = False

    def activate(
        self,
        entry_ask: float,
        entry_score: float,
        initial_bid: float,
        sl_price: Optional[float] = None
    ) -> None:
        self.is_active = True
        self.entry_ask = entry_ask
        self.entry_score = entry_score
        self.sl_price = sl_price
        self.highest_bid = initial_bid
        self._breakeven_locked = False

    def reset(self) -> None:
        self.is_active = False
        self.entry_ask = self.entry_score = self.sl_price = None
        self.highest_bid = 0.0
        self._breakeven_locked = False

    def update(
        self,
        current_bid: float,
        atr_48: float,
        current_score: float
    ) -> Tuple[str, Optional[float], float]:
        if not self.is_active or current_bid is None or atr_48 is None or atr_48 <= 0:
            return "NONE", None, 0.0

        self.highest_bid = max(self.highest_bid, current_bid)
        raw_trail = self.highest_bid - (atr_48 * self.atr_mult)
        be_floor = self.entry_ask + max(2.0, atr_48 * 0.15)
        active_trail = max(raw_trail, be_floor)

        # 🔴 Priority 1: SL Hit
        if self.sl_price is not None and current_bid <= self.sl_price:
            return "SL_HIT", self.sl_price, self.sl_price

        # 🔴 Priority 2: Trail Hit
        if current_bid <= active_trail:
            return "TRAIL_HIT", active_trail, active_trail

        # 🔒 Priority 3: Breakeven Lock
        if not self._breakeven_locked and active_trail == be_floor:
            self._breakeven_locked = True
            return "BREAKEVEN_LOCK", be_floor, active_trail

        # ⚠️ Priority 4: Score Fade
        if self.entry_score is not None and (self.entry_score - current_score) >= self.score_drop_thresh:
            return "SCORE_FADE", active_trail, active_trail

        # 📈 Priority 5: Normal
        return "TP_UPDATED", active_trail, active_trail