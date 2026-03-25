import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from scripts.telegram_daemon import invest, monitor, report, research, scan, start, stats


async def run_e2e_tests():
    update = MagicMock()
    update.message = AsyncMock()
    context = MagicMock()
    context.args = []

    await start(update, context)
    assert update.message.reply_text.call_count == 1
    assert "Binance research bot" in update.message.reply_text.call_args[0][0]
    update.message.reply_text.reset_mock()

    await invest(update, context)
    assert "disabled" in update.message.reply_text.call_args[0][0]
    update.message.reply_text.reset_mock()

    await scan(update, context)
    assert "Use `/research`" in update.message.reply_text.call_args[0][0]
    update.message.reply_text.reset_mock()

    await monitor(update, context)
    assert "Use `/report`" in update.message.reply_text.call_args[0][0]
    update.message.reply_text.reset_mock()

    with patch("scripts.telegram_daemon._run_cli", side_effect=["sync ok", '[{"symbol":"POLYX"}]', "Binance Research Alert\n- POLYX"]):
        await research(update, context)
        assert update.message.reply_text.call_count == 2
        assert "Syncing Binance Earn offers" in update.message.reply_text.call_args_list[0][0][0]
        assert "POLYX" in update.message.reply_text.call_args_list[1][0][0]
    update.message.reply_text.reset_mock()

    with patch("scripts.telegram_daemon._run_cli", return_value="Binance Two-Sleeve Daily Report\nSnapshot: test\nTotal equity: $1"):
        await report(update, context)
        assert "Binance Two-Sleeve Daily Report" in update.message.reply_text.call_args[0][0]
    update.message.reply_text.reset_mock()

    with patch(
        "scripts.telegram_daemon._run_cli",
        return_value="Binance Two-Sleeve Daily Report\nSnapshot: test\nTotal equity: $1\nEarn sleeve: $1\nSpot sleeve: $0\nLocked cash: $0\nRealized PnL: $0\nRolling returns: 7d 0.00% | 30d 0.00%",
    ):
        await stats(update, context)
        assert "Total equity" in update.message.reply_text.call_args[0][0]


def test_run_e2e_telegram():
    asyncio.run(run_e2e_tests())
