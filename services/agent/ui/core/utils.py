"""
utils.py — Utility functions (weighted voting, helpers)
Gold Trading Agent v3.2
"""
from typing import Dict, List, Tuple
from ui.core.config import INTERVAL_WEIGHTS
from logs.logger_setup import sys_logger

# ─────────────────────────────────────────────
# Weighted Voting Logic
# ─────────────────────────────────────────────

def calculate_weighted_vote(interval_results: Dict[str, dict]) -> dict:
    """
    Calculate weighted voting from multiple interval results
    
    Each interval has a weight (from config):
    - 1m: 3% (scalping, noisy)
    - 5m: 5% (day trading)
    - 15m: 10% (decent)
    - 30m: 15% (good)
    - 1h: 22% (sweet spot)
    - 4h: 30% (strong)
    - 1d: 12% (trend)
    - 1w: 3% (very long-term)
    
    Weighted score for signal = sum(confidence × weight) for that signal
    
    Example Input:
    {
        "1m":  {"signal": "HOLD", "confidence": 0.5},
        "15m": {"signal": "BUY", "confidence": 0.8},
        "1h":  {"signal": "BUY", "confidence": 0.85},
        "4h":  {"signal": "BUY", "confidence": 0.9},
        "1d":  {"signal": "SELL", "confidence": 0.6},
    }
    
    Example Output:
    {
        "final_signal": "BUY",
        "weighted_confidence": 0.822,
        "voting_breakdown": {
            "BUY": {
                "count": 3,
                "avg_conf": 0.85,
                "total_weight": 0.52,
                "weighted_score": 0.442
            },
            "SELL": {...},
            "HOLD": {...}
        },
        "interval_details": [...]
    }
    """
    
    if not interval_results:
        return {
            "final_signal": "HOLD",
            "weighted_confidence": 0.0,
            "voting_breakdown": {},
            "interval_details": [],
            "error": "No interval results provided"
        }
    
    # Step 1: Collect votes with weights
    interval_details = []
    signal_votes = {"BUY": [], "SELL": [], "HOLD": []}
    total_weight = 0
    
    for interval, result in interval_results.items():
        signal = result.get("signal", "HOLD")
        confidence = result.get("confidence", 0.0)
        weight = INTERVAL_WEIGHTS.get(interval, 0.0)
        
        if weight == 0:
            sys_logger.warning(f"Unknown interval {interval}, skipping weight")
            continue
        
        total_weight += weight
        signal_votes[signal].append({
            "confidence": confidence,
            "weight": weight,
            "interval": interval
        })
        
        interval_details.append({
            "interval": interval,
            "signal": signal,
            "confidence": round(confidence, 3),
            "weight": round(weight, 3)
        })
    
    if total_weight == 0:
        return {
            "final_signal": "HOLD",
            "weighted_confidence": 0.0,
            "voting_breakdown": {},
            "interval_details": interval_details,
            "error": "Total weight is zero"
        }
    
    # Step 2: Calculate weighted voting
    voting_breakdown = {}
    max_weighted_score = 0
    final_signal = "HOLD"
    
    for signal in ["BUY", "SELL", "HOLD"]:
        votes = signal_votes[signal]
        
        if not votes:
            voting_breakdown[signal] = {
                "count": 0,
                "avg_conf": 0.0,
                "total_weight": 0.0,
                "weighted_score": 0.0,
                "intervals": []
            }
            continue
        
        # Calculate average confidence
        avg_conf = sum(v["confidence"] for v in votes) / len(votes)
        
        # Calculate total weight for this signal
        total_signal_weight = sum(v["weight"] for v in votes)
        
        # Calculate weighted score = sum(confidence × weight) / total_weight
        weighted_score = sum(v["confidence"] * v["weight"] for v in votes) / total_weight
        
        interval_names = [v["interval"] for v in votes]
        
        voting_breakdown[signal] = {
            "count": len(votes),
            "avg_conf": round(avg_conf, 3),
            "total_weight": round(total_signal_weight, 3),
            "weighted_score": round(weighted_score, 3),
            "intervals": interval_names
        }
        
        # Track best signal
        if weighted_score > max_weighted_score:
            max_weighted_score = weighted_score
            final_signal = signal
            
        if max_weighted_score < 0.4: # ถ้าคะแนนรวมความมั่นใจน้อยกว่า 40%
             final_signal = "HOLD"
    
    # Step 3: Calculate overall confidence
    weighted_confidence = max_weighted_score
    
    sys_logger.info(
        f"Weighted voting: {final_signal} "
        f"(conf: {weighted_confidence:.1%}, "
        f"BUY: {voting_breakdown['BUY']['weighted_score']:.1%}, "
        f"SELL: {voting_breakdown['SELL']['weighted_score']:.1%}, "
        f"HOLD: {voting_breakdown['HOLD']['weighted_score']:.1%})"
    )
    
    return {
        "final_signal": final_signal,
        "weighted_confidence": round(weighted_confidence, 3),
        "voting_breakdown": voting_breakdown,
        "interval_details": interval_details
    }


