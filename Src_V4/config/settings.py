import os
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

load_dotenv()

# ─── Mode ─────────────────────────────────────────────────────────────────────
DRY_RUN     = os.getenv("DRY_RUN", "false").lower() == "true"
LOG_LEVEL   = os.getenv("LOG_LEVEL", "INFO")
TIMEZONE    = os.getenv("TIMEZONE", "Asia/Bangkok")

# ─── Model ────────────────────────────────────────────────────────────────────
MODEL_PATH          = "models/lambdamart_v11.json"
MODEL_META_PATH     = "models/lambdamart_v11_meta.json"
SIGNAL_THRESHOLD    = 0.07          # ranker score ≥ this → trigger BUY/SELL check
TIMEFRAME_MIN       = 10            # M10
LOOKBACK_BARS       = 2200          # bars to load (≥ OLS_WINDOW 2016)

# ─── Gold Constants ───────────────────────────────────────────────────────────
WEIGHT_TH_BAHT      = 15.244        # grams per 1 บาทไทย
WEIGHT_TROY_OUNCE   = 31.1035       # grams per troy oz
PURITY_TH_GOLD      = 0.965
PURITY_GLOBAL_GOLD  = 0.995
CONV_FACTOR         = (WEIGHT_TH_BAHT / WEIGHT_TROY_OUNCE) * (PURITY_TH_GOLD / PURITY_GLOBAL_GOLD)
# ≈ 0.4744

# ─── State ────────────────────────────────────────────────────────────────────
STATE_EMPTY   = "EMPTY"             # ไม่มีทองในมือ → อนุญาตเฉพาะ BUY
STATE_HOLDING = "HOLDING"           # มีทองในมืออยู่ → อนุญาตเฉพาะ SELL

# ─── Session Definitions (M10 bars) ───────────────────────────────────────────
SESSION_HOURS = {
    "Morning"   : (6*60,  12*60),   # 06:00 - 11:59 → 360-720 นาที
    "Afternoon" : (12*60, 18*60),   # 12:00 - 17:59 → 720-1080 นาที
    "Night"     : (18*60, 2*60),    # 18:00 - 01:59 → 1080-120 นาที [ข้ามเที่ยงคืน]
}
SESSION_EXPECTED_BARS = {
    "Morning"   : 36,  # 6 ชม. × 6 แท่ง/ชม.
    "Afternoon" : 36,  # 6 ชม. × 6 แท่ง/ชม.
    "Night"     : 48,  # 8 ชม. × 6 แท่ง/ชม.
}

# ─── Feature Windows (M10) ────────────────────────────────────────────────────
OLS_WINDOW          = 2016   # 2016 × 10min ≈ 2 สัปดาห์
ATR_WINDOW          = 48     # 48 × 10min  = 8 ชั่วโมง
CORR_WINDOW         = 18
VOL_WINDOW          = 144
SPREAD_NORM_WINDOW  = 144

# ─── Signal Gate Thresholds ───────────────────────────────────────────────────
GATE_SRVR_MIN           = 0.15
GATE_SPREAD_NORM_MAX    = 2.5
GATE_REGIME_REQUIRED    = 1
BUY_GATE_MODE           = os.getenv("BUY_GATE_MODE", "STRICT")  # STRICT | LIVE_RELAXED

# ─── Supabase ─────────────────────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# ─── Discord ──────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_MENTION_ID  = os.getenv("DISCORD_MENTION_ID", "")

# ─── Send trade log ───────────────────────────────────────────────────────────
TRADE_LOG_API_URL = os.getenv("TRADE_LOG_API_URL", "")
TRADE_LOG_API_KEY = os.getenv("TRADE_LOG_API_KEY", "")

# ─── Dynamic TP Manager ──────────────────────────────────────────
TP_ATR_MULTIPLIER       = 1.5   # Trail distance
TP_BREAKEVEN_ATR_MULT   = 1.0   # Lock trail after this profit
TP_SCORE_DROP_THRESH    = 0.15  # Early warning threshold

# ─── Execution Confirmation ──────────────────────────────────────────────────
REQUIRE_BUY_CONFIRM = os.getenv("REQUIRE_BUY_CONFIRM", "true").lower() == "true"
AUTO_CONFIRM_SELL   = os.getenv("AUTO_CONFIRM_SELL", "true").lower() == "true"

SIGNALS_TABLE       = os.getenv("SIGNALS_TABLE", "v3_signals")
BAR_LOGS_TABLE      = os.getenv("BAR_LOGS_TABLE", "v3_bar_logs")
SYSTEM_STATE_TABLE  = os.getenv("SYSTEM_STATE_TABLE", "v3_system_state")
ACTIVE_TRADES_TABLE = os.getenv("ACTIVE_TRADES_TABLE", "v3_active_trades")