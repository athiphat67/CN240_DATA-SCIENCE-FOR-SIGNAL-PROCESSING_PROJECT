"""
gold_omni_interceptor.py
ดักข้อมูลราคาทองคำฮั่วเซ่งเฮง พร้อม Fallback Intergold
(เวอร์ชัน: อัปเดตเฉพาะตอนราคาเปลี่ยน)
"""

from curl_cffi import requests
import websocket
import json
import time
import ssl
from data_engine.thailand_timestamp import get_thai_time

LATEST_DATA_FILE = "latest_gold_price.json"

# ==========================================
# ⚙️ ตั้งค่า API
# ==========================================
HSH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Origin": "https://www.huasengheng.com",
    "Referer": "https://www.huasengheng.com/",
}
HSH_API_STATUS = "https://apicheckpricev3.huasengheng.com/api/values/GetMarketStatus"
HSH_API_PRICE_96 = "https://apicheckpricev3.huasengheng.com/api/values/getprice/"
HSH_API_PRICE_99 = "https://apicheckpricev3.huasengheng.com/api/values/values"

IG_WS_URL = "wss://ws.intergold.co.th:3000/socket.io/?EIO=4&transport=websocket"

# ==========================================
# 🧠 ตัวแปรสำหรับ "จดจำ" ข้อมูลล่าสุด
# ==========================================
last_hsh_update_time = None
last_ig_prices = None

_usd_thb_cache: float = 34.0 
_usd_thb_last_fetch: float = 0.0
_USD_THB_CACHE_SECONDS: int = 60

