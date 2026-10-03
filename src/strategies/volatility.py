"""Volatility Strategy - Keltner Channels, Squeeze, ATR"""

from datetime import datetime
from typing import Dict, Optional

import numpy as np
import pandas as pd

from src.strategies.base import BaseStrategy, Signal, add_common_indicators


class VolatilityStrategy(BaseStrategy):
    def __init__(self, config: dict):
        super().__init__("volatility", config)
        self.keltner_period = self.params.get("keltner_period", 20)
        self.keltner_multiplier = self.params.get("keltner_multiplier", 2.0)
        self.atr_period = self.params.get("atr_period", 14)
        self.squeeze_threshold = self.params.get("squeeze_threshold", 0.05)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = add_common_indicators(df)
        
        # Keltner Channels
        df["kc_mid"] = df["close"].ewm(span=self.keltner_period, adjust=False).mean()
        df["kc_upper"] = df["kc_mid"] + df["atr_14"] * self.keltner_multiplier
        df["kc_lower"] = df["kc_mid"] - df["atr_14"] * self.keltner_multiplier
        df["kc_width"] = (df["kc_upper"] - df["kc_lower"]) / df["kc_mid"]
        
        # Bollinger Bands width (from base)
        # Squeeze: BB inside KC
        df["squeeze_on"] = (df["bb_upper"] < df["kc_upper"]) & (df["bb_lower"] > df["kc_lower"])
        df["squeeze_off"] = ~df["squeeze_on"] & df["squeeze_on"].shift(1).fillna(False)
        
        # Volatility regime
        df["volatility_rank"] = df["kc_width"].rolling(252).rank(pct=True)
        
        # Momentum for squeeze direction
        df["squeeze_momentum"] = df["close"].pct_change(5)
        
        return df

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if len(df) < max(self.keltner_period, self.atr_period) + 20:
            return None
        
        df = self.calculate_indicators(df)
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        current_price = latest["close"]
        
        # Squeeze detection
        squeeze_on = latest.get("squeeze_on", False)
        squeeze_off = latest.get("squeeze_off", False)
        kc_width = latest.get("kc_width", 0)
        volatility_rank = latest.get("volatility_rank", 0.5)
        momentum = latest.get("squeeze_momentum", 0)
        
        # Keltner channel position
        kc_pct = (current_price - latest["kc_lower"]) / (latest["kc_upper"] - latest["kc_lower"])
        
        long_score = 0
        short_score = 0
        reasons = []
        
        # Squeeze breakout
        if squeeze_off:
            if momentum > 0:
                long_score += 3
                reasons.append("Squeeze release bullish")
            elif momentum < 0:
                short_score += 3
                reasons.append("Squeeze release bearish")
        
        # Low volatility + momentum building
        if squeeze_on and volatility_rank < 0.2:
            if momentum > 0.01:
                long_score += 2
                reasons.append("Low vol + positive momentum")
            elif momentum < -0.01:
                short_score += 2
                reasons.append("Low vol + negative momentum")
        
        # Keltner channel extremes
        if kc_pct < 0.1:
            long_score += 1
            reasons.append(f"Near KC lower ({kc_pct:.1%})")
        elif kc_pct > 0.9:
            short_score += 1
            reasons.append(f"Near KC upper ({kc_pct:.1%})")
        
        # BB vs KC width comparison
        bb_width = latest.get("bb_width", 0)
        if bb_width < kc_width * 0.8:
            reasons.append("BB inside KC (compression)")
            if momentum > 0:
                long_score += 1
            else:
                short_score += 1
        
        # Volume
        if latest.get("volume_ratio", 1) > 1.5:
            if long_score > short_score:
                long_score += 1
            else:
                short_score += 1
            reasons.append("Volume confirmation")
        
        if long_score >= 2:
            direction = "long"
            confidence = min(0.8, 0.4 + long_score * 0.12)
            entry = current_price
            stop = current_price * 0.96  # Tighter stop for vol strategy
            target = current_price * 1.10
        elif short_score >= 2:
            direction = "short"
            confidence = min(0.8, 0.4 + short_score * 0.12)
            entry = current_price
            stop = current_price * 1.04
            target = current_price * 0.90
        else:
            return None
        
        risk_reward = abs(target - entry) / abs(entry - stop)
        
        signal = Signal(
            symbol=symbol,
            strategy=self.name,
            direction=direction,
            entry_price=entry,
            stop_loss=stop,
            take_profit=target,
            confidence=confidence,
            risk_reward=risk_reward,
            timestamp=df.index[-1],
            metadata={
                "kc_upper": round(latest.get("kc_upper", 0), 6),
                "kc_lower": round(latest.get("kc_lower", 0), 6),
                "kc_pct": round(kc_pct, 3),
                "kc_width": round(kc_width, 4),
                "bb_width": round(bb_width, 4),
                "squeeze_on": squeeze_on,
                "squeeze_off": squeeze_off,
                "volatility_rank": round(volatility_rank, 3),
                "momentum": round(momentum, 4),
                "reasons": reasons,
                "long_score": long_score,
                "short_score": short_score
            }
        )
        
        if self._validate_signal(signal):
            return signal
        return None