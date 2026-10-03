"""Momentum Strategy - MACD, EMA Crossover, ROC"""

from datetime import datetime
from typing import Dict, Optional

import numpy as np
import pandas as pd

from src.strategies.base import BaseStrategy, Signal, add_common_indicators


class MomentumStrategy(BaseStrategy):
    def __init__(self, config: dict):
        super().__init__("momentum", config)
        self.ema_fast = self.params.get("ema_fast", 12)
        self.ema_slow = self.params.get("ema_slow", 26)
        self.macd_signal = self.params.get("macd_signal", 9)
        self.roc_period = self.params.get("roc_period", 10)
        self.roc_threshold = self.params.get("roc_threshold", 0.02)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = add_common_indicators(df)
        
        # EMA crossover
        df["ema_cross"] = df[f"ema_{self.ema_fast}"] - df[f"ema_{self.ema_slow}"]
        df["ema_cross_prev"] = df["ema_cross"].shift(1)
        
        # MACD already in base
        # ROC
        roc_col = f"roc_{self.roc_period}"
        if roc_col not in df.columns:
            df[roc_col] = df["close"].pct_change(self.roc_period)
        
        # Momentum score
        df["momentum_score"] = 0
        # Price above EMAs
        df.loc[df["close"] > df[f"ema_{self.ema_fast}"], "momentum_score"] += 1
        df.loc[df["close"] > df[f"ema_{self.ema_slow}"], "momentum_score"] += 1
        # MACD bullish
        df.loc[df["macd"] > df["macd_signal"], "momentum_score"] += 1
        # ROC positive
        df.loc[df[roc_col] > 0, "momentum_score"] += 1
        # Volume confirmation
        df.loc[df["volume_ratio"] > 1.2, "momentum_score"] += 1
        
        return df

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if len(df) < max(self.ema_slow, self.roc_period) + 10:
            return None
        
        df = self.calculate_indicators(df)
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        current_price = latest["close"]
        momentum_score = latest.get("momentum_score", 0)
        macd = latest.get("macd", 0)
        macd_signal = latest.get("macd_signal", 0)
        roc = latest.get(f"roc_{self.roc_period}", 0)
        volume_ratio = latest.get("volume_ratio", 1)
        
        # EMA crossover
        ema_cross = latest.get("ema_cross", 0)
        ema_cross_prev = prev.get("ema_cross", 0)
        bullish_cross = ema_cross_prev <= 0 and ema_cross > 0
        bearish_cross = ema_cross_prev >= 0 and ema_cross < 0
        
        # MACD crossover
        macd_bullish = prev["macd"] <= prev["macd_signal"] and macd > macd_signal
        macd_bearish = prev["macd"] >= prev["macd_signal"] and macd < macd_signal
        
        long_score = 0
        short_score = 0
        reasons = []
        
        # EMA crossover
        if bullish_cross:
            long_score += 2
            reasons.append("EMA bullish crossover")
        elif bearish_cross:
            short_score += 2
            reasons.append("EMA bearish crossover")
        
        # MACD
        if macd_bullish:
            long_score += 2
            reasons.append("MACD bullish crossover")
        elif macd_bearish:
            short_score += 2
            reasons.append("MACD bearish crossover")
        
        # Trend alignment
        if macd > macd_signal and latest["close"] > latest[f"ema_{self.ema_fast}"]:
            long_score += 1
            reasons.append("MACD + EMA aligned bullish")
        elif macd < macd_signal and latest["close"] < latest[f"ema_{self.ema_fast}"]:
            short_score += 1
            reasons.append("MACD + EMA aligned bearish")
        
        # ROC
        if roc > self.roc_threshold:
            long_score += 1
            reasons.append(f"ROC positive ({roc:.2%})")
        elif roc < -self.roc_threshold:
            short_score += 1
            reasons.append(f"ROC negative ({roc:.2%})")
        
        # Volume
        if volume_ratio > 1.5:
            if long_score > short_score:
                long_score += 1
            else:
                short_score += 1
            reasons.append(f"High volume ({volume_ratio:.1f}x)")
        
        if long_score >= 3:
            direction = "long"
            confidence = min(0.9, 0.4 + long_score * 0.1)
            entry = current_price
            stop = current_price * 0.94  # 6% stop for momentum
            target = current_price * 1.12  # 12% target
        elif short_score >= 3:
            direction = "short"
            confidence = min(0.9, 0.4 + short_score * 0.1)
            entry = current_price
            stop = current_price * 1.06
            target = current_price * 0.88
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
                "momentum_score": int(momentum_score),
                "macd": round(macd, 6),
                "macd_signal": round(macd_signal, 6),
                "roc": round(roc, 4),
                "volume_ratio": round(volume_ratio, 2),
                "ema_cross": round(ema_cross, 6),
                "reasons": reasons,
                "long_score": long_score,
                "short_score": short_score
            }
        )
        
        if self._validate_signal(signal):
            return signal
        return None