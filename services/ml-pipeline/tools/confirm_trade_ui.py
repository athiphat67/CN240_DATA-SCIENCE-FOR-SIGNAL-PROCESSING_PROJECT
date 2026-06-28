# tools/confirm_trade_ui.py
"""
Manual Trade Confirmation UI
เปิดเว็บ → กด BUY / SELL → ระบบอัปเดต State ใน DB ให้อัตโนมัติ

รันด้วย:
    python tools/confirm_trade_ui.py
"""
import os
import sys
import logging

# ── Path Setup ────────────────────────────────────────────────────────────────
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir    = os.path.dirname(current_dir)
sys.path.insert(0, root_dir)

# ── Imports ───────────────────────────────────────────────────────────────────
import gradio as gr
from datetime import datetime, timezone, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from config.settings import STATE_EMPTY, STATE_HOLDING, SUPABASE_URL, SUPABASE_KEY
from core.state_manager import get_current_state, set_state
from db.supabase_writer import (
    get_latest_pending_buy_signal,
    get_latest_pending_sell_signal,
    mark_signal_execution,
    open_trade_from_signal,
    close_open_trade,
    get_signal_by_id,
    insert_signal,
)
from notifier.trade_log_api import send_trade_log
from notifier.discord_notifier import notify_buy_confirmed, notify_sell_confirmed
from supabase import create_client

# ── Constants ─────────────────────────────────────────────────────────────────
TZ_BKK = timezone(timedelta(hours=7))

logger = logging.getLogger("trading")

def _get_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)


# ─────────────────────────────────────────────────────────────────────────────
# Data Fetchers
# ─────────────────────────────────────────────────────────────────────────────

def _format_pending(s: dict | None, signal_type: str) -> tuple:
    """Format pending signal dict into 7 display fields.

    Returns: (signal_id, sig_label, bar_time, ask, bid, reason/status, rationale)
    """
    if not s:
        return ("-", f"ไม่พบ PENDING {signal_type}", "-", "-", "-", "-", "-")

    signal_id = s.get("id", "-")
    bar_time  = s.get("bar_time", "-")
    sig_type  = s.get("signal_type", signal_type)
    score     = float(s.get("ranker_score", 0) or 0)
    reason    = s.get("execution_status") or "PENDING_CONFIRM"
    ask       = s.get("hsh_ask_price")
    bid       = s.get("hsh_bid_price")
    session   = s.get("session", "-")
    rationale = s.get("rationale_text", "-")
    reject    = s.get("reject_reason")

    label_parts = [f"⏳ PENDING {sig_type}", f"score={score:.4f}", session]
    if reject and reject.startswith("FORCED_BY_"):
        label_parts.append(f"🤖 {reject.replace('FORCED_BY_', '')}")
    sig_label = " | ".join(label_parts)

    ask_str = f"{float(ask):,.2f} THB" if ask not in (None, "-") else "-"
    bid_str = f"{float(bid):,.2f} THB" if bid not in (None, "-") else "-"

    return (
        str(signal_id),
        sig_label,
        str(bar_time),
        ask_str,
        bid_str,
        str(reason),
        str(rationale),
    )