def format_voting_summary(voting_result: dict) -> str:
    """Format voting result as readable text"""
    breakdown = voting_result.get("voting_breakdown", {})
    interval_details = voting_result.get("interval_details", [])
    
    lines = []
    lines.append(f"\n{'='*70}")
    lines.append(f"🗳️  WEIGHTED VOTING SUMMARY")
    lines.append(f"{'='*70}")
    
    # Show per-interval breakdown
    lines.append("\n📊 Per-Interval Results:")
    for detail in interval_details:
        iv = detail["interval"]
        sig = detail["signal"]
        conf = detail["confidence"]
        weight = detail["weight"]
        icon = {"BUY": "🟢", "SELL": "🔴"}.get(sig, "🟡")
        lines.append(
            f"  {iv:5s} → {icon} {sig:4s} | conf: {conf:6.1%} | weight: {weight:5.1%}"
        )
    
    # Show vote tallies
    lines.append("\n🎯 Vote Tally:")
    for signal in ["BUY", "SELL", "HOLD"]:
        vote_data = breakdown.get(signal, {})
        if vote_data.get("count", 0) > 0:
            icon = {"BUY": "🟢", "SELL": "🔴"}.get(signal, "🟡")
            intervals_str = ", ".join(vote_data.get("intervals", []))
            lines.append(
                f"  {icon} {signal:4s} → {vote_data['count']} votes | "
                f"avg conf: {vote_data['avg_conf']:.1%} | "
                f"total weight: {vote_data['total_weight']:.1%} | "
                f"weighted score: {vote_data['weighted_score']:.1%}"
            )
            lines.append(f"         Intervals: {intervals_str}")
    
    # Final decision
    final_signal = voting_result.get("final_signal", "HOLD")
    final_conf = voting_result.get("weighted_confidence", 0.0)
    icon = {"BUY": "🟢", "SELL": "🔴"}.get(final_signal, "🟡")
    
    lines.append(f"\n{'─'*70}")
    lines.append(f"🎯 FINAL DECISION: {icon} {final_signal}")
    lines.append(f"📊 Weighted Confidence: {final_conf:.1%}")
    lines.append(f"{'='*70}\n")
    
    return "\n".join(lines)


# ─────────────────────────────────────────────
# Error Message Formatting
# ─────────────────────────────────────────────

def format_error_message(error_dict: dict) -> str:
    """Format error dict to human-readable message"""
    status = error_dict.get("status", "unknown")
    error = error_dict.get("error", "Unknown error")
    error_type = error_dict.get("error_type", "general")
    attempt = error_dict.get("attempt", 0)
    
    if error_type == "validation":
        return f"❌ Validation Error:\n{error}"
    elif error_type == "api_failure":
        return f"⚠️  API Failed (Attempt {attempt}):\n{error}"
    else:
        return f"❌ Error:\n{error}"


def format_retry_status(attempt: int, max_retries: int, error: str) -> str:
    """Format retry status message"""
    if attempt < max_retries:
        return f"⏳ Attempt {attempt}/{max_retries} failed. Retrying... ({error})"
    else:
        return f"❌ Failed after {max_retries} attempts: {error}"


# ─────────────────────────────────────────────
# Confidence & Signal Helpers
# ─────────────────────────────────────────────

