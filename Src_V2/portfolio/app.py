import gradio as gr
import os
import sys

# --- 1. บังคับให้ Python รู้จักโฟลเดอร์หลัก (Root Directory) ---
current_dir = os.path.dirname(os.path.abspath(__file__)) # ตำแหน่งโฟลเดอร์ portfolio/
root_dir = os.path.dirname(current_dir)                  # ถอยออกมา 1 ขั้น (โฟลเดอร์หลัก)
sys.path.append(root_dir)                                # เพิ่มเข้าไประบบของ Python

# --- 2. ตอนนี้จะสามารถ Import ได้แล้ว! ---
# โครงสร้างคือ: โฟลเดอร์ database -> ไฟล์ database.py -> คลาส RunDatabase
from database.database import RunDatabase 

from datetime import datetime, timezone, timedelta

# โหลด .env สำหรับการรันบนเครื่อง Local
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ตั้งค่าโซนเวลาไทย (UTC+7)
tz_th = timezone(timedelta(hours=7))

def fetch_latest_portfolio():
    """ดึงข้อมูลพอร์ตล่าสุดมาแสดงผล"""
    try:
        db = RunDatabase()
        data = db.get_portfolio()
        
        return (
            f"{data.get('cash_balance', 0.0):,.2f}",
            f"{data.get('gold_grams', 0.0):,.4f}",
            f"{data.get('cost_basis_thb', 0.0):,.2f}",
            f"{data.get('unrealized_pnl', 0.0):,.2f}",
            str(data.get("trades_today", 0)),
            f"✅ โหลดข้อมูลล่าสุดสำเร็จ อัพเดตเมื่อ: {data.get('updated_at')}"
        )
    except Exception as e:
        return ("0.00", "0.0000", "0.00", "0.00", "0", f"❌ Error: {str(e)}")

def process_manual_trade(action, grams_str, amount_str):
    """รับค่าแค่ ซื้อ/ขาย, น้ำหนัก, และจำนวนเงิน แล้วให้ระบบจัดการที่เหลือ"""
    try:
        grams = float(grams_str)
        amount_thb = float(amount_str)
        
        if grams <= 0 or amount_thb <= 0:
            return "❌ กรุณากรอกตัวเลขให้มากกว่า 0"
            
        # คำนวณราคาต่อกรัม (เพราะ DB เก็บเป็น THB/gram)
        price_per_gram = amount_thb / grams
        
        db = RunDatabase()
        portfolio = db.get_portfolio()
        
        cash_before = float(portfolio.get("cash_balance", 0.0))
        gold_before = float(portfolio.get("gold_grams", 0.0))
        cost_basis_before = float(portfolio.get("cost_basis_thb", 0.0))
        trades_today = int(portfolio.get("trades_today", 0))
        
        now_str = datetime.now(tz_th).strftime("%Y-%m-%d %H:%M:%S")
        session_name = "manual_ui" # กำหนด session สำหรับการคีย์มือ
        
        if action == "BUY":
            # คำนวณพอร์ตหลังซื้อ
            cash_after = cash_before - amount_thb
            gold_after = gold_before + grams
            # คำนวณต้นทุนเฉลี่ยใหม่: (มูลค่าทุนเดิม + เงินที่ซื้อใหม่) / น้ำหนักทองรวม
            new_cost_basis = ((gold_before * cost_basis_before) + amount_thb) / gold_after if gold_after > 0 else 0.0
            
            # 1. บันทึก Trade Log
            db.save_trade(run_id=None, trade={
                "action": "BUY",
                "price_thb": price_per_gram,
                "gold_grams": grams,
                "amount_thb": amount_thb,
                "cash_before": cash_before,
                "cash_after": cash_after,
                "gold_before": gold_before,
                "gold_after": gold_after,
                "cost_basis_thb": cost_basis_before,
                "pnl_thb": None,
                "pnl_pct": None,
                "note": "Manual Entry via UI"
            })
            
            # 2. อัปเดต Portfolio
            db.save_portfolio({
                "cash_balance": cash_after,
                "gold_grams": gold_after,
                "cost_basis_thb": new_cost_basis,
                "current_value_thb": gold_after * price_per_gram,
                "unrealized_pnl": 0.0,
                "trades_today": trades_today + 1,
                "position_opened_session": session_name
            })
            
            # 3. อัปเดต Session Quota
            db.mark_session_buy(session_name)
            
            return f"✅ บันทึกการซื้อสำเร็จ! (ได้ทอง {grams}g จ่ายเงิน {amount_thb} บาท)"
            
        elif action == "SELL":
            if grams > gold_before:
                return f"❌ ทองไม่พอขาย! (คุณมี {gold_before}g แต่พยายามขาย {grams}g)"
                
            # คำนวณพอร์ตหลังขาย
            cash_after = cash_before + amount_thb
            gold_after = gold_before - grams
            new_cost_basis = cost_basis_before if gold_after > 0 else 0.0
            
            # คำนวณกำไร/ขาดทุน (PnL) = (ราคาขายต่อกรัม - ต้นทุนต่อกรัม) * จำนวนกรัมที่ขาย
            pnl_thb = (price_per_gram - cost_basis_before) * grams
            pnl_pct = (pnl_thb / (cost_basis_before * grams)) if cost_basis_before > 0 else 0.0
            
            # 1. บันทึก Trade Log
            db.save_trade(run_id=None, trade={
                "action": "SELL",
                "price_thb": price_per_gram,
                "gold_grams": grams,
                "amount_thb": amount_thb,
                "cash_before": cash_before,
                "cash_after": cash_after,
                "gold_before": gold_before,
                "gold_after": gold_after,
                "cost_basis_thb": cost_basis_before,
                "pnl_thb": pnl_thb,
                "pnl_pct": pnl_pct,
                "note": "Manual Entry via UI"
            })
            
            # 2. อัปเดต Portfolio
            db.save_portfolio({
                "cash_balance": cash_after,
                "gold_grams": gold_after,
                "cost_basis_thb": new_cost_basis,
                "current_value_thb": gold_after * price_per_gram,
                "unrealized_pnl": 0.0,
                "trades_today": trades_today + 1,
                "position_opened_session": None
            })
            
            # 3. อัปเดต Session Quota
            db.mark_session_sell(session_name)
            
            pnl_text = f"กำไร {pnl_thb:,.2f} บาท" if pnl_thb >= 0 else f"ขาดทุน {abs(pnl_thb):,.2f} บาท"
            return f"✅ บันทึกการขายสำเร็จ! (ขายทอง {grams}g ได้เงิน {amount_thb} บาท | {pnl_text})"

    except ValueError:
        return "❌ ข้อมูลไม่ถูกต้อง โปรดตรวจสอบตัวเลขให้ครบถ้วน"
    except Exception as e:
        return f"❌ Error: {str(e)}"

