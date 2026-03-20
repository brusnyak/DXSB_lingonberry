import os
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

from binance.client import Client
from dotenv import load_dotenv

from src.planner.models import utc_now_iso


load_dotenv()


class BinanceGateway:
    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None, client: Optional[Client] = None):
        self.client = client or Client(
            api_key or os.getenv("BINANCE_API_KEY"),
            api_secret or os.getenv("BINANCE_SECRET_KEY"),
        )

    def get_account(self) -> Dict:
        return self.client.get_account()

    def get_exchange_info(self) -> Dict:
        return self.client.get_exchange_info()

    def get_symbol_ticker(self, symbol: str) -> Dict:
        return self.client.get_symbol_ticker(symbol=symbol)

    def get_ticker_24h(self, symbol: str) -> Dict:
        return self.client.get_ticker(symbol=symbol)

    def get_klines(self, symbol: str, interval: str, limit: int = 200) -> List[Dict]:
        rows = self.client.get_klines(symbol=symbol, interval=interval, limit=limit)
        candles = []
        for row in rows:
            candles.append(
                {
                    "open_time": int(row[0]),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "close_time": int(row[6]),
                    "quote_volume": float(row[7]),
                }
            )
        return candles

    def get_historical_klines(self, symbol: str, interval: str, start_str: str, end_str: Optional[str] = None) -> List[Dict]:
        rows = self.client.get_historical_klines(symbol, interval, start_str, end_str)
        candles = []
        for row in rows:
            candles.append(
                {
                    "open_time": int(row[0]),
                    "open": float(row[1]),
                    "high": float(row[2]),
                    "low": float(row[3]),
                    "close": float(row[4]),
                    "volume": float(row[5]),
                    "close_time": int(row[6]),
                    "quote_volume": float(row[7]),
                }
            )
        return candles

    def get_my_trades(self, symbol: str, limit: int = 1000) -> List[Dict]:
        return self.client.get_my_trades(symbol=symbol, limit=limit)

    def get_simple_earn_account(self) -> Dict:
        return self.client.get_simple_earn_account()

    def get_simple_earn_flexible_product_position(self, size: int = 100) -> Dict:
        return self.client.get_simple_earn_flexible_product_position(size=size)

    def get_simple_earn_locked_product_position(self, size: int = 100) -> Dict:
        return self.client.get_simple_earn_locked_product_position(size=size)

    def get_simple_earn_flexible_product_list(self, size: int = 100) -> Dict:
        return self.client.get_simple_earn_flexible_product_list(size=size)

    def get_simple_earn_locked_product_list(self, size: int = 100) -> Dict:
        return self.client.get_simple_earn_locked_product_list(size=size)


def parse_binance_rows(payload: Dict) -> List[Dict]:
    if isinstance(payload, list):
        return payload
    for key in ("rows", "data", "positionAmountVos", "list"):
        if isinstance(payload.get(key), list):
            return payload[key]
    return []


def ms_to_iso(ms: Optional[int]) -> Optional[str]:
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

