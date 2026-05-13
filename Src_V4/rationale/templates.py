# rationale/templates.py

# ==========================================
# 🟢 BULLISH DRIVERS (ใช้เมื่อสั่ง BUY)
# ==========================================
bullish_drivers = {
    'F_Thai_Premium': "significant mispricing detected in the Thai gold premium",
    'F_Regime': "bullish EMA crossover confirming a strong directional momentum",
    'F_Corr_XAU_USD': "highly supportive XAU/USD macro correlation setup",
    'F_RSI_14': "extreme RSI exhaustion signaling an immediate explosive bounce",
    'F_SRVR': "massive Session Remaining Volatility (SRVR) providing a wide profit runway",
    'F_Spread_vs_ATR': "highly favorable spread-to-ATR ratio justifying the transaction cost",
    'F_XAU_Mom_Short': "explosive short-term bullish momentum on XAU",
    'F_Syn_Price': "price trading heavily below the theoretical synthetic fair value",
    'F_XAU_Mom_Mid': "strong mid-term momentum aligning with the bullish trajectory",
    'F_BB_Pos': "price bouncing off the lower Bollinger Band indicating oversold conditions",
    'F_SA_TWAP_Dev': "price trading significantly below the session TWAP (mean reversion signal)",
    # ── v11 dominant features ──────────────────────────────────────────────────
    'F_FSP': "FSP forward price structure showing a bullish carry advantage over spot",
    'F_SA_Range': "wide session range signaling explosive intraday movement potential",
}

# ==========================================
# 🟡 HOLDING DRIVERS (ใช้เมื่อสั่ง HOLD และ ranker_score > 0 — "Patient & Sustained")
# ==========================================
holding_drivers = {
    'F_Thai_Premium': "Thai gold premium remains structurally supportive of our current position",
    'F_Regime': "bullish EMA regime remains firmly in control, validating the hold",
    'F_Corr_XAU_USD': "XAU/USD macro correlation continues to back our long thesis",
    'F_RSI_14': "RSI maintains healthy levels without overbought exhaustion, giving the trend room to run",
    'F_SRVR': "sufficient session volatility remaining to carry the position towards targets",
    'F_Spread_vs_ATR': "spread remains well-contained relative to volatility, keeping holding costs minimal",
    'F_XAU_Mom_Short': "sustained short-term momentum continues to underpin the current trade",
    'F_Syn_Price': "price action stays well-aligned with the synthetic fair value thesis",
    'F_XAU_Mom_Mid': "steady mid-term momentum confirms the broader trend is still intact",
    'F_BB_Pos': "price maintaining a healthy position within the Bollinger Bands without extreme deviation",
    'F_SA_TWAP_Dev': "price holding steadily above session TWAP, confirming intraday strength",
    # ── v11 dominant features ──────────────────────────────────────────────────
    'F_FSP': "FSP alignment continues to support the structural case for holding the position",
    'F_SA_Range': "healthy session range providing adequate volatility for position continuation",
}

# ==========================================
# 🔴 BEARISH DRAGS (ใช้เมื่อสั่ง SELL)
# ==========================================
bearish_drivers = {
    'F_Thai_Premium': "unfavorable and overpriced Thai gold premium destroying the edge",
    'F_Regime': "bearish regime activating, overriding short-term noise",
    'F_Corr_XAU_USD': "breakdown in standard XAU/USD correlation indicating macro stress",
    'F_RSI_14': "RSI overbought conditions indicating potential exhaustion and downside risk",
    'F_SRVR': "insufficient remaining volatility to justify the trade risk",
    'F_Spread_vs_ATR': "transaction cost (spread) is excessively high relative to current market volatility",
    'F_XAU_Mom_Short': "negative short-term momentum bleeding into local pricing",
    'F_Syn_Price': "price trading above synthetic fair value, structurally overvalued",
    'F_XAU_Mom_Mid': "loss of mid-term momentum, signaling a lack of buying pressure",
    'F_BB_Pos': "price trading above the upper Bollinger Band, at risk of a mean-reversion pullback",
    'F_SA_TWAP_Dev': "price trading significantly above the session TWAP (exhaustion signal)",
    # ── v11 dominant features ──────────────────────────────────────────────────
    'F_FSP': "FSP forward structure deteriorating, signaling an adverse carry cost headwind",
    'F_SA_Range': "session range compression exhausting volatility and increasing reversal risk",
}

# ==========================================
# ⚪ CAUTIOUS DRIVERS (ใช้เมื่อสั่ง HOLD และ ranker_score < 0 — "No Entry / Below Threshold")
# ใช้ negative SHAP features เพื่อ narrate เหตุผลที่ block entry
# ==========================================
cautious_drivers = {
    'F_Thai_Premium': "Thai gold premium is unfavorably priced, eroding the statistical edge",
    'F_Regime': "regime signal is insufficiently bullish to warrant entering the market",
    'F_Corr_XAU_USD': "XAU/USD macro correlation is misaligned, undermining the directional thesis",
    'F_RSI_14': "RSI configuration does not support a high-conviction entry at current levels",
    'F_SRVR': "remaining session volatility is too low to achieve an adequate reward-to-risk ratio",
    'F_Spread_vs_ATR': "transaction cost relative to volatility makes this entry uneconomical",
    'F_XAU_Mom_Short': "short-term momentum is negative, blocking the long entry signal",
    'F_Syn_Price': "price is above synthetic fair value — no statistical discount available",
    'F_XAU_Mom_Mid': "mid-term momentum is insufficient to support a high-confidence long",
    'F_BB_Pos': "Bollinger Band position indicates overbought conditions, blocking entry",
    'F_SA_TWAP_Dev': "price trading above session TWAP removes the mean-reversion setup",
    # ── v11 dominant features ──────────────────────────────────────────────────
    'F_FSP': "FSP signal is net negative — forward carry structure does not support entry",
    'F_SA_Range': "compressed session range limits the reward potential below the minimum threshold",
}