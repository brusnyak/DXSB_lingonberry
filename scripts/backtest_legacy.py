import json
import logging
import time
from datetime import datetime, timezone
from typing import List, Dict
from adapters import DexScreenerAdapter, BinanceAdapter, StockAdapter
from ict_analyst import ICTAnalyst, Candle
from performance_journal import PerformanceJournal
from dex_bot import DexScreenerClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("backtest")

def run_backtest(adapter_type: str, pool_address: str):
    """Simulates a trade based on the last 100 candles."""
    with open("config.json", "r") as f:
        config = json.load(f)

    client = DexScreenerClient()
    journal = PerformanceJournal(config["database_path"])
    analyst = ICTAnalyst()

    if adapter_type == "binance":
        adapter = BinanceAdapter()
    elif adapter_type == "stock":
        adapter = StockAdapter(config)
    else:
        adapter = DexScreenerAdapter(client, config)

    logger.info(f"Backtesting {pool_address} via {adapter_type}...")
    candles = adapter.fetch_candles(pool_address)
    
    if not candles:
        logger.error("No data found.")
        return

    # Split into history (first 80) and test (last 20)
    history = candles[:80]
    test_set = candles[80:]
    
    patterns = analyst.analyze(history)
    if not patterns:
        logger.warning("No ICT patterns found in history. Skipping.")
        return

    # Simulate entry at candle 80 close
    entry_price = history[-1].close
    logger.info(f"Entry Signal Detected! Entry at ${entry_price:.8f}")
    
    # Check test set for TP/SL
    stop_pct = 5.0 # Fixed for test
    tp_pct = 15.0  # Fixed for test
    stop_price = entry_price * (1 - stop_pct/100)
    tp_price = entry_price * (1 + tp_pct/100)
    
    outcome = "EXPIRED"
    final_price = test_set[-1].close
    
    for c in test_set:
        if c.low <= stop_price:
            outcome = "SL"
            final_price = stop_price
            break
        if c.high >= tp_price:
            outcome = "TP"
            final_price = tp_price
            break
            
    pnl_pct = ((final_price / entry_price) - 1) * 100
    journal.log_trade(
        symbol=pool_address,
        chain_id="backtest",
        adapter=adapter_type,
        entry=entry_price,
        exit=final_price,
        pnl_pct=pnl_pct,
        outcome=outcome,
        reasoning=f"BACKTEST: Found {len(patterns)} ICT patterns (e.g. {patterns[0].type})"
    )
    
    print(f"\nBACKTEST COMPLETE: {pool_address}")
    print(f"Result: {outcome} | PnL: {pnl_pct:.2f}%")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", default="dex", choices=["dex", "binance", "stock"])
    parser.add_argument("--pool", required=True)
    args = parser.parse_args()
    
    run_backtest(args.type, args.pool)
