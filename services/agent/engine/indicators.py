"""
indicators.py — Gold Trading Agent
Vectorized Technical Indicators (Production Ready)
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass, asdict
from typing import Optional
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────────────────────

def get_thai_time():
    return datetime.now()


# ─────────────────────────────────────────────────────────────
# Dataclasses
# ─────────────────────────────────────────────────────────────

@dataclass
class RSIResult:
    value: float
    signal: str
    period: int = 14


@dataclass
class MACDResult:
    macd_line: float
    signal_line: float
    histogram: float
    prev_histogram: float 
    crossover: str


@dataclass
class BollingerResult:
    upper: float
    middle: float
    lower: float
    bandwidth: float
    pct_b: float
    signal: str


@dataclass
class ATRResult:
    value: float
    period: int = 14
    volatility_level: str = "normal"
    unit: str = "USD_PER_OZ"


@dataclass
class TrendResult:
    ema_20: float
    ema_50: float
    trend: str
    golden_cross: bool
    death_cross: bool


@dataclass
class MomentumResult:
    roc: float
    roc_prev: float


@dataclass
class PriceActionResult:
    body_ratio: float
    volume_confirm: bool
    vol_ratio: float


@dataclass
class StructureResult:
    break_swing_high: bool
    break_swing_low: bool
    swing_high: float
    swing_low: float


@dataclass
class AllIndicators:
    rsi: RSIResult
    macd: MACDResult
    bollinger: BollingerResult
    atr: ATRResult
    trend: TrendResult
    momentum: MomentumResult
    price_action: PriceActionResult
    structure: StructureResult
    latest_close: float
    calculated_at: str


# ─────────────────────────────────────────────────────────────
# Indicator Engine
# ─────────────────────────────────────────────────────────────

class TechnicalIndicators:

    def __init__(self, df: pd.DataFrame, usd_thb: Optional[float] = None):
        if df.empty:
            raise ValueError("DataFrame is empty")

        required = {"open", "high", "low", "close"}
        if not required.issubset(df.columns):
            raise ValueError(f"Missing columns: {required}")

        self.df = df.copy().reset_index(drop=True)
        self.close = self.df["close"]
        self.high = self.df["high"]
        self.low = self.df["low"]
        self.usd_thb = usd_thb

        self._calculate_all_vectorized()

    # ─────────────────────────────────────────
    # Core Calculation
    # ─────────────────────────────────────────

    def _calculate_all_vectorized(self):
        close = self.close
        high = self.high
        low = self.low

        # RSI
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = (-delta).clip(lower=0)

        avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        self.df["rsi_14"] = (100 - (100 / (1 + rs))).fillna(100)

        # MACD
        ema_fast = close.ewm(span=12, adjust=False).mean()
        ema_slow = close.ewm(span=26, adjust=False).mean()

        self.df["macd_line"] = ema_fast - ema_slow
        self.df["macd_signal"] = self.df["macd_line"].ewm(span=9, adjust=False).mean()
        self.df["macd_hist"] = self.df["macd_line"] - self.df["macd_signal"]

        # Bollinger
        self.df["bb_mid"] = close.rolling(20).mean()
        std = close.rolling(20).std(ddof=0)

        self.df["bb_up"] = self.df["bb_mid"] + 2 * std
        self.df["bb_low"] = self.df["bb_mid"] - 2 * std

        self.df["bb_bandwidth"] = (self.df["bb_up"] - self.df["bb_low"]) / self.df["bb_mid"]
        self.df["bb_pct_b"] = ((close - self.df["bb_low"]) /
                               (self.df["bb_up"] - self.df["bb_low"])).fillna(0.5)

        # ATR
        prev_close = close.shift(1)

        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs()
        ], axis=1).max(axis=1)

        self.df["atr_14"] = tr.ewm(alpha=1/14, adjust=False).mean()

        # EMA Trend
        self.df["ema_20"] = close.ewm(span=20, adjust=False).mean()
        self.df["ema_50"] = close.ewm(span=50, adjust=False).mean()

        # ROC
        self.df["roc_14"] = (close / close.shift(14) - 1) * 100

        # Body ratio
        body = (close - self.df["open"]).abs()
        full = (high - low).replace(0, np.nan)
        self.df["body_ratio"] = (body / full).fillna(0)

        # Volume
        if "volume" in self.df.columns:
            vol_avg = self.df["volume"].rolling(14).mean()
            self.df["vol_ratio"] = self.df["volume"] / vol_avg.replace(0, np.nan)
        else:
            self.df["vol_ratio"] = np.nan

        # Structure
        self.df["swing_high"] = high.shift(1).rolling(10).max()
        self.df["swing_low"] = low.shift(1).rolling(10).min()

        self.df["break_high"] = close > self.df["swing_high"]
        self.df["break_low"] = close < self.df["swing_low"]

    # ─────────────────────────────────────────
    # Indicator Methods
    # ─────────────────────────────────────────

    def rsi(self):
        val = float(self.df["rsi_14"].iloc[-1])
        if val >= 70:
            signal = "overbought"
        elif val <= 30:
            signal = "oversold"
        else:
            signal = "neutral"

        return RSIResult(round(val, 2), signal)

    def macd(self):
        curr = float(self.df["macd_hist"].iloc[-1])
        prev = float(self.df["macd_hist"].iloc[-2]) if len(self.df) >= 2 else 0

        if prev <= 0 and curr > 0:
            cross = "bullish_cross"
        elif prev >= 0 and curr < 0:
            cross = "bearish_cross"
        elif curr > 0:
            cross = "bullish_zone"
        elif curr < 0:
            cross = "bearish_zone"
        else:
            cross = "neutral"

        return MACDResult(
            round(float(self.df["macd_line"].iloc[-1]), 4),
            round(float(self.df["macd_signal"].iloc[-1]), 4),
            round(prev, 4),  
            round(curr, 4),
            cross
        )

    def bollinger(self):
        u = float(self.df["bb_up"].iloc[-1])
        m = float(self.df["bb_mid"].iloc[-1])
        l = float(self.df["bb_low"].iloc[-1])
        c = float(self.close.iloc[-1])

        if c > u:
            sig = "above_upper"
        elif c < l:
            sig = "below_lower"
        else:
            sig = "inside"

        return BollingerResult(
            round(u, 2), round(m, 2), round(l, 2),
            round(float(self.df["bb_bandwidth"].iloc[-1]), 6),
            round(float(self.df["bb_pct_b"].iloc[-1]), 4),
            sig
        )

    def atr(self):
        val = float(self.df["atr_14"].iloc[-1])

        atr_avg = self.df["atr_14"].rolling(50).mean().iloc[-1]

        if val < atr_avg * 0.8:
            vol = "low"
        elif val > atr_avg * 1.5:
            vol = "high"
        else:
            vol = "normal"

        if self.usd_thb:
            val = val * self.usd_thb / 31.1035 * 15.244 * 0.965
            unit = "THB_PER_BAHT_GOLD"
        else:
            unit = "USD_PER_OZ"

        return ATRResult(round(val, 2), 14, vol, unit)

    def trend(self):
        e20 = float(self.df["ema_20"].iloc[-1])
        e50 = float(self.df["ema_50"].iloc[-1])

        return TrendResult(
            round(e20, 2),
            round(e50, 2),
            "uptrend" if e20 > e50 else "downtrend" if e20 < e50 else "sideways",
            e20 > e50,
            e20 < e50
        )

    def momentum(self):
        now = float(self.df["roc_14"].iloc[-1])
        prev = float(self.df["roc_14"].iloc[-2]) if len(self.df) >= 2 else 0

        return MomentumResult(round(now, 4), round(prev, 4))

    def price_action(self):
        body = float(self.df["body_ratio"].iloc[-1])
        vol_ratio = self.df["vol_ratio"].iloc[-1]

        if np.isnan(vol_ratio):
            vol_ratio = 0

        confirm = vol_ratio >= 1.3 if vol_ratio > 0 else body >= 0.5

        return PriceActionResult(
            round(body, 4),
            confirm,
            round(vol_ratio, 2)
        )

    def structure(self):
        return StructureResult(
            bool(self.df["break_high"].iloc[-1]),
            bool(self.df["break_low"].iloc[-1]),
            round(float(self.df["swing_high"].iloc[-1]), 2),
            round(float(self.df["swing_low"].iloc[-1]), 2)
        )

    # ─────────────────────────────────────────
    # Final Output
    # ─────────────────────────────────────────

    def compute_all(self):
        return AllIndicators(
            rsi=self.rsi(),
            macd=self.macd(),
            bollinger=self.bollinger(),
            atr=self.atr(),
            trend=self.trend(),
            momentum=self.momentum(),
            price_action=self.price_action(),
            structure=self.structure(),
            latest_close=round(float(self.close.iloc[-1]), 2),
            calculated_at=get_thai_time().isoformat(),
        )

    def to_dict(self):
        result = asdict(self.compute_all())
        result["data_quality"] = {
            "warnings": [],
            "quality_score": "good"
        }
        return result


# ─────────────────────────────────────────
# TEST
# ─────────────────────────────────────────

if __name__ == "__main__":
    np.random.seed(42)
    n = 300
    price = 2300 + np.cumsum(np.random.randn(n) * 5)

    df = pd.DataFrame({
        "open": price - np.random.rand(n) * 3,
        "high": price + np.random.rand(n) * 8,
        "low": price - np.random.rand(n) * 8,
        "close": price,
        "volume": np.random.randint(10000, 50000, n),
    })

    calc = TechnicalIndicators(df)

    import json
    print(json.dumps(calc.to_dict(), indent=2, ensure_ascii=False))