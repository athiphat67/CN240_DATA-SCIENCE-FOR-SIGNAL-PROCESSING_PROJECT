class DirectiveBuilder:
    @staticmethod
    def build_session_directive(portfolio, quota_ctx: dict) -> str:
        """สร้างข้อความ Prompt บังคับพฤติกรรม LLM ให้สอดคล้องกับเป้าหมายรายวัน (6 ไม้)"""
        
        session_id  = quota_ctx.get("session_id") or "DEAD"
        session_end = quota_ctx.get("session_end_time", "")
        
        # 🌟 [NEW] ถ้าตลาดปิด ไม่ต้องไปขู่ให้มันเทรด
        if session_id == "DEAD":
            return f"Session DEAD | Market is closed. You MUST output HOLD. Do NOT trade."
        
        # 🌟 [FIX] ดึงยอดเทรดรายวันจาก Portfolio โดยตรง จะได้ตรงกันเป๊ะ!
        trades_today = getattr(portfolio, "trades_today", 0)
        daily_target = 6
        remaining = max(0, daily_target - trades_today)

        # บรรทัดสรุปข้อมูลเวลา
        quota_line = f"Session {session_id} | Session ends: {session_end} | Daily Progress: {trades_today}/{daily_target}"
        
        if remaining > 0:
            # เปลี่ยนจาก BE AGGRESSIVE เป็น Opportunity-based
            quota_line += f"\nMANDATE: You have {remaining} trades to complete today. LOOK for entry signals (RSI/MACD). Do not spam trades."
        else:
            quota_line += f"\nMANDATE: Daily quota met. Trade only high-probability setups."
            
        # สร้างคำสั่งตามสถานะถือครองทอง
        if portfolio.gold_grams <= 1e-4:
            # กรณีไม่มีทอง (รอจังหวะซื้อ)
            directive = (
                f"{quota_line}\n"
                f"STATE: No gold held. You MUST find a BUY entry. "
                f"Do NOT SELL (no position to sell)."
            )
        else:
            # กรณีมีทอง (รอจังหวะขาย)
            tp_price = portfolio._open_trade.take_profit_price if getattr(portfolio, "_open_trade", None) else 0.0
            sl_price = portfolio._open_trade.stop_loss_price   if getattr(portfolio, "_open_trade", None) else 0.0
            directive = (
                f"{quota_line}\n"
                f"STATE: Holding gold. BUY is FORBIDDEN. Focus on SELL signal. "
                f"TP=฿{tp_price:,.0f} | SL=฿{sl_price:,.0f}. "
                f"If momentum drops, SELL immediately to free up cash for the next trade."
            )
            
        return directive