import json
import logging
import os
import pandas as pd
from datetime import datetime, timezone
from typing import List, Dict
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.adapters.market_adapters import ParquetAdapter
from src.analysis.ict_analyst import ICTAnalyst, Candle
from src.core.performance_journal import PerformanceJournal
from src.utils.ict_visualizer import ICTVisualizer

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("sliding_bt")

def run_sliding_backtest(file_path: str, window_size: int = 300, step: int = 20, max_bars: int = 5000):
    """
    Runs a sliding window backtest over a large Parquet file.
    window_size: Number of candles for analysis.
    step: How many candles to skip between analysis attempts.
    """
    with open("config.json", "r") as f:
        config = json.load(f)

    journal = PerformanceJournal(config["database_path"])
    analyst = ICTAnalyst()
    adapter = ParquetAdapter()
    visualizer = ICTVisualizer()

    symbol = os.path.basename(file_path).replace(".parquet", "")
    logger.info(f"Starting Sliding Backtest for {symbol}...")
    
    all_candles = adapter.fetch_candles(file_path)
    if not all_candles:
        logger.error("No candles found.")
        return

    # Slice to last max_bars
    if max_bars > 0:
        all_candles = all_candles[-max_bars:]

    logger.info(f"Loaded {len(all_candles)} candles. Window: {window_size}, Step: {step}")
    
    trades = []
    
    # Iterate through the data in windows
    for i in range(0, len(all_candles) - window_size - 100, step):
        window = all_candles[i : i + window_size]
        future = all_candles[i + window_size : i + window_size + 100] # Check next 100 bars
        
        patterns = analyst.analyze(window)
        if not patterns:
            continue
            
        confluence = [p for p in patterns if p.type == "Confluence"]
        if not confluence:
            continue
            
        best_p = confluence[0]
        if best_p.strength < 6.5: # Extreme threshold for high win rate
            continue

        entry_price = window[-1].close
        direction = best_p.direction
        
        # Parse Targets from Analyst if available
        target_override = None
        if "TP_TARGET:" in best_p.context:
            try:
                target_override = float(best_p.context.split("TP_TARGET:")[1].split(";")[0])
            except:
                pass

        # Soft confirmation: Not strictly requiring green/red but checking for exhaustion
        last_c = window[-1]
        # (Removed strict check for now)

        # Dynamic TP/SL targeting min 2.5 RR
        # Find local structural low/high for SL
        lookback = window[-15:]
        if direction == "BULLISH":
            sl_price = min(c.low for c in lookback) * 0.999 # Slightly below
            risk = entry_price - sl_price
            if risk <= 0: continue
            tp_price = target_override if target_override else entry_price + (risk * 3.0) # Aim for 3R
        else:
            sl_price = max(c.high for c in lookback) * 1.001
            risk = sl_price - entry_price
            if risk <= 0: continue
            tp_price = target_override if target_override else entry_price - (risk * 3.0)
            
        # Risk-Reward check skip if target is too close
        actual_rr = abs(tp_price - entry_price) / risk if risk > 0 else 0
        if actual_rr < 1.1: continue # Reject low RR target trades
            
        outcome = "EXPIRED"
        exit_price = future[-1].close
        be_triggered = False
        
        target_be = entry_price + (risk * 1.5) if direction == "BULLISH" else entry_price - (risk * 1.5)

        for c in future:
            # 1. Break Even Logic
            if not be_triggered:
                if direction == "BULLISH" and c.high >= target_be:
                    be_triggered = True
                    sl_price = entry_price # Move SL to BE
                elif direction == "BEARISH" and c.low <= target_be:
                    be_triggered = True
                    sl_price = entry_price
            
            # 2. SL / TP Logic
            if direction == "BULLISH":
                if c.low <= sl_price:
                    outcome = "SL" if not be_triggered else "BE"
                    exit_price = sl_price
                    break
                if c.high >= tp_price:
                    outcome = "TP"
                    exit_price = tp_price
                    break
            else: # BEARISH
                if c.high >= sl_price:
                    outcome = "SL" if not be_triggered else "BE"
                    exit_price = sl_price
                    break
                if c.low <= tp_price:
                    outcome = "TP"
                    exit_price = tp_price
                    break

        pnl_pct = ((exit_price / entry_price) - 1) * 100
        if direction == "BEARISH": pnl_pct = -pnl_pct
        
        # Buffer for fees/spread in BE
        if outcome == "BE": pnl_pct = -0.1 
        
        trade_info = {
            "timestamp": window[-1].timestamp,
            "entry_price": entry_price,
            "tp_price": tp_price,
            "sl_price": sl_price,
            "outcome": outcome,
            "pnl": pnl_pct,
            "pattern": best_p.type,
            "confluence": best_p.context
        }
        trades.append(trade_info)
        
        logger.info(f"Trade: {direction} | Result: {outcome} | PnL: {pnl_pct:.2f}% | Reason: {best_p.context}")
        
        journal.log_trade(
            symbol=symbol,
            chain_id="parquet_bt",
            adapter="parquet",
            entry=entry_price,
            exit=exit_price,
            pnl_pct=pnl_pct,
            outcome=outcome,
            reasoning=f"BT: {best_p.type} {direction} ({best_p.context})"
        )
        
        if len(trades) <= 5: 
            report_name = f"data/reports/bt_report_{symbol}_{len(trades)}.html"
            visualizer.generate_report(
                window + future[:50], 
                patterns, 
                f"{symbol}_BT_{len(trades)}", 
                "parquet", 
                report_name,
                trades=[trade_info]
            )

    # Summary
    if not trades:
        logger.info("No trades triggered.")
        return

    win_rate = len([t for t in trades if t["outcome"] == "TP"]) / len(trades) * 100
    be_rate = len([t for t in trades if t["outcome"] == "BE"]) / len(trades) * 100
    total_pnl = sum([t["pnl"] for t in trades])
    logger.info(f"BACKTEST SUMMARY FOR {symbol}:")
    logger.info(f"Total Trades: {len(trades)}")
    logger.info(f"Win Rate: {win_rate:.1f}%")
    logger.info(f"BE Rate: {be_rate:.1f}%")
    logger.info(f"Total PnL: {total_pnl:.2f}%")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", required=True, help="Path to parquet file")
    parser.add_argument("--max-bars", type=int, default=5000, help="Max bars to process")
    args = parser.parse_args()
    
    run_sliding_backtest(args.file, max_bars=args.max_bars)
