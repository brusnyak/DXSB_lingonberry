import sys
import os
from typing import List

# Ensure project root is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis.sentiment_analyst import SentimentAnalyst
from src.analysis.ict_analyst import ICTAnalyst, Candle

def test_sentiment_analyst():
    print("\n--- Testing SentimentAnalyst ---")
    sentiment = SentimentAnalyst()
    crypto = sentiment.get_crypto_sentiment()
    print(f"Crypto Sentiment: {crypto}")
    
    bonus = sentiment.get_contrarian_bonus("crypto")
    print(f"Contrarian Bonus (Crypto): {bonus}")

def test_sector_alpha_logic():
    print("\n--- Testing Sector Alpha Logic ---")
    analyst = ICTAnalyst()
    
    def create_mock_candles(count: int, start: float, trend: float) -> List[Candle]:
        candles = []
        cur = start
        for i in range(count):
            c = Candle(i*1000, cur, cur*1.01, cur*0.99, cur*(1+trend), 1000)
            cur = c.close
            candles.append(c)
        return candles

    asset_candles = create_mock_candles(100, 100.0, 0.01) # Asset +100%
    sector_candles = create_mock_candles(100, 100.0, 0.005) # Sector +50%
    
    # Calculate score with sector benchmark
    res = analyst.calculate_investment_score(
        asset_candles, 
        "ALPHA_TEST", 
        sector_candles=sector_candles,
        sentiment_bonus=15.0 # Simulating Extreme Fear bonus
    )
    
    print(f"Logic: {res.logic}")
    print(f"Score: {res.score}")
    print(f"Sector Alpha: {res.extra_metadata.get('sector_alpha')}")
    print(f"Market Sentiment: {res.extra_metadata.get('market_sentiment')}")

if __name__ == "__main__":
    test_sentiment_analyst()
    test_sector_alpha_logic()
