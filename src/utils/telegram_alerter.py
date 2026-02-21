import requests
import logging
import os
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("dxsb.telegram")

class TelegramAlerter:
    """Sends formatted alerts to Telegram for strategic investment discoveries."""
    
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.api_url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    def send_discovery_alert(self, r):
        """
        Sends a high-conviction discovery alert.
        r: InvestmentResult object
        """
        if not self.token or not self.chat_id:
            logger.warning("Telegram credentials missing in .env")
            return

        emoji = "💎" if r.score >= 90 else "🟢"
        chart_url = r.url or "https://tradingview.com"
        
        message = (
            f"{emoji} *INVESTMENT ALERT: {r.symbol}*\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🏆 *Score:* `{r.score:.1f}/100`\n"
            f"🔭 *Logic:* _{r.logic}_\n"
            f"📊 *Potential:* `{r.target_potential}`\n\n"
            f"📥 *Entry Zone:* `{r.entry_zone}`\n"
            f"🛡️ *Invalidation:* `{r.invalidation_level}`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🔗 [VIEW LIVE CHART]({chart_url})"
        )

        try:
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False
            }
            resp = requests.post(self.api_url, json=payload, timeout=10)
            resp.raise_for_status()
            logger.info(f"Telegram Alert Sent: {r.symbol}")
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")

    def send_status_update(self, symbol: str, status: str, price: float):
        """Notifies about status changes (Invalidated or Target Reached)."""
        icon = "🚨" if "INVALIDATED" in status else "🚀"
        message = (
            f"{icon} *MONITORING UPDATE: {symbol}*\n\n"
            f"Status changed to: *{status}*\n"
            f"Current Price: `{price:.8f}`"
        )
        try:
            payload = {"chat_id": self.chat_id, "text": message, "parse_mode": "Markdown"}
            requests.post(self.api_url, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Failed to send status update: {e}")
