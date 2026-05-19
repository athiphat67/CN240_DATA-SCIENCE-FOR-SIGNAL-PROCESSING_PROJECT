# core/signal_gate.py
import logging
from config.settings import (
    SIGNAL_THRESHOLD, DRY_RUN,
    STATE_EMPTY, STATE_HOLDING,
    GATE_SRVR_MIN, GATE_SPREAD_NORM_MAX, GATE_REGIME_REQUIRED,
    BUY_GATE_MODE, SIGNAL_CONFIG,
)
from core.state_manager import get_current_state
from core.feature_engine import FeaturesRow

logger = logging.getLogger("trading")


# Plausible sanity ranges. Outside these → bad feed / corrupted bar → skip.
_USD_THB_RANGE = (25.0, 40.0)
_XAU_USD_RANGE = (2000.0, 8000.0)


def _validate_features_quality(features_row: FeaturesRow) -> tuple[bool, str | None]:
    """Sanity check critical features before any gate decision.

    Catches two real-world failure modes seen in production:
      1. ATR_48 = 0  → no volatility data (early-session cold-start with bad
         IG feed). Trade entered here has no SL/Trail protection.
      2. Frozen price → SA_Range / SA_Vol / BB_Pos all zero simultaneously
         (single bad tick contaminated the resample and ffill carried it for
         multiple bars). Score and gates become meaningless.

    Returns (True, None) when the bar is healthy, else (False, reason_slug).
    """
    if features_row["F_ATR_48"] <= 0:
        return False, "atr_48_zero"

    if features_row["F_Historical_Vol_THB"] <= 0:
        return False, "hist_vol_zero"

    usd = features_row["usd_close"]
    if not (_USD_THB_RANGE[0] < usd < _USD_THB_RANGE[1]):
        return False, "usd_close_out_of_range"

    xau = features_row["xau_close"]
    if not (_XAU_USD_RANGE[0] < xau < _XAU_USD_RANGE[1]):
        return False, "xau_close_out_of_range"

    # Frozen-price signature: same hsh_close_ask carried for many bars → all
    # session-aware variance metrics collapse to 0 simultaneously.
    if (
        features_row["F_SA_Range"] == 0
        and features_row["F_SA_Vol"] == 0
        and abs(features_row["F_BB_Pos"]) < 1e-9
    ):
        return False, "frozen_price"

    return True, None


def _get_buy_config(session: str) -> tuple[float, float | None]:
    """
    คืนค่า (score_threshold, bb_pos_max) ตาม session ที่รับมา
    bb_pos_max = None หมายความว่าปิด filter BB ใน session นั้น
    """
    s = session.lower()
    if s == "morning":
        return (
            SIGNAL_CONFIG["score_threshold_morning"],
            SIGNAL_CONFIG["bb_pos_max_morning"],
        )
    elif s == "afternoon":
        return (
            SIGNAL_CONFIG["score_threshold_afternoon"],
            SIGNAL_CONFIG["bb_pos_max_afternoon"],
        )
    else:  # Night / fallback
        return (
            SIGNAL_CONFIG["score_threshold_night"],
            SIGNAL_CONFIG["bb_pos_max_night"],
        )


