from typing import Optional, Tuple
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger("trading")

_TP_STATE_FILE = str(Path(__file__).parent.parent / "tp_state.json")  # Always resolves to Src_V4/

class DynamicTPManager:
    def __init__(
        self,
        atr_multiplier: float = 1.5,
        breakeven_atr_mult: float = 1.0,
        score_drop_threshold: float = 0.15,
        be_floor_offset: float = 2.0
    ):
        self.atr_mult = atr_multiplier
        self.be_mult = breakeven_atr_mult
        self.score_drop_thresh = score_drop_threshold
        self.be_floor_offset = be_floor_offset
        
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
        self._clear_state_file()  # ✅ I-2: Remove persisted state on reset

    def update(
        self,
        current_bid: float,
        atr_48: float,
        current_score: float
    ) -> Tuple[str, Optional[float], float]:
        if not self.is_active or current_bid is None or atr_48 is None or atr_48 <= 0:
            return "NONE", None, 0.0

        # 🔴 Priority 1: SL Hit — check BEFORE updating highest_bid
        # so that a gap-down below SL does not pollute the highest_bid state
        if self.sl_price is not None and current_bid <= self.sl_price:
            return "SL_HIT", self.sl_price, self.sl_price

        self.highest_bid = max(self.highest_bid, current_bid)
        raw_trail = self.highest_bid - (atr_48 * self.atr_mult)
        
        # The price target to trigger breakeven lock
        be_trigger_price = self.entry_ask + max(self.be_floor_offset, atr_48 * self.be_mult)
        
        # Floor for the trail once breakeven is locked
        be_floor = self.entry_ask + max(self.be_floor_offset, atr_48 * self.be_mult) 
        
        just_locked = False
        if not self._breakeven_locked and self.highest_bid >= be_trigger_price:
            self._breakeven_locked = True
            just_locked = True
            
        active_trail = max(raw_trail, be_floor) if self._breakeven_locked else raw_trail

        # 🔒 Priority 2: Breakeven Lock
        # Fire once when highest_bid reaches the trigger price
        if just_locked:
            return "BREAKEVEN_LOCK", be_floor, active_trail

        # 🔴 Priority 3: Trail Hit
        if current_bid <= active_trail:
            return "TRAIL_HIT", active_trail, active_trail

        # ⚠️ Priority 4: Score Fade
        if self.entry_score is not None and (self.entry_score - current_score) >= self.score_drop_thresh:
            return "SCORE_FADE", active_trail, active_trail

        # 📈 Priority 5: Normal
        return "TP_UPDATED", active_trail, active_trail

    # ── Restart persistence ───────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Snapshot current TP state for disk persistence."""
        return {
            "is_active"         : self.is_active,
            "entry_ask"         : self.entry_ask,
            "entry_score"       : self.entry_score,
            "sl_price"          : self.sl_price,
            "highest_bid"       : self.highest_bid,
            "_breakeven_locked" : self._breakeven_locked,
        }

    def save_to_file(self, path: str = _TP_STATE_FILE) -> None:
        """Persist TP state to disk so it survives an orchestrator restart."""
        try:
            temp_path = f"{path}.tmp"
            Path(temp_path).write_text(json.dumps(self.to_dict()), encoding="utf-8")
            os.replace(temp_path, path)
            logger.debug(f"[TP] State saved → {path}")
        except Exception as e:
            logger.warning(f"[TP] Failed to save state: {e}")

    def restore_from_file(self, path: str = _TP_STATE_FILE) -> bool:
        """
        Restore TP state from disk after a restart.
        Returns True if state was restored and is_active == True.
        """
        try:
            p = Path(path)
            if not p.exists():
                return False
            data = json.loads(p.read_text(encoding="utf-8"))
            self.is_active         = data.get("is_active", False)
            self.entry_ask         = data.get("entry_ask")
            self.entry_score       = data.get("entry_score")
            self.sl_price          = data.get("sl_price")
            self.highest_bid       = data.get("highest_bid", 0.0)
            self._breakeven_locked = data.get("_breakeven_locked", False)
            if self.is_active:
                logger.info(
                    f"[TP] ✅ Restored active TP state from {path} | "
                    f"entry_ask={self.entry_ask} highest_bid={self.highest_bid:.2f} "
                    f"sl_price={self.sl_price} breakeven_locked={self._breakeven_locked}"
                )
            return self.is_active
        except Exception as e:
            logger.warning(f"[TP] Failed to restore state from {path}: {e}")
            return False

    def _clear_state_file(self, path: str = _TP_STATE_FILE) -> None:
        """Remove the persisted state file when position is closed."""
        try:
            p = Path(path)
            if p.exists():
                p.unlink()
                logger.debug(f"[TP] State file cleared → {path}")
        except Exception as e:
            logger.warning(f"[TP] Failed to clear state file: {e}")