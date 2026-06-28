import pandas as pd

class MarketStateBuilder:
    """
    คลาสกลางสำหรับประกอบร่าง JSON Market State 
    รองรับทั้งโหมด Live (Orchestrator) และโหมด Backtest (run_main_backtest.py)
    """
    
    @staticmethod
    def build(
        row: pd.Series, 
        past_5_rows: pd.DataFrame, 
        current_time: str, 
        data_mode: str = "csv_backtest",
        portfolio_dict: dict = None,
        news_data: dict = None,
        interval: str = "1h"
    ) -> dict:
    
        
        # 1. จัดการข้อมูลราคาย้อนหลัง 5 แท่ง
        recent_price_action = []
        if past_5_rows is not None and not past_5_rows.empty:
            for _, r in past_5_rows.iterrows():
                recent_price_action.append({
                    "datetime": str(r.get("timestamp", "")),
                    "open":  float(r.get("Mock_HSH_Sell_Open",  r.get("open",  0))),
                    "high":  float(r.get("Mock_HSH_Sell_High",  r.get("high",  0))),
                    "low":   float(r.get("Mock_HSH_Sell_Low",   r.get("low",   0))),
                    "close": float(r.get("Mock_HSH_Sell_Close", r.get("close", 0))),
                })

        # 2. คำนวณ/ดึง Signal ถ้าใน CSV ไม่มีมาให้สำเร็จรูป (Backtest Fallback)
        rsi_val = float(row.get("rsi", 50))
        rsi_sig = str(row.get("rsi_signal", "overbought" if rsi_val > 70 else "oversold" if rsi_val < 30 else "neutral"))
        
        macd_hist = float(row.get("macd_hist", row.get("macd_histogram", 0)))
        macd_sig = "bullish" if macd_hist > 0 else "bearish" if macd_hist < 0 else "neutral"

        ema20 = float(row.get("ema_20", 0))
        ema50 = float(row.get("ema_50", 0))
        trend_sig = str(row.get("trend_signal", "uptrend" if ema20 > ema50 else "downtrend" if ema20 < ema50 else "neutral"))

        # 3. ประกอบร่าง JSON
        state = {
            "meta": {
                "generated_at": str(current_time),
                "data_mode": data_mode
            },
            "market_data": {
                "spot_price_usd": {
                    "price_usd_per_oz": float(row.get("gold_spot_usd", row.get("CLOSE_XAUUSD", 0.0))),
                    "spread_points":    float(row.get("SPREAD_XAUUSD", 0.0)),
                    "source":           "premium_csv"
                },
                "forex": {
                    "usd_thb":        float(row.get("usd_thb_rate", row.get("CLOSE_USDTHB", 0.0))),
                    "spread_points":  float(row.get("SPREAD_USDTHB", 0.0)),
                    "source":         "premium_csv"
                },
                "thai_gold_thb": {
                    "buy_price_thb":  float(row.get("Mock_HSH_Buy_Close", row.get("Buy", 0))),
                    "sell_price_thb": float(row.get("Mock_HSH_Sell_Close", row.get("Sell", 0))),
                    "mid_price_thb": float(row.get("Mock_HSH_Sell_Close", row.get("close", 0))),
                    "premium_buy":       float(row.get("premium_buy", 0.0)),
                    "premium_sell":      float(row.get("premium_sell", 0.0)),
                    "pred_premium_buy":  float(row.get("pred_premium_buy", 0.0)),
                    "pred_premium_sell": float(row.get("pred_premium_sell", 0.0)),
                    "ohlcv": {  # คงโครงสร้างเดิมที่ Agent คุ้นเคยไว้ด้วย
                        "open":   float(row.get("Mock_HSH_Sell_Open",  row.get("open",  0))),
                        "high":   float(row.get("Mock_HSH_Sell_High",  row.get("high",  0))),
                        "low":    float(row.get("Mock_HSH_Sell_Low",   row.get("low",   0))),
                        "close":  float(row.get("Mock_HSH_Sell_Close", row.get("close", 0))),
                        "volume": float(row.get("volume", 0)),
                    },
                    "source":            "mock_hsh_csv",
                    "timestamp":         str(current_time)
                },
                "recent_price_action": recent_price_action
            },
            "technical_indicators": {
                "rsi": {"value": rsi_val, "signal": rsi_sig},
                "macd": {
                    "macd_line": float(row.get("macd_line", 0)),
                    "signal_line": float(row.get("signal_line", row.get("macd_signal", 0))),
                    "histogram": macd_hist,
                    "signal": macd_sig
                },
                "bollinger": {
                    "upper": float(row.get("bb_upper", row.get("bollinger_upper", 0))),
                    "middle": float(row.get("bb_mid", row.get("bollinger_mid", 0))),
                    "lower": float(row.get("bb_lower", row.get("bollinger_lower", 0)))
                },
                "atr": {"value": float(row.get("atr", 0)), "unit": "THB"},
                "trend": {
                    "ema_20": ema20,
                    "ema_50": ema50,
                    "trend": trend_sig,          # รองรับ Prompt เดิม
                    "trend_signal": trend_sig    # รองรับ Prompt ใหม่
                }
            },
            "news": news_data if news_data is not None else {},
            "portfolio": portfolio_dict if portfolio_dict is not None else {},
            "interval": str(interval) if interval else row.get("interval", "1h"),
            "timestamp": str(current_time),
        }
        return state