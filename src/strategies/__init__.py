"""Strategies"""
from src.strategies.base import BaseStrategy, Signal, BacktestResult, add_common_indicators
from src.strategies.mean_reversion import MeanReversionStrategy
from src.strategies.momentum import MomentumStrategy
from src.strategies.breakout import BreakoutStrategy
from src.strategies.volatility import VolatilityStrategy
from src.strategies.trend_following import TrendFollowingStrategy
from src.strategies.volume_breakout import VolumeBreakoutStrategy
from src.strategies.mean_reversion_scalp import MeanReversionScalpStrategy

__all__ = [
    "BaseStrategy",
    "Signal",
    "BacktestResult",
    "add_common_indicators",
    "MeanReversionStrategy",
    "MomentumStrategy",
    "BreakoutStrategy",
    "VolatilityStrategy",
    "TrendFollowingStrategy",
    "VolumeBreakoutStrategy",
    "MeanReversionScalpStrategy"
]