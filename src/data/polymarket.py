"""Polymarket Data Source - Testnet (free)"""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

import aiohttp
from loguru import logger

from src.data.cache import Cache


@dataclass
class PolymarketMarket:
    condition_id: str
    question: str
    outcomes: List[str]
    outcome_prices: Dict[str, float]
    volume_24h: float
    liquidity: float
    category: str
    end_date: str
    last_updated: datetime


class PolymarketClient:
    def __init__(self, config: dict):
        self.config = config["data"]["polymarket"]
        self.cache = Cache(config["data"]["cache"])
        self.base_url = self.config["base_url"]
        self.gamma_url = self.base_url.replace("clob", "gamma-api")
        self.min_volume = self.config.get("min_volume_24h", 1000)
        self.min_liquidity = self.config.get("min_liquidity", 500)

    async def get_markets(self) -> List[PolymarketMarket]:
        """Fetch all active markets from Gamma API"""
        cache_key = "polymarket_markets"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        url = f"{self.gamma_url}/markets"
        params = {
            "active": "true",
            "closed": "false",
            "limit": 500
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url, params=params) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
            except Exception as e:
                logger.error(f"Polymarket fetch error: {e}")
                return []

        markets = []
        for m in data.get("data", []):
            try:
                volume = float(m.get("volume24h", 0))
                liquidity = float(m.get("liquidity", 0))
                
                if volume < self.min_volume or liquidity < self.min_liquidity:
                    continue

                outcomes = [o["name"] for o in m.get("outcomes", [])]
                prices = {o["name"]: float(o.get("price", 0)) for o in m.get("outcomes", [])}
                
                market = PolymarketMarket(
                    condition_id=m["conditionId"],
                    question=m["question"],
                    outcomes=outcomes,
                    outcome_prices=prices,
                    volume_24h=volume,
                    liquidity=liquidity,
                    category=m.get("category", "unknown"),
                    end_date=m.get("endDate", ""),
                    last_updated=datetime.utcnow()
                )
                markets.append(market)
            except Exception as e:
                logger.warning(f"Error parsing market {m.get('conditionId')}: {e}")

        self.cache.set(cache_key, markets)
        return markets

    async def get_orderbook(self, asset_id: str) -> Optional[dict]:
        """Get orderbook for specific asset (outcome)"""
        url = f"{self.base_url}/orderbook/{asset_id}"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        return await resp.json()
            except Exception as e:
                logger.error(f"Orderbook fetch error: {e}")
        return None

    def calculate_implied_prob_sum(self, market: PolymarketMarket) -> float:
        """Sum of all outcome probabilities (should be ~1.0)"""
        return sum(market.outcome_prices.values())

    def find_mispricing(self, market: PolymarketMarket) -> Optional[dict]:
        """Detect complementary mispricing (YES + NO != 1)"""
        if len(market.outcomes) != 2:
            return None
        
        prob_sum = self.calculate_implied_prob_sum(market)
        edge = abs(1.0 - prob_sum)
        
        if edge < 0.01:  # Less than 1% edge
            return None
        
        return {
            "condition_id": market.condition_id,
            "question": market.question,
            "outcomes": market.outcomes,
            "prices": market.outcome_prices,
            "prob_sum": prob_sum,
            "edge_pct": edge * 100,
            "direction": "buy_both" if prob_sum < 1.0 else "sell_both",
            "volume_24h": market.volume_24h,
            "liquidity": market.liquidity
        }


async def test():
    import yaml
    with open("config.yaml") as f:
        config = yaml.safe_load(f)
    
    client = PolymarketClient(config)
    markets = await client.get_markets()
    print(f"Found {len(markets)} markets")
    
    for m in markets[:5]:
        misprice = client.find_mispricing(m)
        if misprice:
            print(f"  MISPRICING: {m.question[:50]}... edge={misprice['edge_pct']:.2f}%")
        print(f"  {m.question[:60]}... prices={m.outcome_prices}")


if __name__ == "__main__":
    asyncio.run(test())