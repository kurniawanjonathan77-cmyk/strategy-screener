"""Main Screener Orchestrator"""

import asyncio
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set

import pandas as pd
from loguru import logger

from src.data.coingecko import CoinGeckoClient
from src.data.polymarket import PolymarketClient
from src.data.binance import BinanceClient
from src.data.cache import Cache, JSONCache
from src.strategies import (
    MeanReversionStrategy,
    MomentumStrategy,
    BreakoutStrategy,
    VolatilityStrategy,
    TrendFollowingStrategy,
    VolumeBreakoutStrategy,
    MeanReversionScalpStrategy
)
from src.strategies.futures import add_futures_to_signal
from src.backtest.engine import run_symbol_backtest
from src.dashboard.generate import generate_dashboard


class StrategyScreener:
    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
        
        self.setup_logging()
        
        # Data clients
        self.coingecko = CoinGeckoClient(self.config)
        self.binance = BinanceClient(self.config)
        self.polymarket = PolymarketClient(self.config)
        self.json_cache = JSONCache("docs")
        
        # Strategies
        self.strategies = self._init_strategies()
        
        # Results storage
        self.all_signals = []
        self.all_backtests = []
        self.discovered_symbols: Set[str] = set()

    def setup_logging(self):
        logger.remove()
        logger.add("logs/screener.log", rotation="1 day", retention="7 days")
        logger.add(lambda msg: print(msg), level="INFO")

    def _init_strategies(self) -> Dict:
        strategies = {}
        strat_configs = self.config["strategies"]
        
        if strat_configs["mean_reversion"]["enabled"]:
            strategies["mean_reversion"] = MeanReversionStrategy(self.config)
        if strat_configs["momentum"]["enabled"]:
            strategies["momentum"] = MomentumStrategy(self.config)
        if strat_configs["breakout"]["enabled"]:
            strategies["breakout"] = BreakoutStrategy(self.config)
        if strat_configs["volatility"]["enabled"]:
            strategies["volatility"] = VolatilityStrategy(self.config)
        if strat_configs["trend_following"]["enabled"]:
            strategies["trend_following"] = TrendFollowingStrategy(self.config)
        if strat_configs["volume_breakout"]["enabled"]:
            strategies["volume_breakout"] = VolumeBreakoutStrategy(self.config)
        if strat_configs["mean_reversion_scalp"]["enabled"]:
            strategies["mean_reversion_scalp"] = MeanReversionScalpStrategy(self.config)
        return strategies

    async def run_screening(self):
        """Main screening loop"""
        logger.info("Starting strategy screening...")
        
        # 1. Discover symbols dynamically
        await self._discover_symbols()
        
        # 2. Fetch market data for discovered symbols
        market_data = await self._fetch_market_data()
        logger.info(f"Got market data for {len(market_data)} symbols")
        
        # 3. Fetch Polymarket data
        pm_markets = []
        if self.config["data"]["polymarket"]["enabled"]:
            logger.info("Fetching Polymarket data...")
            pm_markets = await self.polymarket.get_markets()
            logger.info(f"Got {len(pm_markets)} Polymarket markets")
        
        # 4. Run backtests
        logger.info("Running backtests...")
        await self._run_backtests(market_data)
        
        # 5. Generate current signals
        logger.info("Generating signals...")
        await self._generate_signals(market_data, pm_markets)
        
        # 6. Generate dashboard
        logger.info("Generating dashboard...")
        generate_dashboard(
            signals=self.all_signals,
            backtests=self.all_backtests,
            config=self.config,
            output_dir="docs"
        )
        
        # 7. Save JSON for API
        self._save_json_output()
        
        logger.info("Screening complete!")

    async def _discover_symbols(self):
        """Discover symbols from multiple sources and modes"""
        discovery_cfg = self.config["data"]["discovery"]
        
        if not discovery_cfg["enabled"]:
            logger.info("Symbol discovery disabled, using static CoinGecko symbols")
            return
        
        all_symbols: Set[str] = set()
        binance_success = False
        
        # Binance discovery
        if discovery_cfg["primary_source"] == "binance":
            modes = discovery_cfg["modes"]
            
            for mode in modes:
                try:
                    symbols = await self.binance.discover_symbols(mode)
                    all_symbols.update(symbols)
                    logger.info(f"  {mode}: {len(symbols)} symbols")
                    binance_success = True
                except Exception as e:
                    logger.error(f"Binance discovery error for {mode}: {e}")
        
        # Fallback to CoinGecko if Binance fails
        if not binance_success or len(all_symbols) < 10:
            logger.info("Binance discovery failed or insufficient symbols, falling back to CoinGecko...")
            try:
                cg_data = await self.coingecko.get_all_markets()
                for symbol in cg_data.keys():
                    binance_sym = self._cg_to_binance(symbol)
                    all_symbols.add(binance_sym)
                logger.info(f"CoinGecko fallback: {len(all_symbols)} symbols")
            except Exception as e:
                logger.error(f"CoinGecko fallback also failed: {e}")
        
        # Apply filters
        all_symbols = self._filter_symbols(all_symbols, discovery_cfg)
        
        # Limit total
        max_symbols = discovery_cfg["max_total_symbols"]
        if len(all_symbols) > max_symbols:
            all_symbols = set(list(all_symbols)[:max_symbols])
        
        self.discovered_symbols = all_symbols
        logger.info(f"Total discovered symbols: {len(self.discovered_symbols)}")

    def _filter_symbols(self, symbols: Set[str], discovery_cfg: dict) -> Set[str]:
        """Apply exclusion filters"""
        filtered = set()
        
        for sym in symbols:
            # Exclude stablecoins
            if discovery_cfg["exclude_stablecoins"]:
                stable_suffixes = ["USDT", "USDC", "BUSD", "TUSD", "FDUSD", "PYUSD"]
                base = sym.replace("USDT", "").replace("USDC", "").replace("BUSD", "")
                if base in ["USDT", "USDC", "BUSD", "TUSD", "FDUSD", "PYUSD", "DAI"]:
                    continue
            
            # Exclude leverage tokens
            if discovery_cfg["exclude_leverage_tokens"]:
                if any(x in sym for x in ["UP", "DOWN", "BULL", "BEAR", "3L", "3S", "5L", "5S"]):
                    continue
            
            # Min price filter (handled later with market data)
            filtered.add(sym)
        
        return filtered

    async def _fetch_market_data(self) -> Dict[str, pd.DataFrame]:
        """Fetch market data for all discovered symbols"""
        market_data = {}
        binance_cfg = self.config["data"]["binance"]
        interval = binance_cfg.get("interval", "1h")
        days = binance_cfg.get("days_history", 90)
        min_price = self.config["data"]["discovery"].get("min_price_usd", 0.000001)
        
        # Fetch from Binance
        symbols_list = list(self.discovered_symbols)
        logger.info(f"Fetching Binance data for {len(symbols_list)} symbols...")
        
        # Process in batches to avoid rate limits
        batch_size = 20
        for i in range(0, len(symbols_list), batch_size):
            batch = symbols_list[i:i+batch_size]
            try:
                batch_data = await self.binance.get_multiple_market_data(batch, interval, days)
                
                # Filter by min price
                for symbol, data in batch_data.items():
                    if data.current_price >= min_price:
                        market_data[symbol] = data.ohlcv
                    else:
                        logger.debug(f"Filtered {symbol}: price ${data.current_price:.8f} < ${min_price}")
                        
            except Exception as e:
                logger.error(f"Batch fetch error: {e}")
            
            # Small delay between batches
            if i + batch_size < len(symbols_list):
                await asyncio.sleep(0.5)
        
        # Also fetch major coins from CoinGecko for comparison
        if self.config["data"]["coingecko"]["enabled"]:
            try:
                cg_data = await self.coingecko.get_all_markets()
                for symbol, data in cg_data.items():
                    # Convert CoinGecko symbol to Binance format
                    binance_symbol = self._cg_to_binance(symbol)
                    if binance_symbol not in market_data:
                        market_data[binance_symbol] = data.ohlcv
            except Exception as e:
                logger.error(f"CoinGecko fetch error: {e}")
        
        logger.info(f"Final market data: {len(market_data)} symbols")
        return market_data

    def _cg_to_binance(self, cg_symbol: str) -> str:
        """Convert CoinGecko symbol to Binance format"""
        mapping = {
            "bitcoin": "BTCUSDT",
            "ethereum": "ETHUSDT",
            "solana": "SOLUSDT",
            "bonk": "BONKUSDT",
            "dogwifhat": "WIFUSDT",
            "popcat": "POPCATUSDT",
            "jupiter-exchange-solana": "JUPUSDT",
            "render-token": "RENDERUSDT",
            "fetch-ai": "FETUSDT",
            "near": "NEARUSDT",
        }
        return mapping.get(cg_symbol, cg_symbol.upper() + "USDT")

    async def _run_backtests(self, market_data: Dict):
        """Run backtests for all strategy/symbol combinations"""
        for strategy_name, strategy in self.strategies.items():
            logger.info(f"Backtesting {strategy_name}...")
            
            for symbol, df in market_data.items():
                if len(df) < 100:  # Need minimum data
                    continue
                    
                try:
                    result = run_symbol_backtest(strategy, df, symbol, self.config)
                    if result:
                        self.all_backtests.append(result)
                        logger.debug(f"  {symbol}: {result['overall']['total_trades']} trades, "
                                   f"WR={result['overall']['win_rate']:.1%}, "
                                   f"Exp={result['overall']['expectancy']:.4f}")
                except Exception as e:
                    logger.error(f"Backtest error {strategy_name}/{symbol}: {e}")

    async def _generate_signals(self, market_data: Dict, pm_markets: List):
        """Generate current signals for all markets"""
        screening_cfg = self.config["screening"]
        
        # Crypto signals
        for symbol, df in market_data.items():
            if len(df) < 30:
                continue
                
            for strategy_name, strategy in self.strategies.items():
                try:
                    signal = strategy.generate_signal(df, symbol)
                    if signal and signal.confidence >= screening_cfg["min_confidence"]:
                        if signal.risk_reward >= screening_cfg["min_risk_reward"]:
                            # Add backtest performance to signal
                            bt_perf = self._get_backtest_perf(strategy_name, symbol)
                            signal.metadata["backtest"] = bt_perf
                            signal.metadata["source"] = "binance"
                            signal.metadata["position_size_pct"] = self.config["screening"].get("default_position_size_pct", 0.02)
                            
                            # Add futures analysis
                            if self.config.get("futures", {}).get("enabled", False):
                                signal_dict = signal.to_dict()
                                portfolio_value = self.config.get("futures", {}).get("portfolio_value_usdt", 100)
                                signal_dict = add_futures_to_signal(signal_dict, self.config, portfolio_value)
                                signal.metadata.update(signal_dict["metadata"])
                            
                            self.all_signals.append(signal)
                except Exception as e:
                    logger.error(f"Signal error {strategy_name}/{symbol}: {e}")
        
        # Polymarket signals (mispricing)
        for market in pm_markets:
            misprice = self.polymarket.find_mispricing(market)
            if misprice:
                from src.strategies.base import Signal
                signal = Signal(
                    symbol=market.condition_id,
                    strategy="polymarket_arb",
                    direction=misprice["direction"],
                    entry_price=list(misprice["prices"].values())[0],
                    stop_loss=list(misprice["prices"].values())[0] * 0.98,
                    take_profit=list(misprice["prices"].values())[0] * 1.02,
                    confidence=min(0.9, misprice["edge_pct"] / 5),
                    risk_reward=1.0,
                    timestamp=datetime.utcnow(),
                    metadata={
                        "market_question": market.question,
                        "outcomes": misprice["outcomes"],
                        "prices": misprice["prices"],
                        "edge_pct": misprice["edge_pct"],
                        "volume_24h": misprice["volume_24h"],
                        "liquidity": misprice["liquidity"],
                        "source": "polymarket"
                    }
                )
                if signal.confidence >= screening_cfg["min_confidence"]:
                    self.all_signals.append(signal)
        
        # Sort signals by confidence * expectancy
        self.all_signals.sort(
            key=lambda s: s.confidence * s.metadata.get("backtest", {}).get("expectancy", 0),
            reverse=True
        )
        
        # Limit to top N
        self.all_signals = self.all_signals[:screening_cfg["top_n"]]
        
        logger.info(f"Generated {len(self.all_signals)} signals")

    def _get_backtest_perf(self, strategy: str, symbol: str) -> dict:
        """Get backtest performance for strategy/symbol"""
        for bt in self.all_backtests:
            if bt["strategy"] == strategy and bt["symbol"] == symbol:
                return {
                    "win_rate": bt["overall"]["win_rate"],
                    "expectancy": bt["overall"]["expectancy"],
                    "sharpe": bt["overall"]["sharpe_ratio"],
                    "max_dd": bt["overall"]["max_drawdown"],
                    "total_trades": bt["overall"]["total_trades"]
                }
        return {}

    def _save_json_output(self):
        """Save signals and backtests as JSON"""
        signals_data = [s.to_dict() for s in self.all_signals]
        backtests_data = []
        for bt in self.all_backtests:
            backtests_data.append({
                "strategy": bt["strategy"],
                "symbol": bt["symbol"],
                "overall": bt["overall"],
                "windows_count": len(bt["windows"])
            })
        
        self.json_cache.save("signals.json", {
            "timestamp": datetime.utcnow().isoformat(),
            "signals": signals_data
        })
        
        self.json_cache.save("performance.json", {
            "timestamp": datetime.utcnow().isoformat(),
            "backtests": backtests_data
        })
        
        # Summary stats
        strategy_stats = {}
        for bt in self.all_backtests:
            key = f"{bt['strategy']}"
            if key not in strategy_stats:
                strategy_stats[key] = {
                    "symbols": 0,
                    "total_trades": 0,
                    "avg_win_rate": 0,
                    "avg_expectancy": 0,
                    "avg_sharpe": 0
                }
            s = strategy_stats[key]
            s["symbols"] += 1
            s["total_trades"] += bt["overall"]["total_trades"]
            s["avg_win_rate"] += bt["overall"]["win_rate"]
            s["avg_expectancy"] += bt["overall"]["expectancy"]
            s["avg_sharpe"] += bt["overall"]["sharpe_ratio"]
        
        for s in strategy_stats.values():
            if s["symbols"] > 0:
                s["avg_win_rate"] /= s["symbols"]
                s["avg_expectancy"] /= s["symbols"]
                s["avg_sharpe"] /= s["symbols"]
        
        self.json_cache.save("summary.json", {
            "timestamp": datetime.utcnow().isoformat(),
            "total_signals": len(self.all_signals),
            "total_backtests": len(self.all_backtests),
            "discovered_symbols": len(self.discovered_symbols),
            "strategy_stats": strategy_stats
        })


async def main():
    screener = StrategyScreener()
    await screener.run_screening()


if __name__ == "__main__":
    asyncio.run(main())