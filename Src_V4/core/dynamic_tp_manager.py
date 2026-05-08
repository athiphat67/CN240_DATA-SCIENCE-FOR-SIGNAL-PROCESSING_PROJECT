# core/dynamic_tp_manager.py
from typing import Optional, Tuple
import logging

logger = logging.getLogger("trading")

class DynamicTPManager:
    """
    M10-compatible dynamic take-profit/trailing stop manager.
    Designed for signal-only workflow: calculates exit levels and returns
    trigger types for Discord notifications. Manual execution required.
    """
    def __init__(
        self,
        atr_multiplier: float = 1.5,
        breakeven_atr_mult: float = 1.0,
        score_drop_threshold: float = 0.15
    ):
        self.atr_mult = atr_multiplier
        self.be_mult = breakeven_atr_mult
        self.score_drop_thresh = score_drop_threshold

        # In-memory state (survives pipeline calls, resets on SELL)
        self.is_active = False
        self.entry_ask: Optional[float] = None
        self.entry_score: Optional[float] = None
        self.highest_bid: float = 0.0
        self._breakeven_locked = False

    def activate(self, entry_ask: float, entry_score: float, initial_bid: float) -> None:
        """Call when a BUY signal is confirmed."""
        self.is_active = True
        self.entry_ask = entry_ask
        self.entry_score = entry_score
        self.highest_bid = initial_bid
        self._breakeven_locked = False
        logger.info(
            f"[TPManager] Activated | Entry Ask: {entry_ask:.2f} | "
            f"Score: {entry_score:.4f} | Initial Bid: {initial_bid:.2f}"
        )

    def reset(self) -> None:
        """Call when a SELL signal fires or position is manually closed."""
        self.is_active = False
        self.entry_ask = self.entry_score = None
        self.highest_bid = 0.0
        self._breakeven_locked = False
        logger.info("[TPManager] Reset on SELL/State change")

    def update(
        self,
        current_bid: float,
        atr_48: float,
        current_score: float
    ) -> Tuple[str, Optional[float], float]:
        """
        Evaluate trailing stop & model confidence every M10 bar.
        Returns: (trigger_type, suggested_price, current_trail_level)
        trigger_type: "NONE" | "TP_UPDATED" | "BREAKEVEN_LOCK" | "TRAIL_HIT" | "SCORE_FADE"
        """
        if not self.is_active or current_bid is None or atr_48 is None or atr_48 <= 0:
            return "NONE", None, 0.0

        # 1. Track highest bid since entry
        self.highest_bid = max(self.highest_bid, current_bid)

        # 2. Calculate raw trailing stop
        raw_trail = self.highest_bid - (atr_48 * self.atr_mult)

        # 3. Calculate breakeven floor (entry ask + spread buffer)
        # Buffer covers spread + minimal slippage. Volatility-relative for robustness.
        be_floor = self.entry_ask + max(2.0, atr_48 * 0.15)

        # 4. Active trail cannot drop below breakeven floor
        active_trail = max(raw_trail, be_floor)

        # --- Trigger Evaluation (Priority Order) ---

        # 🟢 Breakeven Lock (fires once when trail first hits the floor)
        if not self._breakeven_locked and active_trail == be_floor:
            self._breakeven_locked = True
            return "BREAKEVEN_LOCK", be_floor, active_trail

        # 🔴 Trail Hit (Price crossed below active trail → Exit Now)
        if current_bid <= active_trail:
            return "TRAIL_HIT", active_trail, active_trail

        # ⚠️ Score Fade (Model confidence dropped significantly since entry)
        if self.entry_score is not None and (self.entry_score - current_score) >= self.score_drop_thresh:
            return "SCORE_FADE", active_trail, active_trail

        # 📈 Normal Update (Trail moved up or held steady)
        return "TP_UPDATED", active_trail, active_trail