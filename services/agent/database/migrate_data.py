import sys
import os

# --- แก้ Path ก่อนเริ่ม Import ---
# ให้มันมองหาไฟล์จากโฟลเดอร์ 'Src' (โฟลเดอร์หลัก)
current_dir = os.path.dirname(os.path.abspath(__file__)) # /Src/database
parent_dir = os.path.dirname(current_dir)                 # /Src
sys.path.insert(0, parent_dir)

# --- ตอนนี้ค่อย Import ได้แล้ว ---
from database.database import RunDatabase
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

# ตั้งค่า Supabase (ใช้ os.getenv)
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
db = RunDatabase()

def migrate():
    print("Fetching data from Supabase...")
    try:
        response = supabase.table("gold_prices_ig") \
                    .select("*") \
                    .order("timestamp", desc=True) \
                    .limit(10) \
                    .execute()
        
        with db.get_connection() as conn:
            with conn.cursor() as cursor:
                for row in response.data:
                    # เช็คก่อนว่ามี timestamp นี้หรือยัง
                    cursor.execute("SELECT 1 FROM gold_prices_ig WHERE timestamp = %s", (row['timestamp'],))
                    exists = cursor.fetchone()
                    
                    if not exists:
                        cursor.execute("""
                            INSERT INTO gold_prices_ig (timestamp, ask_96, bid_96, spot_price, usd_thb)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (row['timestamp'], row['ask_96'], row['bid_96'], row['spot_price'], row['usd_thb']))
                conn.commit()
        print(f"Migrated {len(response.data)} records to Render DB successfully!")
    except Exception as e:
        print(f"Migration Failed: {e}")

if __name__ == "__main__":
    migrate()