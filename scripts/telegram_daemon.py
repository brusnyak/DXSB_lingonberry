import asyncio
import logging
import os
import subprocess
import sys
from typing import List

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes


sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


DEPRECATION_NOTE = (
    "Legacy DexScreener and ICT scanner commands are disabled. "
    "This bot now uses the Binance planner workflow."
)


def _run_cli(args: List[str]) -> str:
    result = subprocess.run(
        [sys.executable, "cli.py", *args],
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "Binance research bot\n\n"
        "Available Commands:\n"
        "/report - Run the planner daily report\n"
        "/research - Sync Binance Earn offers and scan research candidates\n"
        "/scan - Deprecated legacy scanner command\n"
        "/monitor - Deprecated legacy monitoring command\n"
        "/invest - Deprecated legacy analysis command\n"
        "/stats - Show planner-oriented status"
    )
    await update.message.reply_text(msg)


async def invest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"{DEPRECATION_NOTE} Use `/report` and `/research` instead."
    )


async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"{DEPRECATION_NOTE} Use `/research` to sync Earn offers and scan Binance candidates."
    )


async def monitor(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"{DEPRECATION_NOTE} Use `/report` for current positions, cash, and blocked ideas."
    )


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = await asyncio.to_thread(_run_cli, ["report", "daily"])
        await update.message.reply_text(text)
    except Exception as exc:
        await update.message.reply_text(f"Planner report failed: {exc}")


async def research(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        await update.message.reply_text("Syncing Binance Earn offers and scanning research candidates...")
        await asyncio.to_thread(_run_cli, ["research", "sync-earn"])
        await asyncio.to_thread(_run_cli, ["strategy", "scan-research"])
        output = await asyncio.to_thread(_run_cli, ["report", "research"])
        await update.message.reply_text(output[:4000] or "No research alert generated.")
    except Exception as exc:
        await update.message.reply_text(f"Research scan failed: {exc}")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = await asyncio.to_thread(_run_cli, ["report", "daily"])
        lines = text.splitlines()
        summary = "\n".join(lines[:8])
        await update.message.reply_text(summary)
    except Exception as exc:
        await update.message.reply_text(f"Planner status failed: {exc}")


async def eod(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await report(update, context)


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
    application.add_handler(CommandHandler("report", report))
    application.add_handler(CommandHandler("research", research))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("eod", eod))

    logger.info("Starting Telegram planner daemon...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
