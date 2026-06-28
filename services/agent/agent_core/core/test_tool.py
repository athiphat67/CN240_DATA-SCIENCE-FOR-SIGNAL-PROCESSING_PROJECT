import json

# ==========================================
# 1. สร้าง Tool จำลอง (ตัวที่คุณจะเอาไปไว้ใน agent_core/tools/...)
# ==========================================
def fetch_breaking_news(asset: str = "gold") -> dict:
    """ดึงข่าวล่าสุดของสินทรัพย์ที่ระบุ"""
    print(f"🔍 [TOOL EXECUTING] กำลังไปดึงข่าวให้สำหรับ: {asset}...")
    
    # จำลองว่าดึง API ข่าวมาเสร็จแล้ว (ในของจริงก็ใส่ request.get ตรงนี้)
    return {
        "asset": asset,
        "latest_headline": "ตลาดคาดการณ์ Fed อาจลดดอกเบี้ยในการประชุมรอบหน้า",
        "sentiment_score": 0.85,
        "impact": "High"
    }

def get_support_resistance(timeframe: str) -> dict:
    """ดึงแนวรับแนวต้าน"""
    print(f"🔍 [TOOL EXECUTING] คำนวณแนวรับแนวต้านใน TF: {timeframe}...")
    return {
        "timeframe": timeframe,
        "support_1": 2350.00,
        "resistance_1": 2400.00
    }

# ==========================================
# 2. จำลอง Tool Registry (เหมือนที่คุณจะทำใน services.py)
# ==========================================
my_tools = {
    "fetch_news": fetch_breaking_news,
    "get_sr": get_support_resistance
}

# ==========================================
# 3. จำลองสิ่งที่ LLM ตอบกลับมา (JSON ที่โดน extract_json() แล้ว)
# ==========================================
# สมมติว่า LLM อ่าน prompt แล้วบอกว่า "ขอข้อมูลข่าวทองหน่อย"
llm_mock_response = {
    "action": "CALL_TOOL",
    "tool_name": "fetch_news",
    "tool_args": {
        "asset": "XAUUSD"
    }
}

print("🤖 [LLM THOUGHT] LLM สั่งให้เรียก Tool:", llm_mock_response["tool_name"])
print("📦 [LLM THOUGHT] ส่ง Parameters มาคือ:", llm_mock_response["tool_args"])
print("-" * 40)

# ==========================================
# 4. ทดสอบการรันแบบที่ Orchestrator ทำ
# ==========================================
tool_name = llm_mock_response.get("tool_name")
tool_args = llm_mock_response.get("tool_args", {})

if tool_name in my_tools:
    # 🎯 เวทมนตร์อยู่บรรทัดนี้: มันจะเอา Dict ไปกระจายเป็น Kwargs โยนเข้าฟังก์ชัน
    observation = my_tools[tool_name](**tool_args)
    
    print("-" * 40)
    print("✅ [OBSERVATION] ผลลัพธ์ที่จะส่งกลับไปแปะใน Prompt ให้ LLM ดูรอบถัดไป:")
    print(json.dumps(observation, indent=2, ensure_ascii=False))
else:
    print(f"❌ [ERROR] ไม่พบ Tool ชื่อ '{tool_name}' ใน Registry")