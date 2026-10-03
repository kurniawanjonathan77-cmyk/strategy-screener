"""Base Strategy Class"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import numpy as np


@dataclass
class Signal:
    """Trading signal output"""
    symbol: str
    strategy: str
    direction: str  # "long" or "short"
    entry_price: float
    stop_loss: float
    take_profit: float
    confidence: float  # 0-1
    risk_reward: float
    timestamp: datetime
    metadata: Dict[str, Any]
    
    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "strategy": self.strategy,
            "direction": self.direction,
            "entry_price": round(self.entry_price, 6),
            "stop_loss": round(self.stop_loss, 6),
            "take_profit": round(self.take_profit, 6),
            "confidence": round(self.confidence, 3),
            "risk_reward": round(self.risk_reward, 2),
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata
        }


@dataclass
class BacktestResult:
    """Backtest performance metrics"""
    strategy: str
    symbol: str
    total_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    expectancy: float
    sharpe_ratio: float
    max_drawdown: float
    total_return: float
    params: Dict


class BaseStrategy(ABC):
    """Abstract base class for all strategies"""
    
    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config.get("strategies", {}).get(name, {})
        self.params = self.config.get("params", {})
        self.enabled = self.config.get("enabled", True)
        self.weight = self.config.get("weight", 1.0)
        self.min_score = self.config.get("min_score", 0.5)
    
    @abstractmethod
    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add strategy-specific indicators to dataframe"""
        pass
    
    @abstractmethod
    def generate_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Signal]:
        """Generate trading signal from latest data. df.index[-1] should be used for timestamp."""
        pass
    
    def backtest(self, df: pd.DataFrame, symbol: str) -> Optional[BacktestResult]:
        """Run walk-forward backtest (implemented in backtest engine)"""
        return None
    
    def _calculate_risk_reward(self, entry: float, stop: float, target: float) -> float:
        risk = abs(entry - stop)
        reward = abs(target - entry)
        return reward / risk if risk > 0 else 0
    
    def _validate_signal(self, signal: Signal) -> bool:
        """Basic signal validation"""
        if signal.confidence < self.min_score:
            return False
        if signal.risk_reward < 1.0:
            return False
        return True


def add_common_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add common technical indicators using pandas-ta"""
    df = df.copy()
    
    # Returns
    df["returns"] = df["close"].pct_change()
    df["log_returns"] = np.log(df["close"] / df["close"].shift(1))
    
    # Moving averages
    for period in [9, 12, 20, 26, 50, 200]:
        df[f"sma_{period}"] = df["close"].rolling(period).mean()
        df[f"ema_{period}"] = df["close"].ewm(span=period, adjust=False).mean()
    
    # RSI
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df["rsi_14"] = 100 - (100 / (1 + rs))
    
    # MACD
    ema_12 = df["close"].ewm(span=12, adjust=False).mean()
    ema_26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema_12 - ema_26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    
    # Bollinger Bands
    bb_period = 20
    bb_std = 2
    df["bb_mid"] = df["close"].rolling(bb_period).mean()
    bb_std_val = df["close"].rolling(bb_period).std()
    df["bb_upper"] = df["bb_mid"] + bb_std * bb_std_val
    df["bb_lower"] = df["bb_mid"] - bb_std * bb_std_val
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]
    df["bb_pct"] = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])
    
    # ATR
    high_low = df["high"] - df["low"]
    high_close = np.abs(df["high"] - df["close"].shift())
    low_close = np.abs(df["low"] - df["close"].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr_14"] = tr.rolling(14).mean()
    
    # Donchian Channels
    for period in [20, 50]:
        df[f"donchian_high_{period}"] = df["high"].rolling(period).max()
        df[f"donchian_low_{period}"] = df["low"].rolling(period).min()
        df[f"donchian_mid_{period}"] = (df[f"donchian_high_{period}"] + df[f"donchian_low_{period}"]) / 2
    
    # Volume indicators
    df["volume_sma_20"] = df["volume"].rolling(20).mean()
    df["volume_ratio"] = df["volume"] / df["volume_sma_20"]
    
    # ROC (Rate of Change)
    for period in [5, 10, 20]:
        df[f"roc_{period}"] = df["close"].pct_change(period)
    
    # Z-Score
    for period in [20, 50]:
        mean = df["close"].rolling(period).mean()
        std = df["close"].rolling(period).std()
        df[f"zscore_{period}"] = (df["close"] - mean) / std
    
    return df