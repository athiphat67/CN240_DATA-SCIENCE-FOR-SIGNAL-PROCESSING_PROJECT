# notifier/trade_log_api.py
import httpx
import logging
from config.settings import DRY_RUN, TRADE_LOG_API_URL, TRADE_LOG_API_KEY

logger = logging.getLogger("trading")

def send_trade_log(action: str, price: float | str, reason: str) -> bool:
    """
    ยิง Trade Log ไปยัง API อาจารย์
    DRY_RUN=true → ไม่ยิงจริง, Log เท่านั้น
    """
    if DRY_RUN:
        logger.info(f"[DRY_RUN] TradeLog API | action={action} | price={price} | reason={reason[:50]}...")
        return True

    if not TRADE_LOG_API_URL or not TRADE_LOG_API_KEY:
        logger.warning("[TradeLog] API URL/Key not configured. Skipping.")
        return False

    payload = {
        "action": action.upper(),
        "price": price,
        "reason": reason
    }
    
    try:
        with httpx.Client(timeout=10) as client:
            res = client.post(
                f"{TRADE_LOG_API_URL}/logs",
                headers={
                    "Authorization": f"Bearer {TRADE_LOG_API_KEY}",
                    "Content-Type": "application/json"
                },
                json=payload
            )
            if res.status_code == 201:
                logger.info(f"[TradeLog] ✅ Sent | {action} | {res.json().get('data', {}).get('id')}")
                return True
            else:
                logger.error(f"[TradeLog] ❌ HTTP {res.status_code} | {res.text}")
                return False
    except Exception as e:
        logger.error(f"[TradeLog] Network error: {e}")
        return False