from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import pandas as pd
from datetime import datetime

logger = logging.getLogger(__name__)

class CSVOrchestrator:
    """
    Market State Builder ตัวเต็มสำหรับ Phase 1
    รับหน้าที่อ่าน Mock HSH (ราคาไทย) และ Premium/Spot (External)
    เพื่อสร้าง JSON Payload ส่งต่อให้ Pipeline ถัดไป
    """

    def __init__(
        self,
        gold_csv: str,         # แนะนำให้ใส่ Mock_HSH_OHLC.csv
        external_csv: str,     # แนะนำให้ใส่ Premium_Calculated_Feb_Apr.csv
        news_csv: str = "",    # เว้นไว้ก่อนตาม requirement
        interval: str = "5m",
        output_dir: str = "./output",
    ):
        self.gold_csv = gold_csv
        self.external_csv = external_csv
        self.news_csv = news_csv
        self.interval = interval
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self._merged_df: Optional[pd.DataFrame] = None
        self._load_and_merge_data()

    def _load_and_merge_data(self):
        """โหลดและรวมข้อมูลจาก HSH และ Premium เข้าด้วยกัน"""
        try:
            # 1. โหลดข้อมูลราคาทองไทย (Mock HSH)
            df_gold = pd.read_csv(self.gold_csv)
            # หาชื่อคอลัมน์เวลา
            time_col_gold = next((c for c in df_gold.columns if c.lower() in ["datetime", "timestamp", "date"]), None)
            df_gold["timestamp"] = pd.to_datetime(df_gold[time_col_gold], errors="coerce")
            
            # แมปราคา Sell ให้เป็นราคาหลักสำหรับการแสดงผลและทำ Price Action
            if "Mock_HSH_Sell_Close" in df_gold.columns:
                df_gold["close_thai"] = df_gold["Mock_HSH_Sell_Close"]
                df_gold["open_thai"] = df_gold.get("Mock_HSH_Sell_Open", df_gold["Mock_HSH_Sell_Close"])
                df_gold["high_thai"] = df_gold.get("Mock_HSH_Sell_High", df_gold["Mock_HSH_Sell_Close"])
                df_gold["low_thai"] = df_gold.get("Mock_HSH_Sell_Low", df_gold["Mock_HSH_Sell_Close"])
            else:
                df_gold["close_thai"] = df_gold.get("Sell", df_gold.get("close", 0))

            # 2. โหลดข้อมูล External (Premium, Spot, Forex)
            df_ext = pd.read_csv(self.external_csv)
            time_col_ext = next((c for c in df_ext.columns if c.lower() in ["datetime", "timestamp", "datetime_th"]), None)
            df_ext["timestamp"] = pd.to_datetime(df_ext[time_col_ext], errors="coerce")

            # 3. รวมร่าง (Merge) อิงตาม timestamp
            merged = pd.merge(df_gold, df_ext, on="timestamp", how="inner", suffixes=("", "_ext"))
            self._merged_df = merged.sort_values("timestamp").reset_index(drop=True)
            
            logger.info(f"✓ โหลดและรวมข้อมูลสำเร็จ! ได้มา {len(self._merged_df):,} แถว")
            
        except Exception as e:
            raise RuntimeError(f"CSVOrchestrator: เกิดข้อผิดพลาดในการโหลดข้อมูล: {e}") from e

    def run(self, history_days: int = 90, save_to_file: bool = True) -> dict:
        """
        สร้าง market_state_dict ที่สมบูรณ์แบบ
        """
        df = self._merged_df.copy()

        # กรองข้อมูลตามจำนวนวัน
        cutoff = df["timestamp"].max() - pd.Timedelta(days=history_days)
        df = df[df["timestamp"] >= cutoff].reset_index(drop=True)

        if df.empty:
            raise ValueError(f"ไม่มีข้อมูลในช่วง {history_days} วันที่ผ่านมา")

        latest = df.iloc[-1]
        latest_ts = pd.Timestamp(latest["timestamp"])

        # ── ดึงตัวแปรใหม่จาก CSV ─────────────────
        buy_price  = float(latest.get("Buy", 0.0))
        sell_price = float(latest.get("Sell", 0.0))
        close_thai = float(latest.get("close_thai", sell_price)) # ใช้ราคา Sell เป็นหลัก

        # Premium (ระวังการตั้งชื่อซ้ำจากตอน Merge ให้ดึงตัวใดตัวหนึ่ง)
        premium_buy       = float(latest.get("premium_buy", 0.0))
        premium_sell      = float(latest.get("premium_sell", 0.0))
        pred_premium_buy  = float(latest.get("pred_premium_buy", 0.0))
        pred_premium_sell = float(latest.get("pred_premium_sell", 0.0))

        # Spot & Forex & Spread
        gold_spot_usd = float(latest.get("CLOSE_XAUUSD", 0.0))
        spread_xauusd = float(latest.get("SPREAD_XAUUSD", 0.0))
        
        usd_thb_rate  = float(latest.get("CLOSE_USDTHB", 0.0))
        spread_usdthb = float(latest.get("SPREAD_USDTHB", 0.0))

        # ── สร้าง Price Action (อิงจากราคาฝั่ง Sell) ──
        recent_price_action = []
        recent_5 = df.tail(5)
        for _, row in recent_5.iterrows():
            recent_price_action.append({
                "datetime": str(row["timestamp"]),
                "open":     float(row.get("open_thai", row.get("Mock_HSH_Sell_Open", 0))),
                "high":     float(row.get("high_thai", row.get("Mock_HSH_Sell_High", 0))),
                "low":      float(row.get("low_thai",  row.get("Mock_HSH_Sell_Low", 0))),
                "close":    float(row.get("close_thai", row.get("Mock_HSH_Sell_Close", 0))),
            })

        # ── Technical Indicators (รอคุณต่อเชื่อมกับ csv_loader ได้ภายหลัง) ──
        indicators_dict = {
            "status": "pending_integration_with_csv_loader",
            "note": "จะดึงค่า RSI/MACD มาใส่ตรงนี้ในอนาคต"
        }

        # ── ประกอบร่าง Payload (Market State) ──
        payload = {
            "meta": {
                "agent":        "gold-trading-agent",
                "version":      "market-state-builder-v1",
                "generated_at": str(datetime.now()),
                "history_days": history_days,
                "interval":     self.interval,
                "data_mode":    "csv",
            },
            "market_data": {
                "spot_price_usd": {
                    "price_usd_per_oz": gold_spot_usd,
                    "spread_points":    spread_xauusd,
                    "source":           "premium_csv",
                },
                "forex": {
                    "usd_thb":        usd_thb_rate,
                    "spread_points":  spread_usdthb,
                    "source":         "premium_csv",
                },
                "thai_gold_thb": {
                    "broker_buy_price":   buy_price,   # ราคาที่เรารับซื้อ (โบรกเกอร์ซื้อ)
                    "broker_sell_price":  sell_price,  # ราคาที่เราขาย (โบรกเกอร์ขาย) - สำคัญที่สุด
                    "mid_price_thb":      close_thai,
                    "premium_buy":        premium_buy,
                    "premium_sell":       premium_sell,
                    "pred_premium_buy":   pred_premium_buy,
                    "pred_premium_sell":  pred_premium_sell,
                    "source":             "mock_hsh_csv",
                    "timestamp":          str(latest_ts),
                },
                "recent_price_action": recent_price_action,
            },
            "technical_indicators": indicators_dict,
            "news": "skipped_for_now"
        }

        # ── บันทึกไฟล์ให้เพื่อนใช้งาน ──
        if save_to_file:
            ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            files_to_save = [
                self.output_dir / f"market_state_{ts_str}.json",
                self.output_dir / "market_state_latest.json",
            ]
            for fp in files_to_save:
                try:
                    with open(fp, "w", encoding="utf-8") as f:
                        json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
                except Exception as e:
                    logger.error(f"Save JSON Error: {e}")

        logger.info(f"✓ สร้าง Market State เรียบร้อย! (Spot: {gold_spot_usd}, USDTHB: {usd_thb_rate})")
        return payload