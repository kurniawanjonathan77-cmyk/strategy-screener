# Strategy Screener 📊

**Free, automated multi-market strategy screener with walk-forward backtesting. Runs on GitHub Actions + GitHub Pages (100% free).**

## Features

- **Multi-market**: Crypto (CoinGecko) + Prediction Markets (Polymarket Testnet)
- **4 Built-in Strategies**: Mean Reversion, Momentum, Breakout, Volatility
- **Walk-Forward Backtest**: Realistic performance validation (no lookahead bias)
- **Web Dashboard**: Auto-deployed to GitHub Pages, updates every 15 min
- **Zero Cost**: GitHub Actions (2000 min/mo free) + GitHub Pages (free)
- **No API Keys Needed**: CoinGecko public API + Polymarket testnet

## Quick Start

### 1. Fork this repo
Click **Fork** → your GitHub account

### 2. Enable GitHub Pages
- Settings → Pages → Source: **Deploy from branch** → **gh-pages** → Save

### 3. Enable GitHub Actions
- Actions tab → "I understand my workflows, go ahead and enable them"

### 4. Configure (optional)
Edit `config.yaml`:
```yaml
data:
  coingecko:
    symbols:  # Add/remove symbols
      - "bitcoin"
      - "ethereum"
      - "solana"
      # ... your favorites

strategies:
  mean_reversion:
    enabled: true
    params:
      rsi_oversold: 30
      rsi_overbought: 70
  # ... adjust params
```

### 5. Trigger first run
- Actions → Strategy Screener → **Run workflow**

### 6. View Dashboard
- `https://YOUR_USERNAME.github.io/strategy-screener/`
- Updates automatically every 15 minutes

## Dashboard Preview

The dashboard shows:
- **Strategy Performance**: Walk-forward backtest results per strategy
- **Current Signals**: Top opportunities with entry/stop/target
- **Confidence Scores**: Based on strategy agreement + backtest expectancy
- **Polymarket Arb**: Mispricing detection (YES+NO ≠ 1)

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  GitHub Actions │────▶│  Strategy        │────▶│  GitHub Pages   │
│  (cron 15 min)  │     │  Screener        │     │  Dashboard      │
└─────────────────┘     └──────────────────┘     └─────────────────┘
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
             ┌─────────────┐     ┌─────────────┐
             │  CoinGecko  │     │ Polymarket  │
             │  (Free API) │     │  (Testnet)  │
             └─────────────┘     └─────────────┘
```

## Strategies

| Strategy | Logic | Best For |
|----------|-------|----------|
| **Mean Reversion** | RSI + Bollinger + Z-Score | Ranging markets |
| **Momentum** | MACD + EMA Cross + ROC | Trending markets |
| **Breakout** | Donchian + Volume Surge | Volatility expansion |
| **Volatility** | Keltner + Squeeze + ATR | Low vol → breakout |

## Backtest Methodology

**Walk-Forward Validation** (prevents overfitting):
1. Train on 60 days → Test on 7 days
2. Step forward 7 days → Repeat
3. Aggregate metrics across all windows
4. Filter: Min 30 trades, Max 25% DD, Min 0.5 Sharpe

## Customization

### Add New Strategy
```python
# src/strategies/my_strategy.py
from src.strategies.base import BaseStrategy, Signal

class MyStrategy(BaseStrategy):
    def calculate_indicators(self, df): ...
    def generate_signal(self, df, symbol): ...
```

Register in `src/screener.py`:
```python
from src.strategies.my_strategy import MyStrategy
# Add to _init_strategies()
```

### Add Data Source
```python
# src/data/my_source.py
class MySource:
    async def get_data(self): ...
```

## Output Files (docs/)

| File | Description |
|------|-------------|
| `index.html` | Interactive dashboard |
| `signals.json` | Current signals API |
| `performance.json` | Backtest results API |
| `summary.json` | Strategy summary stats |

## Local Development

```bash
# Clone
git clone https://github.com/YOUR_USERNAME/strategy-screener
cd strategy-screener

# Install
pip install -r requirements.txt

# Run once
python run.py

# View dashboard
open docs/index.html
```

## Requirements

- Python 3.10+
- GitHub account (for free hosting)
- Optional: TA-Lib for faster indicators (`pip install ta-lib`)

## Disclaimer

**Educational/research tool only.** Not financial advice. Signals are algorithmic outputs based on historical patterns. Past performance ≠ future results. Always do your own research and risk management.

## License

MIT