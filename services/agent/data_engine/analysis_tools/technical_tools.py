import logging
import pandas as pd
import numpy as np
import time
from scipy.signal import find_peaks
from sklearn.cluster import DBSCAN
from data_engine.ohlcv_fetcher import OHLCVFetcher
from data_engine.indicators import TechnicalIndicators

logger = logging.getLogger(__name__)

# Shared fetcher instance
_fetcher = OHLCVFetcher()

#--------------------------------------------------------------------------------------------------
# Group A Tools (Requires Candle Series) 
#--------------------------------------------------------------------------------------------------
def check_spot_thb_alignment(interval: str = "15m", lookback_candles: int = 4, df_spot: pd.DataFrame = None, df_thb: pd.DataFrame = None) -> dict:
    try:
        if df_spot is None or df_spot.empty:
            df_spot = _fetcher.fetch_historical_ohlcv(days=3, interval=interval, twelvedata_symbol="XAU/USD")
        else:
            logger.info(f"⚡ [check_spot_thb_alignment] Using memory df_spot ({len(df_spot)} candles)")
 
        if df_thb is None or df_thb.empty:
            df_thb = _fetcher.fetch_historical_ohlcv(days=3, interval=interval, twelvedata_symbol="USD/THB")
        else:
            logger.info(f"⚡ [check_spot_thb_alignment] Using memory df_thb ({len(df_thb)} candles)")
 
        if len(df_spot) < lookback_candles or len(df_thb) < lookback_candles:
            return {"status": "error", "message": "Insufficient data for alignment comparison"}
 
        spot_start = df_spot['close'].iloc[-lookback_candles]
        spot_end = df_spot['close'].iloc[-1]
        spot_pct = ((spot_end - spot_start) / spot_start) * 100
 
        thb_start = df_thb['close'].iloc[-lookback_candles]
        thb_end = df_thb['close'].iloc[-1]
        thb_pct = ((thb_end - thb_start) / thb_start) * 100
 
        if spot_pct > 0 and thb_pct > 0:
            alignment = "Strong Bullish"

        elif spot_pct < 0 and thb_pct < 0:
            alignment = "Strong Bearish"
          
        elif spot_pct > 0 and thb_pct < 0:
            alignment = "Neutral (Spot Leading)"

        else:
            alignment = "Neutral (THB Leading)"
            
 
        return {
            "status": "success",
            "interval": interval,
            "alignment": alignment,
            "details": {
                "spot_pct_change": round(spot_pct, 4),
                "thb_pct_change": round(thb_pct, 4)
            },

        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    
def detect_breakout_confirmation(zone_top: float, zone_bottom: float, interval: str = "15m", history_days: int = 3, ohlcv_df: pd.DataFrame = None) -> dict:
    try:
        if ohlcv_df is not None and not ohlcv_df.empty:
            df = ohlcv_df
        else:
            df = _fetcher.fetch_historical_ohlcv(days=history_days, interval=interval)
            
        if len(df) < 2:
            return {"status": "error", "message": "Insufficient data"}

        latest = df.iloc[-1]
        open_p = latest['open']
        close_p = latest['close']
        high_p = latest['high']
        low_p = latest['low']

        is_breaking_up = close_p > zone_top
        is_breaking_down = close_p < zone_bottom

        if not is_breaking_up and not is_breaking_down:
            return {
                "status": "success",
                "is_confirmed_breakout": False,
            }

        body_size = abs(close_p - open_p)
        total_size = high_p - low_p
        
        if total_size == 0:
            return {
                "status": "success",
                "is_confirmed_breakout": False,
            }

        body_pct = (body_size / total_size) * 100
        is_strong_body = body_pct >= 50.0 

        if is_breaking_up:
            upper_wick = high_p - max(open_p, close_p)
            wick_rejected = upper_wick > body_size
            confirmed = is_strong_body and not wick_rejected
            direction = "Upward (Resistance Breakout)"
        else:
            lower_wick = min(open_p, close_p) - low_p
            wick_rejected = lower_wick > body_size
            confirmed = is_strong_body and not wick_rejected
            direction = "Downward (Support Breakdown)"

        return {
            "status": "success",
            "interval": interval,
            "breakout_direction": direction,
            "is_confirmed_breakout": bool(confirmed),
            "details": {
                "body_strength_pct": round(float(body_pct), 2),
                "closed_price": round(float(close_p), 2)
            },
            
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    
def get_support_resistance_zones(interval: str = "15m", history_days: int = 5, ohlcv_df: pd.DataFrame = None) -> dict:
    try:
        if ohlcv_df is not None and not ohlcv_df.empty:
            df = ohlcv_df
            logger.info(f"⚡ [get_support_resistance_zones] Using memory df ({len(df)} candles)")
        else:
            df = _fetcher.fetch_historical_ohlcv(days=history_days, interval=interval)
            
        if len(df) < 50:
            return {"status": "error", "message": "Insufficient candles for zone detection (needs 50+)"}

        calc = TechnicalIndicators(df) 
        df_with_ind = calc.df
        
        latest_atr = float(df_with_ind["atr_14"].iloc[-1])
        adaptive_eps = latest_atr * 0.7
        final_eps = np.clip(adaptive_eps, latest_atr * 0.3, latest_atr * 3.0)

        current_price = float(df['close'].iloc[-1])
        prominence = latest_atr * 1.5

        peaks_idx, _ = find_peaks(df['high'], prominence=prominence)
        troughs_idx, _ = find_peaks(-df['low'], prominence=prominence)
        
        swing_highs = df['high'].iloc[peaks_idx].values
        swing_lows = df['low'].iloc[troughs_idx].values
        all_swings = np.concatenate([swing_highs, swing_lows]).reshape(-1, 1)
        
        if len(all_swings) == 0:
            return {"status": "success", "current_price": current_price, "zones": [], "eps_used": round(final_eps, 2)}

        clustering = DBSCAN(eps=final_eps, min_samples=2).fit(all_swings)
        labels = clustering.labels_
        
        zones = []
        for label in set(labels):
            if label == -1: continue
                
            cluster_prices = all_swings[labels == label].flatten()
            top_edge = float(np.max(cluster_prices))
            bottom_edge = float(np.min(cluster_prices))
            
            touches = len(cluster_prices)
            strength = "High" if touches >= 4 else "Medium" if touches == 3 else "Low"
            if bottom_edge > current_price:
                zone_type = "Resistance"
            elif top_edge < current_price:
                zone_type = "Support"
            else:
                zone_type = "In-Range (Testing Zone)"
            
            zones.append({
                "type": zone_type,
                "bottom": round(bottom_edge, 2),
                "top": round(top_edge, 2),
                "touches": touches,
                "strength": strength
            })
            
        zones = sorted(zones, key=lambda x: x['top'], reverse=True)

        return {
            "status": "success",
            "interval": interval,
            "current_price": current_price,
            "adaptive_metrics": {
                "atr_used": round(latest_atr, 2),
                "final_eps": round(float(final_eps), 2)
            },
            "total_zones_found": len(zones),
            "zones": zones
        }
        
    except Exception as e:
        logger.error(f"❌ [get_support_resistance_zones] Error: {e}")
        return {"status": "error", "message": str(e)}
    
def detect_swing_low(interval: str = "15m", history_days: int = 3, lookback_candles: int = 15, ohlcv_df: pd.DataFrame = None) -> dict:
    try:
        if ohlcv_df is not None and not ohlcv_df.empty:
            df = ohlcv_df
            logger.info(f"⚡ [detect_swing_low] Using memory df ({len(df)} candles)")
        else:
            df = _fetcher.fetch_historical_ohlcv(days=history_days, interval=interval)
        
        if len(df) < lookback_candles:
            return {"status": "error", "message": "Insufficient candles for analysis"}

        recent_df = df.tail(lookback_candles).reset_index(drop=True)
        
        setup_found = False
        swing_low_val = None
        confirmation_close = None
        
        for i in range(len(recent_df) - 2, 0, -1):
            left_low = recent_df['low'].iloc[i-1]
            center_low = recent_df['low'].iloc[i]
            right_low = recent_df['low'].iloc[i+1]
            
            if center_low < left_low and center_low < right_low:
                # [FIX] เปลี่ยนจาก swing_high เป็น high ของแท่งตรงกลางที่ทำจุดต่ำสุด
                center_high = recent_df['high'].iloc[i] 
                
                for j in range(i + 1, len(recent_df)):
                    # [FIX] แค่ทะลุ High ของแท่งต่ำสุดได้ ก็ถือว่าเริ่มกลับตัวแล้ว (เหมาะกับ Scalping)
                    if recent_df['close'].iloc[j] > center_high:
                        setup_found = True
                        swing_low_val = center_low
                        confirmation_close = recent_df['close'].iloc[j]
                        break
            
            if setup_found:
                break

        return {
            "status": "success",
            "interval": interval,
            "setup_detected": setup_found,
            "details": {
                "swing_low_price": round(float(swing_low_val), 2) if swing_low_val else None,
                "confirmation_close": round(float(confirmation_close), 2) if confirmation_close else None
            },
            
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    
def detect_swing_high(interval: str = "15m", history_days: int = 3, lookback_candles: int = 15, ohlcv_df: pd.DataFrame = None) -> dict:
    try:
        if ohlcv_df is not None and not ohlcv_df.empty:
            df = ohlcv_df
            logger.info(f"⚡ [detect_swing_high] Using memory df ({len(df)} candles)")
        else:
            df = _fetcher.fetch_historical_ohlcv(days=history_days, interval=interval)
        
        if len(df) < lookback_candles:
            return {"status": "error", "message": "Insufficient candles for analysis"}

        recent_df = df.tail(lookback_candles).reset_index(drop=True)
        
        setup_found = False
        swing_high_val = None
        confirmation_close = None
        
        for i in range(len(recent_df) - 2, 0, -1):
            left_high = recent_df['high'].iloc[i-1]
            center_high = recent_df['high'].iloc[i]
            right_high = recent_df['high'].iloc[i+1]
            
            # ตรวจหาจุดยอด (Peak)
            if center_high > left_high and center_high > right_high:
                center_low = recent_df['low'].iloc[i] 
                
                for j in range(i + 1, len(recent_df)):
                    # ถ้าราคาปิดทะลุจุดต่ำสุดของแท่ง Peak ได้ ถือว่ายืนยันการกลับตัวลง
                    if recent_df['close'].iloc[j] < center_low:
                        setup_found = True
                        swing_high_val = center_high
                        confirmation_close = recent_df['close'].iloc[j]
                        break
            
            if setup_found:
                break

        return {
            "status": "success",
            "interval": interval,
            "setup_detected": setup_found,
            "details": {
                "swing_high_price": round(float(swing_high_val), 2) if swing_high_val else None,
                "confirmation_close": round(float(confirmation_close), 2) if confirmation_close else None
            },
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

def detect_rsi_divergence(interval: str = "15m", history_days: int = 5, lookback_candles: int = 30, ohlcv_df: pd.DataFrame = None) -> dict:
    try:
        if ohlcv_df is not None and not ohlcv_df.empty:
            df = ohlcv_df
            logger.info(f"⚡ [detect_rsi_divergence] Using memory df ({len(df)} candles)")
        else:
            df = _fetcher.fetch_historical_ohlcv(days=history_days, interval=interval)
            
        if len(df) < lookback_candles:
            return {"status": "error", "message": "Insufficient data (needs more than lookback window)"}

        calc = TechnicalIndicators(df)
        df_with_rsi = calc.df.dropna(subset=['rsi_14'])
        recent_df = df_with_rsi.tail(lookback_candles).reset_index(drop=True)

        atr = float(calc.df['atr_14'].iloc[-1])
        troughs_idx, _ = find_peaks(-recent_df['low'], prominence=atr * 1.0)
        
        if len(troughs_idx) < 2:
            return {
                "status": "success", 
                "divergence_detected": False, 
                "logic": "No clear swings to compare divergence",
                "data": {}
            }

        idx1 = troughs_idx[-2]
        idx2 = troughs_idx[-1]
        
        low1 = recent_df['low'].iloc[idx1]
        rsi1 = recent_df['rsi_14'].iloc[idx1]
        
        low2 = recent_df['low'].iloc[idx2]
        rsi2 = recent_df['rsi_14'].iloc[idx2]
        
        is_price_lower = low2 < low1
        is_rsi_higher = rsi2 > rsi1
        bullish_divergence = bool(is_price_lower and is_rsi_higher)

        # ── Bearish Divergence: ราคาทำ higher high แต่ RSI ทำ lower high ──
        peaks_idx, _ = find_peaks(recent_df['high'], prominence=atr * 1.0)
        bearish_divergence = False
        bearish_data: dict = {}
        if len(peaks_idx) >= 2:
            p1 = peaks_idx[-2]
            p2 = peaks_idx[-1]
            high1 = recent_df['high'].iloc[p1]
            hrsi1 = recent_df['rsi_14'].iloc[p1]
            high2 = recent_df['high'].iloc[p2]
            hrsi2 = recent_df['rsi_14'].iloc[p2]
            bearish_divergence = bool(high2 > high1 and hrsi2 < hrsi1)
            bearish_data = {
                "High1": round(float(high1), 2), "RSI1": round(float(hrsi1), 2),
                "High2": round(float(high2), 2), "RSI2": round(float(hrsi2), 2),
            }

        divergence_found = bullish_divergence or bearish_divergence
        if bullish_divergence:
            divergence_type = "bullish"
            logic = "Price lower but RSI higher (Bullish Divergence)"
            data = {
                "Low1": round(float(low1), 2), "RSI1": round(float(rsi1), 2),
                "Low2": round(float(low2), 2), "RSI2": round(float(rsi2), 2),
            }
        elif bearish_divergence:
            divergence_type = "bearish"
            logic = "Price higher but RSI lower (Bearish Divergence)"
            data = bearish_data
        else:
            divergence_type = None
            logic = "Price and RSI aligned (No Divergence)"
            data = {}

        return {
            "status": "success",
            "divergence_detected": divergence_found,
            "divergence_type": divergence_type,   # "bullish" | "bearish" | None
            "logic": logic,
            "data": data,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
    
#--------------------------------------------------------------------------------------------------
# Group B Tools (Snapshot + Threshold) 
#--------------------------------------------------------------------------------------------------

def get_recent_indicators(interval: str = "15m", lookback: int = 5, history_days: int = 5, ohlcv_df: pd.DataFrame = None) -> dict:
    """
    ดึงข้อมูลอินดิเคเตอร์ (RSI, MACD, EMA) ย้อนหลัง N แท่งล่าสุด 
    เพื่อให้ LLM ดูแนวโน้มความชัน (Slope/Trend) ได้อย่างแม่นยำ
    """
    try:
        if ohlcv_df is not None and not ohlcv_df.empty:
            df = ohlcv_df
            logger.info(f"⚡ [get_recent_indicators] Using memory df ({len(df)} candles)")
        else:
            df = _fetcher.fetch_historical_ohlcv(days=history_days, interval=interval)
            
        if len(df) < lookback:
            return {"status": "error", "message": f"Insufficient data for {lookback} candles"}

        calc = TechnicalIndicators(df)
        
        # ดรอปแถวที่คำนวณไม่เสร็จ (ช่วงแรกๆ ของกราฟ)
        df_ind = calc.df.dropna(subset=['rsi_14', 'macd_hist', 'ema_20'])
        
        if len(df_ind) < lookback:
            return {"status": "error", "message": "Insufficient valid indicator data"}

        recent_df = df_ind.tail(lookback)
        
        history = []
        for idx, row in recent_df.iterrows():
            # ดึงเฉพาะเวลา (HH:MM) เพื่อประหยัด Token ของ AI
            time_str = str(idx).split(" ")[-1][:5] if " " in str(idx) else str(idx)
            
            history.append({
                "time": time_str,
                "close": round(float(row['close']), 2),
                "rsi": round(float(row['rsi_14']), 2),
                "macd_hist": round(float(row['macd_hist']), 4),
                "ema_20": round(float(row['ema_20']), 2)
            })
            
        # สรุป Trend ง่ายๆ ให้ AI อ่านเลย จะได้ไม่ต้องคำนวณเอง
        latest = history[-1]
        prev = history[-2]
        
        rsi_trend = "Rising" if latest['rsi'] > prev['rsi'] else "Falling"
        macd_slope = "Upwards" if latest['macd_hist'] > prev['macd_hist'] else "Downwards"

        return {
            "status": "success",
            "interval": interval,
            "lookback": lookback,
            "summary": {
                "rsi_trend": rsi_trend,
                "macd_histogram_slope": macd_slope
            },
            "history_data": history
        }
    except Exception as e:
        logger.error(f"❌ [get_recent_indicators] Error: {e}")
        return {"status": "error", "message": str(e)}
    
def check_bb_rsi_combo(interval: str = "15m", history_days: int = 5, ohlcv_df: pd.DataFrame = None) -> dict:
    try:
        if ohlcv_df is not None and not ohlcv_df.empty:
                df = ohlcv_df
                logger.info(f"⚡ [check_bb_rsi_combo] Using memory df ({len(df)} candles)")
        else:
                df = _fetcher.fetch_historical_ohlcv(days=history_days, interval=interval)
                
        calc = TechnicalIndicators(df)
            
        # 🚀 1. ระบบค้นหาคอลัมน์ Bollinger Bands อัตโนมัติ (ไม่สนว่าจะตั้งชื่อมาแบบไหน)
        bb_up_cols = [c for c in calc.df.columns if 'bb' in c.lower() and ('up' in c.lower() or 'high' in c.lower())]
        bb_dn_cols = [c for c in calc.df.columns if 'bb' in c.lower() and ('low' in c.lower() or 'dn' in c.lower())]

        if not bb_up_cols or not bb_dn_cols:
         # ถ้าหาไม่เจอจริงๆ ให้พ่นชื่อคอลัมน์ทั้งหมดออกมาดูใน Log จะได้รู้ว่าเกิดอะไรขึ้น
            logger.error(f"ไม่พบคอลัมน์ BB! คอลัมน์ที่มี: {calc.df.columns.tolist()}")
            return {"status": "error", "message": "Bollinger Bands indicators not found"}

        col_bb_upper = bb_up_cols[0]
        col_bb_lower = bb_dn_cols[0]

       # 🚀 2. อัปเดต dropna ให้ใช้คอลัมน์ที่หาเจอ
        df_ind = calc.df.dropna(subset=['rsi_14', col_bb_lower, col_bb_upper, 'macd_hist'])
            
        if len(df_ind) < 2:
            return {"status": "error", "message": "Insufficient data for combo calculation"}

        latest = df_ind.iloc[-1]
        prev = df_ind.iloc[-2]

        current_price = float(latest['close'])
            
        # 🚀 3. ใช้ชื่อคอลัมน์ที่หาเจอมาดึงข้อมูล
        lower_bb = float(latest[col_bb_lower])
        upper_bb = float(latest[col_bb_upper])
            
        rsi = float(latest['rsi_14'])
        macd_hist_current = float(latest['macd_hist'])
        macd_hist_prev = float(prev['macd_hist'])
        atr = float(latest['atr_14'])

        # ── Bullish combo: oversold ──
        is_price_low    = current_price < lower_bb
        is_rsi_oversold = rsi < 35.0
        is_macd_flatten = abs(macd_hist_current) < (atr * 0.05) or (macd_hist_current > macd_hist_prev)
        bullish_combo   = bool(is_price_low and is_rsi_oversold and is_macd_flatten)

        # ── Bearish combo: overbought ──
        is_price_high      = current_price > upper_bb
        is_rsi_overbought  = rsi > 65.0
        is_macd_flatten_dn = abs(macd_hist_current) < (atr * 0.05) or (macd_hist_current < macd_hist_prev)
        bearish_combo      = bool(is_price_high and is_rsi_overbought and is_macd_flatten_dn)

        combo_met = bullish_combo or bearish_combo
        if bullish_combo:
            combo_direction = "bullish"
            details = f"Price<LowerBB: {is_price_low}, RSI<35: {is_rsi_oversold}, MACD_Flatten: {is_macd_flatten}"
        elif bearish_combo:
            combo_direction = "bearish"
            details = f"Price>UpperBB: {is_price_high}, RSI>65: {is_rsi_overbought}, MACD_Flatten: {is_macd_flatten_dn}"
        else:
            combo_direction = None
            details = f"Price<BB: {is_price_low}, RSI<35: {is_rsi_oversold}, MACD_Flatten: {is_macd_flatten}"

        return {
            "status": "success",
            "interval": interval,
            "combo_detected": combo_met,
            "combo_direction": combo_direction,   # "bullish" | "bearish" | None
            "raw_data": {
                "price": round(float(current_price), 2),
                "lower_bb": round(float(lower_bb), 2),
                "upper_bb": round(float(upper_bb), 2),
                "rsi": round(float(rsi), 2),
                "macd_hist": round(float(macd_hist_current), 2),
            },
            "details": details,
        }
    except Exception as e:
        logger.error(f"❌ [check_bb_rsi_combo] Error: {e}")
        return {"status": "error", "message": str(e)}
    
def check_bb_squeeze(interval: str = "15m", history_days: int = 1, 
                     ohlcv_df: pd.DataFrame = None) -> dict:
    """
    Detect Bollinger Band squeeze (low volatility)
    Squeeze = (upper - lower) / midpoint < threshold
    """
    try:
        # 1. จัดเตรียม DataFrame
        if ohlcv_df is not None and not ohlcv_df.empty:
            df = ohlcv_df.copy()
        else:
            # สมมติว่ามี _fetcher ให้เรียกใช้ในไฟล์
            df = _fetcher.fetch_historical_ohlcv(
                days=history_days, interval=interval
            )
        
        # 2. ค้นหาชื่อคอลัมน์แบบยืดหยุ่น (ก่อนคำนวณใหม่)
        col_bb_upper = next((c for c in df.columns if c in ['bb_upper', 'bb_high', 'bb_up', 'BBU', 'bollinger_upper']), None)
        col_bb_lower = next((c for c in df.columns if c in ['bb_lower', 'bb_low', 'BBL', 'bollinger_lower']), None)
        col_bb_mid = next((c for c in df.columns if c in ['bb_mid', 'bb_middle', 'BBM', 'bollinger_mid']), None)

        # 3. ถ้าไม่มีคอลัมน์ Bollinger Bands ถึงจะทำการคำนวณใหม่
        if not col_bb_upper or not col_bb_lower or not col_bb_mid:
            from data_engine.indicators import TechnicalIndicators
            calc = TechnicalIndicators(df)
            df = calc.df
            
            # ค้นหาอีกครั้งหลังคำนวณ
            col_bb_upper = next((c for c in df.columns if c in ['bb_upper', 'bb_high', 'bb_up', 'BBU', 'bollinger_upper']), None)
            col_bb_lower = next((c for c in df.columns if c in ['bb_lower', 'bb_low', 'BBL', 'bollinger_lower']), None)
            col_bb_mid = next((c for c in df.columns if c in ['bb_mid', 'bb_middle', 'BBM', 'bollinger_mid']), None)

        # 4. ตรวจสอบขั้นสุดท้าย
        if not col_bb_upper or not col_bb_lower or not col_bb_mid:
            return {
                "status": "error", 
                "message": f"Bollinger Bands columns missing. Available columns: {list(df.columns)}"
            }
        
        # 5. คำนวณความกว้าง Squeeze
        upper = float(df[col_bb_upper].iloc[-1])
        lower = float(df[col_bb_lower].iloc[-1])
        mid = float(df[col_bb_mid].iloc[-1])
        
        bb_width = (upper - lower) / mid if mid > 0 else 0
        threshold = 0.0025  # 2% width
        
        is_squeeze = bb_width < threshold
        
        return {
            "status": "success",
            "interval": interval,
            "is_squeeze": bool(is_squeeze),
            "bb_width_pct": round(bb_width * 100, 2),
            "upper": round(upper, 2),
            "lower": round(lower, 2),
            "recommendation": "AVOID BUY - No momentum" if is_squeeze 
                             else "OK - Normal volatility"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

def calculate_ema_distance(interval: str = "15m", history_days: int = 5, ohlcv_df: pd.DataFrame = None) -> dict:
    try:
        if ohlcv_df is not None and not ohlcv_df.empty:
            df = ohlcv_df
        else:
            df = _fetcher.fetch_historical_ohlcv(days=history_days, interval=interval)
            
        calc = TechnicalIndicators(df)
        df_ind = calc.df.dropna(subset=['ema_20', 'atr_14']) 
        
        latest = df_ind.iloc[-1]
        current_price = float(latest['close'])
        ema_20 = float(latest['ema_20'])
        atr = float(latest['atr_14'])

        if atr <= 0:
            return {"status": "error", "message": "Invalid ATR value (<= 0)"}
            
        distance = (current_price - ema_20) / atr
        is_overextended = abs(distance) > 2.5
        
        return {
            "status": "success",
            "interval": interval,
            "distance_atr_ratio": round(distance, 2),
            "is_overextended": bool(is_overextended),
            "metrics": {
                "current_price": round(current_price, 2),
                "ema_20": round(ema_20, 2),
                "atr": round(atr, 2)
            },
            
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

#--------------------------------------------------------------------------------------------------
# Higher Timeframe + General Indicators
#--------------------------------------------------------------------------------------------------

_HTF_CACHE = {}
_CACHE_TTL_SECONDS = 1800  # ให้จำค่าไว้ 30 นาที (1800 วินาที)

def get_htf_trend(timeframe: str = "1h", history_days: int = 15, ohlcv_df: pd.DataFrame = None) -> dict:
    try:
        # 1. ตรวจสอบ Cache ก่อนทำอย่างอื่น
        now = time.time()
        if timeframe in _HTF_CACHE:
            cached_data = _HTF_CACHE[timeframe]
            # ถ้าเวลายังไม่หมดอายุ (ยังไม่เกิน 30 นาที)
            if now - cached_data["timestamp"] < _CACHE_TTL_SECONDS:
                logger.info(f"🟢 [get_htf_trend] ใช้ข้อมูลจาก Cache สำหรับ {timeframe}")
                return cached_data["result"]

        # 2. คำนวณจำนวนวันขั้นต่ำที่ต้องใช้เพื่อให้ได้ 200 แท่งเทียน
        safe_days = history_days
        if timeframe == "1h":
            safe_days = max(history_days, 15)   
        elif timeframe == "4h":
            safe_days = max(history_days, 45)   
        elif timeframe == "1d":
            safe_days = max(history_days, 300)  

        # 3. ดึงข้อมูล
        if ohlcv_df is not None and not ohlcv_df.empty:
            if len(ohlcv_df) >= 200:
                df = ohlcv_df
                logger.info(f"⚡ [get_htf_trend] Using memory df ({len(df)} candles)")
            else:
                logger.info(f"⚠️ Memory df has only {len(ohlcv_df)} candles. Fetching {safe_days}d for EMA200...")
                df = _fetcher.fetch_historical_ohlcv(days=safe_days, interval=timeframe)
        else:
            df = _fetcher.fetch_historical_ohlcv(days=safe_days, interval=timeframe)

        if len(df) < 200:
            if timeframe == "4h":
                logger.info("4h data insufficient, falling back to 1h...")
                return get_htf_trend(timeframe="1h", history_days=15) # ลองเรียกใหม่ด้วย 1h
            return {"status": "error", "message": f"Insufficient {timeframe} data..."}
 
        # 4. คำนวณ EMA200
        calc = TechnicalIndicators(df)
        df_ind = calc.df.dropna(subset=['ema_200']) 
        
        latest_candle = df_ind.iloc[-1]
        current_price = latest_candle['close']
        ema_200 = latest_candle['ema_200']
        
        trend = "Bullish" if current_price > ema_200 else "Bearish"
        distance_pct = ((current_price - ema_200) / ema_200) * 100
 
        # 5. สร้างผลลัพธ์
        final_result = {
            "status": "success",
            "timeframe": timeframe,
            "trend": trend,
            "current_price": round(float(current_price), 2),
            "ema_200": round(float(ema_200), 2),
            "distance_from_ema_pct": round(float(distance_pct), 2),

        }

        # 6. บันทึกผลลัพธ์ลง Cache ก่อนส่งกลับไปให้ AI
        _HTF_CACHE[timeframe] = {
            "timestamp": now,
            "result": final_result
        }

        return final_result

    except Exception as e:
        return {"status": "error", "message": str(e)}