def evaluate_signal_gate(inference_result: dict, features_row: FeaturesRow) -> dict:
    """
    Phase 4: ตรวจสอบ State + Gate Conditions → ตัดสินใจ BUY / SELL / No Signal

    BUY gates (state = EMPTY):
      - market_open      : session != "Closed"
      - noise_gate       : F_XAU_Spread_Norm < GATE_SPREAD_NORM_MAX
      - score_gate       : ranker_score >= threshold ที่ตรงกับ session (SIGNAL_CONFIG)
      - srvr_gate        : F_SRVR >= GATE_SRVR_MIN
      - regime_gate      : F_Regime == GATE_REGIME_REQUIRED
      - bb_pos_gate      : F_BB_Pos <= bb_pos_max (ปิดได้ต่อ session ถ้า None)
      - rsi6_gate        : F_RSI_6 <= rsi6_max (ป้องกันซื้อตอน overbought ทุก session)
    """
    score     = inference_result["ranker_score"]
    session   = features_row["session"]
    F_SRVR    = features_row["F_SRVR"]
    F_Regime  = features_row["F_Regime"]
    F_BB_Pos  = features_row["F_BB_Pos"]
    F_RSI_6   = features_row["F_RSI_6"]

    # ใช้ F_XAU_Spread_Norm เป็น noise/spread gate
    F_Noise_Ratio = features_row["F_XAU_Spread_Norm"]

    current_state = get_current_state()

    # ── Data Quality Pre-Gate ─────────────────────────────────────────────────
    # Reject the bar entirely if the feature snapshot looks corrupted
    # (frozen prices, ATR=0, out-of-range macro). Without this, a single bad
    # tick from the HSH feed can pass a BUY gate with ATR=0 → no SL setup.
    quality_ok, quality_reason = _validate_features_quality(features_row)
    if not quality_ok:
        bt = features_row["bar_time"][:19].replace("-", "").replace(":", "").replace("T", "_")
        logger.warning(
            f"[Gate] 🛑 Bar rejected by data-quality pre-gate "
            f"(reason={quality_reason}, bar={features_row['bar_time']}, "
            f"F_ATR_48={features_row['F_ATR_48']}, "
            f"usd={features_row['usd_close']}, xau={features_row['xau_close']})"
        )
        return {
            "signal_id": f"sig_{bt}",
            "bar_time": features_row["bar_time"],
            "session": session,
            "signal_type": "HOLD",
            "ranker_score": score,
            "state_before": current_state,
            "gates_detail": {"data_quality_gate": False, "reason": quality_reason},
            "passed": False,
            "reject_reason": f"data_quality_{quality_reason}",
            "dry_run": DRY_RUN,
            "features_snap": inference_result["features_snap"],
            "hsh_ask": features_row["hsh_close_ask"],
            "hsh_bid": features_row["hsh_close_bid"],
            "xau_close": features_row["xau_close"],
            "usd_close": features_row["usd_close"],
            "atr_48": features_row["F_ATR_48"],
        }

    # ─── Shared Gates ─────────────────────────────────────────────────────────
    base_gates = {
        "market_open": session != "Closed",
        "noise_gate" : F_Noise_Ratio < GATE_SPREAD_NORM_MAX,
    }

    signal_type   = None
    passed        = False
    reject_reason = None
    gates_detail  = {}

    # ─── BUY Logic (state = EMPTY) ────────────────────────────────────────────
    if current_state == STATE_EMPTY:
        score_threshold, bb_pos_max = _get_buy_config(session)
        rsi6_max = SIGNAL_CONFIG["rsi6_max"]

        # bb_pos_gate: ปิดถ้า bb_pos_max เป็น None (เช่น Morning)
        bb_pos_ok = (bb_pos_max is None) or (F_BB_Pos <= bb_pos_max)

        buy_gates = {
            **base_gates,
            "score_gate"  : score >= score_threshold,
            "srvr_gate"   : F_SRVR >= GATE_SRVR_MIN,
            "regime_gate" : F_Regime == GATE_REGIME_REQUIRED,
            "bb_pos_gate" : bb_pos_ok,
            "rsi6_gate"   : F_RSI_6 <= rsi6_max,
        }

        gates_detail = buy_gates.copy()
        gates_detail["buy_gate_mode"]    = BUY_GATE_MODE
        gates_detail["score_threshold"]  = score_threshold
        gates_detail["bb_pos_max"]       = bb_pos_max
        gates_detail["rsi6_max"]         = rsi6_max

        logger.debug(
            f"[Gate] BUY eval | session={session} | score={score:.4f} "
            f"(thr={score_threshold}) | BB={F_BB_Pos:.3f} (max={bb_pos_max}) "
            f"| RSI6={F_RSI_6:.1f} (max={rsi6_max})"
        )

        if BUY_GATE_MODE == "LIVE_RELAXED":
            passed = (
                buy_gates["market_open"]
                and buy_gates["noise_gate"]
                and buy_gates["score_gate"]
                and buy_gates["bb_pos_gate"]
                and buy_gates["rsi6_gate"]
                and (buy_gates["srvr_gate"] or buy_gates["regime_gate"])
            )
        else:  # STRICT — ต้องผ่านทุก gate
            passed = all(v for k, v in buy_gates.items() if k != "buy_gate_mode")

        signal_type   = "BUY" if passed else "HOLD"
        reject_reason = None if passed else next(
            k for k, v in buy_gates.items()
            if isinstance(v, bool) and not v
        )

    # ─── SELL Logic (state = HOLDING) ─────────────────────────────────────────────
    elif current_state == STATE_HOLDING:
        # ── Profit-Aware Exit Check ─────────────────────────────────────
        # The model is only allowed to exit if the trade is actually in profit.
        # If in a drawdown, we hold and let the Dynamic TP Manager handle the actual Stop Loss.
        #
        # Safety: when no active trade can be located (DB miss / desync / error)
        # we SUPPRESS the SELL signal. State=HOLDING without an active_trade row
        # is a desync that requires UI reconciliation — emitting a phantom SELL
        # here would create an orphan pending signal.
        profit_ok = False
        active_trade_missing = False

        try:
            from db.supabase_writer import get_open_trade
            open_trade = get_open_trade()
            if open_trade and open_trade.get("entry_ask"):
                entry_ask = float(open_trade["entry_ask"])
                current_bid = float(features_row["hsh_close_bid"])

                if current_bid > entry_ask:
                    profit_ok = True
                else:
                    logger.info(
                        f"[Gate] 🛑 SELL suppressed: Not in profit "
                        f"(Bid: {current_bid} <= Ask: {entry_ask}). "
                        "Waiting for TP Manager to handle Stop Loss."
                    )
            else:
                active_trade_missing = True
                logger.warning(
                    "[Gate] 🛑 SELL suppressed: state=HOLDING but no active trade found. "
                    "Reconcile via UI (Force Reset or re-confirm BUY)."
                )
        except Exception as _e:
            active_trade_missing = True
            logger.error(f"[Gate] Profit-Aware check failed; SELL suppressed: {_e}")

        sell_gates = {
            **base_gates,
            "score_below_threshold": score < SIGNAL_THRESHOLD,
            "profit_ok"            : profit_ok,
            "active_trade_exists"  : not active_trade_missing,
        }
        gates_detail = sell_gates
        passed = all(sell_gates.values())
        signal_type   = "SELL" if passed else "HOLD"  # 🔁 เปลี่ยน None → HOLD
        reject_reason = None if passed else next(k for k, v in sell_gates.items() if not v)

    else:
        raise RuntimeError(f"[Gate] Unknown state: {current_state}")
        
    # ─── Signal ID Generation ─────────────────────────────────────────────────
    # Format: sig_YYYYMMDD_HHMMSS
    bt = features_row["bar_time"][:19].replace("-", "").replace(":", "").replace("T", "_")
    signal_id = f"sig_{bt}"
    
    return {
        "signal_id": signal_id,
        "bar_time": features_row["bar_time"],
        "session": session,
        "signal_type": signal_type,
        "ranker_score": score,
        "state_before": current_state,
        "gates_detail": gates_detail,
        "passed": passed,
        "reject_reason": reject_reason,
        "dry_run": DRY_RUN,
        "features_snap": inference_result["features_snap"],
        "hsh_ask": features_row["hsh_close_ask"],
        "hsh_bid": features_row["hsh_close_bid"],
        "xau_close": features_row["xau_close"],
        "usd_close": features_row["usd_close"],
        "atr_48": features_row["F_ATR_48"],
    }