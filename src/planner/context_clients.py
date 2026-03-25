import os
from typing import Dict, Optional

import requests
from dotenv import load_dotenv


load_dotenv()


class _BaseHttpClient:
    def __init__(self, base_url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 15):
        self.base_url = base_url.rstrip("/")
        self.headers = headers or {}
        self.timeout = timeout

    def _get(self, path: str, params: Optional[Dict] = None) -> Dict:
        response = requests.get(
            f"{self.base_url}{path}",
            headers=self.headers,
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def _post(self, path: str, payload: Optional[Dict] = None) -> Dict:
        response = requests.post(
            f"{self.base_url}{path}",
            headers=self.headers,
            json=payload or {},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()


class CoinGeckoClient(_BaseHttpClient):
    def __init__(self, api_key: Optional[str] = None):
        key = api_key or os.getenv("COINGECKO_API_KEY")
        headers = {"accept": "application/json"}
        if key:
            headers["x-cg-demo-api-key"] = key
        super().__init__("https://api.coingecko.com/api/v3", headers=headers)

    def ping(self) -> Dict:
        return self._get("/ping")

    def search(self, query: str) -> Dict:
        return self._get("/search", {"query": query})

    def trending(self) -> Dict:
        return self._get("/search/trending")

    def markets(self, vs_currency: str = "usd", ids: Optional[str] = None, category: Optional[str] = None, per_page: int = 50, page: int = 1) -> Dict:
        params = {
            "vs_currency": vs_currency,
            "per_page": per_page,
            "page": page,
            "sparkline": "false",
        }
        if ids:
            params["ids"] = ids
        if category:
            params["category"] = category
        return self._get("/coins/markets", params)

    def coin_details(self, coin_id: str) -> Dict:
        return self._get(
            f"/coins/{coin_id}",
            {
                "localization": "false",
                "tickers": "false",
                "market_data": "true",
                "community_data": "false",
                "developer_data": "false",
                "sparkline": "false",
            },
        )


class DefiLlamaClient(_BaseHttpClient):
    def __init__(self):
        super().__init__("https://api.llama.fi")

    def protocols(self) -> Dict:
        return self._get("/protocols")

    def chains(self) -> Dict:
        return self._get("/v2/chains")

    def protocol_tvl(self, protocol: str) -> Dict:
        return self._get(f"/tvl/{protocol}")


class DuneClient(_BaseHttpClient):
    def __init__(self, api_key: Optional[str] = None):
        key = api_key or os.getenv("DUNE_API_KEY")
        headers = {"accept": "application/json"}
        if key:
            headers["X-Dune-API-Key"] = key
        super().__init__("https://api.dune.com/api/v1", headers=headers, timeout=30)

    def read_query(self, query_id: int) -> Dict:
        return self._get(f"/query/{query_id}")

    def execute_query(self, query_id: int, query_parameters: Optional[Dict] = None, performance: str = "medium") -> Dict:
        payload = {
            "query_parameters": query_parameters or {},
            "performance": performance,
        }
        return self._post(f"/query/{query_id}/execute", payload)

    def latest_result(self, query_id: int, limit: Optional[int] = None) -> Dict:
        params = {"limit": limit} if limit else None
        return self._get(f"/query/{query_id}/results", params)

    def execute_sql(self, sql: str, performance: str = "medium") -> Dict:
        return self._post("/sql/execute", {"sql": sql, "performance": performance})

    def execution_status(self, execution_id: str) -> Dict:
        return self._get(f"/execution/{execution_id}/status")

    def execution_results(self, execution_id: str) -> Dict:
        return self._get(f"/execution/{execution_id}/results")
