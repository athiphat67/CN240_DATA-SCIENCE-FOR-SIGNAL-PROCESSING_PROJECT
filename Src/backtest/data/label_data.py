import pandas as pd
import numpy as np

def merge_gold_data():
    print("กำลังโหลดข้อมูล...")
    
    # 1. โหลดข้อมูลทั้ง 3 ไฟล์ (กรุณาแก้ไข Path ให้ตรงกับไฟล์ในเครื่องของคุณ)
    news_path = "news_data/gold_macro_news_v1.csv"
    sniper_path = "label/sniper_data.csv"
    gold_5min_path = "merge_data/merged_gold_5min_TH_TIME.csv"
    
    try:
        df_news = pd.read_csv(news_path)
        df_sniper = pd.read_csv(sniper_path)
        df_gold = pd.read_csv(gold_5min_path)
    except FileNotFoundError as e:
        print(f"Error: ไม่พบไฟล์ {e}")
        return

    print("กำลังจัดการรูปแบบเวลา (Timestamp)...")
    
    # 2. แปลงเวลาของทุกไฟล์เป็น Datetime
    # จัดการไฟล์ Sniper Data
    # ใช้วิธี infer_datetime_format และระบุ dayfirst หากรูปแบบเป็น DD/MM/YYYY
    df_sniper['timestamp'] = pd.to_datetime(df_sniper['timestamp'], dayfirst=True, format='mixed')
    
    # จัดการไฟล์ Gold 5min
    df_gold['timestamp'] = pd.to_datetime(df_gold['timestamp'])
    
    # จัดการไฟล์ News
    df_news['timestamp'] = pd.to_datetime(df_news['Date_Thai'])
    # ปัดเศษเวลาของข่าวลงให้ตรงกับแท่งเทียน 5 นาที (เพื่อให้ Merge กันได้พอดี)
    df_news['timestamp'] = df_news['timestamp'].dt.floor('5min')

    # 3. จัดการข้อมูลข่าว (หากใน 5 นาทีมีข่าวออกหลายตัว ให้จับรวมกันไว้ใน Row เดียว)
    print("กำลัง Aggregate ข้อมูลข่าว...")
    df_news_agg = df_news.groupby('timestamp').agg({
        'Category': lambda x: ', '.join(x.dropna().astype(str).unique()),
        'Impact': lambda x: ', '.join(x.dropna().astype(str).unique()),
        'Title': lambda x: ' | '.join(x.dropna().astype(str)),
        'Source_Type': lambda x: ', '.join(x.dropna().astype(str).unique()),
        'Publisher': lambda x: ', '.join(x.dropna().astype(str).unique())
    }).reset_index()

    # เปลี่ยนชื่อคอลัมน์ข่าวเพื่อป้องกันการสับสน
    df_news_agg = df_news_agg.rename(columns={
        'Category': 'news_category',
        'Impact': 'news_impact',
        'Title': 'news_title_macro',
        'Publisher': 'news_publisher'
    })

    # 4. จัดการคอลัมน์ที่ซ้ำกันระหว่าง Sniper Data และ Gold 5min
    print("กำลังรวมไฟล์ Sniper และ Gold 5Min...")
    # หาคอลัมน์ที่ซ้ำกัน (ยกเว้น timestamp)
    overlap_cols = set(df_sniper.columns).intersection(set(df_gold.columns)) - {'timestamp'}
    print(f"คอลัมน์ที่ซ้ำกัน และจะถูกใช้ของ Sniper เป็นหลัก: {overlap_cols}")
    
    # ลบคอลัมน์ซ้ำออกจาก df_gold เพื่อไม่ให้เกิด _x, _y ตอน Merge
    df_gold_clean = df_gold.drop(columns=list(overlap_cols))

    # ทำการ Merge ไฟล์ราคาทั้งสองเข้าด้วยกัน (ใช้ Outer Join เพื่อเก็บข้อมูลไว้ให้ครบถ้วน)
    df_merged_price = pd.merge(df_sniper, df_gold_clean, on='timestamp', how='outer')

    # 5. นำไฟล์ราคาที่รวมแล้ว มาเชื่อมกับไฟล์ข่าว
    print("กำลังรวมข้อมูลข่าวเข้ากับข้อมูลราคา...")
    # ใช้ Left Join เพื่อยึดแกนเวลาของราคาเป็นหลัก ข่าวจะเข้าไปแปะตามเวลาที่มี
    df_final = pd.merge(df_merged_price, df_news_agg, on='timestamp', how='left')

    # 6. จัดเรียงข้อมูลตามเวลา และรีเซ็ต Index
    df_final = df_final.sort_values('timestamp').reset_index(drop=True)

    # 7. บันทึกเป็นไฟล์ใหม่
    output_filename = "master_merged_data.csv"
    df_final.to_csv(output_filename, index=False)
    
    print(f"\n✅ เสร็จสิ้น! บันทึกไฟล์ผลลัพธ์เป็น: {output_filename}")
    print(f"ขนาดของข้อมูลทั้งหมด: {df_final.shape[0]} แถว, {df_final.shape[1]} คอลัมน์")

if __name__ == "__main__":
    merge_gold_data()