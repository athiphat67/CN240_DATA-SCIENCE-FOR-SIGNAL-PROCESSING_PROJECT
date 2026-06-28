import pandas as pd
import os

# 1. หาตำแหน่งโฟลเดอร์ปัจจุบัน (ตอนนี้สคริปต์กับ CSV อยู่ที่เดียวกันแล้ว)
current_dir = os.path.dirname(os.path.abspath(__file__))
file_path = os.path.join(current_dir, 'MOCK_HSH965_New_M5_202512221515_202604021955.csv')

try:
    # 2. อ่านไฟล์ CSV
    df = pd.read_csv(file_path, sep='\t')
    
    # [เคล็ดลับกันเหนียว] ลบช่องว่างหรืออักขระซ่อนเร้นที่อาจติดมากับชื่อคอลัมน์ MT5
    df.columns = df.columns.str.strip()
    
    # 3. นำวันที่และเวลามารวมกัน
    df['Datetime'] = pd.to_datetime(df['<DATE>'] + ' ' + df['<TIME>'])
    
    # ปรับเวลาให้เป็นโซนไทย (+4 ชั่วโมง ตามที่โบรกเกอร์ห่างจากเรา)
    df['Datetime'] = df['Datetime'] + pd.Timedelta(hours=4)
    
    # 4. เลือกเก็บเฉพาะคอลัมน์ที่จำเป็น 
    # (จังหวะนี้ต้องมีคำว่า 'Datetime' ที่เพิ่งสร้างใหม่ด้วย)
    cols_to_keep = ['Datetime', '<OPEN>', '<HIGH>', '<LOW>', '<CLOSE>', '<TICKVOL>']
    df = df[cols_to_keep]
    
    # 5. เปลี่ยนชื่อคอลัมน์ให้เรียกใช้งานง่าย
    # (บรรทัดนี้แหละครับที่จะกำหนดให้มีคอลัมน์ชื่อ 'Datetime' แน่ๆ)
    df.columns = ['Datetime', 'Open', 'High', 'Low', 'Close', 'Volume']
    
    # 6. ตั้ง 'Datetime' ให้เป็น Index ของตาราง
    df.set_index('Datetime', inplace=True)
    
    # 7. เซฟเป็นไฟล์ใหม่
    output_file = os.path.join(current_dir, 'Cleaned_HSH965_M5_TH_Time.csv')
    df.to_csv(output_file)
    
    print("✅ แปลงข้อมูลสำเร็จ! เซฟไฟล์ไว้ที่:")
    print(output_file)
    print("-" * 40)
    print("ตัวอย่างข้อมูลที่คลีนแล้ว:")
    print(df.head())

except FileNotFoundError:
    print("❌ หาไฟล์ไม่เจอ: เช็คชื่อไฟล์ CSV ว่าตรงกับของจริงไหม")
except KeyError as e:
    print(f"❌ ไม่พบคอลัมน์: {e} - ลองพริ้นต์ df.columns ดูว่าชื่อคอลัมน์ตอนโหลดมาชื่ออะไร")