# สร้างหน้าตา UI ด้วย Gradio
with gr.Blocks(theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 📈 Gold Trading Logger")
    gr.Markdown("ระบบบันทึกการซื้อขายทองคำ (ระบบจะคำนวณต้นทุนและกำไรให้อัตโนมัติ)")
    
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 💼 สถานะพอร์ตปัจจุบัน")
            btn_fetch = gr.Button("🔄 โหลดข้อมูลพอร์ตล่าสุด")
            cash_disp = gr.Textbox(label="เงินสดคงเหลือ (THB)", interactive=False)
            gold_disp = gr.Textbox(label="ทองคำที่มี (Grams)", interactive=False)
            cost_disp = gr.Textbox(label="ต้นทุนเฉลี่ย (THB/Gram)", interactive=False)
            pnl_disp = gr.Textbox(label="Unrealized PnL (THB)", interactive=False)
            trades_disp = gr.Textbox(label="จำนวนการเทรดวันนี้", interactive=False)
            
        with gr.Column(scale=2):
            gr.Markdown("### 📝 บันทึกรายการซื้อขายใหม่ (อิงตามแอป)")
            action_input = gr.Radio(choices=["BUY", "SELL"], label="ประเภทรายการ (สั่งซื้อ/ขาย)", value="BUY")
            
            with gr.Row():
                grams_input = gr.Textbox(label="น้ำหนักทอง (กรัม) เช่น 0.2134", placeholder="0.0000")
                amount_input = gr.Textbox(label="ราคารวม (บาท) เช่น 1000", placeholder="0.00")
                
            btn_insert = gr.Button("💾 บันทึกรายการ", variant="primary")
            status_text = gr.Textbox(label="Status / ข้อความแจ้งเตือน", interactive=False)

    # ผูกฟังก์ชันปุ่มโหลดข้อมูล
    btn_fetch.click(
        fn=fetch_latest_portfolio,
        inputs=[],
        outputs=[cash_disp, gold_disp, cost_disp, pnl_disp, trades_disp, status_text]
    )
    
    # ผูกฟังก์ชันปุ่มบันทึกรายการ
    btn_insert.click(
        fn=process_manual_trade,
        inputs=[action_input, grams_input, amount_input],
        outputs=[status_text]
    ).then( # บันทึกเสร็จให้โหลดพอร์ตใหม่มาโชว์อัตโนมัติ
        fn=fetch_latest_portfolio,
        inputs=[],
        outputs=[cash_disp, gold_disp, cost_disp, pnl_disp, trades_disp, status_text]
    )

# รัน Server
if __name__ == "__main__":
    APP_USER = os.environ.get("APP_USER", "admin")
    APP_PASS = os.environ.get("APP_PASS", "admin123")
    
    port = int(os.environ.get("PORT", 7860))
    demo.launch(
        server_name="0.0.0.0", 
        server_port=port,
        auth=(APP_USER, APP_PASS) 
    )