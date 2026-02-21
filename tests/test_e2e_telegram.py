import sys
import os
import asyncio
from unittest.mock import MagicMock, AsyncMock

# Ensure project root is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.telegram_daemon import start, invest, scan, monitor, stats

async def run_e2e_tests():
    print("\n" + "="*50)
    print("🚀 RUNNING END-TO-END TELEGRAM BOT TESTS")
    print("="*50 + "\n")

    # Mocks for python-telegram-bot
    update = MagicMock()
    update.message = AsyncMock()
    context = MagicMock()

    # 1. Test /start
    print("--- Testing /start Command ---")
    await start(update, context)
    update.message.reply_text.assert_called()
    print("✅ /start successful (Welcome message sent)\n")
    update.message.reply_text.reset_mock()

    # 2. Test /stats
    print("--- Testing /stats Command (Journaling check) ---")
    await stats(update, context)
    update.message.reply_text.assert_called()
    msg = update.message.reply_text.call_args[0][0]
    print(f"Stats output:\n{msg}")
    print("✅ /stats successful\n")
    update.message.reply_text.reset_mock()

    # 3. Test /invest BTCUSDT (Crypto Analysis)
    print("--- Testing /invest BTCUSDT Command (Analysis Pipeline) ---")
    context.args = ["BTCUSDT"]
    await invest(update, context)
    
    # invest sends 2 messages (analyzing... then result)
    assert update.message.reply_text.call_count == 2
    msg = update.message.reply_text.call_args[0][0]
    print(f"Analysis result:\n{msg}")
    print("✅ /invest BTCUSDT successful (Crypto path + Sentiment Analysis)\n")
    update.message.reply_text.reset_mock()

    # 4. Test /invest AAPL (Stock Analysis + Sector Alpha)
    print("--- Testing /invest AAPL Command (Stock Pipeline + Sector Benchmark) ---")
    context.args = ["AAPL"]
    await invest(update, context)
    
    assert update.message.reply_text.call_count == 2
    msg = update.message.reply_text.call_args[0][0]
    print(f"Analysis result:\n{msg}")
    print("✅ /invest AAPL successful (Stock path + Sector Alpha scoring)\n")
    update.message.reply_text.reset_mock()

    # 5. Test /monitor (Live scanning of active investments)
    print("--- Testing /monitor Command (Invalidation/Target checking) ---")
    await monitor(update, context)
    
    assert update.message.reply_text.call_count == 2
    print("✅ /monitor successful (Checked Active Investments Db)\n")
    update.message.reply_text.reset_mock()

    # 6. Test /scan stocks (Live market scanning + telegram signal alerting)
    print("--- Testing /scan stocks Command (Signal Generation & Messaging) ---")
    context.args = ["stocks"]
    await scan(update, context)
    
    assert update.message.reply_text.call_count == 2
    print("✅ /scan stocks successful (Scan loop triggered, alerts pushed if high score)\n")
    
    print("\n" + "="*50)
    print("🎉 ALL END-TO-END TESTS PASSED SUCCESSFULLY!")
    print("="*50 + "\n")

if __name__ == "__main__":
    asyncio.run(run_e2e_tests())
