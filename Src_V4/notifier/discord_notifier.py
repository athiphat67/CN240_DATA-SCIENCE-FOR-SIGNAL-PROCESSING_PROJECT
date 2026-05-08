# notifier/discord_notifier.py
import httpx
import logging
from typing import Optional
from config.settings import DISCORD_WEBHOOK_URL, DISCORD_MENTION_ID, DRY_RUN

logger = logging.getLogger("trading")

def send_discord(content: str) -> None:
    """Fire-and-forget webhook ไม่ block trading logic"""
    if not DISCORD_WEBHOOK_URL:
        return
        
    dry_prefix = "🧪 **[DRY RUN]** " if DRY_RUN else ""
    # ตัดข้อความถ้าเกิน 1900 ตัวอักษร (Discord limit 2000)
    safe_content = (dry_prefix + content)[:1900] + ("..." if len(dry_prefix + content) > 1900 else "")
    
    try:
        httpx.post(
            DISCORD_WEBHOOK_URL,
            json={"content": safe_content},
            timeout=10
        )
    except Exception as e:
        logger.warning(f"[Discord] Webhook failed: {e}")

def notify_buy_signal(gate_result: dict, rationale_payload: Optional[dict] = None) -> None:
    mention = f"<@{DISCORD_MENTION_ID}> " if DISCORD_MENTION_ID else ""
    atr     = gate_result.get("atr_48", 0) or 0
    ask     = gate_result.get("hsh_ask", 0) or 0
    bid     = gate_result.get("hsh_bid", 0) or 0
    
    tp_ref = ask + atr * 1.5
    sl_ref = ask - atr * 1.0
    
    msg = (
        f"{mention}\n"
        f"🟢 **BUY SIGNAL** — `{gate_result['bar_time']}`\n"
        f"```\n"
        f"Session     : {gate_result['session']}\n"
        f"Score       : {gate_result['ranker_score']:.4f}\n"
        f"HSH Ask     : {ask:,.2f} THB  ← ราคาซื้อ\n"
        f"HSH Bid     : {bid:,.2f} THB\n"
        f"XAU/USD     : {gate_result.get('xau_close', 0):.2f}\n"
        f"ATR(48)     : {atr:.2f} THB  ← ใช้ตั้ง TP/SL\n"
        f"TP แนะนำ    : {tp_ref:,.2f} (1.5× ATR)\n"
        f"SL แนะนำ    : {sl_ref:,.2f} (1.0× ATR)\n"
        f"```"
    )
    
    if rationale_payload and rationale_payload.get("rationale_text"):
        msg += f"\n📊 **Rationale:** {rationale_payload['rationale_text']}"
        
    send_discord(msg)

def notify_sell_signal(gate_result: dict, rationale_payload: Optional[dict] = None) -> None:
    mention = f"<@{DISCORD_MENTION_ID}> " if DISCORD_MENTION_ID else ""
    bid     = gate_result.get("hsh_bid", 0) or 0
    
    msg = (
        f"{mention}\n"
        f"🔴 **SELL SIGNAL** — `{gate_result['bar_time']}`\n"
        f"```\n"
        f"Session     : {gate_result['session']}\n"
        f"Score       : {gate_result['ranker_score']:.4f} (ต่ำกว่า threshold)\n"
        f"HSH Bid     : {bid:,.2f} THB  ← ราคาขาย\n"
        f"XAU/USD     : {gate_result.get('xau_close', 0):.2f}\n"
        f"```"
    )
    
    if rationale_payload and rationale_payload.get("rationale_text"):
        msg += f"\n📉 **Rationale:** {rationale_payload['rationale_text']}"
        
    send_discord(msg)

def notify_heartbeat(state: str, last_bar: str, score: float) -> None:
    msg = (
        f"💓 **Heartbeat** — บอททำงานปกติ\n"
        f"State: `{state}` · Last bar: `{last_bar}` · Score: `{score:.4f}`"
    )
    send_discord(msg)

def notify_error(context: str, error: str) -> None:
    msg = f"⚠️ **ERROR** [{context}]\n```{str(error)[:1500]}```"
    send_discord(msg)

# 🆕 ─── Dynamic TP Notifications ──────────────────────────────────────────────
def notify_dynamic_tp(trigger: str, price: float, trail: float, score: float, atr: float) -> None:
    """ส่งแจ้งเตือน Dynamic TP / Trailing Stop ตาม trigger type"""
    mention = f"<@{DISCORD_MENTION_ID}> " if DISCORD_MENTION_ID else ""
    
    messages = {
        "TP_UPDATED": f"📈 TP Adjusted → `{price:,.2f}` THB\nTrail Level: `{trail:,.2f}`",
        "BREAKEVEN_LOCK": f"🔒 Breakeven Locked\nTrail fixed at `{trail:,.2f}`. Downside risk removed.",
        "TRAIL_HIT": f"🔴 {mention}**DYNAMIC EXIT TRIGGERED**\nPrice hit trail at `{trail:,.2f}`. Consider closing now.\nCurrent Score: `{score:.4f}`",
        "SCORE_FADE": f"⚠️ Momentum Fading\nScore dropped significantly (`{score:.4f}`). Trail at `{trail:,.2f}`. Consider scaling out."
    }
    
    send_discord(f"🤖 **HSH Dynamic TP**\n{messages[trigger]}\nATR(48): `{atr:,.2f}`")