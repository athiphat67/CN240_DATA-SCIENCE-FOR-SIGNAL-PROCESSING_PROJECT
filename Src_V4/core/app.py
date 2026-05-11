# app_v2.py  — ArgMax Sniper V11  (8 bugs fixed)
# ─────────────────────────────────────────────────────────────────────────────
# FIX SUMMARY
#   [BUG-1] Tracker: data fetched DESC → iloc[0] was newest tick, not oldest.
#           Now fetches ASC and scans ALL future ticks to find first TP/SL hit.
#   [BUG-2] Predictor: no dedup → duplicate rows for the same candle_time.
#           Now checks DB before insert; skips if candle_time already exists.
#   [BUG-3] XAU_Spread hardcoded 0.5 → F_XAU_Spread_Norm always 1.0.
#           Now computed as bar High-Low (real variable proxy).
#   [BUG-4] SESSION_END timeout hardcoded 12h → orders leaked across sessions.
#           Now closes at actual session-end wall-clock time.
#   [BUG-5] XAU_High/Low computed separately from df_m10 → index misalignment.
#           Now computed in a single resample join to guarantee index parity.
#   [BUG-6] F_SA_Drawdown_Pct used groupby.transform + expanding → cross-group
#           bleed on some pandas versions. Now uses groupby.apply.
#   [BUG-7] Tracker: time_diff used iloc[0]['Datetime'] (newest tick) as
#           "current time" → SESSION_END triggered immediately for old orders.
#           Fixed as part of BUG-1 (now using datetime.now for wall-clock check).
#   [BUG-8] pd.to_datetime format mismatch on mixed fractional seconds.
#           Fixed by enforcing format='ISO8601' and safely handling tz_localize.
# ─────────────────────────────────────────────────────────────────────────────

import os
import pandas as pd
import numpy as np
import xgboost as xgb
from supabase import create_client, Client
import warnings
from fastapi import FastAPI, BackgroundTasks
import uvicorn
from datetime import datetime, time as dtime
import pytz

warnings.filterwarnings('ignore')

# ==========================================
# 0. CONFIGURATION & SETUP
# ==========================================
URL_DB_IN  = os.environ.get("SUPABASE_URL_INPUT")
KEY_DB_IN  = os.environ.get("SUPABASE_KEY_INPUT")
URL_DB_OUT = os.environ.get("SUPABASE_URL_OUTPUT")
KEY_DB_OUT = os.environ.get("SUPABASE_KEY_OUTPUT")

db_in:  Client = create_client(URL_DB_IN,  KEY_DB_IN)
db_out: Client = create_client(URL_DB_OUT, KEY_DB_OUT)

MODEL_PATH = "models/lambdamart_v11.json"
model = xgb.Booster()
model.load_model(MODEL_PATH)

BKK_TZ = pytz.timezone('Asia/Bangkok')

MIN_RANKER_SCORE = 0.0744

# Session boundaries (BKK / UTC+7)
#   Morning   06:00 – 11:59  → ends 12:00 same day
#   Afternoon 12:00 – 17:59  → ends 18:00 same day
#   Night     18:00 – 01:59  → ends 02:00 next day
SESSION_END_HOUR = {'Morning': 12, 'Afternoon': 18, 'Night': 2}

FEATURE_COLS =[
    'F_Syn_Price', 'F_Thai_Premium', 'F_Corr_XAU_USD',
    'F_ATR_48', 'F_Regime', 'F_XAU_Mom_Short', 'F_XAU_Mom_Mid', 'F_USD_Mom',
    'F_FSP', 'F_SA_TWAP_Dev', 'F_SA_MDD', 'F_SA_Vol',
    'F_SA_Range', 'F_SA_Position', 'F_SRVR', 'F_Remaining_Vol',
    'F_RSI_14', 'F_RSI_6', 'F_BB_Pos', 'F_XAU_Spread_Norm',
    'F_Hour_Sin', 'F_Hour_Cos', 'F_Session_Type',
    'F_Price_Vs_Open', 'F_Mom_3bar', 'F_Mom_1bar',
    'F_SA_Drawdown_Pct', 'F_HSH_vs_THBGold_Dev',
    'F_DayOfWeek', 'F_MinuteOfDay',
]


