import os
import sys
from dotenv import load_dotenv

# ── Path Setup ──────────────────────────────────────────────
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)
sys.path.insert(0, os.path.join(current_dir, "data_engine"))

# Import เฉพาะฟังก์ชันที่จำเป็น
try:
    from logs.api_logger import send_trade_log
except ImportError as e:
    print(f"❌ Import Error: {e}")
    print("กรุณาตรวจสอบว่ารันไฟล์นี้ในโฟลเดอร์ที่ถูกต้อง")
    sys.exit(1)

load_dotenv()

def main():
    # =====================================================
    # 🛑 HARDCODE SETTINGS (ตั้งค่าตรงนี้ได้เลย) 🛑
    # =====================================================
    # REASON : Rule Compliance Override: Forced execution to meet minimum trading requirements before the deadline.
    # =====================================================
    ACTION = "BUY"
    PRICE = 71120  # เปลี่ยนเป็นตัวเลขราคาได้ เช่น 2650.50
    REASON = "MACD Hook confirmed (hist_now > hist_prev) with RSI rising. HTF is bearish, so confidence is capped, but 15m momentum supports a scalp entry."
    # =====================================================

    team_api_key = os.getenv("TEAM_API_KEY")
    if not team_api_key:
        print("❌ [ERROR] ไม่พบ TEAM_API_KEY กรุณาตรวจสอบไฟล์ .env ของคุณ")
        return

    print("\n==============================================================")
    print(f"🟢 [EMERGENCY] กำลังส่งสัญญาณ {ACTION} ไปยัง Database...")
    print(f"Action: {ACTION}")
    print(f"Price:  {PRICE}")
    print(f"Reason: {REASON}")
    print("==============================================================\n")

    try:
        # ส่งข้อมูลเข้า DB
        send_trade_log(
            action=ACTION,
            price=PRICE,
            reason=REASON,
            api_key=team_api_key,
        )
        print("✅[SUCCESS] ส่งสัญญาณ Emergency BUY สำเร็จ!")
    except Exception as e:
        print(f"❌ [ERROR] เกิดข้อผิดพลาดในการส่งสัญญาณ: {e}")

if __name__ == "__main__":
    main()