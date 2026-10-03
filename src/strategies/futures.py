"""Futures Analysis Module - Leverage, Liquidation, Margin, Funding Rates"""

from dataclasses import dataclass
from typing import Dict, Optional
import math


@dataclass
class FuturesMetrics:
    """Complete futures analysis metrics for a signal"""
    
    # Position sizing
    suggested_leverage: int              # Conservative recommended leverage
    max_safe_leverage: int               # Maximum before liq hits SL
    
    # Liquidation
    liq_price_long: float                # Liquidation price for long
    liq_price_short: float               # Liquidation price for short
    liq_buffer_pct: float                # % buffer from SL to liq price
    
    # Margin
    initial_margin_pct: float            # Initial margin % (1/leverage)
    maintenance_margin_pct: float        # Maintenance margin %
    margin_required_usdt: float          # USDT needed for position
    
    # Returns (Spot vs Futures)
    spot_return_at_tp: float             # % return if spot
    spot_return_at_sl: float             # % return if spot
    futures_return_at_tp: float          # % return with leverage
    futures_return_at_sl: float          # % return with leverage
    roe_at_tp: float                     # Return on Equity at TP
    roe_at_sl: float                     # Return on Equity at SL
    
    # Funding
    funding_rate_8h: float               # Current funding rate (8h)
    funding_rate_daily: float            # Estimated daily funding cost
    funding_cost_to_tp: float            # Total funding cost to reach TP (assuming avg hold time)
    
    # Risk metrics
    max_drawdown_estimate: float         # Estimated max DD with leverage
    liquidation_risk_score: float        # 0-1 risk score
    
    # Position sizing
    position_size_usdt: float            # Notional position size
    margin_used_usdt: float              # Margin locked
    available_margin_usdt: float         # Free margin after position


