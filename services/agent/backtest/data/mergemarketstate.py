import sys
import os
import pandas as pd
import numpy as np

# ─── 1. System Path Setup ────────────────────────────────────────────────────────
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.abspath(os.path.join(current_dir, '..', '..'))
if src_dir not in sys.path:
    sys.path.append(src_dir)

from data_engine.indicators import TechnicalIndicators

# ─── 2. Helper Functions ─────────────────────────────────────────────────────────

def load_and_standardize_time(filepath, sep=','):
    """โหลดไฟล์และค้นหาคอลัมน์เวลาอัตโนมัติ พร้อมเปลี่ยนชื่อเป็น 'time'"""
    df = pd.read_csv(filepath, sep=sep)
    
    possible_time_cols = ['time', 'Time', 'datetime', 'Datetime', 'date', 'Date', 'timestamp', 'Timestamp', 'date_th']
    
    for col in possible_time_cols:
        if col in df.columns:
            df.rename(columns={col: 'time'}, inplace=True)
            return df
            
    if '<DATE>' in df.columns and '<TIME>' in df.columns:
        df['time'] = df['<DATE>'] + ' ' + df['<TIME>']
        df.drop(columns=['<DATE>', '<TIME>'], inplace=True)
        df.columns = [c.replace('<', '').replace('>', '').lower() for c in df.columns]
        return df

    raise KeyError(f"หาคอลัมน์เวลาไม่เจอในไฟล์ {filepath}\nคอลัมน์ที่มีคือ: {list(df.columns)}")

def normalize_to_thai_time(df, time_col='time', source_tz='UTC'):
    """แปลงเวลาจาก Source Timezone ให้เป็นเวลาไทย (Asia/Bangkok)"""
    df[time_col] = pd.to_datetime(df[time_col])
    
    if df[time_col].dt.tz is None:
        df[time_col] = df[time_col].dt.tz_localize(source_tz, ambiguous='infer').dt.tz_convert('Asia/Bangkok')
    else:
        df[time_col] = df[time_col].dt.tz_convert('Asia/Bangkok')
    
    df[time_col] = df[time_col].dt.tz_localize(None)
    return df

def extract_news_features(df_news):
    """
    ปัดเศษเวลาข่าวเป็น 00:00 และ 12:00 (Cache)
    หา Overall Sentiment และดึง Top 5 Headline พร้อมคะแนน Sentiment 1-5
    """
    if 'title' in df_news.columns and 'sentiment_score' in df_news.columns:
        df_news['cache_time'] = df_news['time'].dt.floor('12h')
        
        news_records = []
        for cache_time, group in df_news.groupby('cache_time'):
            top_news = group.head(5)
            
            overall_sent = group['sentiment_score'].mean()
            top_headlines = " | ".join(top_news['title'].astype(str).tolist())
            
            sentiments = top_news['sentiment_score'].tolist()
            while len(sentiments) < 5:
                sentiments.append(0.0)
                
            news_records.append({
                'time': cache_time, 
                'news_overall_sentiment': round(overall_sent, 4) if pd.notnull(overall_sent) else 0.0,
                'news_top_headlines': top_headlines,
                'sent_hl_1': round(sentiments[0], 4),
                'sent_hl_2': round(sentiments[1], 4),
                'sent_hl_3': round(sentiments[2], 4),
                'sent_hl_4': round(sentiments[3], 4),
                'sent_hl_5': round(sentiments[4], 4)
            })
        return pd.DataFrame(news_records).sort_values('time')
        
    return df_news.sort_values('time')

# ─── 3. Main Processing Function ─────────────────────────────────────────────────

