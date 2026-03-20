import os
import sys
import json
import logging
import time
from datetime import datetime, timezone
from typing import List, Dict, Optional

# Ensure project root is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.adapters.market_adapters import DexScreenerAdapter, BinanceAdapter, StockAdapter
from src.analysis.ict_analyst import ICTAnalyst, InvestmentResult
from src.analysis.sentiment_analyst import SentimentAnalyst
from src.utils.ict_visualizer import ICTVisualizer
from src.utils.static_chart import generate_static_chart
from src.dex_bot import DexScreenerClient
from src.core.investment_journal import InvestmentJournal
from src.core.performance_journal import PerformanceJournal
from src.utils.telegram_alerter import TelegramAlerter

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("investment_scanner")


def _parse_metadata(raw_meta) -> Dict:
    if isinstance(raw_meta, dict):
        return raw_meta
    if isinstance(raw_meta, str) and raw_meta.strip():
        try:
            return json.loads(raw_meta)
        except Exception:
            return {}
    return {}


def _parse_entry_price_from_zone(entry_zone: str) -> Optional[float]:
    if not isinstance(entry_zone, str):
        return None
    marker = "@"
    if marker in entry_zone:
        try:
            return float(entry_zone.split(marker)[-1].strip())
        except Exception:
            return None
    return None