def fetch_dashboard():
    """ดึงข้อมูล State + Pending BUY + Pending SELL"""
    try:
        now_str = datetime.now(TZ_BKK).strftime("%H:%M:%S")

        current_state = get_current_state()
        state_icon = "🟢 HOLDING" if current_state == STATE_HOLDING else "⚪ EMPTY"

        buy_fields  = _format_pending(get_latest_pending_buy_signal(), "BUY")
        sell_fields = _format_pending(get_latest_pending_sell_signal(), "SELL")

        return (
            state_icon, current_state,
            *buy_fields,
            *sell_fields,
            f"✅ โหลดสำเร็จ | {now_str}",
        )

    except Exception as e:
        err = ("-", f"❌ {e}", "-", "-", "-", "-", "-")
        return ("❌ Error", "UNKNOWN", *err, *err, f"❌ {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Trade Actions
# ─────────────────────────────────────────────────────────────────────────────

def _create_manual_buy_signal(price: float) -> dict:
    """
    สร้าง manual BUY signal row ใน v3_signals
    ใช้เมื่อไม่มี PENDING signal จาก model — เช่น ซื้อเองนอกสัญญาณ
    คืน signal dict ที่ insert แล้ว หรือ raise Exception ถ้าล้มเหลว
    """
    now_str = datetime.now(TZ_BKK).strftime("%Y%m%d_%H%M%S")
    signal_id = f"manual_buy_{now_str}"

    manual_buy_record = {
        "id": signal_id,
        "bar_time": datetime.now(TZ_BKK).isoformat(),
        "session": "Manual",
        "signal_type": "BUY",
        "ranker_score": 0.0,
        "state_before": STATE_EMPTY,
        "hsh_ask_price": price,
        "hsh_bid_price": None,
        "xau_price": None,
        "atr_at_signal": None,
        "passed": True,
        "reject_reason": None,
        "dry_run": False,
        "features_snap": {},
        "rationale_text": "Manual BUY — entered outside model signal",
        "top_shap_features": {},
        "execution_status": "CONFIRMED",
        "confirmed_price": price,
        "confirmed_at": datetime.now(TZ_BKK).isoformat(),
        "created_at": datetime.now(TZ_BKK).isoformat(),
    }

    ok = insert_signal(manual_buy_record)
    if not ok:
        raise RuntimeError(f"Failed to insert manual BUY signal {signal_id}")

    return manual_buy_record


def confirm_buy(price_str: str, signal_id: str):
    """
    ยืนยัน BUY → State: HOLDING
    รองรับ 2 กรณี:
      A) มี PENDING signal จาก model  → ใช้ signal นั้น (เดิม)
      B) ไม่มี signal / ซื้อเองมือ    → สร้าง manual signal แล้วเปิด trade
    """
    try:
        if not price_str.strip():
            return "❌ กรุณากรอกราคาที่ Execute จริง"

        price = float(price_str.replace(",", ""))
        if price <= 0:
            return "❌ ราคาต้องมากกว่า 0"

        current = get_current_state()
        if current == STATE_HOLDING:
            # ── Guard: only block if a real OPEN trade exists ──────────────
            # If state=HOLDING but NO trade in v3_active_trades, the state is
            # desynchronised. Allow the confirm to proceed and create the trade.
            from db.supabase_writer import get_open_trade as _get_open
            if _get_open():
                return "⚠️ State เป็น HOLDING อยู่แล้ว และมี OPEN trade อยู่ — ไม่ต้องทำอะไร"
            logger.warning(
                "[UI] State=HOLDING but no OPEN trade found — "
                "proceeding to create missing trade (desync recovery)."
            )

        is_manual = False

        # ── หา signal ที่จะใช้ ────────────────────────────────────────────
        if not signal_id or signal_id == "-":
            s = get_latest_pending_buy_signal()
            if not s:
                # ไม่มี pending signal → สร้าง manual signal แทน
                s = _create_manual_buy_signal(price)
                is_manual = True
        else:
            s = get_signal_by_id(signal_id)
            if not s:
                return f"❌ ไม่พบ Signal ID: {signal_id}"

        # ── Validate (เฉพาะ signal จาก model เท่านั้น ไม่ validate manual) ──
        if not is_manual:
            if s.get("signal_type") != "BUY":
                return "❌ This signal is not a BUY signal."
            if not s.get("passed"):
                return "❌ This BUY signal did not pass the gate."
            execution_status = s.get("execution_status")
            if execution_status not in ("PENDING_CONFIRM", "SIGNAL_ONLY", None):
                return f"❌ This signal is not pending anymore. Current status: {execution_status}"
            if s.get("state_before") != STATE_EMPTY:
                return f"❌ Invalid signal state_before: {s.get('state_before')}. Expected EMPTY."

        # ── เปิด active trade ──────────────────────────────────────────────
        ok_trade, err_msg = open_trade_from_signal(s, price)
        if not ok_trade:
            return f"❌ Failed to open active trade. DB Error: {err_msg}"

        # ── mark signal (ถ้าไม่ใช่ manual ที่ CONFIRMED ไปแล้ว) ───────────
        if not is_manual:
            ok_mark = mark_signal_execution(s["id"], "CONFIRMED", price)
            if not ok_mark:
                logger.warning(
                    f"[UI] mark_signal_execution failed but trade is OPEN — "
                    f"forcing state to HOLDING | signal_id={s['id']}"
                )
                set_state(STATE_HOLDING)
                notify_buy_confirmed(s["id"], price, note="⚠️ mark_signal failed — state forced to HOLDING")
                now_str = datetime.now(TZ_BKK).strftime("%Y-%m-%d %H:%M:%S")
                return (
                    f"⚠️ Trade opened @ {price:,.2f} THB แต่ mark signal ไม่สำเร็จ | "
                    f"State → HOLDING แล้ว | กรุณาตรวจสอบ v3_signals ใน Supabase | {now_str}"
                )

        set_state(STATE_HOLDING)
        notify_buy_confirmed(s["id"], price)

        now_str = datetime.now(TZ_BKK).strftime("%Y-%m-%d %H:%M:%S")
        mode_label = "Manual (no signal)" if is_manual else "Signal Confirmed"
        return f"✅ BUY Confirmed! [{mode_label}] | ราคา {price:,.2f} THB | State → HOLDING | {now_str}"

    except ValueError:
        return "❌ ราคาไม่ถูกต้อง — กรอกตัวเลขเท่านั้น"
    except Exception as e:
        return f"❌ Error: {e}"


def _create_manual_sell_signal(price: float) -> dict:
    """สร้าง manual SELL signal row ใน v3_signals (ใช้เมื่อไม่มี pending SELL จาก model)."""
    now_str = datetime.now(TZ_BKK).strftime("%Y%m%d_%H%M%S")
    signal_id = f"manual_sell_{now_str}"

    manual_sell_record = {
        "id": signal_id,
        "bar_time": datetime.now(TZ_BKK).isoformat(),
        "session": "Manual",
        "signal_type": "SELL",
        "ranker_score": 0.0,
        "state_before": STATE_HOLDING,
        "hsh_ask_price": None,
        "hsh_bid_price": price,
        "xau_price": None,
        "atr_at_signal": None,
        "passed": True,
        "reject_reason": None,
        "dry_run": False,
        "features_snap": {},
        "rationale_text": "Manual SELL — exited outside model signal",
        "top_shap_features": {},
        "execution_status": "CONFIRMED",
        "confirmed_price": price,
        "confirmed_at": datetime.now(TZ_BKK).isoformat(),
        "created_at": datetime.now(TZ_BKK).isoformat(),
    }

    ok = insert_signal(manual_sell_record)
    if not ok:
        raise RuntimeError(f"Failed to insert manual SELL signal {signal_id}")

    return manual_sell_record


def confirm_sell(price_str: str, signal_id: str):
    """
    ยืนยัน SELL → State: EMPTY
    รองรับ 2 กรณี:
      A) มี PENDING SELL signal จาก model (gate SELL หรือ forced exit) → ใช้ signal นั้น
      B) ไม่มี signal / ขายเองมือ → สร้าง manual signal แล้วปิด trade
    """
    try:
        if not price_str.strip():
            return "❌ กรุณากรอกราคาที่ Execute จริง"

        price = float(price_str.replace(",", ""))
        if price <= 0:
            return "❌ ราคาต้องมากกว่า 0"

        current = get_current_state()
        if current == STATE_EMPTY:
            return "⚠️ State เป็น EMPTY อยู่แล้ว — ไม่มี Position ที่จะปิด"

        is_manual = False

        # ── หา signal ที่จะใช้ ────────────────────────────────────────────
        if not signal_id or signal_id == "-":
            s = get_latest_pending_sell_signal()
            if not s:
                # ไม่มี pending SELL signal → สร้าง manual signal แทน
                s = _create_manual_sell_signal(price)
                is_manual = True
        else:
            s = get_signal_by_id(signal_id)
            if not s:
                return f"❌ ไม่พบ Signal ID: {signal_id}"

        # ── Validate (เฉพาะ signal จาก model เท่านั้น ไม่ validate manual) ──
        if not is_manual:
            if s.get("signal_type") != "SELL":
                return "❌ This signal is not a SELL signal."
            if not s.get("passed"):
                return "❌ This SELL signal did not pass the gate."
            execution_status = s.get("execution_status")
            valid_statuses = ("PENDING_CONFIRM", "PENDING_AUTO_EXIT", "SIGNAL_ONLY", None)
            if execution_status not in valid_statuses:
                return f"❌ This signal is not pending anymore. Current status: {execution_status}"

        # ── ปิด active trade ──────────────────────────────────────────────
        reject_reason = (s.get("reject_reason") or "").upper()
        if is_manual:
            close_reason = "MANUAL_SELL_CONFIRMED"
        elif reject_reason.startswith("FORCED_BY_"):
            # Path A: trailing-stop / SL — preserve original trigger
            close_reason = reject_reason.replace("FORCED_BY_", "FORCED_") + "_CONFIRMED"
        else:
            close_reason = "MODEL_SELL_CONFIRMED"

        ok_close = close_open_trade(
            exit_bid=price,
            exit_signal_id=s["id"],
            reason=close_reason,
        )
        if not ok_close:
            return "❌ Failed to close active trade. State was NOT changed."

        # ── mark signal (ถ้าไม่ใช่ manual ที่ CONFIRMED ไปแล้ว) ───────────
        if not is_manual:
            ok_mark = mark_signal_execution(s["id"], "CONFIRMED", price)
            if not ok_mark:
                logger.warning(
                    f"[UI] mark_signal_execution failed but trade is CLOSED — "
                    f"forcing state to EMPTY | signal_id={s['id']}"
                )

        set_state(STATE_EMPTY)
        send_trade_log("SELL", price, close_reason)
        notify_sell_confirmed(price, close_reason, signal_id=s["id"])

        now_str = datetime.now(TZ_BKK).strftime("%Y-%m-%d %H:%M:%S")
        mode_label = "Manual (no signal)" if is_manual else "Signal Confirmed"
        return f"✅ SELL Confirmed! [{mode_label}] | ราคา {price:,.2f} THB | State → EMPTY | {now_str}"

    except ValueError:
        return "❌ ราคาไม่ถูกต้อง — กรอกตัวเลขเท่านั้น"
    except Exception as e:
        return f"❌ Error: {e}"


def force_reset_state(target: str):
    """Force reset State (กรณีฉุกเฉิน)"""
    try:
        new_state = STATE_HOLDING if target == "HOLDING" else STATE_EMPTY
        
        # ── Solution B: Auto-cleanup on Force Reset ─────────────────
        if new_state == STATE_EMPTY:
            from db.supabase_writer import get_open_trade, get_supabase_client
            from config.settings import ACTIVE_TRADES_TABLE
            
            existing_trade = get_open_trade()
            if existing_trade:
                logger.info(f"[UI] Force Reset to EMPTY: Cancelling orphaned trade {existing_trade['id']}")
                get_supabase_client().table(ACTIVE_TRADES_TABLE).update({
                    "status": "CANCELLED",
                    "exit_reason": "FORCE_RESET_TO_EMPTY",
                    "exit_note": "Cancelled via UI Force Reset"
                }).eq("id", existing_trade["id"]).execute()
                
        set_state(new_state)
        now_str = datetime.now(TZ_BKK).strftime("%H:%M:%S")
        return f"✅ Force Reset → {new_state} | {now_str}"
    except Exception as e:
        return f"❌ Error: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# UI Layout
# ─────────────────────────────────────────────────────────────────────────────

with gr.Blocks(theme=gr.themes.Soft(), title="Aom NOW — Trade Confirm") as demo:

    gr.Markdown("# ⚡ Aom NOW — Manual Trade Confirmation")
    gr.Markdown("ดูสัญญาณล่าสุด → Execute ที่ HSH → กดยืนยันที่นี่เพื่ออัปเดต State")

    # ── Section 1: Dashboard ─────────────────────────────────────────────────
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 🔵 System State")
            state_disp   = gr.Textbox(label="State ปัจจุบัน", interactive=False)
            state_raw    = gr.Textbox(label="Raw State", interactive=False, visible=False)
            btn_refresh  = gr.Button("🔄 Refresh", variant="secondary")
            status_disp  = gr.Textbox(label="Last Refresh", interactive=False)

    with gr.Row():
        with gr.Column():
            gr.Markdown("### 📡 Pending BUY ล่าสุด")
            buy_signal_id_disp  = gr.Textbox(label="Signal ID", interactive=False)
            buy_sig_label_disp  = gr.Textbox(label="Signal", interactive=False)
            buy_bar_time_disp   = gr.Textbox(label="Bar Time", interactive=False)
            with gr.Row():
                buy_ask_disp = gr.Textbox(label="Ask Price", interactive=False)
                buy_bid_disp = gr.Textbox(label="Bid Price", interactive=False)
            buy_reason_disp     = gr.Textbox(label="Status", interactive=False)
            buy_rationale_disp  = gr.Textbox(label="Rationale", interactive=False, lines=3)

        with gr.Column():
            gr.Markdown("### 📡 Pending SELL ล่าสุด")
            sell_signal_id_disp  = gr.Textbox(label="Signal ID", interactive=False)
            sell_sig_label_disp  = gr.Textbox(label="Signal", interactive=False)
            sell_bar_time_disp   = gr.Textbox(label="Bar Time", interactive=False)
            with gr.Row():
                sell_ask_disp = gr.Textbox(label="Ask Price", interactive=False)
                sell_bid_disp = gr.Textbox(label="Bid Price", interactive=False)
            sell_reason_disp     = gr.Textbox(label="Status", interactive=False)
            sell_rationale_disp  = gr.Textbox(label="Rationale", interactive=False, lines=3)

    gr.Markdown("---")

    # ── Section 2: Confirm Trade ─────────────────────────────────────────────
    gr.Markdown("### 💰 ยืนยันการ Execute")
    gr.Markdown("กรอกราคาที่คุณ Execute จริงที่ HSH แล้วกดปุ่ม")

    with gr.Row():
        with gr.Column():
            gr.Markdown("#### 🟢 BUY")
            buy_price_input = gr.Textbox(
                label="ราคา Ask ที่ Execute (THB)",
                placeholder="เช่น 71930"
            )
            buy_signal_id_input = gr.Textbox(
                label="Signal ID (เว้นว่างเพื่อใช้ PENDING ล่าสุด)",
                placeholder="sig_..."
            )
            btn_buy    = gr.Button("✅ Confirm BUY → State: HOLDING", variant="primary")
            buy_status = gr.Textbox(label="Status", interactive=False)

        with gr.Column():
            gr.Markdown("#### 🔴 SELL")
            sell_price_input = gr.Textbox(
                label="ราคา Bid ที่ Execute (THB)",
                placeholder="เช่น 71840"
            )
            sell_signal_id_input = gr.Textbox(
                label="Signal ID (เว้นว่างเพื่อใช้ PENDING ล่าสุด)",
                placeholder="sig_... หรือ tp_..."
            )
            btn_sell    = gr.Button("✅ Confirm SELL → State: EMPTY", variant="stop")
            sell_status = gr.Textbox(label="Status", interactive=False)

    gr.Markdown("---")

    # ── Section 3: Force Reset ───────────────────────────────────────────────
    with gr.Accordion("⚠️ Force Reset State (กรณีฉุกเฉิน)", open=False):
        gr.Markdown("ใช้เมื่อ State ใน DB ไม่ตรงกับความเป็นจริง เช่น หลัง Manual trade นอกระบบ")
        with gr.Row():
            force_target = gr.Radio(
                choices=["EMPTY", "HOLDING"],
                label="Reset ไปที่ State",
                value="EMPTY"
            )
            btn_force  = gr.Button("🔧 Force Reset", variant="huggingface")
            force_status = gr.Textbox(label="Status", interactive=False)

    # ── All Outputs List ──────────────────────────────────────────────────────
    _dashboard_outputs = [
        state_disp, state_raw,
        # Pending BUY (7 fields)
        buy_signal_id_disp,
        buy_sig_label_disp, buy_bar_time_disp,
        buy_ask_disp, buy_bid_disp,
        buy_reason_disp, buy_rationale_disp,
        # Pending SELL (7 fields)
        sell_signal_id_disp,
        sell_sig_label_disp, sell_bar_time_disp,
        sell_ask_disp, sell_bid_disp,
        sell_reason_disp, sell_rationale_disp,
        status_disp,
    ]

    # ── Event Bindings ────────────────────────────────────────────────────────
    btn_refresh.click(fn=fetch_dashboard, inputs=[], outputs=_dashboard_outputs)

    btn_buy.click(
        fn=confirm_buy,
        inputs=[buy_price_input, buy_signal_id_input],
        outputs=[buy_status],
    ).then(fn=fetch_dashboard, inputs=[], outputs=_dashboard_outputs)

    btn_sell.click(
        fn=confirm_sell,
        inputs=[sell_price_input, sell_signal_id_input],
        outputs=[sell_status],
    ).then(fn=fetch_dashboard, inputs=[], outputs=_dashboard_outputs)

    btn_force.click(
        fn=force_reset_state,
        inputs=[force_target],
        outputs=[force_status],
    ).then(fn=fetch_dashboard, inputs=[], outputs=_dashboard_outputs)

    # Auto-load ตอนเปิดหน้า
    demo.load(fn=fetch_dashboard, inputs=[], outputs=_dashboard_outputs)


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    APP_USER = os.environ.get("APP_USER", "admin")
    APP_PASS = os.environ.get("APP_PASS", "admin123")
    port     = int(os.environ.get("PORT", 7861))  # port ต่างจาก app.py (7860)

    demo.launch(
        server_name="0.0.0.0",
        server_port=port,
        auth=(APP_USER, APP_PASS),
    )