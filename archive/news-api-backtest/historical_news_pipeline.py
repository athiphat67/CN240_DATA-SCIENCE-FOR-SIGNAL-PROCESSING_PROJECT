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
DAYS_TO_FETCH = 90 # ดึงย้อนหลัง 30 วันเต็ม

# ใช้ Ticker เป็น Proxy ในการดึงข่าว และกำหนดน้ำหนัก (Impact Weight)
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
# 3. Fetch Historical News (1 Month Full)
# ==========================================
def fetch_historical_news():
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=DAYS_TO_FETCH)
    
    all_raw_articles = []
    
    print(f"\n📡 Fetching {DAYS_TO_FETCH}-Day Historical News (Day-by-Day)...")
    
    for symbol, meta in PROXY_SYMBOLS.items():
        print(f"\n  📥 Fetching data for: {symbol} (Category: {meta['category']})")
        
        # วนลูปดึงทีละ 1 วัน เพื่อแก้ปัญหา API Limit คืนค่าแค่ 250 ข่าว
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
                            all_raw_articles.append({
                                "published_at": datetime.fromtimestamp(article['datetime'], tz=timezone.utc),
                                "title": article.get("headline"),
                                "source": article.get("source"),
                                "category": meta['category'],
                                "weight": meta['weight']
                            })
                        # Print วันที่เพื่อให้รู้ว่าโปรแกรมไม่ได้ค้าง
                        print(f"     ✅ {_from_str}: Found {len(news_data)} articles")
                    else:
                        print(f"     ⚠️ Error on {_from_str}: {news_data}")
                else:
                    print(f"     ⚠️ API Error {response.status_code} on {_from_str}")
                    
            except Exception as e:
                print(f"     ❌ Fetch error on {_from_str}: {e}")
                
            # Finnhub Limit คือ 60 requests/minute ให้รอ 1 วินาทีถือว่าปลอดภัย
            time.sleep(1) 
            current_date = next_date
            
    df = pd.DataFrame(all_raw_articles)
    
    if not df.empty:
        initial_len = len(df)
        df.drop_duplicates(subset=['title'], inplace=True)
        print(f"\n🧹 Dropped {initial_len - len(df)} duplicate articles.")
        
    return df

# ==========================================
# 4. Processing & Sentiment Scoring
# ==========================================
def calculate_sentiment(title):
    try:
        result = sentiment_analyzer(title[:500])[0] 
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
    
    print("\n🎭 Running FinBERT Sentiment Analysis...")
    df['sentiment_score'] = df['title'].progress_apply(calculate_sentiment)
    
    # แปลงเวลาเป็นเวลาไทย (Asia/Bangkok)
    df['published_at'] = df['published_at'].dt.tz_convert('Asia/Bangkok')
    df['published_at'] = df['published_at'].dt.tz_localize(None) 
    df.set_index('published_at', inplace=True)
    
    # ==========================================
    # 6. Aggregation (รวมกลุ่ม 1 ชั่วโมง + ลบ 0.0)
    # ==========================================
    print("\n📊 Aggregating data into 1-Hour timeframes (Thai Time)...")
    
    def weighted_sentiment(group):
        if group.empty or group['weight'].sum() == 0:
            return 0.0
        return (group['sentiment_score'] * group['weight']).sum() / group['weight'].sum()

    def join_titles(titles):
        if len(titles) == 0: return ""
        return " | ".join(titles[:3])

    grouped = df.groupby(pd.Grouper(freq='1h'))
    
    summary_df = pd.DataFrame({
        'news_count': grouped['title'].count(),
        'overall_sentiment': grouped.apply(weighted_sentiment),
        'top_headlines_summary': grouped['title'].apply(join_titles)
    })
    
    # ปัดเศษ
    summary_df['overall_sentiment'] = summary_df['overall_sentiment'].round(4)
    
    # ลบชั่วโมงที่คะแนนเป็น 0.0 ทิ้ง (ลดขนาดไฟล์ เก็บเฉพาะที่มี Signal)
    summary_df = summary_df[summary_df['overall_sentiment'] != 0.0]
    
    output_filename = "finnhub_1month_news_ready.csv"
    summary_df.to_csv(output_filename)
    
    print(f"\n🎉 Pipeline เสร็จสมบูรณ์! ได้ข่าวย้อนหลัง 1 เดือนเต็ม")
    print(f"✅ บันทึกไฟล์ลง: {output_filename} (ทั้งหมด {len(summary_df)} ชั่วโมงที่มีข่าว)")

else:
    print("❌ ไม่พบข้อมูลข่าว หรือ API Key มีปัญหา")