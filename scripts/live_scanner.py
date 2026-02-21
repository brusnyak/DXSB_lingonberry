import os
import sys
import json
import logging
import time
from typing import List, Dict, Optional

# Ensure project root is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.adapters.market_adapters import DexScreenerAdapter, BinanceAdapter, StockAdapter
from src.analysis.ict_analyst import ICTAnalyst, InvestmentResult
from src.utils.ict_visualizer import ICTVisualizer
from src.dex_bot import DexScreenerClient

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("investment_scanner")

def run_investment_scanner(limit: int = 15, mode: str = "crypto"):
    """
    Scans markets for mid-term investment opportunities (The 'Expansion' model).
    mode: 'crypto' (Dex + Binance) or 'stocks'
    """
    with open("config.json", "r") as f:
        config = json.load(f)
        
    analyst = ICTAnalyst()
    visualizer = ICTVisualizer()
    results: List[InvestmentResult] = []

    # 1. Fetch Benchmark (BTC for Crypto, SPY for Stocks)
    benchmark_candles = None
    if mode == "crypto":
        # We use Binance for reliable BTC benchmark
        binance = BinanceAdapter(config)
        benchmark_candles = binance.fetch_candles("BTCUSDT", "1d", limit=100)
        logger.info("Fetched BTC Benchmark for Relative Strength analysis.")

    # 2. Market Scanning
    if mode == "crypto":
        # Scanning DexScreener Trending
        client = DexScreenerClient()
        dex = DexScreenerAdapter(client, config)
        logger.info("📡 Scanning DexScreener Trending for potential gems...")
        candidates = dex.fetch_candidates()
        
        scan_limit = min(len(candidates), limit)
        for i in range(scan_limit):
            item = candidates[i]
            symbol = item.get("baseToken", {}).get("symbol", "???")
            address = item.get("pairAddress")
            chain = item.get("chainId")
            
            logger.info(f"[{i+1}/{scan_limit}] Evaluating {symbol}...")
            time.sleep(0.5) # Throttling
            
            candles = dex.fetch_candles(address, chain)
            if not candles: continue
            
            res = analyst.calculate_investment_score(candles, symbol, benchmark_candles)
            if res.score > 60: # High quality threshold
                results.append(res)
                # Generate visual report for the gem
                report_path = f"data/reports/invest_{symbol}.html"
                patterns = analyst.analyze(candles)
                visualizer.generate_report(candles, patterns, symbol, "dex", report_path)

    elif mode == "stocks":
        stock_adapter = StockAdapter(config)
        # Static list for now, could be expanded to a top-50 scan
        stock_list = ["TSLA", "NVDA", "AAPL", "AMD", "MSFT", "GOOGL", "META", "AMZN", "PLTR", "SOFI"]
        logger.info(f"📡 Scanning major stocks: {stock_list}")
        
        for symbol in stock_list:
            logger.info(f"Evaluating {symbol}...")
            candles = stock_adapter.fetch_candles(symbol, "1d")
            if not candles: continue
            
            # For stocks, we could fetch SPY as benchmark
            res = analyst.calculate_investment_score(candles, symbol)
            if res.score > 55:
                results.append(res)
                report_path = f"data/reports/invest_{symbol}.html"
                patterns = analyst.analyze(candles)
                visualizer.generate_report(candles, patterns, symbol, "stock", report_path)

    # 3. Present Results
    results.sort(key=lambda x: x.score, reverse=True)

    print("\n" + "💎" * 30)
    print("STRATEGIC INVESTMENT SCANNER")
    print("Mode: " + mode.upper() + " | Criteria: Accumulation & Expansion")
    print("💎" * 30)
    
    if not results:
        print("No high-probability investment opportunities found.")
    else:
        for r in results:
            color_code = "🟢" if r.score > 80 else "🟡"
            print(f"{color_code} {r.symbol}: Score {r.score:.1f} | Type: {r.discovery_type}")
            print(f"  Logic: {r.logic}")
            print(f"  Target: {r.target_potential}")
            print("-" * 40)
    
    print("=" * 60)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=15, help="Number of assets to scan")
    parser.add_argument("--mode", choices=["crypto", "stocks"], default="crypto")
    args = parser.parse_args()
    
    run_investment_scanner(limit=args.limit, mode=args.mode)
