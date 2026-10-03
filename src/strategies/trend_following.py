"""Trend Following Strategy - EMA Trend + ADX + ATR Trailing"""

from datetime import datetime
from typing import Dict, Optional

import numpy as np
import pandas as pd

from src.strategies.base import BaseStrategy, Signal, add_common_indicators


class TrendFollowingStrategy(BaseStrategy):
    def __init__(self, config: dict):
        super().__init__("trend_following", config)
        self.ema_trend = self.params.get("ema_trend", 200)
        self.ema_fast = self.params.get("ema_fast", 20)
        self.ema_slow = self.params.get("ema_slow", 50)
        self.adx_period = self.params.get("adx_period", 14)
        self.adx_threshold = self.params.get("adx_threshold", 25)
        self.atr_period = self.params.get("atr_period", 14)
        self.atr_multiplier = self.params.get("atr_multiplier", 2.5)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = add_common_indicators(df)
        
        # ADX (Average Directional Index)
        df = self._calculate_adx(df)
        
        # Trend EMAs
        df[f"ema_{self.ema_trend}"] = df["close"].ewm(span=self.ema_trend, adjust=False).mean()
        df[f"ema_{self.ema_fast}"] = df["close"].ewm(span=self.ema_fast, adjust=False).mean()
        df[f"ema_{self.ema_slow}"] = df["close"].ewm(span=self.ema_slow, adjust=False).mean()
        
        # Trend alignment
        df["trend_up"] = (df["close"] > df[f"ema_{self.ema_trend}"]) & \
                         (df[f"ema_{self.ema_fast}"] > df[f"ema_{self.ema_slow}"])
        df["trend_down"] = (df["close"] < df[f"ema_{self.ema_trend}"]) & \
                           (df[f"ema_{self.ema_fast}"] < df[f"ema_{self.ema_slow}"])
        
        # Pullback detection
        df["pullback_long"] = df["trend_up"] & (df["close"] < df[f"ema_{self.ema_fast}"]) & \
                              (df["close"] > df[f"ema_{self.ema_slow}"])
        df["pullback_short"] = df["trend_down"] & (df["close"] > df[f"ema_{self.ema_fast}"]) & \
                               (df["close"] < df[f"ema_{self.ema_slow}"])
        
        # ATR for trailing stop
        df["trailing_stop_long"] = df["close"] - df["atr_14"] * self.atr_multiplier
        df["trailing_stop_short"] = df["close"] + df["atr_14"] * self.atr_multiplier
        
        return df

    def _calculate_adx(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate ADX indicator"""
        high = df["high"]
        low = df["low"]
        close = df["close"]
        
        # True Range
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        
        # Directional Movement
        up_move = high - high.shift()
        down_move = low.shift() - low
        
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)
        
        # Smoothed values
        atr = tr.ewm(alpha=1/self.adx_period, adjust=False).mean()
        plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1/self.adx_period, adjust=False).mean() / atr
        minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1/self.adx_period, adjust=False).mean() / atr
        
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.ewm(alpha=1/self.adx_period, adjust=False).mean()
        
        df["adx"] = adx
        df["plus_di"] = plus_di
        df["minus_di"] = minus_di
        
        return df

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if len(df) < max(self.ema_trend, self.adx_period) + 20:
            return None
        
        df = self.calculate_indicators(df)
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        current_price = latest["close"]
        adx = latest.get("adx", 0)
        plus_di = latest.get("plus_di", 0)
        minus_di = latest.get("minus_di", 0)
        
        trend_up = latest.get("trend_up", False)
        trend_down = latest.get("trend_down", False)
        pullback_long = latest.get("pullback_long", False)
        pullback_short = latest.get("pullback_short", False)
        
        long_score = 0
        short_score = 0
        reasons = []
        
        # Strong trend required
        if adx < self.adx_threshold:
            return None
        
        # Long: Uptrend + pullback to fast EMA + DI+ > DI-
        if trend_up and pullback_long and plus_di > minus_di:
            long_score += 3
            reasons.append(f"Uptrend pullback (ADX={adx:.0f})")
        
        # Short: Downtrend + pullback to fast EMA + DI- > DI+
        if trend_down and pullback_short and minus_di > plus_di:
            short_score += 3
            reasons.append(f"Downtrend pullback (ADX={adx:.0f})")
        
        # Trend continuation (break of pullback)
        if trend_up and latest["close"] > prev["high"] and plus_di > minus_di:
            long_score += 2
            reasons.append("Trend continuation breakout")
        if trend_down and latest["close"] < prev["low"] and minus_di > plus_di:
            short_score += 2
            reasons.append("Downtrend continuation")
        
        # Volume confirmation
        if latest.get("volume_ratio", 1) > 1.2:
            if long_score > short_score:
                long_score += 1
            else:
                short_score += 1
            reasons.append("Volume confirmation")
        
        # ADX rising = trend strengthening
        if latest.get("adx", 0) > prev.get("adx", 0):
            if long_score > short_score:
                long_score += 1
            else:
                short_score += 1
            reasons.append("ADX rising")
        
        if long_score >= 2:
            direction = "long"
            confidence = min(0.85, 0.5 + long_score * 0.1)
            entry = current_price
            stop = latest.get("trailing_stop_long", current_price * 0.95)
            target = current_price * 1.15  # 1.5:1 minimum, let winners run
        elif short_score >= 2:
            direction = "short"
            confidence = min(0.85, 0.5 + short_score * 0.1)
            entry = current_price
            stop = latest.get("trailing_stop_short", current_price * 1.05)
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
                "adx": round(adx, 1),
                "plus_di": round(plus_di, 1),
                "minus_di": round(minus_di, 1),
                "trend_up": trend_up,
                "trend_down": trend_down,
                "pullback_long": pullback_long,
                "pullback_short": pullback_short,
                "ema_trend": round(latest.get(f"ema_{self.ema_trend}", 0), 2),
                "reasons": reasons,
                "long_score": long_score,
                "short_score": short_score
            }
        )
        
        if self._validate_signal(signal):
            return signal
        return None