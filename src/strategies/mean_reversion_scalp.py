"""Mean Reversion Scalp - Fast RSI + Wide BB for Quick Mean Reversion"""

from datetime import datetime
from typing import Dict, Optional

import pandas as pd

from src.strategies.base import BaseStrategy, Signal, add_common_indicators


class MeanReversionScalpStrategy(BaseStrategy):
    def __init__(self, config: dict):
        super().__init__("mean_reversion_scalp", config)
        self.bb_period = self.params.get("bb_period", 20)
        self.bb_std = self.params.get("bb_std", 2.5)
        self.rsi_period = self.params.get("rsi_period", 7)
        self.rsi_extreme_low = self.params.get("rsi_extreme_low", 20)
        self.rsi_extreme_high = self.params.get("rsi_extreme_high", 80)
        self.holding_periods = self.params.get("holding_periods", 12)

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = add_common_indicators(df)
        
        # Fast RSI
        delta = df["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(self.rsi_period).mean()
        rs = gain / loss
        df[f"rsi_{self.rsi_period}"] = 100 - (100 / (1 + rs))
        
        # Wider Bollinger Bands
        bb_std = self.bb_std
        df["bb_mid"] = df["close"].rolling(self.bb_period).mean()
        bb_std_val = df["close"].rolling(self.bb_period).std()
        df["bb_upper"] = df["bb_mid"] + bb_std * bb_std_val
        df["bb_lower"] = df["bb_mid"] - bb_std * bb_std_val
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]
        df["bb_pct"] = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])
        
        # Keltner Channel for squeeze filter
        df["kc_mid"] = df["close"].ewm(span=self.bb_period, adjust=False).mean()
        df["kc_upper"] = df["kc_mid"] + df["atr_14"] * 1.5
        df["kc_lower"] = df["kc_mid"] - df["atr_14"] * 1.5
        df["squeeze"] = (df["bb_upper"] < df["kc_upper"]) & (df["bb_lower"] > df["kc_lower"])
        
        # Mean reversion signals
        df["rsi_oversold"] = df[f"rsi_{self.rsi_period}"] <= self.rsi_extreme_low
        df["rsi_overbought"] = df[f"rsi_{self.rsi_period}"] >= self.rsi_extreme_high
        df["bb_extreme_low"] = df["bb_pct"] <= 0.05
        df["bb_extreme_high"] = df["bb_pct"] >= 0.95
        
        # Exit signals (mean reversion target)
        df["bb_mid_touch_long"] = (df["close"] >= df["bb_mid"]) & (df["close"].shift(1) < df["bb_mid"].shift(1))
        df["bb_mid_touch_short"] = (df["close"] <= df["bb_mid"]) & (df["close"].shift(1) > df["bb_mid"].shift(1))
        
        return df

    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        if len(df) < max(self.bb_period, self.rsi_period) + 10:
            return None
        
        df = self.calculate_indicators(df)
        latest = df.iloc[-1]
        prev = df.iloc[-2]
        
        current_price = latest["close"]
        rsi = latest.get(f"rsi_{self.rsi_period}", 50)
        bb_pct = latest.get("bb_pct", 0.5)
        squeeze = latest.get("squeeze", False)
        
        rsi_oversold = latest.get("rsi_oversold", False)
        rsi_overbought = latest.get("rsi_overbought", False)
        bb_extreme_low = latest.get("bb_extreme_low", False)
        bb_extreme_high = latest.get("bb_extreme_high", False)
        
        bb_mid_touch_long = latest.get("bb_mid_touch_long", False)
        bb_mid_touch_short = latest.get("bb_mid_touch_short", False)
        
        long_score = 0
        short_score = 0
        reasons = []
        
        # Extreme oversold + BB lower band
        if rsi_oversold and bb_extreme_low:
            long_score += 3
            reasons.append(f"RSI {rsi:.0f} + BB extreme low")
        
        # Extreme overbought + BB upper band
        if rsi_overbought and bb_extreme_high:
            short_score += 3
            reasons.append(f"RSI {rsi:.0f} + BB extreme high")
        
        # RSI extreme alone
        if rsi_oversold and not bb_extreme_low:
            long_score += 1
            reasons.append(f"RSI oversold ({rsi:.0f})")
        if rsi_overbought and not bb_extreme_high:
            short_score += 1
            reasons.append(f"RSI overbought ({rsi:.0f})")
        
        # BB extreme alone
        if bb_extreme_low and not rsi_oversold:
            long_score += 1
            reasons.append(f"BB lower extreme (pct={bb_pct:.2f})")
        if bb_extreme_high and not rsi_overbought:
            short_score += 1
            reasons.append(f"BB upper extreme (pct={bb_pct:.2f})")
        
        # Squeeze = don't trade (wait for expansion)
        if squeeze:
            long_score = max(0, long_score - 1)
            short_score = max(0, short_score - 1)
            reasons.append("Squeeze - avoid")
        
        # Volume confirmation
        if latest.get("volume_ratio", 1) > 1.5:
            if long_score > short_score:
                long_score += 1
            else:
                short_score += 1
            reasons.append("Volume spike")
        
        # Quick profit target at BB mid
        if long_score >= 2:
            direction = "long"
            confidence = min(0.75, 0.4 + long_score * 0.1)
            entry = current_price
            stop = current_price * 0.97  # Tight stop for scalp
            target = latest.get("bb_mid", current_price * 1.02)  # Target BB mid
            # Ensure minimum R:R
            if (target - entry) / (entry - stop) < 1.2:
                target = entry + (entry - stop) * 1.5
        elif short_score >= 2:
            direction = "short"
            confidence = min(0.75, 0.4 + short_score * 0.1)
            entry = current_price
            stop = current_price * 1.03
            target = latest.get("bb_mid", current_price * 0.98)
            if (entry - target) / (stop - entry) < 1.2:
                target = entry - (stop - entry) * 1.5
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
                "bb_width": round(latest.get("bb_width", 0), 4),
                "squeeze": squeeze,
                "rsi_oversold": rsi_oversold,
                "rsi_overbought": rsi_overbought,
                "bb_extreme_low": bb_extreme_low,
                "bb_extreme_high": bb_extreme_high,
                "holding_periods": self.holding_periods,
                "reasons": reasons,
                "long_score": long_score,
                "short_score": short_score
            }
        )
        
        if self._validate_signal(signal):
            return signal
        return None