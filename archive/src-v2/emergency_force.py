"""
emergency_force.py — Force BUY / SELL (bypass XGBoost + gates)
==============================================================

ใช้เมื่อ model ส่ง HOLD ไม่หยุด แต่ session ใกล้หมด
สามารถสั่ง force_buy() หรือ force_sell() ได้ทันที
ระบบจะ:
    1. ดึงราคาทองคำล่าสุดจาก latest_gold_price.json หรือ MTS API
    2. ส่ง Trade Log ผ่าน api_logger (เหมือนปกติ)
    3. ส่งแจ้งเตือน Discord (เหมือนปกติ)
    4. บันทึกลง Database (ถ้ามี)

ใช้งาน:
    python Src_V2/emergency_force.py buy     # Force BUY
    python Src_V2/emergency_force.py sell    # Force SELL
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

# ── Path setup ────────────────────────────────────────────────
_SELF_DIR = Path(__file__).resolve().parent
if str(_SELF_DIR) not in sys.path:
    sys.path.insert(0, str(_SELF_DIR))

from dotenv import load_dotenv

load_dotenv(_SELF_DIR / ".env")

from logs.api_logger import send_trade_log  # noqa: E402
from logs.logger_setup import sys_logger  # noqa: E402

# ── Optional imports (graceful) ───────────────────────────────
try:
    from notification.discord_notifier import DiscordNotifier
except Exception:
    DiscordNotifier = None  # type: ignore

try:
    from database.database import RunDatabase
except Exception:
    RunDatabase = None  # type: ignore

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────

PROVIDER_TAG: str = "emergency-force"

# --- แก้ไขตรงนี้เพื่อ Hardcode ค่าที่ต้องการ ---
HARDCODED_BUY_PRICE: Optional[float] = 71410.0   # ตั้งเป็น None ถ้าต้องการใช้ราคา Real-time
HARDCODED_SELL_PRICE: Optional[float] = 71290.0  # ตั้งเป็น None ถ้าต้องการใช้ราคา Real-time

REASON_FORCE_BUY: str = (
    "เหลือเวลา 43 นาที session ใกล้หมด quota ไม่พอ จึงรีบเข้าซื้อตามsession"
)
REASON_FORCE_SELL: str = (
    "ใกล้หมดเวลาตามsession จึงต้องขายออก"
)


# ─────────────────────────────────────────────────────────────
# Price fetcher — lightweight (ไม่ต้องเรียก Orchestrator ทั้งตัว)
# ─────────────────────────────────────────────────────────────


def _fetch_latest_price() -> Dict[str, Any]:
    """
    ดึงราคาทองคำล่าสุดจาก latest_gold_price.json
    คืน dict ที่มี sell_price_thb, buy_price_thb, gold_spot_usd, etc.
    """
    json_path = _SELF_DIR / "latest_gold_price.json"
    if json_path.exists():
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            sys_logger.info(
                f"[force] ราคาล่าสุดจาก {json_path.name}: "
                f"sell=฿{data.get('sell_price_thb', 0):,.0f} "
                f"buy=฿{data.get('buy_price_thb', 0):,.0f}"
            )
            return data
        except Exception as exc:
            sys_logger.error(f"[force] อ่าน {json_path.name} ไม่ได้: {exc}")

    # Fallback: MTS API
    try:
        import requests

        end_ts = int(time.time())
        start_ts = end_ts - 3600
        url = (
            "https://tradingview.mtsgold.co.th/mgb/history"
            f"?symbol=GLD965&resolution=1&from={start_ts}&to={end_ts}"
            "&countback=1&currencyCode=THB"
        )
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("s") == "ok" and payload.get("c"):
            price = float(payload["c"][-1])
            sys_logger.info(f"[force] ราคาจาก MTS API: ฿{price:,.0f}")
            return {"sell_price_thb": price, "buy_price_thb": price, "source": "mts_api"}
    except Exception as exc:
        sys_logger.error(f"[force] MTS API failed: {exc}")

    sys_logger.warning("[force] ไม่สามารถดึงราคาได้เลย — ใช้ 0")
    return {"sell_price_thb": 0, "buy_price_thb": 0, "source": "none"}


# ─────────────────────────────────────────────────────────────
# Discord notification
# ─────────────────────────────────────────────────────────────


def _send_discord_notification(
    action: str,
    price: float,
    reason: str,
    *,
    confidence: float = 1.0,
) -> bool:
    """ส่ง Discord notification สำหรับ force trade"""
    if DiscordNotifier is None:
        sys_logger.warning("[force] DiscordNotifier ไม่สามารถ import ได้ — ข้าม")
        return False

    try:
        notifier = DiscordNotifier()
    except Exception as exc:
        sys_logger.error(f"[force] DiscordNotifier init failed: {exc}")
        return False

    voting_result = {
        "final_signal": action,
        "weighted_confidence": confidence,
        "rationale": reason,
    }
    interval_results = {
        "force": {
            "signal": action,
            "confidence": confidence,
            "entry_price": price,
            "stop_loss": None,
            "take_profit": None,
            "provider": PROVIDER_TAG,
            "rationale": reason,
        }
    }
    # สร้าง market_state จำลองจากราคาล่าสุด
    market_state = {
        "market_data": {
            "thai_gold_thb": {
                "sell_price_thb": price,
                "buy_price_thb": price,
            },
            "forex": {"usd_thb": 0},
            "spot_price_usd": {},
        },
        "data_quality": {"quality_score": "good"},
    }

    try:
        ok = notifier.notify(
            voting_result=voting_result,
            interval_results=interval_results,
            market_state=market_state,
            provider=PROVIDER_TAG,
            period="force",
        )
        sys_logger.info(f"[force] Discord sent={ok}")
        return ok
    except Exception as exc:
        sys_logger.error(f"[force] Discord failed: {exc}")
        return False


# ─────────────────────────────────────────────────────────────
# Trade log
# ─────────────────────────────────────────────────────────────


def _send_trade_log(
    action: str,
    price: float,
    reason: str,
    *,
    confidence: float = 1.0,
) -> None:
    """ส่ง Trade Log ผ่าน api_logger"""
    team_api_key = os.getenv("TEAM_API_KEY")
    if not team_api_key:
        sys_logger.error("[force] TEAM_API_KEY ไม่ได้ตั้ง — ไม่สามารถส่ง trade log ได้")
        return

    try:
        send_trade_log(
            action=action,
            price=price,
            reason=reason,
            api_key=team_api_key,
            # confidence=confidence,
            # stop_loss=0.0,
            # take_profit=0.0,
            # provider=PROVIDER_TAG,
            # session_id="force",
        )
        sys_logger.info("[force] ✅ Trade log ส่งสำเร็จ")
    except Exception as exc:
        sys_logger.error(f"[force] ❌ Trade log ส่งไม่สำเร็จ: {exc}")


# ─────────────────────────────────────────────────────────────
# Database persist (optional)
# ─────────────────────────────────────────────────────────────


def _persist_to_db(action: str, price: float, reason: str) -> Optional[int]:
    """บันทึกลง Database (ถ้ามี)"""
    if RunDatabase is None:
        sys_logger.debug("[force] Database ไม่พร้อม — ข้าม")
        return None

    try:
        db = RunDatabase()
        run_id = db.save_run(
            provider=PROVIDER_TAG,
            result={
                "signal": action,
                "confidence": 1.0,
                "entry_price": price,
                "stop_loss": None,
                "take_profit": None,
                "position_size_thb": 0.0,
                "rationale": reason,
                "rejection_reason": None,
                "model_signal": action,
                "iterations_used": 0,
                "tool_calls_used": 0,
            },
            market_state={},
            interval_tf="force",
            period="force",
        )
        sys_logger.info(f"[force] ✅ บันทึก DB run_id={run_id}")
        db.close()
        return run_id
    except Exception as exc:
        sys_logger.error(f"[force] ❌ บันทึก DB ไม่สำเร็จ: {exc}")
        return None


# ─────────────────────────────────────────────────────────────
# Public API — force_buy / force_sell
# ─────────────────────────────────────────────────────────────


def force_buy(
    send_log: bool = True,
    send_discord: bool = True,
    save_db: bool = True
) -> Dict[str, Any]:
    """
    🟢 สั่งซื้อทันที — bypass XGBoost + gates ทั้งหมด

    Reason: "เหลือเวลา 43 นาที session ใกล้หมด quota ไม่พอ จึงรีบเข้าซื้อตามsession"
    """
    sys_logger.info("=" * 60)
    sys_logger.info("🟢 [FORCE BUY] เริ่มกระบวนการ Force Buy")
    sys_logger.info("=" * 60)

    price_data = _fetch_latest_price()
    
    # ใช้ราคา Hardcoded ถ้ามีการระบุไว้ ไม่งั้นใช้ราคา Real-time
    if HARDCODED_BUY_PRICE is not None:
        price = HARDCODED_BUY_PRICE
        sys_logger.info(f"[FORCE BUY] 📌 ใช้ราคา Hardcoded: ฿{price:,.0f}")
    else:
        # ใช้ sell_price เป็น entry price (ราคาที่ร้านขายให้เรา = ราคาที่เราซื้อ)
        price = float(price_data.get("sell_price_thb", 0))

    sys_logger.info(f"[FORCE BUY] Action=BUY | Price=฿{price:,.0f}")
    sys_logger.info(f"[FORCE BUY] Reason: {REASON_FORCE_BUY}")

    # 1) ส่ง Trade Log
    if send_log:
        _send_trade_log(action="BUY", price=price, reason=REASON_FORCE_BUY)
    else:
        sys_logger.info("[FORCE BUY] ⏭️ ข้ามการส่ง Trade Log (Disabled)")

    # 2) ส่ง Discord
    if send_discord:
        _send_discord_notification(action="BUY", price=price, reason=REASON_FORCE_BUY)
    else:
        sys_logger.info("[FORCE BUY] ⏭️ ข้ามการส่ง Discord (Disabled)")

    # 3) บันทึก DB
    run_id = None
    if save_db:
        run_id = _persist_to_db(action="BUY", price=price, reason=REASON_FORCE_BUY)
    else:
        sys_logger.info("[FORCE BUY] ⏭️ ข้ามการบันทึก Database (Disabled)")

    result = {
        "action": "BUY",
        "price": price,
        "reason": REASON_FORCE_BUY,
        "provider": PROVIDER_TAG,
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(),
    }

    sys_logger.info(f"🟢 [FORCE BUY] เสร็จสิ้น — run_id={run_id}")
    return result


def force_sell(
    send_log: bool = True,
    send_discord: bool = True,
    save_db: bool = True
) -> Dict[str, Any]:
    """
    🔴 สั่งขายทันที — bypass XGBoost + gates ทั้งหมด

    Reason: "ใกล้หมดเวลาตามsession จึงต้องขายออก"
    """
    sys_logger.info("=" * 60)
    sys_logger.info("🔴 [FORCE SELL] เริ่มกระบวนการ Force Sell")
    sys_logger.info("=" * 60)

    price_data = _fetch_latest_price()

    # ใช้ราคา Hardcoded ถ้ามีการระบุไว้ ไม่งั้นใช้ราคา Real-time
    if HARDCODED_SELL_PRICE is not None:
        price = HARDCODED_SELL_PRICE
        sys_logger.info(f"[FORCE SELL] 📌 ใช้ราคา Hardcoded: ฿{price:,.0f}")
    else:
        # ใช้ buy_price เป็น exit price (ราคาที่ร้านรับซื้อจากเรา = ราคาที่เราขาย)
        price = float(price_data.get("buy_price_thb", 0))

    sys_logger.info(f"[FORCE SELL] Action=SELL | Price=฿{price:,.0f}")
    sys_logger.info(f"[FORCE SELL] Reason: {REASON_FORCE_SELL}")

    # 1) ส่ง Trade Log
    if send_log:
        _send_trade_log(action="SELL", price=price, reason=REASON_FORCE_SELL)
    else:
        sys_logger.info("[FORCE SELL] ⏭️ ข้ามการส่ง Trade Log (Disabled)")

    # 2) ส่ง Discord
    if send_discord:
        _send_discord_notification(action="SELL", price=price, reason=REASON_FORCE_SELL)
    else:
        sys_logger.info("[FORCE SELL] ⏭️ ข้ามการส่ง Discord (Disabled)")

    # 3) บันทึก DB
    run_id = None
    if save_db:
        run_id = _persist_to_db(action="SELL", price=price, reason=REASON_FORCE_SELL)
    else:
        sys_logger.info("[FORCE SELL] ⏭️ ข้ามการบันทึก Database (Disabled)")

    result = {
        "action": "SELL",
        "price": price,
        "reason": REASON_FORCE_SELL,
        "provider": PROVIDER_TAG,
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(),
    }

    sys_logger.info(f"🔴 [FORCE SELL] เสร็จสิ้น — run_id={run_id}")
    return result


# ─────────────────────────────────────────────────────────────
# CLI entrypoint
# ─────────────────────────────────────────────────────────────

import argparse

def main() -> int:
    """
    CLI:
        python Src_V2/emergency_force.py buy --no-log
        python Src_V2/emergency_force.py sell --no-discord
    """
    parser = argparse.ArgumentParser(description="Force BUY / SELL (Emergency)")
    parser.add_argument("action", choices=["buy", "sell"], help="Action to perform")
    parser.add_argument("--no-log", action="store_true", help="Skip sending Trade Log (API)")
    parser.add_argument("--no-discord", action="store_true", help="Skip sending Discord notification")
    parser.add_argument("--no-db", action="store_true", help="Skip saving to Database")
    
    args = parser.parse_args()

    # กลับ logic: ถ้ามี flag --no-xxx แสดงว่าให้เป็น False
    send_log = not args.no_log
    send_discord = not args.no_discord
    save_db = not args.no_db

    if args.action == "buy":
        result = force_buy(send_log=send_log, send_discord=send_discord, save_db=save_db)
    else:
        result = force_sell(send_log=send_log, send_discord=send_discord, save_db=save_db)

    print("\n" + "=" * 50)
    print(f"✅ Force {result['action']} สำเร็จ!")
    
    # จัดการการแสดงผลราคาให้ยืดหยุ่น (รองรับทั้ง numeric และ string ที่อาจจะถูกแก้มา)
    price_val = result['price']
    if isinstance(price_val, (int, float)):
        print(f"   ราคา: ฿{price_val:,.0f}")
    else:
        print(f"   ราคา: ฿{price_val}")
        
    print(f"   เหตุผล: {result['reason']}")
    print(f"   ส่ง Trade Log: {'YES' if send_log else 'NO (Skipped)'}")
    print(f"   ส่ง Discord: {'YES' if send_discord else 'NO (Skipped)'}")
    print(f"   บันทึก DB: {'YES' if save_db else 'NO (Skipped)'} (ID: {result.get('run_id', '-')})")
    print(f"   เวลา: {result['timestamp']}")
    print("=" * 50)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
