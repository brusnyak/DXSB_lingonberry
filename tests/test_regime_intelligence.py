import sys
import os
import unittest
from typing import List

# Ensure project root is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis.ict_analyst import ICTAnalyst, Candle

class TestRegimeIntelligence(unittest.TestCase):
    def setUp(self):
        self.analyst = ICTAnalyst()

    def create_mock_candles(self, count: int, close_start: float, trend: float = 0.0, vol: float = 0.01, vol_decay: float = 1.0) -> List[Candle]:
        candles = []
        current_close = close_start
        current_vol = vol
        for i in range(count):
            c = Candle(
                timestamp=i * 1000,
                open=current_close,
                high=current_close * (1 + current_vol),
                low=current_close * (1 - current_vol),
                close=current_close * (1 + trend),
                volume=1000
            )
            current_close = c.close
            current_vol *= vol_decay
            candles.append(c)
        return candles

    def test_quiet_regime(self):
        # Quiet: Tightening volatility
        candles = self.create_mock_candles(100, 100.0, trend=0.0001, vol=0.05, vol_decay=0.98)
        regime = self.analyst._classify_regime(candles)
        self.assertEqual(regime, "QUIET")
        
        res = self.analyst.calculate_investment_score(candles, "QUIET_TEST")
        print(f"\nQuiet Regime Score Logic: {res.logic}")
        # In quiet, VPC should have higher weight (w_vpc = 20)

    def test_volatile_regime(self):
        # Volatile: High volatility expansion
        candles = self.create_mock_candles(100, 100.0, trend=0.0, vol=0.01, vol_decay=1.1)
        regime = self.analyst._classify_regime(candles)
        self.assertEqual(regime, "VOLATILE")
        
        res = self.analyst.calculate_investment_score(candles, "VOL_TEST")
        print(f"Volatile Regime Score Logic: {res.logic}")

    def test_momentum_regime(self):
        # Momentum: Strong trend
        candles = self.create_mock_candles(100, 100.0, trend=0.01, vol=0.01)
        regime = self.analyst._classify_regime(candles)
        self.assertEqual(regime, "MOMENTUM")
        
        res = self.analyst.calculate_investment_score(candles, "MOM_TEST")
        print(f"Momentum Regime Score Logic: {res.logic}")

    def test_bearish_regime(self):
        # Bearish: Price below EMA 200 (Mocked by starting high and crashing)
        candles = self.create_mock_candles(300, 1000.0, trend=-0.01, vol=0.02)
        regime = self.analyst._classify_regime(candles)
        self.assertEqual(regime, "BEARISH")
        
        res = self.analyst.calculate_investment_score(candles, "BEAR_TEST")
        print(f"Bearish Regime Score Logic: {res.logic}")
        # Check if bearish penalty is mentioned
        self.assertIn("Bearish Regime", res.logic)

if __name__ == "__main__":
    unittest.main()
