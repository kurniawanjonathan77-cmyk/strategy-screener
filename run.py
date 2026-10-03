#!/usr/bin/env python
"""Strategy Screener - Main Entry Point"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.screener import main


if __name__ == "__main__":
    # Create necessary directories
    Path("logs").mkdir(exist_ok=True)
    Path("data/cache").mkdir(parents=True, exist_ok=True)
    Path("docs").mkdir(exist_ok=True)
    
    asyncio.run(main())