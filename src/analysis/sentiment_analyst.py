import requests
import logging
import time
from typing import Dict, Optional

logger = logging.getLogger("dxsb.sentiment")

class SentimentAnalyst:
    """Fetches and caches market sentiment data (Fear & Greed Index)."""
    
    def __init__(self):
        self._crypto_cache = None
        self._stock_cache = None
        self._last_update = 0
        self._cache_ttl = 3600 # 1 hour

    def get_crypto_sentiment(self) -> Dict:
        """Fetches the Crypto Fear & Greed Index from alternative.me."""
        now = time.time()
        if self._crypto_cache and (now - self._last_update < self._cache_ttl):
            return self._crypto_cache
            
        try:
            url = "https://api.alternative.me/fng/"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                fng_val = int(data["data"][0]["value"])
                classification = data["data"][0]["value_classification"]
                
                self._crypto_cache = {
                    "value": fng_val,
                    "sentiment": classification,
                    "timestamp": now
                }
                self._last_update = now
                logger.info(f"Crypto Sentiment: {fng_val} ({classification})")
                return self._crypto_cache
        except Exception as e:
            logger.error(f"Failed to fetch crypto sentiment: {e}")
            
        return {"value": 50, "sentiment": "Neutral", "timestamp": now}

    def get_stock_sentiment(self) -> Dict:
        """
        Fetches the Stock Market Fear & Greed Index.
        Note: CNN doesn't have a public API, so this is a simplified proxy or placeholder.
        """
        # For now, returning neutral. In a real scenario, this would scrape CNN or use a paid API.
        return {"value": 50, "sentiment": "Neutral", "timestamp": time.time()}

    def get_contrarian_bonus(self, market_type: str) -> float:
        """Calculates a score bonus based on extreme market fear."""
        sentiment = self.get_crypto_sentiment() if market_type == "crypto" else self.get_stock_sentiment()
        val = sentiment.get("value", 50)
        
        if val < 20: # Extreme Fear
            return 15.0
        if val < 35: # Fear
            return 7.0
        if val > 80: # Extreme Greed
            return -10.0 # Penalty for late-stage exuberance
        return 0.0
