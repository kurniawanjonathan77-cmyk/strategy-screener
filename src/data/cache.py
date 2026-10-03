"""File-based Cache"""

import json
import pickle
import time
from pathlib import Path
from typing import Any, Optional


class Cache:
    def __init__(self, config: dict):
        self.enabled = config.get("enabled", True)
        self.ttl = config.get("ttl_seconds", 300)
        self.path = Path(config.get("path", "data/cache"))
        self.path.mkdir(parents=True, exist_ok=True)

    def _get_path(self, key: str) -> Path:
        safe_key = key.replace("/", "_").replace(":", "_")
        return self.path / f"{safe_key}.pkl"

    def get(self, key: str) -> Optional[Any]:
        if not self.enabled:
            return None
        
        path = self._get_path(key)
        if not path.exists():
            return None
        
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
            
            # Check TTL
            if "cached_at" in data:
                if time.time() - data["cached_at"] > self.ttl:
                    return None
                return data["value"]
            return data
        except Exception:
            return None

    def set(self, key: str, value: Any):
        if not self.enabled:
            return
        
        path = self._get_path(key)
        try:
            with open(path, "wb") as f:
                pickle.dump({
                    "value": value,
                    "cached_at": time.time()
                }, f)
        except Exception as e:
            print(f"Cache write error: {e}")

    def clear(self):
        for f in self.path.glob("*.pkl"):
            f.unlink()


class JSONCache:
    """Human-readable JSON cache for dashboard data"""
    
    def __init__(self, path: str = "docs"):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)

    def save(self, filename: str, data: dict):
        filepath = self.path / filename
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def load(self, filename: str) -> Optional[dict]:
        filepath = self.path / filename
        if not filepath.exists():
            return None
        with open(filepath) as f:
            return json.load(f)