def _fetch_usd_thb_rate() -> float:
    """
    ดึง USD/THB ล่าสุดจาก Yahoo Finance (lightweight - ไม่ต้อง import yfinance)
    ใช้ cache 60 วินาที เพื่อไม่ hit API ทุกรอบ 5 วินาที
    คืน 0.0 ถ้าดึงไม่ได้ (interceptor จะ keep ค่าเดิมไว้)
    """
    global _usd_thb_cache, _usd_thb_last_fetch
    
    now = time.time()
    if now - _usd_thb_last_fetch < _USD_THB_CACHE_SECONDS and _usd_thb_cache > 0:
        return _usd_thb_cache  # คืน cache โดยไม่ hit API
        
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/USDTHB=X"
        resp = requests.get(
            url,
            params={"interval": "1m", "range": "1d"},
            timeout=5,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        data = resp.json()
        closes = (
            data["chart"]["result"][0]
            ["indicators"]["quote"][0]["close"]
        )
        valid = [c for c in closes if c is not None]
        if valid:
            _usd_thb_cache = round(float(valid[-1]), 4)
            _usd_thb_last_fetch = now
            return _usd_thb_cache
    except Exception as e:
        print(f"[Interceptor] _fetch_usd_thb_rate failed: {e}")
        
    return _usd_thb_cache


def save_to_json(payload):
    with open(LATEST_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def fetch_huasengheng(session):
    global last_hsh_update_time

    try:
        # 1. ดึงราคาทอง 96.5% เพื่อเช็คอัปเดตก่อน
        res_96 = session.get(HSH_API_PRICE_96, timeout=5)
        if res_96.status_code != 200:
            raise Exception("HSH 96.5% API Error")

        bid_96, ask_96 = 0.0, 0.0
        current_time_update = ""

        for item in res_96.json():
            if item.get("GoldType") == "HSH" and item.get("GoldCode") == "96.50":
                bid_96 = float(item.get("Buy", "0").replace(",", ""))
                ask_96 = float(item.get("Sell", "0").replace(",", ""))
                current_time_update = item.get("TimeUpdate", "")
                break

        # 🛑 ถ้าราคาไม่อัปเดต (เวลาอัปเดตเท่ากับรอบที่แล้ว) ให้หยุดทำและรอรอบใหม่
        if current_time_update == last_hsh_update_time:
            return True

        # ถ้าอัปเดต ให้จำเวลาใหม่ไว้
        last_hsh_update_time = current_time_update

        # 2. ดึงสถานะตลาด
        market_status = "UNKNOWN"
        try:
            res_status = session.get(HSH_API_STATUS, timeout=5)
            if res_status.status_code == 200:
                market_status = res_status.json().get("MarketStatus", "UNKNOWN")
        except:
            pass

        # 3. ดึงราคาทอง 99.99%
        bid_99, ask_99 = 0.0, 0.0
        try:
            res_99 = session.get(HSH_API_PRICE_99, timeout=5)
            if res_99.status_code == 200:
                data_99 = res_99.json()
                bid_99 = float(data_99.get("Buy", "0").replace(",", ""))
                ask_99 = float(data_99.get("Sell", "0").replace(",", ""))
        except:
            pass

        spot = 0.0 # คง spot ไว้เป็น 0.0 ตามเดิม (ถ้ายังไม่ได้ดึงจากที่อื่น)
        
        if bid_96 > 0 and ask_96 > 0:
            usd_thb = _fetch_usd_thb_rate()  # ← เพิ่มบรรทัดนี้เพื่อดึงค่าจริง
            
            payload = {
                "source": "huasengheng_api",
                "market_status": market_status,
                "price_thb_per_baht_weight": round((bid_96 + ask_96) / 2, 2),
                "sell_price_thb": ask_96,
                "buy_price_thb": bid_96,
                "spread_thb": ask_96 - bid_96,
                "gold_9999_buy": bid_99,
                "gold_9999_sell": ask_99,
                "gold_spot_usd": spot,
                "usd_thb_live": usd_thb,
                "timestamp": get_thai_time().isoformat(),
            }
            save_to_json(payload)
            print(
                f"[{get_thai_time().strftime('%H:%M:%S')}] 🔴 HSH 96.5% อัปเดตใหม่! | Buy: ฿{bid_96:,.0f} | Sell: ฿{ask_96:,.0f} | Status: {market_status}"
            )
            return True

    except Exception as e:
        print(f"⚠️ ฮั่วเซ่งเฮงมีปัญหา: {e}")
        return False


def run_intergold_fallback():
    global last_ig_prices
    print("🚀 ระบบสำรองทำงาน: สลับไปใช้ Intergold (WebSocket)...")
    try:
        session = requests.Session(impersonate="chrome120")
        resp = session.get("https://www.intergold.co.th/", timeout=15)
        cookie_str = "; ".join(
            [f"{k}={v}" for k, v in session.cookies.get_dict().items()]
        )

        ws = websocket.WebSocket()
        ws.connect(
            IG_WS_URL,
            header=[
                "User-Agent: Mozilla/5.0",
                "Origin: https://www.intergold.co.th",
                "Referer: https://www.intergold.co.th/",
            ],
            cookie=cookie_str,
            sslopt={"cert_reqs": ssl.CERT_NONE},
        )
        print("🟢 สลับมาใช้ท่อ Intergold สำเร็จ! (กำลังรอข้อมูลที่เปลี่ยนแปลง...)")

        while True:
            msg_str = ws.recv()
            if not msg_str:
                break

            if msg_str.startswith("0"):
                ws.send("40")
            elif msg_str == "2":
                ws.send("3")
            elif msg_str.startswith("42"):
                try:
                    data_list = json.loads(msg_str[2:])
                    if data_list[0] == "updateGoldRateData":
                        gold = data_list[1]
                        bid_96 = float(gold.get("bidPrice96", 0))
                        ask_96 = float(gold.get("offerPrice96", 0))
                        spot = float(gold.get("AUXBuy", 0))
                        fx = float(gold.get("usdBuy", 0))

                        current_prices = (bid_96, ask_96, spot, fx)

                        if bid_96 > 0 and ask_96 > 0:
                            # 🛑 เช็คว่าราคา 4 ตัวนี้ ตัวใดตัวหนึ่งขยับหรือไม่ ถ้าไม่ขยับให้ข้ามไป
                            if current_prices != last_ig_prices:
                                last_ig_prices = current_prices  # จำราคาใหม่

                                payload = {
                                    "source": "intergold_fallback_ws",
                                    "market_status": "UNKNOWN",
                                    "price_thb_per_baht_weight": round(
                                        (bid_96 + ask_96) / 2, 2
                                    ),
                                    "sell_price_thb": ask_96,
                                    "buy_price_thb": bid_96,
                                    "spread_thb": ask_96 - bid_96,
                                    "gold_9999_buy": float(gold.get("bidPrice99", 0)),
                                    "gold_9999_sell": float(
                                        gold.get("offerPrice99", 0)
                                    ),
                                    "gold_spot_usd": spot,
                                    "usd_thb_live": fx,
                                    "timestamp": get_thai_time().isoformat(),
                                }
                                save_to_json(payload)
                                print(
                                    f"[{get_thai_time().strftime('%H:%M:%S')}] 🟡 FALLBACK (IG) ขยับ! | Buy: ฿{bid_96:,.0f} | Sell: ฿{ask_96:,.0f} | Spot: ${spot:,.2f} | FX: ฿{fx:,.2f}"
                                )
                except json.JSONDecodeError:
                    pass
    except Exception as e:
        print(f"❌ ระบบสำรอง (IG) หลุด: {e}")


def start_interceptor():
    """ฟังก์ชันหลักสำหรับเริ่มระบบดักจับ (เพื่อให้ Orchestrator เรียกใช้ได้)"""
    print("🤖 เริ่มเดินเครื่องระบบดักจับราคาทองคำ...")
    hsh_session = requests.Session(impersonate="chrome120", headers=HSH_HEADERS)

    while True:
        success = fetch_huasengheng(hsh_session)

        if success:
            time.sleep(5)  # เช็ค HSH ทุกๆ 5 วินาที
        else:
            run_intergold_fallback()
            print("🔄 กำลังพยายามกลับไปเชื่อมต่อ HSH ใหม่อีกครั้งใน 5 วินาที...")
            time.sleep(5)


if __name__ == "__main__":
    # รันแบบทดสอบไฟล์เดียว (Standalone)
    start_interceptor()