def run_investment_scanner(limit: int = 15, mode: str = "crypto", monitor: bool = False):
    """
    Scans markets for mid-term investment opportunities (The 'Expansion' model).
    mode: 'crypto' (Dex + Binance) or 'stocks'
    """
    with open("config.json", "r") as f:
        config = json.load(f)
        
    db_path = config.get("database_path", "dex_analytics.db")

    analyst = ICTAnalyst()
    sentiment = SentimentAnalyst()
    visualizer = ICTVisualizer()
    journal = InvestmentJournal(db_path)
    perf_journal = PerformanceJournal(db_path)
    alerter = TelegramAlerter()
    results: List[InvestmentResult] = []

    # Phase 16: External Sentiment
    sentiment_bonus = sentiment.get_contrarian_bonus(mode)

    # 0. Monitoring Mode
    if monitor:
        logger.info("🕵️ Monitoring active investments...")
        active = journal.get_active_investments()
        binance = BinanceAdapter()
        stocks = StockAdapter(config)
        dex_client = DexScreenerClient()
        dex = DexScreenerAdapter(dex_client, config)
        now_utc = datetime.now(timezone.utc)
        max_hold_days = 14
        
        for inv in active:
            symbol = inv["symbol"]
            current_price = 0.0
            metadata = _parse_metadata(inv.get("extra_metadata"))
            entry_price = metadata.get("signal_price") or _parse_entry_price_from_zone(inv.get("entry_zone", ""))
            signal_ts = inv.get("ts_utc")
            
            # Fetch current price based on discovery type
            if inv["discovery_type"] == "crypto":
                # Prefer Dex pair price for DEX-native tokens; fallback to Binance if needed.
                pair_address = metadata.get("pair_address")
                chain_id = metadata.get("chain_id")
                if pair_address and chain_id:
                    data = dex.get_market_data(pair_address, chain_id=chain_id)
                    current_price = float(data.get("priceUsd", 0) or 0)
                if current_price == 0:
                    data = binance.get_market_data(f"{symbol}USDT")
                    current_price = float(data.get("priceUsd", 0) or 0)
            elif inv["discovery_type"] == "stocks":
                data = stocks.get_market_data(symbol)
                current_price = float(data.get("priceUsd", 0) or 0)
            
            if current_price == 0:
                logger.warning(f"Could not fetch price for {symbol}")
                continue

            logger.info(f"Monitoring {symbol}: Price {current_price:.8f} (Inv: {inv['inv_level']:.8f}, Target: {inv['target_level']:.8f})")
            
            # Check Invalidation
            if current_price <= inv["inv_level"]:
                msg = f"THESIS INVALIDATED: Price broke below {inv['inv_level']:.8f}"
                alerter.send_status_update(symbol, "INVALIDATED", current_price)
                journal.update_status(inv["id"], "INVALIDATED", current_price)
                if entry_price and entry_price > 0:
                    pnl_pct = ((current_price / float(entry_price)) - 1) * 100
                    entry_for_log = float(entry_price)
                else:
                    pnl_pct = -1.5
                    entry_for_log = current_price
                perf_journal.log_trade(symbol, "auto", inv["discovery_type"], entry=entry_for_log, exit=current_price, pnl_pct=pnl_pct, outcome="SL")
                logger.warning(f"❌ {symbol} {msg}")
                
            # Check Target
            elif current_price >= inv["target_level"]:
                msg = f"TARGET REACHED: Price hit/exceeded {inv['target_level']:.8f}"
                alerter.send_status_update(symbol, "TARGET_REACHED", current_price)
                journal.update_status(inv["id"], "TARGET_REACHED", current_price)
                if entry_price and entry_price > 0:
                    pnl_pct = ((current_price / float(entry_price)) - 1) * 100
                    entry_for_log = float(entry_price)
                else:
                    pnl_pct = 5.0
                    entry_for_log = current_price
                perf_journal.log_trade(symbol, "auto", inv["discovery_type"], entry=entry_for_log, exit=current_price, pnl_pct=pnl_pct, outcome="TP")
                logger.info(f"🚀 {symbol} {msg}")

            # Time-based thesis expiry to avoid stale active thesis inflation.
            elif signal_ts:
                try:
                    opened_at = datetime.fromisoformat(signal_ts)
                    age_days = (now_utc - opened_at).total_seconds() / 86400
                    if age_days >= max_hold_days:
                        alerter.send_status_update(symbol, "EXPIRED", current_price)
                        journal.update_status(inv["id"], "EXPIRED", current_price)
                        if entry_price and entry_price > 0:
                            pnl_pct = ((current_price / float(entry_price)) - 1) * 100
                        else:
                            pnl_pct = 0.0
                        perf_journal.log_trade(
                            symbol, "auto", inv["discovery_type"],
                            entry=float(entry_price or current_price), exit=current_price,
                            pnl_pct=pnl_pct, outcome="EXPIRED"
                        )
                        logger.info(f"⌛ {symbol} thesis expired after {age_days:.1f} days")
                except Exception:
                    pass
        return

    # 1. Fetch Benchmark (BTC for Crypto, SPY for Stocks)
    benchmark_candles = None
    if mode == "crypto":
        binance = BinanceAdapter()
        benchmark_candles = binance.fetch_candles("BTCUSDT", interval="1d", limit=100)
        logger.info("Fetched BTC Benchmark for Relative Strength analysis.")

    # 2. Market Scanning
    active_symbols = [inv["symbol"] for inv in journal.get_active_investments()]
    
    if mode == "crypto":
        client = DexScreenerClient()
        dex = DexScreenerAdapter(client, config)
        logger.info(f"📡 Scanning DexScreener Trending for potential gems (skipping {len(active_symbols)} already active)...")
        candidates = dex.fetch_candidates()
        
        scan_limit = min(len(candidates), limit)
        for i in range(scan_limit):
            item = candidates[i]
            symbol = item.get("baseToken", {}).get("symbol", "???")
            address = item.get("pairAddress")
            chain = item.get("chainId")
            
            logger.info(f"[{i+1}/{scan_limit}] Evaluating {symbol}...")
            
            if symbol in active_symbols:
                logger.info(f"Skipping {symbol} - Already an active investment in journal.")
                continue
                
            time.sleep(3.0) # GeckoTerminal limit is 30/min (2.0s min). 3.0s is safe.
            
            candles = dex.fetch_candles(address, interval="day", limit=100, chain_id=chain)
            if not candles: continue
            
            url = f"https://dexscreener.com/{chain}/{address}"
            res = analyst.calculate_investment_score(candles, symbol, benchmark_candles, sentiment_bonus=sentiment_bonus, url=url)
            
            # Quality filter: reject tokens with tiny target potential or low score
            try:
                target_pct = float(res.target_potential.split("~")[1].split("%")[0])
            except (IndexError, ValueError):
                target_pct = 0.0
            if res.score <= 70 or target_pct < 5.0:
                logger.info(f"Skipping {symbol} – Score: {res.score:.0f}, TP: {target_pct:.1f}%")
                continue

            entry_state = (res.extra_metadata or {}).get("entry_state", "UNKNOWN")
            overextended = bool((res.extra_metadata or {}).get("overextended", False))
            upside_to_target = float((res.extra_metadata or {}).get("upside_to_target_pct", 0.0) or 0.0)

            if entry_state != "READY":
                logger.info(f"Skipping {symbol} – Entry state: {entry_state}")
                continue
            if overextended:
                logger.info(f"Skipping {symbol} – Overextended setup")
                continue
            if upside_to_target < 4.0:
                logger.info(f"Skipping {symbol} – Low runway ({upside_to_target:.1f}%)")
                continue
            
            # High-conviction signal found!
            res.discovery_type = "crypto"
            if res.extra_metadata is None:
                res.extra_metadata = {}
            res.extra_metadata.update({
                "pair_address": address,
                "chain_id": chain,
                "token_address": item.get("baseToken", {}).get("address"),
            })
            results.append(res)
            report_path = f"data/reports/invest_{symbol}.html"
            report_png = f"data/reports/invest_{symbol}.png"
            patterns = analyst.analyze(candles)
            visualizer.generate_report(candles, patterns, symbol, "dex", report_path, investment_result=res)
            generate_static_chart(candles, symbol, output_path=report_png)
            
            # Alert & Journal
            journal.add_thesis(
                symbol, res.score, "crypto", res.logic, 
                res.entry_zone, res.invalidation_level, res.inv_level,
                res.target_potential, res.target_level, report_path,
                res.extra_metadata
            )
            alerter.send_discovery_alert(res, image_path=report_png)

    elif mode == "stocks":
        stock_adapter = StockAdapter(config)
        stock_list = config.get("stock_watchlist", ["TSLA", "NVDA", "AAPL", "PLTR", "SOFI", "AMD", "GME", "AMC"])
        logger.info(f"📡 Scanning major stocks: {stock_list}")
        
        # S&P 500 Benchmark (Phase 16)
        benchmark_candles = stock_adapter.fetch_candles("SPY", interval="1d", limit=100)
        
        for symbol in stock_list:
            logger.info(f"Evaluating {symbol}...")
            
            if symbol in active_symbols:
                logger.info(f"Skipping {symbol} - Already an active investment in journal.")
                continue
                
            candles = stock_adapter.fetch_candles(symbol, interval="1d")
            if not candles: continue
            
            # Sector Benchmarking (Phase 16)
            sector_etf = stock_adapter.get_sector_etf(symbol)
            sector_candles = stock_adapter.fetch_candles(sector_etf, interval="1d")
            
            url = f"https://www.tradingview.com/chart/?symbol={symbol}"
            res = analyst.calculate_investment_score(candles, symbol, benchmark_candles, sector_candles=sector_candles, sentiment_bonus=sentiment_bonus, url=url)
            
            # Quality filter: reject stocks with tiny target potential or low score
            try:
                target_pct = float(res.target_potential.split("~")[1].split("%")[0])
            except (IndexError, ValueError):
                target_pct = 0.0
            if res.score <= 65 or target_pct < 5.0:
                logger.info(f"Skipping {symbol} – Score: {res.score:.0f}, TP: {target_pct:.1f}%")
                continue
            
            # High-conviction signal found!
            res.discovery_type = "stocks"
            results.append(res)
            report_path = f"data/reports/invest_{symbol}.html"
            report_png = f"data/reports/invest_{symbol}.png"
            patterns = analyst.analyze(candles)
            visualizer.generate_report(candles, patterns, symbol, "stock", report_path, investment_result=res)
            generate_static_chart(candles, symbol, output_path=report_png)
            
            # Alert & Journal
            journal.add_thesis(
                symbol, res.score, "stocks", res.logic, 
                res.entry_zone, res.invalidation_level, res.inv_level,
                res.target_potential, res.target_level, report_path,
                res.extra_metadata
            )
            alerter.send_discovery_alert(res, image_path=report_png)

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
