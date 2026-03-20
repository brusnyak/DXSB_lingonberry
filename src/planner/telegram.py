import os

import requests
from dotenv import load_dotenv


load_dotenv()


def send_plain_text(message: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": True,
    }
    response = requests.post(url, json=payload, timeout=10)
    response.raise_for_status()
    return True
