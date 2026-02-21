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
from src.core.investment_journal import InvestmentJournal
from src.utils.telegram_alerter import TelegramAlerter

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("investment_scanner")

def run_investment_scanner(limit: int = 15, mode: str = "crypto", monitor: bool = False):
    """
    Scans markets for mid-term investment opportunities (The 'Expansion' model).
    mode: 'crypto' (Dex + Binance) or 'stocks'
    """
    with open("config.json", "r") as f:
        config = json.load(f)
        
    analyst = ICTAnalyst()
    visualizer = ICTVisualizer()
    journal = InvestmentJournal("dex_analytics.db")
    alerter = TelegramAlerter()
    results: List[InvestmentResult] = []

    # 0. Monitoring Mode
    if monitor:
        logger.info("🕵️ Monitoring active investments...")
        active = journal.get_active_investments()
        binance = BinanceAdapter()
        stocks = StockAdapter(config)
        
        for inv in active:
            symbol = inv["symbol"]
            current_price = 0.0
            
            # Fetch current price based on discovery type
            if inv["discovery_type"] == "crypto":
                # Try Binance first, then fallback
                data = binance.get_market_data(f"{symbol}USDT")
                current_price = data.get("priceUsd", 0)
            elif inv["discovery_type"] == "stocks":
                data = stocks.get_market_data(symbol)
                current_price = data.get("priceUsd", 0)
            
            if current_price == 0:
                logger.warning(f"Could not fetch price for {symbol}")
                continue

            logger.info(f"Monitoring {symbol}: Price {current_price:.8f} (Inv: {inv['inv_level']:.8f}, Target: {inv['target_level']:.8f})")
            
            # Check Invalidation
            if current_price <= inv["inv_level"]:
                msg = f"THESIS INVALIDATED: Price broke below {inv['inv_level']:.8f}"
                alerter.send_status_update(symbol, "INVALIDATED", current_price)
                journal.update_status(inv["id"], "INVALIDATED", current_price)
                logger.warning(f"❌ {symbol} {msg}")
                
            # Check Target
            elif current_price >= inv["target_level"]:
                msg = f"TARGET REACHED: Price hit/exceeded {inv['target_level']:.8f}"
                alerter.send_status_update(symbol, "TARGET_REACHED", current_price)
                journal.update_status(inv["id"], "TARGET_REACHED", current_price)
                logger.info(f"🚀 {symbol} {msg}")
        return

    # 1. Fetch Benchmark (BTC for Crypto, SPY for Stocks)
    benchmark_candles = None
    if mode == "crypto":
        binance = BinanceAdapter()
        benchmark_candles = binance.fetch_candles("BTCUSDT", interval="1d", limit=100)
        logger.info("Fetched BTC Benchmark for Relative Strength analysis.")

    # 2. Market Scanning
    if mode == "crypto":
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
            time.sleep(0.5) 
            
            candles = dex.fetch_candles(address, interval="day", limit=100, chain_id=chain)
            if not candles: continue
            
            url = f"https://dexscreener.com/{chain}/{address}"
            res = analyst.calculate_investment_score(candles, symbol, benchmark_candles, url=url)
            if res.score > 70: 
                results.append(res)
                report_path = f"data/reports/invest_{symbol}.html"
                patterns = analyst.analyze(candles)
                visualizer.generate_report(candles, patterns, symbol, "dex", report_path, investment_result=res)
                
                # Alert & Journal
                journal.add_thesis(
                    symbol, res.score, mode, res.logic, 
                    res.entry_zone, res.invalidation_level, res.inv_level,
                    res.target_potential, res.target_level, report_path
                )
                alerter.send_discovery_alert(res)

    elif mode == "stocks":
        stock_adapter = StockAdapter(config)
        stock_list = config.get("stock_watchlist", ["TSLA", "NVDA", "AAPL", "PLTR", "SOFI", "AMD", "GME", "AMC"])
        logger.info(f"📡 Scanning major stocks: {stock_list}")
        
        for symbol in stock_list:
            logger.info(f"Evaluating {symbol}...")
            candles = stock_adapter.fetch_candles(symbol, interval="1d")
            if not candles: continue
            
            url = f"https://www.tradingview.com/chart/?symbol={symbol}"
            res = analyst.calculate_investment_score(candles, symbol, url=url)
            if res.score > 65:
                results.append(res)
                report_path = f"data/reports/invest_{symbol}.html"
                patterns = analyst.analyze(candles)
                visualizer.generate_report(candles, patterns, symbol, "stock", report_path, investment_result=res)
                
                # Alert & Journal
                journal.add_thesis(
                    symbol, res.score, mode, res.logic, 
                    res.entry_zone, res.invalidation_level, res.inv_level,
                    res.target_potential, res.target_level, report_path
                )
                alerter.send_discovery_alert(res)

    # 3. Present Results (CLI)
    results.sort(key=lambda x: x.score, reverse=True)

    print("\n" + "💎" * 30)
    print("STRATEGIC INVESTMENT SCANNER")
    print(f"Mode: {mode.upper()} | Criteria: Accumulation & Expansion")
    print("💎" * 30)
    
    if not results:
        print("No high-probability investment opportunities found.")
    else:
        for r in results:
            color_code = "🟢" if r.score > 80 else "🟡"
            print(f"{color_code} {r.symbol}: Score {r.score:.1f} | Type: {r.discovery_type}")
            print(f"  Logic: {r.logic}")
            print(f"  Entry: {r.entry_zone}")
            print(f"  Invalidation: {r.invalidation_level}")
            print(f"  Target: {r.target_potential}")
            print("-" * 40)
    
    print("=" * 60)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=15, help="Number of assets to scan")
    parser.add_argument("--mode", choices=["crypto", "stocks"], default="crypto")
    parser.add_argument("--monitor", action="store_true", help="Monitor active investments")
    args = parser.parse_args()
    
    run_investment_scanner(limit=args.limit, mode=args.mode, monitor=args.monitor)
