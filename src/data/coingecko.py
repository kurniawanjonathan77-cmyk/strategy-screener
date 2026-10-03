"""CoinGecko Data Source - Free, no API key required"""

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
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
    market_cap: float
    ohlcv: pd.DataFrame  # columns: timestamp, open, high, low, close, volume
    last_updated: datetime


class CoinGeckoClient:
    def __init__(self, config: dict):
        self.config = config["data"]["coingecko"]
        self.cache = Cache(config["data"]["cache"])
        self.base_url = self.config["base_url"]
        self.symbols = self.config["symbols"]
        self.vs_currency = self.config["vs_currency"]
        self.days_history = self.config["days_history"]
        self.rate_limit = self.config["rate_limit"]
        
        self._last_request = 0
        self._min_interval = 60.0 / self.rate_limit

    async def _rate_limit_wait(self):
        elapsed = time.time() - self._last_request
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
        self._last_request = time.time()

    async def _fetch(self, session: aiohttp.ClientSession, endpoint: str, params: dict = None) -> dict:
        await self._rate_limit_wait()
        url = f"{self.base_url}{endpoint}"
        try:
            async with session.get(url, params=params) as resp:
                if resp.status == 429:
                    logger.warning("Rate limited, waiting 60s")
                    await asyncio.sleep(60)
                    return await self._fetch(session, endpoint, params)
                resp.raise_for_status()
                return await resp.json()
        except Exception as e:
            logger.error(f"CoinGecko fetch error {endpoint}: {e}")
            raise

    async def get_market_data(self, symbol: str) -> Optional[MarketData]:
        """Get current market data + OHLCV history (hourly for <=90 days)"""
        cache_key = f"coingecko_{symbol}_{self.days_history}d"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        # Use min(days, 90) for hourly data from market_chart
        chart_days = min(self.days_history, 90)
        
        async with aiohttp.ClientSession() as session:
            # Get current data
            current = await self._fetch(session, "/simple/price", {
                "ids": symbol,
                "vs_currencies": self.vs_currency,
                "include_24hr_change": "true",
                "include_24hr_vol": "true",
                "include_market_cap": "true",
                "include_last_updated_at": "true"
            })
            
            if symbol not in current:
                return None
            
            c = current[symbol]
            
            # Get market chart with prices (hourly for <=90 days)
            market_chart = await self._fetch(session, f"/coins/{symbol}/market_chart", {
                "vs_currency": self.vs_currency,
                "days": chart_days
            })

        # Build OHLCV DataFrame from market_chart prices (hourly)
        df = self._build_ohlcv_from_chart(market_chart)
        
        data = MarketData(
            symbol=symbol,
            name=symbol.replace("-", " ").title(),
            current_price=c[f"{self.vs_currency}"],
            price_change_24h=c.get(f"{self.vs_currency}_24h_change", 0),
            price_change_pct_24h=c.get(f"{self.vs_currency}_24h_change", 0),
            volume_24h=c.get(f"{self.vs_currency}_24h_vol", 0),
            market_cap=c.get(f"{self.vs_currency}_market_cap", 0),
            ohlcv=df,
            last_updated=datetime.fromtimestamp(c.get("last_updated_at", time.time()))
        )
        
        self.cache.set(cache_key, data)
        return data

    def _build_ohlcv_from_chart(self, market_chart: dict) -> pd.DataFrame:
        """Build hourly OHLCV from market_chart prices array"""
        # market_chart["prices"] = [[timestamp, price], ...] hourly for <=90 days
        prices = market_chart.get("prices", [])
        volumes = market_chart.get("total_volumes", [])
        
        if not prices:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        
        # Convert to DataFrame
        price_df = pd.DataFrame(prices, columns=["timestamp", "price"])
        price_df["timestamp"] = pd.to_datetime(price_df["timestamp"], unit="ms")
        price_df = price_df.set_index("timestamp")
        
        # Resample to 1H OHLCV
        ohlc = price_df["price"].resample("1h").ohlc()
        vol_df = pd.DataFrame(volumes, columns=["timestamp", "volume"])
        vol_df["timestamp"] = pd.to_datetime(vol_df["timestamp"], unit="ms")
        vol_df = vol_df.set_index("timestamp")
        vol = vol_df["volume"].resample("1h").sum()
        
        # Merge
        df = pd.concat([ohlc, vol.rename("volume")], axis=1)
        df = df.dropna()
        
        return df[["open", "high", "low", "close", "volume"]]

    async def get_all_markets(self) -> Dict[str, MarketData]:
        """Fetch all configured symbols"""
        results = {}
        chart_days = min(self.days_history, 90)
        
        async with aiohttp.ClientSession() as session:
            # Batch current prices
            current = await self._fetch(session, "/simple/price", {
                "ids": ",".join(self.symbols),
                "vs_currencies": self.vs_currency,
                "include_24hr_change": "true",
                "include_24hr_vol": "true",
                "include_market_cap": "true",
                "include_last_updated_at": "true"
            })
            
            for symbol in self.symbols:
                if symbol in current:
                    # Get market chart for hourly data
                    market_chart = await self._fetch(session, f"/coins/{symbol}/market_chart", {
                        "vs_currency": self.vs_currency,
                        "days": chart_days
                    })
                    
                    df = self._build_ohlcv_from_chart(market_chart)
                    c = current[symbol]
                    
                    results[symbol] = MarketData(
                        symbol=symbol,
                        name=symbol.replace("-", " ").title(),
                        current_price=c[f"{self.vs_currency}"],
                        price_change_24h=c.get(f"{self.vs_currency}_24h_change", 0),
                        price_change_pct_24h=c.get(f"{self.vs_currency}_24h_change", 0),
                        volume_24h=c.get(f"{self.vs_currency}_24h_vol", 0),
                        market_cap=c.get(f"{self.vs_currency}_market_cap", 0),
                        ohlcv=df,
                        last_updated=datetime.fromtimestamp(c.get("last_updated_at", time.time()))
                    )
        
        return results


async def test():
    import yaml
    with open("config.yaml") as f:
        config = yaml.safe_load(f)
    
    client = CoinGeckoClient(config)
    data = await client.get_market_data("bitcoin")
    print(f"BTC: ${data.current_price:,.2f} | 24h: {data.price_change_pct_24h:.2f}%")
    print(f"OHLCV shape: {data.ohlcv.shape}")
    print(data.ohlcv.tail())


if __name__ == "__main__":
    asyncio.run(test())