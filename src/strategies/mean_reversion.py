"""Mean Reversion Strategy - RSI, Bollinger Bands, Z-Score"""

from datetime import datetime
from typing import Dict, Optional

import numpy as np
import pandas as pd

from src.strategies.base import BaseStrategy, Signal, add_common_indicators


class MeanReversionStrategy(BaseStrategy):
    def __init__(self, config: dict):
        super().__init__("mean_reversion", config)
        self.rsi_period = self.params.get("rsi_period", 14)
        self.rsi_oversold = self.params.get("rsi_oversold", 30)
        self.rsi_overbought = self.params.get("rsi_overbought", 70)
        self.bb_period = self.params.get("bb_period", 20)
        self.bb_std = self.params.get("bb_std", 2.0)
        self.zscore_period = self.params.get("zscore_period", 20)
        self.zscore_threshold = self.params.get("zscore_threshold", 2.0)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = add_common_indicators(df)
        
        # RSI
        rsi_col = f"rsi_{self.rsi_period}"
        if rsi_col not in df.columns:
            delta = df["close"].diff()
            gain = (delta.where(delta > 0, 0)).rolling(self.rsi_period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(self.rsi_period).mean()
            rs = gain / loss
            df[rsi_col] = 100 - (100 / (1 + rs))
        
        # Bollinger Bands position
        df["bb_pct"] = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])
        
        # Z-Score
        z_col = f"zscore_{self.zscore_period}"
        if z_col not in df.columns:
            mean = df["close"].rolling(self.zscore_period).mean()
            std = df["close"].rolling(self.zscore_period).std()
            df[z_col] = (df["close"] - mean) / std
        
        return df

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if len(df) < max(self.rsi_period, self.bb_period, self.zscore_period) + 10:
            return None
        
        df = self.calculate_indicators(df)
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        current_price = latest["close"]
        rsi = latest.get(f"rsi_{self.rsi_period}", 50)
        bb_pct = latest.get("bb_pct", 0.5)
        zscore = latest.get(f"zscore_{self.zscore_period}", 0)
        
        # Mean reversion signals
        long_score = 0
        short_score = 0
        reasons = []
        
        # RSI oversold/overbought
        if rsi <= self.rsi_oversold:
            long_score += 1
            reasons.append(f"RSI oversold ({rsi:.1f})")
        elif rsi >= self.rsi_overbought:
            short_score += 1
            reasons.append(f"RSI overbought ({rsi:.1f})")
        
        # Bollinger Bands
        if bb_pct <= 0.05:  # Near lower band
            long_score += 1
            reasons.append(f"BB lower band (pct={bb_pct:.2f})")
        elif bb_pct >= 0.95:  # Near upper band
            short_score += 1
            reasons.append(f"BB upper band (pct={bb_pct:.2f})")
        
        # Z-Score
        if zscore <= -self.zscore_threshold:
            long_score += 1
            reasons.append(f"Z-score low ({zscore:.2f})")
        elif zscore >= self.zscore_threshold:
            short_score += 1
            reasons.append(f"Z-score high ({zscore:.2f})")
        
        # Need at least 2 confirmations
        if long_score >= 2:
            direction = "long"
            confidence = min(0.9, 0.5 + long_score * 0.15)
            entry = current_price
            stop = current_price * 0.95  # 5% stop
            target = current_price * 1.08  # 8% target
        elif short_score >= 2:
            direction = "short"
            confidence = min(0.9, 0.5 + short_score * 0.15)
            entry = current_price
            stop = current_price * 1.05
            target = current_price * 0.92
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
                "rsi": round(rsi, 1),
                "bb_pct": round(bb_pct, 3),
                "zscore": round(zscore, 2),
                "reasons": reasons,
                "long_score": long_score,
                "short_score": short_score
            }
        )
        
        if self._validate_signal(signal):
            return signal
        return None