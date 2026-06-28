import pandas as pd

def process_and_calculate_premium():
    # 1. โหลดข้อมูลจากไฟล์ทั้ง 2
    print("กำลังโหลดข้อมูล...")
    df_spot = pd.read_csv("services/agent/backtest/data/premium_hsh/Merged_XAUUSD_USDTHB_M1_ThaiTime_Feb_to_Apr.csv")
    df_hsh = pd.read_csv("services/agent/backtest/data/premium_hsh/HSH965_gold_1min.csv")

    # 2. ปรับแต่งรูปแบบเวลา (Datetime) ให้ตรงกันเพื่อใช้เชื่อมตาราง (Merge)
    # ไฟล์ Spot ให้อ้างอิงคอลัมน์ Datetime_TH
    df_spot['Datetime'] = pd.to_datetime(df_spot['Datetime_TH'])
    
    # ไฟล์ HSH รูปแบบเวลาเป็น YYYY-MM-DD HH.MM (ใช้จุดทศนิยมแทนโคลอน)
    df_hsh['Datetime'] = pd.to_datetime(df_hsh['Datetime'], format='%Y-%m-%d %H.%M')

    # 3. รวมตารางโดยใช้ Datetime ที่ตรงกัน (Inner Join)
    print("กำลังรวมตาราง...")
    df_merged = pd.merge(df_spot, df_hsh, on='Datetime', how='inner')
    
    if len(df_merged) == 0:
        print("ไม่พบข้อมูลที่มีเวลาตรงกันเลย โปรดตรวจสอบช่วงเวลาในไฟล์อีกครั้ง")
        return

    # 4. คำนวณค่า premium_buy และ premium_sell
    print(f"เชื่อมข้อมูลสำเร็จ {len(df_merged)} แถว, กำลังคำนวณ Premium...")
    
    # สูตร: premium_buy(t) = HSH_Buy(t) / (USDTHB(t) * 0.4729) - Spot(t)
    df_merged['premium_buy'] = (df_merged['Buy'] / (df_merged['CLOSE_USDTHB'] * 0.4729)) - df_merged['CLOSE_XAUUSD']
    
    # สูตร: premium_sell(t) = HSH_Sell(t) / (USDTHB(t) * 0.4729) - Spot(t)
    df_merged['premium_sell'] = (df_merged['Sell'] / (df_merged['CLOSE_USDTHB'] * 0.4729)) - df_merged['CLOSE_XAUUSD']

    # 5. บันทึกผลลัพธ์เป็นไฟล์ CSV ใหม่
    output_filename = "Premium_Calculated_Result.csv"
    df_merged.to_csv(output_filename, index=False)
    
    print(f"\nเสร็จสิ้น! บันทึกผลลัพธ์ลงในไฟล์: {output_filename}")
    
    # พรีวิวข้อมูล 5 แถวแรก
    columns_to_show = ['Datetime', 'Buy', 'Sell', 'CLOSE_XAUUSD', 'CLOSE_USDTHB', 'premium_buy', 'premium_sell']
    print("\nตัวอย่างข้อมูลหลังคำนวณ:")
    print(df_merged[columns_to_show].head())

if __name__ == "__main__":
    process_and_calculate_premium()