def strength_indicator(confidence: float) -> str:
    """Convert confidence to strength indicator"""
    if confidence >= 0.9:
        return "💪 Very Strong"
    elif confidence >= 0.75:
        return "💪 Strong"
    elif confidence >= 0.6:
        return "👍 Moderate"
    elif confidence >= 0.4:
        return "🤔 Weak"
    else:
        return "❓ Very Weak"


def confidence_bar(confidence: float, width: int = 20) -> str:
    """Create ASCII bar for confidence visualization"""
    filled = int(confidence * width)
    empty = width - filled
    bar = "█" * filled + "░" * empty
    percentage = f"{confidence:.0%}"
    return f"[{bar}] {percentage}"


def signal_recommendation(signal: str, confidence: float) -> str:
    """Get recommendation text based on signal and confidence"""
    if signal == "BUY":
        if confidence >= 0.8:
            return "🟢 Strong BUY recommendation — Good entry point"
        elif confidence >= 0.6:
            return "🟢 BUY — Consider entry with caution"
        else:
            return "🟢 BUY signal — Weak, wait for confirmation"
    
    elif signal == "SELL":
        if confidence >= 0.8:
            return "🔴 Strong SELL recommendation — Good exit point"
        elif confidence >= 0.6:
            return "🔴 SELL — Consider exit with caution"
        else:
            return "🔴 SELL signal — Weak, wait for confirmation"
    
    else:  # HOLD
        if confidence >= 0.5:
            return "🟡 Strong HOLD — Market is indecisive"
        else:
            return "🟡 HOLD — Insufficient signal, wait for clarity"


# ─────────────────────────────────────────────
# Portfolio Helpers
# ─────────────────────────────────────────────

def calculate_portfolio_metrics(portfolio: dict) -> dict:
    """Calculate additional metrics from portfolio data"""
    cash = portfolio.get("cash_balance", 0.0)
    gold_g = portfolio.get("gold_grams", 0.0)
    cost = portfolio.get("cost_basis_thb", 0.0)
    cur_val = portfolio.get("current_value_thb", 0.0)
    pnl = portfolio.get("unrealized_pnl", 0.0)
    
    total_value = cash + cur_val
    
    # Calculate percentages
    cash_pct = (cash / total_value * 100) if total_value > 0 else 0
    gold_pct = (cur_val / total_value * 100) if total_value > 0 else 0
    
    # Calculate ROI
    roi = ((cur_val - cost) / cost * 100) if cost > 0 else 0
    
    # Can transact?
    can_buy = cash >= 1000
    can_sell = gold_g > 0
    
    return {
        "total_value": round(total_value, 2),
        "cash_percentage": round(cash_pct, 1),
        "gold_percentage": round(gold_pct, 1),
        "roi": round(roi, 1),
        "can_buy": can_buy,
        "can_sell": can_sell,
        "gold_value_per_gram": round(cur_val / gold_g, 2) if gold_g > 0 else 0
    }


def validate_portfolio_update(old: dict, new: dict) -> Tuple[bool, str]:
    """
    Validate portfolio update for data quality
    
    Returns:
        (is_valid, error_message)
    """
    # Check for NaN or None
    for key in ["cash_balance", "gold_grams", "cost_basis_thb", "current_value_thb", "unrealized_pnl"]:
        if key in new:
            val = new[key]
            if val is None or (isinstance(val, float) and val != val):  # NaN check
                return False, f"Invalid value for {key}"
    
    # Check for negative values (except PnL)
    if new.get("cash_balance", 0) < 0:
        return False, "Cash balance cannot be negative"
    
    if new.get("gold_grams", 0) < 0:
        return False, "Gold grams cannot be negative"
    
    if new.get("cost_basis_thb", 0) < 0:
        return False, "Cost basis cannot be negative"
    
    if new.get("current_value_thb", 0) < 0:
        return False, "Current value cannot be negative"
    
    # Check for unrealistic changes
    if old and old.get("cash_balance"):
        old_cash = old.get("cash_balance", 0)
        new_cash = new.get("cash_balance", 0)
        # Alert if > 100% change (but allow it)
        if new_cash > 0 and old_cash > 0:
            change_pct = abs(new_cash - old_cash) / old_cash * 100
            if change_pct > 200:
                sys_logger.warning(f"Large cash change: {change_pct:.0f}%")
    
    return True, ""