class FuturesCalculator:
    """Calculate all futures-related metrics for a trading signal"""
    
    # Binance default maintenance margins (varies by symbol)
    MAINTENANCE_MARGIN_RATES = {
        "default": 0.005,      # 0.5% default
        "BTCUSDT": 0.004,      # 0.4%
        "ETHUSDT": 0.005,      # 0.5%
        "SOLUSDT": 0.005,
    }
    
    # Typical funding rates (annualized estimates)
    FUNDING_RATE_ESTIMATES = {
        "BTCUSDT": 0.0001,     # 0.01% per 8h
        "ETHUSDT": 0.0001,
        "default": 0.0002,     # 0.02% per 8h for alts
    }
    
    def __init__(self, config: dict = None):
        self.config = config or {}
        self.execution_config = self.config.get("execution", {})
        self.risk_config = self.config.get("risk", {})
        
        # Defaults
        self.default_leverage = self.execution_config.get("leverage", 1)
        self.max_leverage = self.risk_config.get("max_leverage", 5)
        self.liq_buffer = self.risk_config.get("liq_buffer_pct", 0.10)
        self.margin_mode = self.execution_config.get("margin_mode", "isolated")
        
    def calculate(self, 
                  entry_price: float,
                  stop_loss: float,
                  take_profit: float,
                  direction: str,           # "long" or "short"
                  symbol: str,
                  portfolio_value: float,
                  position_size_pct: float = 0.02,
                  current_funding_rate: float = None) -> FuturesMetrics:
        """
        Calculate all futures metrics for a signal
        """
        # 1. Basic distances
        sl_distance = abs(entry_price - stop_loss) / entry_price
        tp_distance = abs(take_profit - entry_price) / entry_price
        
        # 2. Leverage calculations
        max_safe_leverage = self._calc_max_safe_leverage(sl_distance)
        suggested_leverage = min(
            max(2, int(max_safe_leverage * 0.5)),  # 50% of max safe
            self.max_leverage
        )
        leverage = max(suggested_leverage, self.default_leverage, 1)
        
        # 3. Liquidation prices
        liq_price_long, liq_price_short = self._calc_liquidation_prices(
            entry_price, leverage, symbol
        )
        
        # 4. Margin calculations
        initial_margin_pct = 1.0 / leverage
        maintenance_margin_pct = self._get_maintenance_margin(symbol)
        margin_required = entry_price * position_size_pct * portfolio_value * initial_margin_pct
        
        # 5. Returns
        spot_return_tp = tp_distance * (1 if direction == "long" else -1)
        spot_return_sl = -sl_distance * (1 if direction == "long" else -1)
        
        futures_return_tp = spot_return_tp * leverage
        futures_return_sl = spot_return_sl * leverage
        
        roe_at_tp = futures_return_tp * 100
        roe_at_sl = futures_return_sl * 100
        
        # 6. Funding costs
        funding_rate = current_funding_rate or self._estimate_funding_rate(symbol)
        avg_hold_hours = self._estimate_hold_time(sl_distance, tp_distance)
        funding_periods = avg_hold_hours / 8
        funding_cost_to_tp = funding_rate * funding_periods * leverage * 100  # % of equity
        
        # 7. Liquidation buffer
        if direction == "long":
            liq_buffer = (stop_loss - liq_price_long) / stop_loss if liq_price_long < stop_loss else 0
        else:
            liq_buffer = (liq_price_short - stop_loss) / stop_loss if liq_price_short > stop_loss else 0
        
        # 8. Risk scoring
        liq_risk = self._calc_liquidation_risk(liq_buffer, leverage, funding_rate)
        
        # 9. Position sizing
        position_notional = portfolio_value * position_size_pct
        margin_used = position_notional * initial_margin_pct
        available_margin = portfolio_value - margin_used
        
        return FuturesMetrics(
            suggested_leverage=suggested_leverage,
            max_safe_leverage=max_safe_leverage,
            liq_price_long=liq_price_long,
            liq_price_short=liq_price_short,
            liq_buffer_pct=liq_buffer * 100,
            initial_margin_pct=initial_margin_pct * 100,
            maintenance_margin_pct=maintenance_margin_pct * 100,
            margin_required_usdt=margin_required,
            spot_return_at_tp=spot_return_tp * 100,
            spot_return_at_sl=spot_return_sl * 100,
            futures_return_at_tp=futures_return_tp * 100,
            futures_return_at_sl=futures_return_sl * 100,
            roe_at_tp=roe_at_tp,
            roe_at_sl=roe_at_sl,
            funding_rate_8h=funding_rate * 100,
            funding_rate_daily=funding_rate * 3 * 100,
            funding_cost_to_tp=funding_cost_to_tp,
            max_drawdown_estimate=abs(futures_return_sl) * 100,
            liquidation_risk_score=liq_risk,
            position_size_usdt=position_notional,
            margin_used_usdt=margin_used,
            available_margin_usdt=available_margin
        )
    
    def _calc_max_safe_leverage(self, sl_distance: float) -> int:
        """Max leverage before liquidation hits stop loss"""
        # Liq price = entry * (1 - 1/leverage) for long
        # Want: liq_price < stop_loss (for long)
        # entry * (1 - 1/lev) < entry * (1 - sl_distance)
        # 1 - 1/lev < 1 - sl_distance
        # 1/lev > sl_distance
        # lev < 1/sl_distance
        max_lev = 1.0 / sl_distance
        # Apply safety buffer
        max_lev = max_lev * (1 - self.liq_buffer)
        return max(1, int(max_lev))
    
    def _calc_liquidation_prices(self, entry: float, leverage: int, symbol: str) -> tuple:
        """Calculate liquidation prices for long and short"""
        mmr = self._get_maintenance_margin(symbol)
        # Long: liq = entry * (1 - 1/lev + mmr)
        # Short: liq = entry * (1 + 1/lev - mmr)
        liq_long = entry * (1 - 1/leverage + mmr)
        liq_short = entry * (1 + 1/leverage - mmr)
        return liq_long, liq_short
    
    def _get_maintenance_margin(self, symbol: str) -> float:
        return self.MAINTENANCE_MARGIN_RATES.get(symbol, self.MAINTENANCE_MARGIN_RATES["default"])
    
    def _estimate_funding_rate(self, symbol: str) -> float:
        return self.FUNDING_RATE_ESTIMATES.get(symbol, self.FUNDING_RATE_ESTIMATES["default"])
    
    def _estimate_hold_time(self, sl_dist: float, tp_dist: float) -> float:
        """Estimate average hold time in hours based on volatility"""
        # Simplified: assume 50% hit TP, 50% hit SL
        # Time proportional to distance / volatility
        avg_dist = (sl_dist + tp_dist) / 2
        # Rough estimate: 1% move ~ 4 hours in crypto
        return max(4, min(72, avg_dist * 400))  # 4h to 72h
    
    def _calc_liquidation_risk(self, liq_buffer: float, leverage: int, funding_rate: float) -> float:
        """0-1 risk score"""
        risk = 0.0
        
        # Leverage risk
        if leverage >= 20: risk += 0.4
        elif leverage >= 10: risk += 0.25
        elif leverage >= 5: risk += 0.1
        
        # Liquidation buffer risk
        if liq_buffer < 0.02: risk += 0.3      # <2% buffer
        elif liq_buffer < 0.05: risk += 0.2    # <5% buffer
        elif liq_buffer < 0.10: risk += 0.1    # <10% buffer
        
        # Funding risk (for shorts paying funding)
        if funding_rate > 0.001: risk += 0.1   # High funding
        
        return min(1.0, risk)


