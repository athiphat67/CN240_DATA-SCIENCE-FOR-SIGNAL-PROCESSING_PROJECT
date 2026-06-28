import vertexai
from vertexai.generative_models import GenerativeModel

# ใช้ Project เดิมที่คุณเซ็ตไว้
vertexai.init(project="gemini-jome-backtest", location="us-central1")

# เปลี่ยนเป็นตัวที่ Stable ที่สุดในตอนนี้ (เมษายน 2026)
model = GenerativeModel("gemini-2.5-pro") 

try:
    print("กำลังติดต่อ Vertex AI ด้วย Gemini 2.5 pro ...")
    response = model.generate_content("วิเคราะห์แนวโน้มราคาทองคำ 96.5% สำหรับคืนนี้")
    print("--- Success! ---")
    print(response.text)
except Exception as e:
    print(f"เกิดข้อผิดพลาด: {e}")