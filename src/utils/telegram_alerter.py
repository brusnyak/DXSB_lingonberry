import requests
import logging
import os
import json
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("dxsb.telegram")

class TelegramAlerter:
    """Sends formatted alerts to Telegram for strategic investment discoveries."""
    
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.api_base = f"https://api.telegram.org/bot{self.token}"

    def send_discovery_alert(self, r, image_path: str = None):
        """
        Sends a high-conviction discovery alert.
        r: InvestmentResult object
        """
        if not self.token or not self.chat_id:
            logger.warning("Telegram credentials missing in .env")
            return

        emoji = "💎" if r.score >= 90 else "🟢"
        chart_url = r.url or "https://tradingview.com"
        meta = r.extra_metadata or {}
        chain_id = meta.get("chain_id", "solana")
        pair_address = meta.get("pair_address")
        token_address = meta.get("token_address", r.symbol)
        
        # Differentiate Crypto vs Stock
        if r.discovery_type == "crypto":
            asset_type_header = "🔗 CRYPTO INVESTMENT SIGNAL"
            score_bar = "🟩" * int(r.score / 10) + "⬜" * (10 - int(r.score / 10))
        else:
            asset_type_header = "📈 STOCK INVESTMENT SIGNAL"
            score_bar = "🟦" * int(r.score / 10) + "⬜" * (10 - int(r.score / 10))
        
        message = (
            f"{emoji} *{asset_type_header}*\n"
            f"*Asset:* `{r.symbol}`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🏆 *Score:* `{r.score:.0f}/95` {score_bar}\n"
            f"🔭 *Logic:*\n_{r.logic}_\n\n"
            f"📊 *Potential:* `{r.target_potential}`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📥 *Entry:* `{r.entry_zone}`\n"
            f"🛑 *Stop/Invalidation:* `{r.invalidation_level}`\n"
            f"🎯 *Target:* `{r.target_potential}`\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🔗 [VIEW LIVE CHART]({chart_url})"
        )

        try:
            # Prepare Inline Keyboard Buttons (Solbix Style)
            dex_url = f"https://dexscreener.com/search?q={r.symbol}"
            tv_url = f"https://www.tradingview.com/chart/?symbol={r.symbol}"
            if pair_address:
                dex_url = f"https://dexscreener.com/{chain_id}/{pair_address}"
            # Specific DEX URL if known (mocked BullX/Trojan style)
            if r.discovery_type == "crypto":
                buylink = f"https://bullx.io/terminal?chainId={chain_id}&address={token_address}"
            else:
                buylink = f"https://finance.yahoo.com/quote/{r.symbol}"

            keyboard = {
                "inline_keyboard": [[
                    {"text": "📊 TradingView", "url": tv_url},
                    {"text": "🦅 DexScreener" if r.discovery_type == "crypto" else "📈 Yahoo Finance", "url": dex_url if r.discovery_type == "crypto" else buylink},
                ], [
                    {"text": "⚡ Trade on BullX" if r.discovery_type == "crypto" else "🏦 Broker", "url": buylink}
                ]]
            }

            if image_path and os.path.exists(image_path):
                # Send Photo with Caption
                url = f"{self.api_base}/sendPhoto"
                payload = {"chat_id": self.chat_id, "caption": message, "parse_mode": "Markdown", "reply_markup": json.dumps(keyboard)}
                with open(image_path, "rb") as photo:
                    resp = requests.post(url, data=payload, files={"photo": photo}, timeout=15)
            else:
                # Fallback to standard Text Message
                url = f"{self.api_base}/sendMessage"
                payload = {"chat_id": self.chat_id, "text": message, "parse_mode": "Markdown", "disable_web_page_preview": False, "reply_markup": json.dumps(keyboard)}
                resp = requests.post(url, json=payload, timeout=10)

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
            url = f"{self.api_base}/sendMessage"
            payload = {"chat_id": self.chat_id, "text": message, "parse_mode": "Markdown"}
            requests.post(url, json=payload, timeout=10)
        except Exception as e:
            logger.error(f"Failed to send status update: {e}")
