import sys
import os
import json
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.adapters.market_adapters import StockAdapter, BinanceAdapter
from src.analysis.ict_analyst import ICTAnalyst
from src.analysis.sentiment_analyst import SentimentAnalyst
from src.core.investment_journal import InvestmentJournal
from src.core.performance_journal import PerformanceJournal
from scripts.live_scanner import run_investment_scanner

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "🤖 *Investment Discovery Engine*\n\n"
        "Available Commands:\n"
        "/invest [symbol] - Run analysis on a specific stock/crypto\n"
        "/scan [stocks|crypto] - Run a full discovery scan\n"
        "/monitor - Check active investments for targets/invalidation\n"
        "/stats - View performance journaling metrics"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Please provide a symbol. Example: /invest AAPL or /invest BTCUSDT")
        return

    symbol = context.args[0].upper()
    await update.message.reply_text(f"🔍 Analyzing {symbol}...")

    with open("config.json", "r") as f:
        config = json.load(f)

    analyst = ICTAnalyst()
    sentiment = SentimentAnalyst()
    
    # Determine if stock or crypto (basic heuristic)
    mode = "crypto" if "USDT" in symbol else "stocks"
    sentiment_bonus = sentiment.get_contrarian_bonus(mode)

    if mode == "crypto":
        adapter = BinanceAdapter()
        candles = adapter.fetch_candles(symbol, interval="1d")
        benchmark = adapter.fetch_candles("BTCUSDT", interval="1d")
        sector_candles = None
    else:
        adapter = StockAdapter(config)
        candles = adapter.fetch_candles(symbol, interval="1d")
        benchmark = adapter.fetch_candles("SPY", interval="1d")
        sector_etf = adapter.get_sector_etf(symbol)
        sector_candles = adapter.fetch_candles(sector_etf, interval="1d")

    if not candles:
        await update.message.reply_text(f"❌ Could not fetch data for {symbol}.")
        return

    res = analyst.calculate_investment_score(
        candles, symbol, benchmark_candles=benchmark, 
        sector_candles=sector_candles, sentiment_bonus=sentiment_bonus
    )

    color = "🟢" if res.score >= 80 else "🟡" if res.score >= 60 else "🔴"
    msg = (
        f"{color} *Analysis for {symbol}*\n\n"
        f"Score: {res.score:.1f}/100\n"
        f"Type: {res.discovery_type}\n\n"
        f"*Logic:*\n{res.logic}\n\n"
        f"*Entry Zone:*\n{res.entry_zone}\n\n"
        f"*Invalidation:*\n{res.invalidation_level}\n\n"
        f"*Target Potential:*\n{res.target_potential}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    mode = "stocks"
    if context.args and context.args[0].lower() == "crypto":
        mode = "crypto"
        
    await update.message.reply_text(f"📡 Starting full discovery scan for {mode}...")
    try:
        run_investment_scanner(limit=10, mode=mode)
        await update.message.reply_text("✅ Scan completed. Check Telegram channel for high-score alerts.")
    except Exception as e:
         await update.message.reply_text(f"❌ Scan failed: {e}")

async def monitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🕵️ Checking active investments...")
    try:
        run_investment_scanner(mode="stocks", monitor=True)
        await update.message.reply_text("✅ Monitoring completed.")
    except Exception as e:
         await update.message.reply_text(f"❌ Monitoring failed: {e}")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    journal = InvestmentJournal("dex_analytics.db")
    perf_journal = PerformanceJournal("dex_analytics.db")
    
    active = len(journal.get_active_investments())
    stats = perf_journal.get_stats()
    
    base_balance = 10000.0
    growth_pct = stats.get("total_pnl_pct", 0.0)
    current_balance = base_balance * (1 + (growth_pct / 100))
    
    msg = (
        "📊 *Paper Trading Performance*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💼 *Simulated Balance:* `${current_balance:,.2f}`\n"
        f"📈 *Net Growth:* `+{growth_pct:.2f}%`\n\n"
        f"🎯 *Win Rate:* `{stats.get('win_rate', 0):.1f}%`\n"
        f"✅ *Wins:* `{stats.get('wins', 0)}` | ❌ *Losses:* `{stats.get('losses', 0)}`\n"
        f"⏱️ *Active Theses:* `{active}`\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "_(Starting theoretical balance: $10,000)_"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set.")
        return

    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("invest", invest))
    application.add_handler(CommandHandler("scan", scan))
    application.add_handler(CommandHandler("monitor", monitor))
    application.add_handler(CommandHandler("stats", stats))

    logger.info("Starting Telegram interactive daemon...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