def process_market_data(tf_label, gld_file, usdthb_file, xauusd_file, news_file):
    input_dir = os.path.join(current_dir, "MarketState_data")
    output_dir = os.path.join(current_dir, "merge_data")
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    print(f"--- Processing {tf_label} with Final Schema (incl. XAUUSD & Timestamp Rename) ---")
    
    try:
        # 1. โหลดและ Normalize เวลา
        df_gld = load_and_standardize_time(os.path.join(input_dir, gld_file), sep=',')
        df_gld = normalize_to_thai_time(df_gld, source_tz='Asia/Bangkok') 

        df_gld.dropna(axis=1, how='all', inplace=True)
        if 'volume' in df_gld.columns:
            df_gld.drop(columns=['volume'], inplace=True)

        df_usdthb = load_and_standardize_time(os.path.join(input_dir, usdthb_file), sep='\t')
        df_usdthb = normalize_to_thai_time(df_usdthb, source_tz='UTC')

        df_xauusd = load_and_standardize_time(os.path.join(input_dir, xauusd_file), sep='\t')
        df_xauusd = normalize_to_thai_time(df_xauusd, source_tz='UTC')

        df_news_raw = load_and_standardize_time(os.path.join(input_dir, news_file), sep=',')
        df_news_raw = normalize_to_thai_time(df_news_raw, source_tz='UTC')

        df_news_features = extract_news_features(df_news_raw)

        # 2. คำนวณ Indicators
        calc = TechnicalIndicators(df_gld)
        df_featured = calc.get_ml_dataframe()
        
        df_featured['sell_price'] = df_featured['close']
        df_featured['buy_price'] = df_featured['close'] - 100

        # 3. รวมข้อมูล Market Data (USDTHB & XAUUSD)
        df_merged = pd.merge_asof(
            df_featured.sort_values('time'),
            df_usdthb[['time', 'close']].rename(columns={'close': 'usd_thb'}).sort_values('time'),
            on='time',
            direction='backward'
        )
        
        df_merged = pd.merge_asof(
            df_merged,
            df_xauusd[['time', 'close']].rename(columns={'close': 'spot_price_usd'}).sort_values('time'),
            on='time',
            direction='backward'
        )
        
        df_merged['usd_thb'] = df_merged['usd_thb'].ffill().bfill()
        df_merged['spot_price_usd'] = df_merged['spot_price_usd'].ffill().bfill()

        # 4. รวมข้อมูลข่าวสาร
        df_merged = pd.merge_asof(
            df_merged,
            df_news_features,
            on='time',
            direction='backward'
        )

        news_cols = ['news_overall_sentiment', 'news_top_headlines', 'sent_hl_1', 'sent_hl_2', 'sent_hl_3', 'sent_hl_4', 'sent_hl_5']
        for col in news_cols:
            if col not in df_merged.columns:
                df_merged[col] = np.nan
        
        df_merged[news_cols] = df_merged[news_cols].ffill().bfill()
        
        df_merged['news_top_headlines'] = df_merged['news_top_headlines'].fillna("No recent news")
        for col in ['news_overall_sentiment', 'sent_hl_1', 'sent_hl_2', 'sent_hl_3', 'sent_hl_4', 'sent_hl_5']:
            df_merged[col] = df_merged[col].fillna(0.0)

        # 5. จัดโครงสร้าง Schema 
        # --- ลบคอลัมน์ timestamp เดิมที่เป็นเลข 1 ทิ้งไปก่อน ---
        if 'timestamp' in df_merged.columns:
            df_merged.drop(columns=['timestamp'], inplace=True)
            
        # เปลี่ยนชื่อ time -> timestamp
        df_merged.rename(columns={'time': 'timestamp'}, inplace=True)

        final_schema_cols = [
            'timestamp', 'open', 'high', 'low', 'close', 
            'rsi_14', 'macd_line', 'macd_signal', 'macd_hist', 
            'bb_up', 'bb_mid', 'bb_low', 'atr_14', 'ema_20', 'ema_50', 
            'sell_price', 'buy_price', 'usd_thb', 'spot_price_usd',
            'news_overall_sentiment', 'news_top_headlines',
            'sent_hl_1', 'sent_hl_2', 'sent_hl_3', 'sent_hl_4', 'sent_hl_5'
        ]
        
        available_cols = [c for c in final_schema_cols if c in df_merged.columns]
        df_merged = df_merged[available_cols]

        # 6. บันทึกไฟล์
        output_filename = f"merged_gold_{tf_label}_TH_TIME.csv"
        output_path = os.path.join(output_dir, output_filename)
        df_merged.to_csv(output_path, index=False)
        
        print(f"Success! Saved merged dataset to: {output_path}")
        return df_merged
        
    except Exception as e:
        print(f"Error processing {tf_label}: {e}\n")
        return None

# ─── 4. Execution ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)

    news_file_name = "gdelt_news_master_2025-01-01_2026-04-16_final.csv"

    # 1. รัน Timeframe 5 นาที
    df_5m = process_market_data(
        tf_label="5min", 
        gld_file="GLD965_5m_20250101_to_20260416.csv", 
        usdthb_file="USDTHB_M5_202501020000_202604160000.csv", 
        xauusd_file="XAUUSD_M5_202501020100_202604152255.csv",
        news_file=news_file_name
    )
    
    if df_5m is not None:
        print("\n=== Data Preview (5min) - Last 5 Rows ===")
        print(df_5m.tail())
        print("="*60 + "\n")

    # 2. รัน Timeframe 15 นาที
    df_15m = process_market_data(
        tf_label="15min", 
        gld_file="GLD965_15m_20250101_to_20260416.csv", 
        usdthb_file="USDTHB_M15_202501020000_202604160000.csv", 
        xauusd_file="XAUUSD_M15_202501020100_202604152245.csv",
        news_file=news_file_name
    )

    if df_15m is not None:
        print("\n=== Data Preview (15min) - Last 5 Rows ===")
        print(df_15m.tail())
        print("="*60 + "\n")