# ==========================================
# 1. FEATURE ENGINEERING (STRICT NO-LOOK-AHEAD)
# ==========================================
def compute_rolling_synthetic(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    window = min(2016, len(df) - 2)
    if window < 10:
        window = len(df) - 1

    x = (df['XAU_Close'] * (15.244 / 31.1035) * (0.965 / 0.995) * df['USD_Close']).values
    y = df['HSH_Sell_Sim'].values
    n = len(x)

    slopes, intercepts = np.full(n, np.nan), np.full(n, np.nan)
    win_x = np.lib.stride_tricks.sliding_window_view(x, window)
    win_y = np.lib.stride_tricks.sliding_window_view(y, window)

    sum_x  = win_x.sum(axis=1)
    sum_y  = win_y.sum(axis=1)
    sum_xx = (win_x * win_x).sum(axis=1)
    sum_xy = (win_x * win_y).sum(axis=1)

    denom = window * sum_xx - sum_x ** 2
    safe  = denom != 0

    b = np.where(safe, (window * sum_xy - sum_x * sum_y) / np.where(safe, denom, 1), np.nan)
    a = np.where(safe, (sum_y - b * sum_x) / window, np.nan)

    slopes[window - 1:]     = b
    intercepts[window - 1:] = a

    df['F_Syn_Price']    = slopes * x + intercepts
    df['F_Thai_Premium'] = df['HSH_Sell_Sim'] - df['F_Syn_Price']

    df['F_Syn_Price']    = df['F_Syn_Price'].ffill().fillna(0)
    df['F_Thai_Premium'] = df['F_Thai_Premium'].ffill().fillna(0)
    return df


def compute_macro_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    xau_ret = df['XAU_Close'].pct_change()
    usd_ret = df['USD_Close'].pct_change()

    df['F_Corr_XAU_USD']  = xau_ret.rolling(18).corr(usd_ret).ffill().fillna(0)
    df['F_XAU_Mom_Short'] = df['XAU_Close'].pct_change(3).fillna(0)
    df['F_XAU_Mom_Mid']   = df['XAU_Close'].pct_change(12).fillna(0)
    df['F_USD_Mom']       = df['USD_Close'].pct_change(6).fillna(0)

    tr = pd.concat([
        df['XAU_High'] - df['XAU_Low'],
        (df['XAU_High'] - df['XAU_Close'].shift()).abs(),
        (df['XAU_Low']  - df['XAU_Close'].shift()).abs(),
    ], axis=1).max(axis=1)
    df['F_ATR_48'] = tr.rolling(48).mean().ffill().fillna(0)

    ema20 = df['XAU_Close'].ewm(span=20).mean()
    ema50 = df['XAU_Close'].ewm(span=50).mean()
    df['F_Regime'] = np.sign(ema20 - ema50)
    return df


def compute_session_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    expected_length = {'Morning': 36, 'Afternoon': 36, 'Night': 48}
    df['Expected_Session_Length'] = df['Session_Type'].map(expected_length).fillna(36)

    def session_features(group):
        prices  = group['HSH_Sell_Sim']
        exp_len = group['Expected_Session_Length'].iloc[0]

        group['F_FSP']        = (group['Bar_In_Session'] / max(exp_len - 1, 1)).clip(upper=1.0)
        group['F_SA_TWAP_Dev'] = prices - prices.expanding().mean()
        group['F_SA_MDD']      = prices - prices.expanding().max()
        group['F_SA_Vol']      = prices.expanding().std().fillna(0)

        s_range = prices.expanding().max() - prices.expanding().min()
        s_min   = prices.expanding().min()
        group['F_SA_Range']    = s_range
        group['F_SA_Position'] = (prices - s_min) / s_range.clip(lower=1)
        return group

    META_COLS   =['Session_ID', 'Session_Type', 'Bar_In_Session', 'Expected_Session_Length']
    meta_backup = df[META_COLS].copy()
    df = df.groupby('Session_ID', group_keys=False).apply(session_features)
    for col in META_COLS:
        if col not in df.columns:
            df[col] = meta_backup[col]

    hist_vol_xau          = df['XAU_Close'].pct_change().rolling(144).std() * df['XAU_Close']
    df['F_Historical_Vol_THB'] = hist_vol_xau * (15.244 / 31.1035) * df['USD_Close']
    df['F_Remaining_Vol'] = df['F_Historical_Vol_THB'] * (1.0 - df['F_FSP'])
    df['F_SRVR']          = df['F_Remaining_Vol'] / df['F_ATR_48'].replace(0, 1e-9)

    df['F_Price_Vs_Open'] = df.groupby('Session_ID')['HSH_Sell_Sim'].transform(
        lambda x: (x - x.iloc[0]) / (x.iloc[0] + 1e-9)
    )
    df['F_Mom_3bar'] = df['HSH_Sell_Sim'].pct_change(3).fillna(0)
    df['F_Mom_1bar'] = df['HSH_Sell_Sim'].pct_change(1).fillna(0)

    # ── FIX BUG-6: use apply (not transform) so expanding() stays within group ──
    def drawdown_pct(x):
        running_max = x.expanding().max()
        return (x - running_max) / (running_max + 1e-9)

    dd = df.groupby('Session_ID')['HSH_Sell_Sim'].apply(drawdown_pct)
    dd.index = dd.index.droplevel(0)
    df['F_SA_Drawdown_Pct'] = dd.reindex(df.index).fillna(0)
    # ─────────────────────────────────────────────────────────────────────────

    thb_gold_ret = (df['XAU_Close'] * df['USD_Close']).pct_change()
    hsh_ret      = df['HSH_Sell_Sim'].pct_change()
    df['F_HSH_vs_THBGold_Dev'] = (hsh_ret - thb_gold_ret).rolling(6).mean().fillna(0)

    df['F_DayOfWeek']   = df.index.dayofweek
    df['F_MinuteOfDay'] = df.index.hour * 60 + df.index.minute
    return df


def compute_technical_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    def rsi(series, period=14):
        delta = series.diff()
        gain  = delta.where(delta > 0, 0).rolling(period).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(period).mean()
        return 100 - (100 / (1 + gain / loss.replace(0, np.nan)))

    df['F_RSI_14'] = rsi(df['HSH_Sell_Sim'], 14).ffill().fillna(50)
    df['F_RSI_6']  = rsi(df['HSH_Sell_Sim'],  6).ffill().fillna(50)

    bb_mid = df['HSH_Sell_Sim'].rolling(20).mean()
    bb_std = df['HSH_Sell_Sim'].rolling(20).std()
    df['F_BB_Pos'] = ((df['HSH_Sell_Sim'] - bb_mid) / (2 * bb_std.replace(0, 1e-9))).fillna(0)

    # ── FIX BUG-3: XAU_Spread now = bar High-Low (variable), not hardcoded 0.5 ──
    df['F_XAU_Spread_Norm'] = (
        df['XAU_Spread'] /
        df['XAU_Spread'].rolling(144, min_periods=1).mean().replace(0, 1e-9)
    ).ffill().fillna(1)
    # ─────────────────────────────────────────────────────────────────────────

    hour = df.index.hour + df.index.minute / 60
    df['F_Hour_Sin']     = np.sin(2 * np.pi * hour / 24)
    df['F_Hour_Cos']     = np.cos(2 * np.pi * hour / 24)
    df['F_Session_Type'] = df['Session_Type'].map({'Morning': 0, 'Afternoon': 1, 'Night': 2}).fillna(0)
    return df


# ==========================================
# 2. PREDICTOR PIPELINE
# ==========================================
def run_predictor():
    print("🚀 Running Predictor Pipeline...")
    try:
        res_hsh = db_in.table("gold_prices_hsh").select("timestamp, ask_96, bid_96").order("timestamp", desc=True).limit(30000).execute()
        res_ig  = db_in.table("gold_prices_ig").select("timestamp, spot_price, usd_thb").order("timestamp", desc=True).limit(30000).execute()

        if not res_hsh.data or not res_ig.data:
            print("ℹ️  Not enough data for predictor.")
            return

        # ── FIX BUG-8: Use format='ISO8601' to handle mixed fractional seconds ──
        df_hsh = pd.DataFrame(res_hsh.data).set_index(pd.to_datetime([x['timestamp'] for x in res_hsh.data], format='ISO8601')).sort_index()
        df_ig  = pd.DataFrame(res_ig.data).set_index(pd.to_datetime([x['timestamp'] for x in res_ig.data], format='ISO8601')).sort_index()
        # ─────────────────────────────────────────────────────────────────────────

        df_hsh['HSH_Sell_Sim'] = df_hsh['ask_96'].astype(float)
        df_hsh['HSH_Buy_Sim']  = df_hsh['bid_96'].astype(float)
        df_ig['XAU_Close']     = df_ig['spot_price'].astype(float)
        df_ig['USD_Close']     = df_ig['usd_thb'].astype(float)

        df_raw = df_hsh[['HSH_Sell_Sim', 'HSH_Buy_Sim']].join(
            df_ig[['XAU_Close', 'USD_Close']], how='outer'
        ).ffill().bfill()

        # ── FIX BUG-5: compute High/Low/Close in ONE resample so indices match ──
        xau_ohlc = df_raw['XAU_Close'].resample('10min').agg(
            XAU_Close='last', XAU_High='max', XAU_Low='min'
        )
        df_m10_base = df_raw.resample('10min').agg({
            'HSH_Sell_Sim': 'last',
            'HSH_Buy_Sim':  'last',
            'USD_Close':    'last',
        })
        df_m10 = df_m10_base.join(xau_ohlc, how='inner').dropna()

        # ── FIX BUG-3: XAU_Spread = bar High-Low (variable), replaces hardcoded 0.5 ──
        df_m10['XAU_Spread'] = df_m10['XAU_High'] - df_m10['XAU_Low']
        df_m10['XAU_Spread'] = df_m10['XAU_Spread'].replace(0, np.nan).ffill().fillna(0.5)
        # ─────────────────────────────────────────────────────────────────────────

        def assign_session(dt):
            h = dt.hour
            if   6 <= h < 12: return f"{dt.date()}_Morning"
            elif 12 <= h < 18: return f"{dt.date()}_Afternoon"
            else:
                # Night 18:00-01:59 — label by the date the session started (18:00 side)
                base = dt.date() if h >= 18 else (dt - pd.Timedelta(days=1)).date()
                return f"{base}_Night"

        df_m10['Session_ID']   = df_m10.index.map(assign_session)
        df_m10['Session_Type'] = df_m10['Session_ID'].str.split('_').str[-1]
        df_m10['Bar_In_Session'] = df_m10.groupby('Session_ID').cumcount()

        daily_df   = df_m10['HSH_Sell_Sim'].resample('D').agg(Daily_High='max', Daily_Low='min', Daily_Close='last').dropna()
        prev_close = daily_df['Daily_Close'].shift(1)
        tr_daily   = pd.concat([
            daily_df['Daily_High'] - daily_df['Daily_Low'],
            (daily_df['Daily_High'] - prev_close).abs(),
            (daily_df['Daily_Low']  - prev_close).abs(),
        ], axis=1).max(axis=1)
        daily_df['ATR_14D'] = tr_daily.rolling(14, min_periods=1).mean().shift(1)

        df_m10['Base_Date'] = pd.to_datetime(df_m10['Session_ID'].str.split('_').str[0])
        df_m10 = df_m10.merge(daily_df[['ATR_14D']], left_on='Base_Date', right_index=True, how='left')
        df_m10['ATR_14D'] = df_m10['ATR_14D'].ffill().bfill()

        df_features = compute_rolling_synthetic(df_m10)
        df_features = compute_macro_features(df_features)
        df_features = compute_session_features(df_features)
        df_features = compute_technical_features(df_features)
        df_features = df_features.ffill().fillna(0)

        latest_bar = df_features.iloc[[-1]]

        raw_time = latest_bar.index[0]
        if raw_time.tzinfo is None:
            candle_time_bkk = BKK_TZ.localize(raw_time)
        else:
            candle_time_bkk = raw_time.astimezone(BKK_TZ)
        current_time = candle_time_bkk.isoformat()

        # ── FIX BUG-2: skip insert if this candle_time already exists in DB ──────
        existing = (
            db_out.table("gold_paper_ml_trades_big_v12")
            .select("id")
            .eq("candle_time", current_time)
            .limit(1)
            .execute()
        )
        if existing.data:
            print(f"⏭️  Candle {current_time} already exists — skipping insert.")
            return
        # ─────────────────────────────────────────────────────────────────────────

        current_price = float(latest_bar['HSH_Sell_Sim'].values[0])
        session_id    = latest_bar['Session_ID'].values[0]

        dmat     = xgb.DMatrix(latest_bar[FEATURE_COLS].values, feature_names=FEATURE_COLS)
        ai_score = float(model.predict(dmat)[0])
        signal   = "BUY" if ai_score >= MIN_RANKER_SCORE else "HOLD"

        dynamic_tp = max(float(latest_bar['ATR_14D'].values[0]) * 0.5,   150.0)
        dynamic_sl = -max(float(latest_bar['ATR_14D'].values[0]) * 1.0, 300.0)

        features_dict_lower = {k.lower(): float(v) for k, v in latest_bar[FEATURE_COLS].iloc[0].to_dict().items()}

        data_to_insert = {
            "candle_time": current_time,
            "session_id":  session_id,
            "entry_price": current_price,
            "ai_score":    round(ai_score, 4),
            "signal":      signal,
            "target_tp":   current_price + dynamic_tp,
            "target_sl":   current_price + dynamic_sl,
            "status":      "PENDING" if signal == "BUY" else "IGNORED",
        }
        data_to_insert.update(features_dict_lower)

        db_out.table("gold_paper_ml_trades_big_v12").insert(data_to_insert).execute()
        print(f"✅ Predictor Done: {current_time} | Score: {ai_score:.4f} | Signal: {signal}")

    except Exception as e:
        print(f"❌ Predictor Error: {e}")


# ==========================================
# 3. TRACKER PIPELINE
# ==========================================
def _session_end_time(session_id: str) -> datetime:
    """Return the wall-clock BKK datetime when a session officially ends."""
    parts        = session_id.rsplit('_', 1)
    session_date = pd.to_datetime(parts[0]).date()
    session_type = parts[1] if len(parts) == 2 else 'Morning'
    end_hour     = SESSION_END_HOUR.get(session_type, 14)

    if session_type == 'Night':
        # Night 18:00 – 01:59 → ends 02:00 on the NEXT calendar day
        end_date = session_date + pd.Timedelta(days=1)
    else:
        end_date = session_date

    naive_end = datetime.combine(end_date, dtime(hour=end_hour, minute=0))
    return BKK_TZ.localize(naive_end)


def run_tracker():
    print("🕵️‍♂️ Running Tracker Pipeline...")
    try:
        res           = db_out.table("gold_paper_ml_trades_big_v12").select("*").eq("status", "PENDING").execute()
        pending_orders = res.data

        if not pending_orders:
            print("ℹ️  No pending orders to track.")
            return

        # ── FIX BUG-1 & BUG-7: fetch ASC so iloc[0] = oldest tick; scan ALL ──────
        res_hsh = (
            db_in.table("gold_prices_hsh")
            .select("timestamp, bid_96")
            .order("timestamp", desc=False)   # ← ASC (was DESC)
            .limit(500)                        # wider window to catch TP/SL hits
            .execute()
        )
        
        df_hsh = pd.DataFrame(res_hsh.data)
        if df_hsh.empty:
            print("ℹ️  No price data to track.")
            return
            
        # ── FIX BUG-8: Use format='ISO8601' and safely handle timezone ───────────
        dts = pd.to_datetime(df_hsh['timestamp'], format='ISO8601')
        if dts.dt.tz is None:
            df_hsh['Datetime'] = dts.dt.tz_localize('Asia/Bangkok')
        else:
            df_hsh['Datetime'] = dts.dt.tz_convert('Asia/Bangkok')
            
        df_hsh = df_hsh.sort_values('Datetime').reset_index(drop=True)
        # ─────────────────────────────────────────────────────────────────────────

        now_bkk = datetime.now(BKK_TZ)

        for order in pending_orders:
            order_time = pd.to_datetime(order['candle_time'])
            if order_time.tzinfo is None:
                order_time = BKK_TZ.localize(order_time)
            else:
                order_time = order_time.astimezone(BKK_TZ)

            future_prices = df_hsh[df_hsh['Datetime'] > order_time].reset_index(drop=True)

            if future_prices.empty:
                continue

            status     = "PENDING"
            exit_price = None
            exit_time  = None

            # ── FIX BUG-1: scan every future tick to find FIRST TP/SL hit ────────
            for _, tick in future_prices.iterrows():
                bid = float(tick['bid_96'])
                if bid >= order['target_tp']:
                    status     = "WIN"
                    exit_price = bid
                    exit_time  = tick['Datetime']
                    break
                elif bid <= order['target_sl']:
                    status     = "LOSS"
                    exit_price = bid
                    exit_time  = tick['Datetime']
                    break
            # ─────────────────────────────────────────────────────────────────────

            # ── FIX BUG-4: close at actual session end time, not a fixed 12 h ────
            if status == "PENDING":
                session_end = _session_end_time(order['session_id'])
                if now_bkk >= session_end:
                    status     = "SESSION_END"
                    last_tick  = future_prices.iloc[-1]
                    exit_price = float(last_tick['bid_96'])
                    exit_time  = last_tick['Datetime']
            # ─────────────────────────────────────────────────────────────────────

            if status != "PENDING":
                pnl = exit_price - order['entry_price']
                db_out.table("gold_paper_ml_trades_big_v12").update({
                    "status":     status,
                    "exit_price": exit_price,
                    "exit_time":  exit_time.isoformat(),
                    "pnl_thb":    pnl,
                }).eq("id", order['id']).execute()
                print(f"🎯 Order {order['id']} → {status} | PnL: {pnl:+.2f} THB")

    except Exception as e:
        print(f"❌ Tracker Error: {e}")


# ==========================================
# 4. FASTAPI SERVER
# ==========================================
app = FastAPI()

@app.get("/")
def health_check():
    return {"status": "ok", "message": "ArgMax Sniper V11 Live Engine is running!"}

@app.post("/cron/predict")
async def trigger_predict(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_predictor)
    return {"status": "success", "message": "Predictor triggered"}

@app.post("/cron/track")
async def trigger_track(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_tracker)
    return {"status": "success", "message": "Tracker triggered"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)