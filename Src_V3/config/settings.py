import os
from dotenv import load_dotenv

load_dotenv()

# ─── Mode ─────────────────────────────────────────────────────────────────────
DRY_RUN     = os.getenv("DRY_RUN", "false").lower() == "true"
LOG_LEVEL   = os.getenv("LOG_LEVEL", "INFO")
TIMEZONE    = os.getenv("TIMEZONE", "Asia/Bangkok")

# ─── Model ────────────────────────────────────────────────────────────────────
MODEL_PATH      = "models/lambdamart_v11.json"
MODEL_META_PATH = "models/lambdamart_v11_meta.json"
SIGNAL_THRESHOLD    = 0.65          # ranker score ≥ this → BUY
TIMEFRAME_MIN       = 10            # M10
LOOKBACK_BARS       = 2200          # bars to load (≥ OLS_WINDOW 2016)

# ─── Gold Constants ───────────────────────────────────────────────────────────
WEIGHT_TH_BAHT      = 15.244        # grams per 1 บาทไทย
WEIGHT_TROY_OUNCE   = 31.1035       # grams per troy oz
PURITY_TH_GOLD      = 0.965
PURITY_GLOBAL_GOLD  = 0.995
CONV_FACTOR         = (WEIGHT_TH_BAHT / WEIGHT_TROY_OUNCE) * (PURITY_TH_GOLD / PURITY_GLOBAL_GOLD)
# ≈ 0.4744

GOLD_WEIGHT_DECIMALS = 5            # truncate (ไม่ใช่ round) ทศนิยม 5 ตำแหน่ง

# ─── Trade Sizing ─────────────────────────────────────────────────────────────
INVESTMENT_AMOUNT_THB = 1_000.0
MAX_CONCURRENT_TRADES = 1

# ─── TP/SL ────────────────────────────────────────────────────────────────────
TP_ATR_MULTIPLIER   = 1.5
SL_ATR_MULTIPLIER   = 1.0
MIN_TP_DISTANCE_THB = 50.0
MAX_SL_DISTANCE_THB = 200.0

# ─── Session Definitions (M10 bars) ───────────────────────────────────────────
# Morning:   09:00–10:30 → 9 bars × 10min  = 90 min
# Afternoon: 13:00–15:20 → 14 bars × 10min = 140 min
# Night:     18:00–22:00 → 24 bars × 10min = 240 min
SESSION_HOURS = {
    "Morning"   : (9*60,   9*60 + 90),    # 540–630 นาทีนับจากเที่ยงคืน
    "Afternoon" : (13*60,  13*60 + 140),  # 780–920
    "Night"     : (18*60,  18*60 + 240),  # 1080–1320
}
SESSION_EXPECTED_BARS = {
    "Morning"   : 9,
    "Afternoon" : 14,
    "Night"     : 24,
}

# ─── Feature Windows (M10) ────────────────────────────────────────────────────
OLS_WINDOW          = 2016   # 2016 × 10min ≈ 2 สัปดาห์
ATR_WINDOW          = 48     # 48 × 10min  = 8 ชั่วโมง
CORR_WINDOW         = 18
VOL_WINDOW          = 144
SPREAD_NORM_WINDOW  = 144

# ─── Supabase ─────────────────────────────────────────────────────────────────
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# ─── Discord ──────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
DISCORD_MENTION_ID  = os.getenv("DISCORD_MENTION_ID", "")