def add_futures_to_signal(signal_dict: dict, config: dict, portfolio_value: float = 10000) -> dict:
    """Add futures metrics to existing signal dict"""
    calc = FuturesCalculator(config)
    
    metrics = calc.calculate(
        entry_price=signal_dict["entry_price"],
        stop_loss=signal_dict["stop_loss"],
        take_profit=signal_dict["take_profit"],
        direction=signal_dict["direction"],
        symbol=signal_dict["symbol"],
        portfolio_value=portfolio_value,
        position_size_pct=signal_dict.get("metadata", {}).get("position_size_pct", 0.02)
    )
    
    # Add to metadata
    if "metadata" not in signal_dict:
        signal_dict["metadata"] = {}
    
    signal_dict["metadata"]["futures"] = {
        "leverage": {
            "suggested": metrics.suggested_leverage,
            "max_safe": metrics.max_safe_leverage,
            "current": max(metrics.suggested_leverage, config.get("execution", {}).get("leverage", 1))
        },
        "liquidation": {
            "long_price": round(metrics.liq_price_long, 2),
            "short_price": round(metrics.liq_price_short, 2),
            "buffer_from_sl_pct": round(metrics.liq_buffer_pct, 2)
        },
        "margin": {
            "initial_pct": round(metrics.initial_margin_pct, 2),
            "maintenance_pct": round(metrics.maintenance_margin_pct, 3),
            "required_usdt": round(metrics.margin_required_usdt, 2),
            "mode": config.get("execution", {}).get("margin_mode", "isolated")
        },
        "returns": {
            "spot_tp_pct": round(metrics.spot_return_at_tp, 2),
            "spot_sl_pct": round(metrics.spot_return_at_sl, 2),
            "futures_tp_pct": round(metrics.futures_return_at_tp, 2),
            "futures_sl_pct": round(metrics.futures_return_at_sl, 2),
            "roe_tp_pct": round(metrics.roe_at_tp, 2),
            "roe_sl_pct": round(metrics.roe_at_sl, 2)
        },
        "funding": {
            "rate_8h_pct": round(metrics.funding_rate_8h, 4),
            "rate_daily_pct": round(metrics.funding_rate_daily, 4),
            "cost_to_tp_pct": round(metrics.funding_cost_to_tp, 4)
        },
        "risk": {
            "max_dd_estimate_pct": round(metrics.max_drawdown_estimate, 2),
            "liquidation_risk_score": round(metrics.liquidation_risk_score, 2),
            "risk_level": "HIGH" if metrics.liquidation_risk_score > 0.5 else "MEDIUM" if metrics.liquidation_risk_score > 0.25 else "LOW"
        },
        "position": {
            "notional_usdt": round(metrics.position_size_usdt, 2),
            "margin_used_usdt": round(metrics.margin_used_usdt, 2),
            "free_margin_usdt": round(metrics.available_margin_usdt, 2)
        }
    }
    
    return signal_dict