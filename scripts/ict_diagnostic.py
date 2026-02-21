import os
import sys
import logging
import json
import argparse
from typing import List, Dict, Optional

# Ensure project root is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis.ict_analyst import ICTAnalyst, Candle
from src.adapters.market_adapters import DexScreenerAdapter, BinanceAdapter, StockAdapter
from src.utils.ict_visualizer import ICTVisualizer
from src.dex_bot import DexScreenerClient

# Setup basic logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("ict_diag")

def run_diagnostic(pool_address: Optional[str] = None, chain_id: str = "solana", adapter_type: str = "dex"):
    """Fetches real candles and prints every ICT pattern detected."""
    with open("config.json", "r") as f:
        config = json.load(f)
        
    client = DexScreenerClient()
    
    if adapter_type == "binance":
        adapter = BinanceAdapter()
    elif adapter_type == "stock":
        adapter = StockAdapter(config)
    else:
        adapter = DexScreenerAdapter(client, config)
        
    analyst = ICTAnalyst()

    if not pool_address:
        logger.info(f"No pool provided for {adapter_type}. Fetching candidates...")
        candidates = adapter.fetch_candidates()
        if not candidates:
            logger.error("No candidates found.")
            return
        
        pool_address = candidates[0].get("pairAddress")
        if adapter_type == "dex":
            chain_id = candidates[0].get("chainId")
            if chain_id == "ethereum": chain_id = "eth"
        
    if not pool_address:
        logger.error("Could not find a valid pool/symbol.")
        return

    logger.info(f"Starting ICT Diagnostic for {pool_address} on {chain_id} via {adapter_type}")
    
    logger.info(f"Fetching candles for {pool_address} via {adapter_type}...")
    candles = adapter.fetch_candles(pool_address, chain_id)
    
    if not candles:
        logger.error("No candles fetched. Diagnostic failed.")
        return

    logger.info(f"Fetched {len(candles)} candles. Analyzing...")
    
    patterns = analyst.analyze(candles)
    
    if not patterns:
        logger.info("No patterns detected in this timeframe.")
        return

    print("\n" + "="*50)
    print(f"ICT ANALYSIS REPORT: {pool_address}")
    print("="*50)
    
    for p in patterns:
        direction_emoji = "🟢" if p.direction == "BULLISH" else "🔴" if p.direction == "BEARISH" else "⚪"
        print(f"{direction_emoji} {p.type:10} | {p.direction:10} | Strength: {p.strength:.2f}")
        print(f"   Context: {p.context}")
        print(f"   Range:   {p.price_range[0]:.8f} - {p.price_range[1]:.8f}")
        print("-" * 30)

    print(f"\nTotal Patterns: {len(patterns)}")
    print("="*50)

    # Generate Visual Report
    visualizer = ICTVisualizer()
    output_dir = "data/reports"
    os.makedirs(output_dir, exist_ok=True)
    report_file = f"{output_dir}/report_{adapter_type}_{pool_address}.html"
    visualizer.generate_report(candles, patterns, pool_address, adapter_type, report_file)
    print(f"VISUAL REPORT READY: {report_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pool", help="Pool address or symbol")
    parser.add_argument("--chain", default="solana", help="Chain ID")
    parser.add_argument("--type", default="dex", choices=["dex", "binance", "stock"], help="Adapter type")
    
    args = parser.parse_args()
    run_diagnostic(args.pool, args.chain, args.type)
