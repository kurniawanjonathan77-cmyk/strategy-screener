"""Binance Data Source - Public API (no API key needed for basic data)"""

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import aiohttp
import pandas as pd
from loguru import logger

from src.data.cache import Cache


@dataclass
class MarketData:
    symbol: str
    name: str
    current_price: float
    price_change_24h: float
    price_change_pct_24h: float
    volume_24h: float
    quote_volume_24h: float
    ohlcv: pd.DataFrame
    last_updated: datetime


@dataclass
class SymbolInfo:
    symbol: str
    base_asset: str
    quote_asset: str
    status: str
    volume_24h: float
    price_change_pct_24h: float
    quote_volume_24h: float


class BinanceClient:
    def __init__(self, config: dict):
        self.config = config["data"]["binance"]
        self.cache = Cache(config["data"]["cache"])
        # Multiple endpoints for redundancy
        self.endpoints = self.config.get("endpoints", [
            "https://api.binance.com",
            "https://api1.binance.com",
            "https://api2.binance.com",
            "https://api3.binance.com",
            "https://api4.binance.com",
        ])
        self.base_url = self.endpoints[0]
        self.futures_url = self.config.get("futures_url", "https://fapi.binance.com")
        self.quote_assets = self.config.get("quote_assets", ["USDT", "USDC"])
        self.min_volume_usd = self.config.get("min_volume_usd", 1000000)
        self.max_symbols = self.config.get("max_symbols", 100)
        self._endpoint_index = 0
        self._last_request = 0
        self._min_interval = 0.1
        self._consecutive_failures = 0
        self._max_failures_before_switch = 3

    async def _rate_limit_wait(self):
        elapsed = time.time() - self._last_request
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
        self._last_request = time.time()

    def _get_current_url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _rotate_endpoint(self):
        self._endpoint_index = (self._endpoint_index + 1) % len(self.endpoints)
        self.base_url = self.endpoints[self._endpoint_index]
        logger.warning(f"Rotated to endpoint: {self.base_url}")

    async def _fetch(self, session: aiohttp.ClientSession, path: str, params: dict = None) -> dict:
        await self._rate_limit_wait()
        max_retries = len(self.endpoints)
        
        for attempt in range(max_retries):
            url = self._get_current_url(path)
            try:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 429:
                        logger.warning("Binance rate limited, waiting 5s")
                        await asyncio.sleep(5)
                        return await self._fetch(session, path, params)
                    resp.raise_for_status()
                    self._consecutive_failures = 0
                    return await resp.json()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                self._consecutive_failures += 1
                logger.warning(f"Binance endpoint {self.base_url} failed ({self._consecutive_failures}x): {e}")
                if self._consecutive_failures >= self._max_failures_before_switch:
                    self._rotate_endpoint()
                    self._consecutive_failures = 0
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Binance fetch error {url}: {e}")
                raise

    async def get_exchange_info(self) -> List[SymbolInfo]:
        """Get all trading pairs info"""
        cache_key = "binance_exchange_info"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        async with aiohttp.ClientSession() as session:
            data = await self._fetch(session, "/api/v3/exchangeInfo")
        
        symbols = []
        for s in data.get("symbols", []):
            if s["status"] == "TRADING" and s["quoteAsset"] in self.quote_assets:
                symbols.append(SymbolInfo(
                    symbol=s["symbol"],
                    base_asset=s["baseAsset"],
                    quote_asset=s["quoteAsset"],
                    status=s["status"],
                    volume_24h=0,
                    price_change_pct_24h=0,
                    quote_volume_24h=0
                ))
        
        self.cache.set(cache_key, symbols)
        return symbols

    async def get_24h_tickers(self) -> List[SymbolInfo]:
        """Get 24h ticker statistics for all pairs"""
        cache_key = "binance_24h_tickers"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        async with aiohttp.ClientSession() as session:
            data = await self._fetch(session, "/api/v3/ticker/24hr")
        
        tickers = []
        for t in data:
            if t["symbol"].endswith(tuple(self.quote_assets)):
                tickers.append(SymbolInfo(
                    symbol=t["symbol"],
                    base_asset=t["symbol"].replace(t["quoteAsset"], ""),
                    quote_asset=t["quoteAsset"],
                    status="TRADING",
                    volume_24h=float(t["volume"]),
                    price_change_pct_24h=float(t["priceChangePercent"]),
                    quote_volume_24h=float(t["quoteVolume"])
                ))
        
        self.cache.set(cache_key, tickers)
        return tickers

    async def discover_symbols(self, mode: str = "top_volume") -> List[str]:
        """
        Discover symbols based on mode:
        - top_volume: Highest quote volume (most liquid)
        - top_gainers: Biggest 24h % gain
        - top_losers: Biggest 24h % loss
        - high_volatility: Highest ATR/price ratio
        - new_listings: Recently added (requires exchange info comparison)
        - all_liquid: All above min volume
        """
        tickers = await self.get_24h_tickers()
        
        # Filter by min volume
        tickers = [t for t in tickers if t.quote_volume_24h >= self.min_volume_usd]
        
        if mode == "top_volume":
            tickers.sort(key=lambda x: x.quote_volume_24h, reverse=True)
        elif mode == "top_gainers":
            tickers.sort(key=lambda x: x.price_change_pct_24h, reverse=True)
        elif mode == "top_losers":
            tickers.sort(key=lambda x: x.price_change_pct_24h)
        elif mode == "high_volatility":
            # Would need price data, fallback to volume
            tickers.sort(key=lambda x: x.quote_volume_24h, reverse=True)
        elif mode == "all_liquid":
            tickers.sort(key=lambda x: x.quote_volume_24h, reverse=True)
        else:
            tickers.sort(key=lambda x: x.quote_volume_24h, reverse=True)
        
        symbols = [t.symbol for t in tickers[:self.max_symbols]]
        logger.info(f"Discovered {len(symbols)} symbols via {mode}")
        return symbols

    async def get_klines(self, symbol: str, interval: str = "1h", limit: int = 500) -> pd.DataFrame:
        """Get OHLCV klines"""
        cache_key = f"binance_klines_{symbol}_{interval}_{limit}"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": min(limit, 1000)
        }
        
        async with aiohttp.ClientSession() as session:
            data = await self._fetch(session, "/api/v3/klines", params)
        
        df = pd.DataFrame(data, columns=[
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore"
        ])
        
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        for col in ["open", "high", "low", "close", "volume", "quote_volume"]:
            df[col] = df[col].astype(float)
        
        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        df = df.set_index("timestamp").sort_index()
        
        self.cache.set(cache_key, df)
        return df

    async def get_market_data(self, symbol: str, interval: str = "1h", days: int = 90) -> Optional[MarketData]:
        """Get complete market data for a symbol"""
        cache_key = f"binance_market_{symbol}_{days}d"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        # Calculate limit based on days and interval
        interval_minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
        minutes_per_day = 1440
        limit = min(1000, (days * minutes_per_day) // interval_minutes.get(interval, 60))
        
        try:
            # Get klines
            df = await self.get_klines(symbol, interval, limit)
            
            # Get 24h ticker for current stats
            params = {"symbol": symbol}
            async with aiohttp.ClientSession() as session:
                ticker = await self._fetch(session, "/api/v3/ticker/24hr", params)
            
            data = MarketData(
                symbol=symbol,
                name=symbol,
                current_price=float(ticker["lastPrice"]),
                price_change_24h=float(ticker["priceChange"]),
                price_change_pct_24h=float(ticker["priceChangePercent"]),
                volume_24h=float(ticker["volume"]),
                quote_volume_24h=float(ticker["quoteVolume"]),
                ohlcv=df,
                last_updated=datetime.utcnow()
            )
            
            self.cache.set(cache_key, data)
            return data
            
        except Exception as e:
            logger.error(f"Error getting market data for {symbol}: {e}")
            return None

    async def get_multiple_market_data(self, symbols: List[str], interval: str = "1h", days: int = 90) -> Dict[str, MarketData]:
        """Get market data for multiple symbols"""
        results = {}
        for symbol in symbols:
            data = await self.get_market_data(symbol, interval, days)
            if data:
                results[symbol] = data
            await asyncio.sleep(0.05)  # Rate limit
        return results


async def test():
    import yaml
    with open("config.yaml") as f:
        config = yaml.safe_load(f)
    
    client = BinanceClient(config)
    
    # Test symbol discovery
    symbols = await client.discover_symbols("top_volume")
    print(f"Top volume symbols: {symbols[:10]}")
    
    symbols = await client.discover_symbols("top_gainers")
    print(f"Top gainers: {symbols[:10]}")
    
    # Test market data
    data = await client.get_market_data("BTCUSDT")
    if data:
        print(f"BTCUSDT: ${data.current_price:,.2f} | 24h: {data.price_change_pct_24h:.2f}% | Vol: ${data.quote_volume_24h:,.0f}")
        print(f"OHLCV rows: {len(data.ohlcv)}")


if __name__ == "__main__":
    asyncio.run(test())