import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
import time
from transformers import pipeline
import torch
import os
from tqdm import tqdm
from dotenv import load_dotenv
load_dotenv()
# ==========================================
# 1. Configuration (ตั้งค่าพื้นฐาน)
# ==========================================
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
DAYS_TO_FETCH = 90 # ดึงย้อนหลัง 3 เดือน (90 วัน)

PROXY_SYMBOLS = {
    'GLD': {'category': 'gold_price', 'weight': 1.5},
    'SPY': {'category': 'fed_macro', 'weight': 1.2},
    'UUP': {'category': 'dollar_index', 'weight': 1.0}
}

tqdm.pandas()

# ==========================================
# 2. Setup Local AI Model (FinBERT)
# ==========================================
device = "mps" if torch.backends.mps.is_available() else "cuda" if torch.cuda.is_available() else "cpu"
print(f"🖥️ Using device: {device}")
print("⏳ Loading FinBERT (Sentiment Analyzer)...")
sentiment_analyzer = pipeline("sentiment-analysis", model="ProsusAI/finbert", device=device)

# ==========================================
# 3. Fetch Historical News (Day-by-Day Loop)
# ==========================================
def fetch_historical_news():
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=DAYS_TO_FETCH)
    
    all_raw_articles = []
    
    print(f"\n📡 Fetching {DAYS_TO_FETCH}-Day Historical News (Day-by-Day)...")
    
    for symbol, meta in PROXY_SYMBOLS.items():
        print(f"\n  📥 Fetching data for: {symbol} (Category: {meta['category']})")
        
        current_date = start_date
        while current_date < end_date:
            next_date = current_date + timedelta(days=1)
            
            _from_str = current_date.strftime("%Y-%m-%d")
            _to_str = next_date.strftime("%Y-%m-%d")
            
            url = f"https://finnhub.io/api/v1/company-news?symbol={symbol}&from={_from_str}&to={_to_str}&token={FINNHUB_API_KEY}"
            
            try:
                response = requests.get(url)
                if response.status_code == 200:
                    news_data = response.json()
                    
                    if isinstance(news_data, list):
                        for article in news_data:
                            headline = str(article.get("headline", "")).strip().replace('\n', ' ').replace('\r', ' ')
                            summary = str(article.get("summary", "")).strip().replace('\n', ' ').replace('\r', ' ')
                            combined_text = f"{headline}. {summary}"
                            
                            all_raw_articles.append({
                                "published_at": datetime.fromtimestamp(article['datetime'], tz=timezone.utc),
                                "combined_text": combined_text,
                                "source": article.get("source"),
                                "category": meta['category'],
                                "weight": meta['weight']
                            })
                        if len(news_data) > 0:
                            print(f"     ✅ {_from_str}: Found {len(news_data)} articles")
                    else:
                        print(f"     ⚠️ Error on {_from_str}: {news_data}")
                else:
                    print(f"     ⚠️ API Error {response.status_code} on {_from_str}")
                    
            except Exception as e:
                print(f"     ❌ Fetch error on {_from_str}: {e}")
                
            time.sleep(1) # พัก 1 วิ ป้องกันโดนแบน (Rate Limit)
            current_date = next_date
            
    df = pd.DataFrame(all_raw_articles)
    
    if not df.empty:
        initial_len = len(df)
        df.drop_duplicates(subset=['combined_text'], inplace=True)
        print(f"\n🧹 Dropped {initial_len - len(df)} duplicate articles.")
        
    return df

# ==========================================
# 4. Processing & Sentiment Scoring
# ==========================================
def calculate_sentiment(text):
    try:
        # FinBERT รับได้สูงสุด 512 tokens
        result = sentiment_analyzer(text[:1500], truncation=True, max_length=512)[0] 
        label = result['label']
        score = result['score']
        
        if label == "positive": return round(score, 4)
        elif label == "negative": return -round(score, 4)
        else: return 0.0 
    except Exception:
        return 0.0

# ==========================================
# 5. Main Execution
# ==========================================
df = fetch_historical_news()

if not df.empty:
    print(f"📦 Total unique articles to process: {len(df)}")
    
    print("\n🎭 Running FinBERT Sentiment Analysis (Headline + Summary)...")
    df['sentiment_score'] = df['combined_text'].progress_apply(calculate_sentiment)
    
    # แปลงเวลาเป็นเวลาไทย (Asia/Bangkok)
    df['published_at'] = df['published_at'].dt.tz_convert('Asia/Bangkok')
    df['published_at'] = df['published_at'].dt.tz_localize(None) 
    df.set_index('published_at', inplace=True)
    
    # ==========================================
    # 6. Aggregation (รวมกลุ่ม 1 ชั่วโมง + ส่งออก 2 ไฟล์)
    # ==========================================
    print("\n📊 Aggregating data into 1-Hour timeframes (Thai Time)...")
    
    def weighted_sentiment(group):
        if group.empty or group['weight'].sum() == 0:
            return 0.0
        return (group['sentiment_score'] * group['weight']).sum() / group['weight'].sum()

    # ฟังก์ชันสำหรับรวมข้อความข่าวเข้าด้วยกัน (จำกัดแค่ 3 ข่าวแรกต่อชั่วโมงป้องกันไฟล์ใหญ่ไป)
    def join_texts(texts):
        if len(texts) == 0: return ""
        return " | ".join(texts[:3])

    grouped = df.groupby(pd.Grouper(freq='1h'))
    
    # สร้าง DataFrame ตัวเต็ม (มีข้อความ)
    summary_df_full = pd.DataFrame({
        'news_count': grouped['combined_text'].count(),
        'overall_sentiment': grouped.apply(weighted_sentiment),
        'top_headlines_summary': grouped['combined_text'].apply(join_texts)
    })
    
    # ปัดเศษให้สวยงาม
    summary_df_full['overall_sentiment'] = summary_df_full['overall_sentiment'].round(4)
    
    # ลบชั่วโมงที่คะแนนเป็น 0.0 ทิ้ง
    summary_df_full = summary_df_full[summary_df_full['overall_sentiment'] != 0.0]
    
    # --- ส่งออกไฟล์ที่ 1: แบบมีข้อความ (สำหรับเก็บไว้ดู/ใช้ในอนาคต) ---
    output_with_text = "finnhub_3month_news_with_text_v2.csv"
    summary_df_full.to_csv(output_with_text)
    
    # --- ส่งออกไฟล์ที่ 2: แบบไม่มีข้อความ (สำหรับใช้ทำ Backtest) ---
    # ใช้คำสั่ง .drop() เพื่อลบคอลัมน์ข้อความออก
    summary_df_ready = summary_df_full.drop(columns=['top_headlines_summary'])
    output_ready = "finnhub_3month_news_ready_v2.csv"
    summary_df_ready.to_csv(output_ready)
    
    print(f"\n🎉 Pipeline เสร็จสมบูรณ์! ได้ข่าวย้อนหลัง 3 เดือนเต็ม")
    print(f"✅ ไฟล์ 1 (มีข้อความ): {output_with_text}")
    print(f"✅ ไฟล์ 2 (ไม่มีข้อความ): {output_ready}")
    print(f"ข้อมูลถูกจัดเตรียมไว้ทั้งหมด {len(summary_df_full)} ชั่วโมง")

else:
    print("❌ ไม่พบข้อมูลข่าว หรือ API Key มีปัญหา")