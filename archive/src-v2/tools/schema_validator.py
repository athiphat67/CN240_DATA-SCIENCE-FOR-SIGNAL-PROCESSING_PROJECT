"""
tools/schema_validator.py — ตรวจสอบ Schema ของ Market State Payload
"""

import logging

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = [
    "market_data.spot_price_usd",
    "market_data.thai_gold_thb.sell_price_thb",
    "market_data.thai_gold_thb.buy_price_thb",
    "technical_indicators.rsi.value",
]


def validate_market_state(state: dict) -> list[str]:
    """
    ตรวจสอบ payload ว่ามี required fields ครบหรือไม่
    คืน list ของ missing fields (ถ้า list ว่าง = ผ่าน)
    """
    errors = []
    for path in REQUIRED_FIELDS:
        parts = path.split(".")
        obj = state
        for p in parts:
            if not isinstance(obj, dict) or p not in obj:
                errors.append(f"Missing: {path}")
                break
            obj = obj[p]

    if errors:
        logger.error(f"🚨 Schema Validation Failed: {errors}")
    else:
        logger.debug("✅ Schema validation passed")

    return errors
