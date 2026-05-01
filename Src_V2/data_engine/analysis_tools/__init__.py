# 1. Import all Technical Tools
from .technical_tools import (
    get_htf_trend,
    get_support_resistance_zones,
    detect_swing_low,
    detect_rsi_divergence,
    check_bb_rsi_combo,
    calculate_ema_distance,
    check_spot_thb_alignment,
    detect_breakout_confirmation,
    get_recent_indicators, # <--- เพิ่มตรงนี้
    check_bb_squeeze,
    detect_swing_high,
)

# 2. Import all Fundamental Tools
from .fundamental_tools import (
    get_deep_news_by_category,
    check_upcoming_economic_calendar,
    get_intermarket_correlation,
    get_gold_etf_flow,
)

# 3. Map Tool names (Strings returned by LLM) to actual functions
TOOL_REGISTRY = {
    # Technical
    "get_htf_trend": get_htf_trend,
    "get_support_resistance_zones": get_support_resistance_zones,
    "detect_swing_low": detect_swing_low,
    "detect_rsi_divergence": detect_rsi_divergence,
    "check_bb_rsi_combo": check_bb_rsi_combo,
    "calculate_ema_distance": calculate_ema_distance,
    "check_spot_thb_alignment": check_spot_thb_alignment,
    "detect_breakout_confirmation": detect_breakout_confirmation,
    "get_recent_indicators": get_recent_indicators, # <--- เพิ่มตรงนี้
    "check_bb_squeeze": check_bb_squeeze,
    "detect_swing_high": detect_swing_high,
    # Fundamental
    "get_deep_news_by_category": get_deep_news_by_category,
    "check_upcoming_economic_calendar": check_upcoming_economic_calendar,
    "get_intermarket_correlation": get_intermarket_correlation,
    "get_gold_etf_flow": get_gold_etf_flow,
}

# 4. LLM Manual (Injected into System Prompt)
AVAILABLE_TOOLS_INFO = """
[1. TECHNICAL ANALYSIS TOOLS]
1. get_htf_trend: Macro trend vs EMA200 (Recommended timeframe: '1h' for stability). Args: {"timeframe": "1h|4h|1d", "history_days": int}
2. get_support_resistance_zones: ATR-adjusted S/R mapping. Args: {"interval": "15m", "history_days": int}
3. detect_swing_low: V-shape bottom breakout reversal. Args: {"interval": "15m", "history_days": int, "lookback_candles": int}
4. detect_rsi_divergence: Bullish divergence (lower low price, higher low RSI). Args: {"interval": "15m", "history_days": int, "lookback_candles": int}
5. check_bb_rsi_combo: Reversal setup (Price<LowerBB, RSI<35, MACD flat). Args: {"interval": "15m", "history_days": int}
6. calculate_ema_distance: Overextended / Mean reversion check. Args: {"interval": "15m", "history_days": int}
7. check_spot_thb_alignment: XAU/USD vs USD/THB correlation effect on Thai gold. Args: {"interval": "15m", "lookback_candles": int}
8. detect_breakout_confirmation: Validate S/R zone breach (Real vs Fakeout). Args: {"zone_top": float, "zone_bottom": float, "interval": "15m", "history_days": int}
9. get_recent_indicators: Returns the last 5 candles' RSI, MACD hist, and EMA20 to check slope/trend. Args: {"interval": "15m", "lookback": int}
10. check_bb_squeeze: Identify low volatility periods before big moves (Bollinger Band Squeeze). Args: {"interval": "15m", "history_days": int}
11. detect_swing_high: A-shape top reversal. Args: {"interval": "15m", "history_days": int, "lookback_candles": int}

[2. FUNDAMENTAL ANALYSIS TOOLS]
1. get_deep_news_by_category: Current latest news & sentiment (cannot fetch historical news). Args: {"category": "gold_price|usd_thb|fed_policy|inflation|geopolitics|dollar_index|thai_economy|thai_gold_market"}
2. check_upcoming_economic_calendar: Red-folder high impact news (NFP/CPI) risk. Args: {"hours_ahead": int}
3. get_intermarket_correlation: Gold vs DXY/US10Y anomaly divergence. Args: {}
4. get_gold_etf_flow: SPDR GLD institutional flow (Inflow/Outflow). Args: {}
"""