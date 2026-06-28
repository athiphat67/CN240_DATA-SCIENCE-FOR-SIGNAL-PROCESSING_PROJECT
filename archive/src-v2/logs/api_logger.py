import requests

def send_trade_log(action: str, price, reason: str, api_key: str, **kwargs):
    """
    ฟังก์ชันสำหรับส่ง Trade Log ไปยังระบบ GoldTrade Logs API พร้อมข้อมูลเสริม (Optional)
    """
    url = "https://goldtrade-logs-api.poonnatuch.workers.dev/logs"
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    # ข้อมูลบังคับ 3 ฟิลด์
    payload = {
        "action": action,
        "price": price,
        "reason": reason
    }
    
    # นำข้อมูลอื่นๆ ที่ส่งเพิ่มเข้ามา (kwargs) อัปเดตเข้าไปใน payload
    payload.update(kwargs)
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 201:
            data = response.json().get('data', {})
            print(f"  ✅ [API] ส่ง Trade Log สำเร็จ (ID: {data.get('id')})")
        else:
            print(f"  ❌ [API] ส่ง Trade Log ไม่สำเร็จ: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"  ❌ [API] เชื่อมต่อ API ไม่สำเร็จ: {e}")