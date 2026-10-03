"""Walk-Forward Backtest Engine"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from loguru import logger

from src.strategies.base import BaseStrategy, Signal
from src.backtest.metrics import calculate_metrics, calculate_trade_pnl


class WalkForwardBacktest:
    def __init__(self, config: dict):
        self.config = config["backtest"]
        self.wf_config = self.config["walk_forward"]
        self.metrics_config = self.config["metrics"]
        
        self.train_window = self.wf_config["train_window_days"]
        self.test_window = self.wf_config["test_window_days"]
        self.step = self.wf_config["step_days"]
        self.min_train_samples = self.wf_config["min_train_samples"]
        
        self.min_trades = self.metrics_config["min_trades"]
        self.max_dd = self.metrics_config["max_drawdown"]
        self.min_sharpe = self.metrics_config["min_sharpe"]
        self.min_wr = self.metrics_config["min_win_rate"]
        self.min_pf = self.metrics_config["min_profit_factor"]
        self.min_expectancy = self.metrics_config["min_expectancy"]

    def run(self, strategy: BaseStrategy, df: pd.DataFrame, symbol: str) -> Optional[Dict]:
        """Run walk-forward backtest"""
        # Convert days to bars (assuming hourly data)
        bars_per_day = 24
        train_window = self.train_window * bars_per_day
        test_window = self.test_window * bars_per_day
        step = self.step * bars_per_day
        
        if len(df) < train_window + test_window + 50:
            logger.warning(f"{symbol}: Insufficient data for walk-forward")
            return None
        
        # Prepare data with indicators
        df = strategy.calculate_indicators(df)
        
        all_trades = []
        window_results = []
        
        # Walk-forward windows
        for i in range(0, len(df) - train_window - test_window, step):
            train_end = i + train_window
            test_end = train_end + test_window
            
            if test_end > len(df):
                break
            
            train_df = df.iloc[i:train_end].copy()
            test_df = df.iloc[train_end:test_end].copy()
            
            if len(train_df) < self.min_train_samples:
                continue
            
            # Generate signals on test period using train-fitted params
            # (In real implementation, would optimize params on train)
            test_trades = self._simulate_trades(strategy, test_df, symbol)
            
            if test_trades:
                all_trades.extend(test_trades)
                window_metrics = calculate_metrics(pd.DataFrame(test_trades))
                window_results.append({
                    "window_start": test_df.index[0].isoformat(),
                    "window_end": test_df.index[-1].isoformat(),
                    **window_metrics
                })
        
        if not all_trades:
            return None
        
        # Aggregate metrics
        trades_df = pd.DataFrame(all_trades)
        overall_metrics = calculate_metrics(trades_df)
        
        # Filter by minimum criteria
        passes = self._passes_filters(overall_metrics)
        
        return {
            "strategy": strategy.name,
            "symbol": symbol,
            "overall": overall_metrics,
            "windows": window_results,
            "trades": all_trades[-50:],
            "passes_filters": passes
        }

    def _simulate_trades(self, strategy: BaseStrategy, df: pd.DataFrame, symbol: str) -> List[Dict]:
        """Simulate trades for a test window"""
        trades = []
        position = None
        entry_price = 0
        entry_time = None
        direction = None
        
        # Default risk params
        stop_loss_pct = 0.05
        take_profit_pct = 0.10
        
        for i in range(1, len(df)):
            current = df.iloc[i]
            prev = df.iloc[i-1]
            
            # Check exit conditions first
            if position is not None:
                exit_price, exit_reason = self._check_exit(
                    position, entry_price, current, stop_loss_pct, take_profit_pct
                )
                if exit_price:
                    pnl = calculate_trade_pnl(entry_price, exit_price, direction)
                    trades.append({
                        "symbol": symbol,
                        "strategy": strategy.name,
                        "direction": direction,
                        "entry_time": entry_time.isoformat(),
                        "exit_time": current.name.isoformat(),
                        "entry_price": round(entry_price, 6),
                        "exit_price": round(exit_price, 6),
                        "pnl": round(pnl, 2),
                        "exit_reason": exit_reason,
                        "return_pct": round(pnl / entry_price * 100, 2)
                    })
                    position = None
                    continue
            
            # Generate new signal
            # Use data up to current bar (no lookahead)
            signal_df = df.iloc[:i+1].copy()
            signal = strategy.generate_signal(signal_df, symbol)
            
            if signal and position is None:
                position = "open"
                entry_price = signal.entry_price
                entry_time = signal.timestamp
                direction = signal.direction
                # Use signal's stop/target
                stop_loss_pct = abs(signal.stop_loss - signal.entry_price) / signal.entry_price
                take_profit_pct = abs(signal.take_profit - signal.entry_price) / signal.entry_price
        
        # Close any open position at end
        if position is not None:
            last = df.iloc[-1]
            pnl = calculate_trade_pnl(entry_price, last["close"], direction)
            trades.append({
                "symbol": symbol,
                "strategy": strategy.name,
                "direction": direction,
                "entry_time": entry_time.isoformat(),
                "exit_time": last.name.isoformat(),
                "entry_price": round(entry_price, 6),
                "exit_price": round(last["close"], 6),
                "pnl": round(pnl, 2),
                "exit_reason": "end_of_window",
                "return_pct": round(pnl / entry_price * 100, 2)
            })
        
        return trades

    def _check_exit(self, position: str, entry: float, current: pd.Series, 
                    sl_pct: float, tp_pct: float) -> Tuple[Optional[float], str]:
        """Check stop loss / take profit"""
        high = current["high"]
        low = current["low"]
        close = current["close"]
        
        if position == "long":
            stop_price = entry * (1 - sl_pct)
            target_price = entry * (1 + tp_pct)
            
            if low <= stop_price:
                return stop_price, "stop_loss"
            if high >= target_price:
                return target_price, "take_profit"
        else:  # short
            stop_price = entry * (1 + sl_pct)
            target_price = entry * (1 - tp_pct)
            
            if high >= stop_price:
                return stop_price, "stop_loss"
            if low <= target_price:
                return target_price, "take_profit"
        
        return None, ""

    def _passes_filters(self, metrics: dict) -> bool:
        """Check if strategy passes minimum criteria"""
        checks = [
            metrics["total_trades"] >= self.min_trades,
            metrics["max_drawdown"] >= -self.max_dd,
            metrics["sharpe_ratio"] >= self.min_sharpe,
            metrics["win_rate"] >= self.min_wr,
            metrics["profit_factor"] >= self.min_pf,
            metrics["expectancy"] >= self.min_expectancy,
        ]
        return all(checks)


def run_symbol_backtest(strategy: BaseStrategy, df: pd.DataFrame, symbol: str, config: dict) -> Optional[Dict]:
    """Convenience function"""
    backtest = WalkForwardBacktest(config)
    return backtest.run(strategy, df, symbol)