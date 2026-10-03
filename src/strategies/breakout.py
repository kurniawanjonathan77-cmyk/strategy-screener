"""Breakout Strategy - Donchian Channels, Volume Breakout"""

from datetime import datetime
from typing import Dict, Optional

import pandas as pd

from src.strategies.base import BaseStrategy, Signal, add_common_indicators


class BreakoutStrategy(BaseStrategy):
    def __init__(self, config: dict):
        super().__init__("breakout", config)
        self.donchian_period = self.params.get("donchian_period", 20)
        self.volume_multiplier = self.params.get("volume_multiplier", 1.5)
        self.atr_period = self.params.get("atr_period", 14)
        self.atr_multiplier = self.params.get("atr_multiplier", 2.0)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = add_common_indicators(df)
        
        # Donchian channels
        self.high_col = f"donchian_high_{self.donchian_period}"
        self.low_col = f"donchian_low_{self.donchian_period}"
        mid_col = f"donchian_mid_{self.donchian_period}"
        
        # Breakout levels
        df["breakout_up"] = df["high"] > df[self.high_col].shift(1)
        df["breakout_down"] = df["low"] < df[self.low_col].shift(1)
        
        # Distance from channel
        df["dist_from_high"] = (df[self.high_col] - df["close"]) / df["close"]
        df["dist_from_low"] = (df["close"] - df[self.low_col]) / df["close"]
        
        # Volume surge
        df["volume_surge"] = df["volume_ratio"] > self.volume_multiplier
        
        # ATR for stop loss
        df["atr_stop_long"] = df["close"] - df["atr_14"] * self.atr_multiplier
        df["atr_stop_short"] = df["close"] + df["atr_14"] * self.atr_multiplier
        
        return df

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if len(df) < self.donchian_period + 10:
            return None
        
        df = self.calculate_indicators(df)
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        current_price = latest["close"]
        
        # Breakout conditions
        breakout_up = latest.get("breakout_up", False)
        breakout_down = latest.get("breakout_down", False)
        volume_surge = latest.get("volume_surge", False)
        dist_from_high = latest.get("dist_from_high", 0)
        dist_from_low = latest.get("dist_from_low", 0)
        
        long_score = 0
        short_score = 0
        reasons = []
        
        # Upper breakout with volume
        if breakout_up and volume_surge:
            long_score += 3
            reasons.append(f"Donchian upper breakout + volume surge")
        elif breakout_up:
            long_score += 1
            reasons.append(f"Donchian upper breakout (low volume)")
        
        # Lower breakout with volume
        if breakout_down and volume_surge:
            short_score += 3
            reasons.append(f"Donchian lower breakout + volume surge")
        elif breakout_down:
            short_score += 1
            reasons.append(f"Donchian lower breakout (low volume)")
        
        # Near channel edges (anticipation)
        if dist_from_high < 0.02 and not breakout_up:
            long_score += 1
            reasons.append(f"Near upper channel ({dist_from_high:.1%})")
        if dist_from_low < 0.02 and not breakout_down:
            short_score += 1
            reasons.append(f"Near lower channel ({dist_from_low:.1%})")
        
        # Volume confirmation
        if latest.get("volume_ratio", 1) > 2.0:
            if long_score > short_score:
                long_score += 1
            else:
                short_score += 1
            reasons.append(f"Volume spike ({latest['volume_ratio']:.1f}x)")
        
        # Trend filter - only trade breakouts in trend direction
        sma_50 = latest.get("sma_50", current_price)
        if current_price > sma_50:
            long_score += 1
        else:
            short_score += 1
        
        if long_score >= 2:
            direction = "long"
            confidence = min(0.85, 0.45 + long_score * 0.1)
            entry = current_price
            stop = latest.get("atr_stop_long", current_price * 0.94)
            target = current_price * 1.15  # 15% target for breakout
        elif short_score >= 2:
            direction = "short"
            confidence = min(0.85, 0.45 + short_score * 0.1)
            entry = current_price
            stop = latest.get("atr_stop_short", current_price * 1.06)
            target = current_price * 0.85
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
                "donchian_high": round(latest.get(self.high_col, 0), 6),
                "donchian_low": round(latest.get(self.low_col, 0), 6),
                "breakout_up": breakout_up,
                "breakout_down": breakout_down,
                "volume_ratio": round(latest.get("volume_ratio", 1), 2),
                "dist_from_high": round(dist_from_high, 4),
                "dist_from_low": round(dist_from_low, 4),
                "atr": round(latest.get("atr_14", 0), 6),
                "reasons": reasons,
                "long_score": long_score,
                "short_score": short_score
            }
        )
        
        if self._validate_signal(signal):
            return signal
        return None