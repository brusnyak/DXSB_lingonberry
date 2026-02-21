import os
import sys
import json
import logging
import time
from typing import List, Dict

# Ensure project root is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.adapters.market_adapters import DexScreenerAdapter
from src.analysis.ict_analyst import ICTAnalyst
from src.utils.ict_visualizer import ICTVisualizer
from src.dex_bot import DexScreenerClient

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("live_scanner")

def run_live_scanner(limit: int = 20):
    """Scans DexScreener for trending assets and presents ICT analysis."""
    with open("config.json", "r") as f:
        config = json.load(f)
        
    client = DexScreenerClient()
    adapter = DexScreenerAdapter(client, config)
    analyst = ICTAnalyst()
    visualizer = ICTVisualizer()
    
    logger.info("📡 Scanning for trending assets on DexScreener...")
    candidates = adapter.fetch_candidates()
    
    if not candidates:
        logger.error("No candidates found.")
        return

    # Filter for candidates with high volume/liquidity hint
    # Candidates already sorted/filtered by adapter
    scanner_limit = min(len(candidates), limit)
    logger.info(f"Found {len(candidates)} candidates. Analyzing top {scanner_limit}...")

    matched_assets = []

    for i in range(scanner_limit):
        item = candidates[i]
        symbol = item.get("baseToken", {}).get("symbol", "???")
        address = item.get("pairAddress")
        chain = item.get("chainId")
        
        logger.info(f"[{i+1}/{scanner_limit}] Analyzing {symbol} ({chain})...")
        
        # Throttling to avoid API blocks
        time.sleep(1.0)
        
        candles = adapter.fetch_candles(address, chain)
        if not candles:
            continue
            
        patterns = analyst.analyze(candles)
        
        # High conviction filter: Confluence score > 2.0
        confluence = [p for p in patterns if p.type == "Confluence" and p.strength > 2.0]
        
        if confluence:
            best_p = confluence[0]
            logger.info(f"✨ MATCH: {symbol} | {best_p.context} (Str: {best_p.strength:.1f})")
            
            # Generate report
            report_name = f"data/reports/live_{chain}_{symbol}_{int(time.time())}.html"
            os.makedirs("data/reports", exist_ok=True)
            visualizer.generate_report(candles, patterns, symbol, "dex", report_name)
            
            matched_assets.append({
                "symbol": symbol,
                "chain": chain,
                "confluence": best_p.context,
                "strength": best_p.strength,
                "report": report_name
            })

    print("\n" + "🚀" * 20)
    print("LIVE SCANNER RESULTS")
    print("🚀" * 20)
    if not matched_assets:
        print("No high-confluence setups found in the current trending list.")
    else:
        for asset in matched_assets:
            print(f"- {asset['symbol']} ({asset['chain']}): {asset['confluence']}")
            print(f"  Strength: {asset['strength']:.1f} | Report: {asset['report']}")
    print("=" * 40)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=20, help="Number of assets to scan")
    args = parser.parse_args()
    
    run_live_scanner(limit=args.limit)
