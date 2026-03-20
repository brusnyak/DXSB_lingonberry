from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from src.analysis.ict_analyst import Candle
import numpy as np
import pandas as pd
import csv
from datetime import datetime

class BaseAdapter(ABC):
    """Base class for all market adapters (DEX, CEX, Stocks)."""
    
    @abstractmethod
    def fetch_candidates(self) -> List[Dict]:
        """Fetch list of potential trading pairs/assets."""
        pass

    @abstractmethod
    def fetch_candles(self, symbol_or_address: str, interval: str = "1m", limit: int = 100, chain_id: Optional[str] = None) -> List[Candle]:
        """Fetch OHLCV historical data for ICT analysis."""
        pass

    @abstractmethod
    def get_market_data(self, symbol_or_address: str, chain_id: Optional[str] = None) -> Dict:
        """Fetch real-time metrics (liquidity, volume, etc)."""
        pass

class DexScreenerAdapter(BaseAdapter):
    def __init__(self, dex_client, config: Dict = None):
        self.dex = dex_client
        self.config = config or {}
        self.gecko_base = "https://api.geckoterminal.com/api/v2"

    def fetch_candidates(self) -> List[Dict]:
        runtime_cfg = self.config.get("runtime", {"profile_scan_limit": 50})
        monitored_chains = {c.lower() for c in self.config.get("monitored_chains", ["solana"])}

        profiles = self.dex.fetch_latest_token_profiles()
        by_pair: Dict[str, Dict] = {}

        # Prioritize these as they are "newly profiled"
        token_addresses = []
        for item in profiles[:100]:
            chain = str(item.get("chainId", "")).lower()
            token_address = str(item.get("tokenAddress", ""))
            if chain in monitored_chains and token_address:
                token_addresses.append(token_address)
        
        # We need a chain to fetch by tokens, let's assume the first monitored chain for profiles
        # or iterate through monitored chains. Simplified for now.
        if monitored_chains and token_addresses:
            for chain in monitored_chains:
                for pair in self.dex.fetch_pairs_by_tokens(chain, token_addresses):
                    key = f"{chain}:{pair.get('pairAddress', '')}".lower()
                    by_pair[key] = pair

        # Use search queries
        for query in self.config.get("search_queries", ["pump", "moon", "solana"]):
            for pair in self.dex.search_pairs(query):
                chain = str(pair.get("chainId", "")).lower()
                if chain in monitored_chains:
                    key = f"{chain}:{pair.get('pairAddress', '')}".lower()
                    by_pair[key] = pair

        # Add established tokens too
        for item in self.config.get("established_tokens", []):
            chain = str(item.get("chainId", "")).lower()
            token_address = str(item.get("tokenAddress", ""))
            if chain in monitored_chains and token_address:
                # Assuming we need to fetch pairs for these established tokens as well
                # This part was originally adding to token_map, which is now removed.
                # For now, we'll just add them to by_pair if we can fetch them.
                # A more robust solution might involve another call to fetch_pairs_by_tokens
                # or directly adding if the item itself is a pair.
                # For simplicity, let's assume item can be treated as a pair if it has pairAddress
                if "pairAddress" in item:
                    key = f"{chain}:{item.get('pairAddress', '')}".lower()
                    by_pair[key] = item
                else:
                    # If it's just a token address, we'd need to fetch its pairs
                    # This is a placeholder for more complex logic if needed
                    pass


        MIN_LIQUIDITY_USD = 50_000
        MIN_VOLUME_24H_USD = 100_000
        
        qualified = []
        for pair in by_pair.values():
            liquidity = pair.get("liquidity", {}).get("usd", 0) or 0
            volume_24h = pair.get("volume", {}).get("h24", 0) or 0
            symbol = pair.get("baseToken", {}).get("symbol", "")
            
            # Quality guard: reject low liquidity/volume garbage meme coins
            if liquidity < MIN_LIQUIDITY_USD or volume_24h < MIN_VOLUME_24H_USD:
                continue
            # Reject tokens without a recognizable symbol
            if not symbol or len(symbol) > 15:
                continue
            qualified.append(pair)
        
        return qualified

    def fetch_candles(self, pool_address: str, interval: str = "1m", limit: int = 100, chain_id: Optional[str] = "solana") -> List[Candle]:
        # Mapping standard intervals to GeckoTerminal
        # minute, hour, day
        gt_interval = "minute"
        if "h" in interval: gt_interval = "hour"
        elif "d" in interval: gt_interval = "day"
        
        gt_chain = "eth" if chain_id == "ethereum" else chain_id
        url = f"{self.gecko_base}/networks/{gt_chain}/pools/{pool_address}/ohlcv/{gt_interval}"
        try:
            import requests
            resp = requests.get(url, params={"aggregate": 1, "limit": limit}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            candles = []
            for item in data.get("data", {}).get("attributes", {}).get("ohlcv_list", []):
                candles.append(Candle(
                    timestamp=item[0],
                    open=item[1],
                    high=item[2],
                    low=item[3],
                    close=item[4],
                    volume=item[5]
                ))
            return candles[::-1] # Ensure chronological order
        except Exception as e:
            print(f"Candle fetch failed for {pool_address}: {e}")
            return []

    def get_market_data(self, pair_address: str, chain_id: Optional[str] = "solana") -> Dict:
        return self.dex.get_pair(chain_id, pair_address) or {}

class BinanceAdapter(BaseAdapter):
    def __init__(self, api_key: Optional[str] = None, secret_key: Optional[str] = None):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = "https://api.binance.com/api/v3"

    def fetch_candidates(self) -> List[Dict]:
        try:
            import requests
            resp = requests.get(f"{self.base_url}/ticker/24hr", timeout=10)
            resp.raise_for_status()
            tickers = resp.json()
            candidates = []
            for t in tickers:
                if t["symbol"].endswith("USDT") and float(t["quoteVolume"]) > 5000000:
                    candidates.append({
                        "chainId": "binance",
                        "pairAddress": t["symbol"],
                        "baseToken": {"symbol": t["symbol"].replace("USDT", ""), "address": t["symbol"]},
                        "volume": float(t["quoteVolume"]),
                        "priceUsd": float(t["lastPrice"])
                    })
            return sorted(candidates, key=lambda x: x["volume"], reverse=True)[:50]
        except Exception as e:
            print(f"Binance candidate fetch failed: {e}")
            return []

    def fetch_candles(self, symbol: str, interval: str = "1m", limit: int = 100, chain_id: Optional[str] = None) -> List[Candle]:
        try:
            import requests
            # Ensure interval is binance compatible
            b_interval = interval
            if interval == "1min": b_interval = "1m"
            params = {"symbol": symbol, "interval": b_interval, "limit": limit}
            resp = requests.get(f"{self.base_url}/klines", params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            candles = []
            for item in data:
                candles.append(Candle(
                    timestamp=int(item[0]) // 1000,
                    open=float(item[1]),
                    high=float(item[2]),
                    low=float(item[3]),
                    close=float(item[4]),
                    volume=float(item[5])
                ))
            return candles
        except Exception as e:
            print(f"Binance candle fetch failed for {symbol}: {e}")
            return []

    def get_market_data(self, symbol: str, chain_id: Optional[str] = None) -> Dict:
        try:
            import requests
            resp = requests.get(f"{self.base_url}/ticker/price", params={"symbol": symbol}, timeout=10)
            resp.raise_for_status()
            return {"priceUsd": float(resp.json().get("price", 0))}
        except:
            return {}

class StockAdapter(BaseAdapter):
    def __init__(self, config: Dict):
        self.config = config

    def get_sector_etf(self, symbol: str) -> str:
        """Maps a stock symbol to its sector ETF."""
        mapping = {
            "NVDA": "SMH", "AMD": "SMH", "INTC": "SMH", "MU": "SMH", "TSM": "SMH",
            "AAPL": "XLK", "MSFT": "XLK", "GOOGL": "XLK", "META": "XLK", "AMZN": "XLY",
            "TSLA": "XLY", "NFLX": "XLY", "JPM": "XLF", "BAC": "XLF", "WFC": "XLF",
            "XOM": "XLE", "CVX": "XLE", "UNH": "XLV", "LLY": "XLV", "PFE": "XLV",
            "BTC-USD": "BTC-USD", "GC=F": "GLD"
        }
        return mapping.get(symbol.upper(), "SPY")

    def fetch_candidates(self) -> List[Dict]:
        watchlist = self.config.get("stock_watchlist", ["AAPL", "TSLA", "NVDA", "BTC-USD", "GC=F"])
        candidates = []
        for symbol in watchlist:
            candidates.append({
                "chainId": "stock",
                "pairAddress": symbol,
                "baseToken": {"symbol": symbol, "address": symbol},
                "priceUsd": 0.0,
                "sector": self.get_sector_etf(symbol)
            })
        return candidates

    def fetch_candles(self, symbol: str, interval: str = "1d", limit: int = 100, chain_id: Optional[str] = None) -> List[Candle]:
        try:
            import yfinance as yf
            # Map intervals for yfinance
            yf_interval = interval
            if interval == "1m": period = "2d"
            elif interval == "1h": period = "10d"
            else: period = "2y" # 1d or higher
            
            ticker = yf.Ticker(symbol)
            df = ticker.history(period=period, interval=yf_interval)
            if df.empty:
                return []
            candles = []
            for idx, row in df.iterrows():
                candles.append(Candle(
                    timestamp=int(idx.timestamp()),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=float(row["Volume"])
                ))
            return candles[-limit:]
        except Exception as e:
            print(f"Stock candle fetch failed for {symbol}: {e}")
            return []

    def get_market_data(self, symbol: str, chain_id: Optional[str] = None) -> Dict:
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            return {"priceUsd": ticker.fast_info.get("last_price") or 0.0}
        except:
            return {}

class ParquetAdapter(BaseAdapter):
    """Loads historical data from local Parquet files for high-fidelity backtesting."""
    def __init__(self, data_dir: str = "data/parquet"):
        self.data_dir = data_dir

    def fetch_candidates(self) -> List[Dict]:
        import os
        candidates = []
        for root, _, files in os.walk(self.data_dir):
            for f in files:
                if f.endswith(".parquet"):
                    symbol = f.replace(".parquet", "")
                    candidates.append({
                        "chainId": "parquet",
                        "pairAddress": os.path.join(root, f),
                        "baseToken": {"symbol": symbol, "address": symbol},
                    })
        return candidates

    def fetch_candles(self, file_path: str, interval: str = "1m", limit: int = 100, chain_id: Optional[str] = None) -> List[Candle]:
        try:
            if file_path.endswith(".csv"):
                return self._fetch_csv_candles(file_path)

            try:
                df = pd.read_parquet(file_path)
            except Exception:
                # Fallback for environments with incompatible parquet stack.
                csv_path = file_path.replace("/parquet/", "/charts/").replace(".parquet", ".csv")
                return self._fetch_csv_candles(csv_path)
            # Standardize columns to lowercase
            df.columns = [c.lower() for c in df.columns]
            
            # Use columns directly or derived from index
            candles = []
            
            # Simple column mapping
            cols = df.columns
            has_ts = "timestamp" in cols or "time" in cols or "date" in cols or "datetime" in cols
            
            # If large file, we might want to take a window, but let's take everything for now
            # and let the caller handle windowing.
            for idx, row in df.iterrows():
                def _scalar(v):
                    if isinstance(v, np.ndarray):
                        if v.size == 0:
                            return None
                        return v.flatten()[0]
                    if isinstance(v, (list, tuple)):
                        if not v:
                            return None
                        return v[0]
                    return v

                def _to_float(v, default=0.0):
                    vv = _scalar(v)
                    try:
                        return float(vv)
                    except Exception:
                        return float(default)

                if has_ts:
                    raw_ts = _scalar(row.get("timestamp")) or _scalar(row.get("time")) or _scalar(row.get("date")) or _scalar(row.get("datetime"))
                    if isinstance(raw_ts, str):
                        ts = int(pd.to_datetime(raw_ts).timestamp())
                    elif hasattr(raw_ts, "timestamp"):
                        ts = int(raw_ts.timestamp())
                    else:
                        ts = int(raw_ts) if raw_ts is not None else 0
                elif hasattr(idx, "timestamp"):
                    ts = int(idx.timestamp())
                else:
                    ts = 0
                    
                candles.append(Candle(
                    timestamp=ts,
                    open=_to_float(row["open"]),
                    high=_to_float(row["high"]),
                    low=_to_float(row["low"]),
                    close=_to_float(row["close"]),
                    volume=_to_float(row.get("volume", 0))
                ))
            return [c for c in candles if c.open > 0 and c.high > 0 and c.low > 0 and c.close > 0]
        except Exception as e:
            print(f"Parquet/CSV fetch failed for {file_path}: {e}")
            return []

    def _fetch_csv_candles(self, csv_path: str) -> List[Candle]:
        candles: List[Candle] = []
        with open(csv_path, "r", newline="", encoding="utf-8") as f:
            first_line = f.readline().strip()
            if not first_line:
                return []
            f.seek(0)

            # Format A: tab-delimited rows without headers: datetime,open,high,low,close,volume
            if "\t" in first_line and ("open" not in first_line.lower()):
                for raw in f:
                    parts = raw.strip().split("\t")
                    if len(parts) < 6:
                        continue
                    dt_str, o, h, l, c, v = parts[:6]
                    try:
                        ts = int(datetime.fromisoformat(dt_str.replace(" ", "T")).timestamp())
                    except Exception:
                        ts = 0
                    try:
                        candles.append(
                            Candle(
                                timestamp=ts,
                                open=float(o),
                                high=float(h),
                                low=float(l),
                                close=float(c),
                                volume=float(v),
                            )
                        )
                    except Exception:
                        continue
            else:
                # Format B: standard CSV with headers
                reader = csv.DictReader(f)
                for row in reader:
                    lower = {k.lower(): v for k, v in row.items() if k is not None}
                    raw_ts = lower.get("timestamp") or lower.get("time") or lower.get("date") or lower.get("datetime")
                    ts = 0
                    if raw_ts:
                        try:
                            ts = int(float(raw_ts))
                        except Exception:
                            try:
                                ts = int(datetime.fromisoformat(raw_ts.replace("Z", "+00:00")).timestamp())
                            except Exception:
                                ts = 0

                    def _f(key: str, default: float = 0.0) -> float:
                        try:
                            return float(lower.get(key, default))
                        except Exception:
                            return float(default)

                    candles.append(
                        Candle(
                            timestamp=ts,
                            open=_f("open"),
                            high=_f("high"),
                            low=_f("low"),
                            close=_f("close"),
                            volume=_f("volume"),
                        )
                    )

        return [c for c in candles if c.open > 0 and c.high > 0 and c.low > 0 and c.close > 0]

    def get_market_data(self, file_path: str, chain_id: Optional[str] = None) -> Dict:
        return {"priceUsd": 0.0}
