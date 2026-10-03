"""Backtest Metrics Calculation"""

import numpy as np
import pandas as pd


def calculate_metrics(trades: pd.DataFrame, initial_capital: float = 10000) -> dict:
    """Calculate comprehensive backtest metrics"""
    if trades.empty:
        return {
            "total_trades": 0,
            "win_rate": 0,
            "avg_win": 0,
            "avg_loss": 0,
            "profit_factor": 0,
            "expectancy": 0,
            "sharpe_ratio": 0,
            "max_drawdown": 0,
            "total_return": 0,
            "equity_curve": []
        }
    
    # Basic stats
    total_trades = len(trades)
    wins = trades[trades["pnl"] > 0]
    losses = trades[trades["pnl"] < 0]
    
    win_rate = len(wins) / total_trades if total_trades > 0 else 0
    avg_win = wins["pnl"].mean() if len(wins) > 0 else 0
    avg_loss = losses["pnl"].mean() if len(losses) > 0 else 0
    
    # Profit factor
    gross_profit = wins["pnl"].sum() if len(wins) > 0 else 0
    gross_loss = abs(losses["pnl"].sum()) if len(losses) > 0 else 1
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
    
    # Expectancy
    expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)
    
    # Equity curve
    equity = initial_capital
    equity_curve = [equity]
    for pnl in trades["pnl"]:
        equity += pnl
        equity_curve.append(equity)
    
    equity_series = pd.Series(equity_curve)
    
    # Returns
    returns = equity_series.pct_change().dropna()
    
    # Sharpe ratio (assuming daily)
    if returns.std() > 0:
        sharpe_ratio = returns.mean() / returns.std() * np.sqrt(252)
    else:
        sharpe_ratio = 0
    
    # Max drawdown
    running_max = equity_series.expanding().max()
    drawdown = (equity_series - running_max) / running_max
    max_drawdown = drawdown.min()
    
    # Total return
    total_return = (equity - initial_capital) / initial_capital
    
    return {
        "total_trades": int(total_trades),
        "win_rate": round(win_rate, 4),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "profit_factor": round(profit_factor, 2),
        "expectancy": round(expectancy, 4),
        "sharpe_ratio": round(sharpe_ratio, 2),
        "max_drawdown": round(max_drawdown, 4),
        "total_return": round(total_return, 4),
        "equity_curve": [round(v, 2) for v in equity_curve]
    }


def calculate_trade_pnl(entry: float, exit: float, direction: str, size: float = 1.0) -> float:
    """Calculate PnL for a single trade"""
    if direction == "long":
        return (exit - entry) * size
    else:
        return (entry - exit) * size