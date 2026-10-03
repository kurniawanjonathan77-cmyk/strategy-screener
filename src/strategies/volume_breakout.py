"""Volume Breakout Strategy - High Volume + Price Expansion"""

from datetime import datetime
from typing import Dict, Optional

import pandas as pd

from src.strategies.base import BaseStrategy, Signal, add_common_indicators


class VolumeBreakoutStrategy(BaseStrategy):
    def __init__(self, config: dict):
        super().__init__("volume_breakout", config)
        self.volume_lookback = self.params.get("volume_lookback", 20)
        self.volume_multiplier = self.params.get("volume_multiplier", 3.0)
        self.price_change_threshold = self.params.get("price_change_threshold", 0.03)
        self.vwap_period = self.params.get("vwap_period", 20)
        self.rsi_period = self.params.get("rsi_period", 14)
        self.rsi_max_entry = self.params.get("rsi_max_entry", 70)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = add_common_indicators(df)
        
        # Volume SMA
        df["volume_sma"] = df["volume"].rolling(self.volume_lookback).mean()
        df["volume_ratio"] = df["volume"] / df["volume_sma"]
        
        # VWAP
        df["typical_price"] = (df["high"] + df["low"] + df["close"]) / 3
        df["vwap_num"] = (df["typical_price"] * df["volume"]).rolling(self.vwap_period).sum()
        df["vwap_den"] = df["volume"].rolling(self.vwap_period).sum()
        df["vwap"] = df["vwap_num"] / df["vwap_den"]
        df["vwap_distance"] = (df["close"] - df["vwap"]) / df["vwap"]
        
        # Price expansion
        df["price_change"] = df["close"].pct_change()
        df["price_change_abs"] = df["price_change"].abs()
        
        # Breakout conditions
        df["volume_spike"] = df["volume_ratio"] >= self.volume_multiplier
        df["price_expansion"] = df["price_change_abs"] >= self.price_change_threshold
        
        # Candle structure
        df["body_size"] = abs(df["close"] - df["open"]) / df["close"]
        df["upper_wick"] = (df["high"] - df[["open", "close"]].max(axis=1)) / df["close"]
        df["lower_wick"] = (df[["open", "close"]].min(axis=1) - df["low"]) / df["close"]
        df["strong_bullish"] = (df["close"] > df["open"]) & (df["body_size"] > 0.01) & (df["upper_wick"] < df["body_size"] * 0.3)
        df["strong_bearish"] = (df["close"] < df["open"]) & (df["body_size"] > 0.01) & (df["lower_wick"] < df["body_size"] * 0.3)
        
        # RSI
        rsi_col = f"rsi_{self.rsi_period}"
        if rsi_col not in df.columns:
            delta = df["close"].diff()
            gain = (delta.where(delta > 0, 0)).rolling(self.rsi_period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(self.rsi_period).mean()
            rs = gain / loss
            df[rsi_col] = 100 - (100 / (1 + rs))
        
        return df

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if len(df) < max(self.volume_lookback, self.vwap_period, self.rsi_period) + 10:
            return None
        
        df = self.calculate_indicators(df)
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        current_price = latest["close"]
        volume_ratio = latest.get("volume_ratio", 1)
        price_change = latest.get("price_change", 0)
        vwap_distance = latest.get("vwap_distance", 0)
        rsi = latest.get(f"rsi_{self.rsi_period}", 50)
        
        strong_bullish = latest.get("strong_bullish", False)
        strong_bearish = latest.get("strong_bearish", False)
        volume_spike = latest.get("volume_spike", False)
        price_expansion = latest.get("price_expansion", False)
        
        long_score = 0
        short_score = 0
        reasons = []
        
        # Core: Volume spike + price expansion in same direction
        if volume_spike and price_expansion:
            if price_change > 0 and strong_bullish:
                long_score += 3
                reasons.append(f"Vol spike {volume_ratio:.1f}x + bullish candle + {price_change:.1%}")
            elif price_change < 0 and strong_bearish:
                short_score += 3
                reasons.append(f"Vol spike {volume_ratio:.1f}x + bearish candle + {price_change:.1%}")
        
        # VWAP reclaim/break
        if vwap_distance > -0.005 and vwap_distance < 0.02 and price_change > 0:
            long_score += 2
            reasons.append("VWAP reclaim bullish")
        elif vwap_distance < 0.005 and vwap_distance > -0.02 and price_change < 0:
            short_score += 2
            reasons.append("VWAP break bearish")
        
        # RSI filter - don't chase overbought
        if rsi < self.rsi_max_entry:
            if long_score > 0:
                long_score += 1
        else:
            long_score = max(0, long_score - 2)
            reasons.append(f"RSI overbought ({rsi:.0f})")
        
        if rsi > (100 - self.rsi_max_entry):
            if short_score > 0:
                short_score += 1
        else:
            short_score = max(0, short_score - 2)
        
        # Previous bar confirmation
        prev_volume_spike = prev.get("volume_spike", False)
        prev_price_change = prev.get("price_change", 0)
        if prev_volume_spike and prev_price_change * price_change > 0:
            if price_change > 0:
                long_score += 1
                reasons.append("Consecutive vol bars")
            else:
                short_score += 1
        
        # Volume trend
        vol_trend = df["volume_ratio"].iloc[-5:].mean()
        if vol_trend > 1.5:
            if long_score > short_score:
                long_score += 1
            else:
                short_score += 1
            reasons.append("Sustained high volume")
        
        if long_score >= 2:
            direction = "long"
            confidence = min(0.8, 0.45 + long_score * 0.1)
            entry = current_price
            stop = current_price * 0.96
            target = current_price * 1.12
        elif short_score >= 2:
            direction = "short"
            confidence = min(0.8, 0.45 + short_score * 0.1)
            entry = current_price
            stop = current_price * 1.04
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
                "volume_ratio": round(volume_ratio, 2),
                "price_change": round(price_change, 4),
                "vwap_distance": round(vwap_distance, 4),
                "rsi": round(rsi, 1),
                "strong_bullish": strong_bullish,
                "strong_bearish": strong_bearish,
                "volume_spike": volume_spike,
                "price_expansion": price_expansion,
                "reasons": reasons,
                "long_score": long_score,
                "short_score": short_score
            }
        )
        
        if self._validate_signal(signal):
            return signal
        return None