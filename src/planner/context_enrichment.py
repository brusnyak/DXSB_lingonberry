from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from src.planner.context_clients import CoinGeckoClient, DuneClient
from src.planner.dune_signals import DuneSignalsService
from src.planner.config import load_config
from src.planner.models import utc_now_iso
from src.planner.storage import PlannerRepository


class ExternalContextService:
    def __init__(
        self,
        repository: Optional[PlannerRepository] = None,
        coingecko_client: Optional[CoinGeckoClient] = None,
        dune_client: Optional[DuneClient] = None,
        config: Optional[Dict] = None,
    ):
        self.repository = repository
        self.coingecko = coingecko_client or CoinGeckoClient()
        self.dune = dune_client or DuneClient()
        self.dune_signals = DuneSignalsService(self.dune)
        self.config = config or load_config()
        self.planner = self.config["planner"]

    @staticmethod
    def _find_exact_symbol(search_payload: Dict, asset: str) -> Optional[Dict]:
        coins = search_payload.get("coins") or []
        asset_upper = asset.upper()
        for coin in coins:
            if str(coin.get("symbol") or "").upper() == asset_upper:
                return coin
        if len(asset_upper) >= 3:
            for coin in coins:
                if str(coin.get("name") or "").upper() == asset_upper:
                    return coin
        return None

    @staticmethod
    def _rows_from_dune_result(payload: Dict) -> List[Dict]:
        result = payload.get("result") or {}
        rows = result.get("rows")
        if isinstance(rows, list):
            return rows
        return payload.get("rows") or []

    @staticmethod
    def _match_dune_row(rows: List[Dict], asset: str) -> Optional[Dict]:
        asset_upper = asset.upper()
        keys = ("symbol", "asset", "token", "ticker")
        for row in rows:
            for key in keys:
                value = row.get(key)
                if value and str(value).upper() == asset_upper:
                    return row
        return None

    @staticmethod
    def _dune_note(label: str, row: Dict) -> Optional[str]:
        if not row:
            return None
        if label == "unlocks":
            unlock_pct = row.get("unlock_pct") or row.get("percent_unlocked")
            unlock_date = row.get("unlock_date") or row.get("date")
            if unlock_pct or unlock_date:
                parts = ["Dune unlock"]
                if unlock_date:
                    parts.append(str(unlock_date))
                if unlock_pct is not None:
                    parts.append(f"{float(unlock_pct):.2f}%")
                return " ".join(parts)
        if label == "flows":
            netflow = row.get("netflow_usd") or row.get("net_flow_usd")
            if netflow is not None:
                return f"Dune Binance netflow ${float(netflow):,.0f}"
        if label == "smart_money":
            wallets = row.get("smart_wallets") or row.get("wallet_count")
            delta = row.get("position_delta_usd") or row.get("net_buy_usd")
            if wallets is not None and delta is not None:
                return f"Dune smart money {int(wallets)} wallets, ${float(delta):,.0f} net"
        return None

    @staticmethod
    def _future_iso(seconds: int) -> str:
        return (
            datetime.now(timezone.utc) + timedelta(seconds=seconds)
        ).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _market_cap_band(market_cap: Optional[float]) -> Optional[str]:
        if market_cap is None:
            return None
        if market_cap >= 10_000_000_000:
            return "mega-cap"
        if market_cap >= 1_000_000_000:
            return "large-cap"
        if market_cap >= 250_000_000:
            return "mid-cap"
        if market_cap >= 50_000_000:
            return "small-cap"
        return "micro-cap"

    def _get_cached_payload(self, provider: str, asset: str) -> Optional[Dict]:
        if not self.repository:
            return None
        cached = self.repository.get_cached_context(provider, asset, utc_now_iso())
        return cached["payload"] if cached else None

    def _save_cached_payload(self, provider: str, asset: str, payload: Dict, ttl_sec: int) -> None:
        if not self.repository:
            return
        fetched_ts = utc_now_iso()
        expires_ts = self._future_iso(ttl_sec)
        self.repository.upsert_cached_context(provider, asset, fetched_ts, expires_ts, payload)

    def _coingecko_context(self, asset: str) -> Dict:
        cached = self._get_cached_payload("coingecko", asset)
        if cached is not None:
            return cached
        context = {
            "coingecko": {},
            "notes": [],
            "risks": [],
        }
        search_payload = self.coingecko.search(asset)
        coin = self._find_exact_symbol(search_payload, asset)
        if coin:
            coin_id = coin.get("id")
            markets = self.coingecko.markets(ids=coin_id) if coin_id else []
            market = markets[0] if markets else {}
            details = self.coingecko.coin_details(coin_id) if coin_id else {}
            trending = self.coingecko.trending()
            trending_ids = {
                str(item.get("item", {}).get("id") or "")
                for item in (trending.get("coins") or [])
            }
            categories = details.get("categories") or []
            context["coingecko"] = {
                "id": coin_id,
                "name": coin.get("name"),
                "symbol": coin.get("symbol"),
                "market_cap_rank": market.get("market_cap_rank"),
                "market_cap": market.get("market_cap"),
                "market_cap_band": self._market_cap_band(market.get("market_cap")),
                "total_volume": market.get("total_volume"),
                "price_change_percentage_24h": market.get("price_change_percentage_24h"),
                "price_change_percentage_7d": market.get("price_change_percentage_7d_in_currency"),
                "trending": coin_id in trending_ids if coin_id else False,
                "categories": categories[:3],
                "homepage": (details.get("links") or {}).get("homepage", [None])[0],
                "genesis_date": details.get("genesis_date"),
            }
            if context["coingecko"]["trending"]:
                context["notes"].append("CoinGecko trending")
            rank = context["coingecko"].get("market_cap_rank")
            if rank:
                context["notes"].append(f"CoinGecko market cap rank #{int(rank)}")
            if context["coingecko"].get("market_cap_band"):
                context["notes"].append(f"CoinGecko {context['coingecko']['market_cap_band']}")
            if categories:
                context["notes"].append("CoinGecko categories: " + ", ".join(categories[:2]))
        self._save_cached_payload(
            "coingecko",
            asset,
            context,
            self.planner["research_coingecko_cache_ttl_sec"],
        )
        return context

    def get_asset_context(self, asset: str) -> Dict:
        context = {
            "coingecko": {},
            "dune": {},
            "notes": [],
            "risks": [],
        }

        try:
            cg_context = self._coingecko_context(asset)
            context["coingecko"] = cg_context.get("coingecko", {})
            context["notes"].extend(cg_context.get("notes", []))
            context["risks"].extend(cg_context.get("risks", []))
        except Exception:
            context["coingecko"] = {}

        return context

    def get_batch_dune_context(self, assets: List[str]) -> Dict[str, Dict]:
        assets = assets[: self.planner["research_dune_max_assets_per_scan"]]
        context_map = {asset: {"notes": [], "risks": [], "dune": {}} for asset in assets}
        uncached = []
        for asset in assets:
            cached = self._get_cached_payload("dune", asset)
            if cached is None:
                uncached.append(asset)
            else:
                context_map[asset] = cached
        if not uncached:
            return context_map
        try:
            flow_rows = self.dune_signals.binance_flows(uncached)
            for asset, row in flow_rows.items():
                item = context_map.setdefault(asset, {"notes": [], "risks": [], "dune": {}})
                item["dune"]["flows"] = row
                note = self._dune_note("flows", row)
                if note:
                    item["notes"].append(note)
        except Exception:
            pass
        try:
            positioning_rows = self.dune_signals.dex_trader_positioning(uncached)
            for asset, row in positioning_rows.items():
                item = context_map.setdefault(asset, {"notes": [], "risks": [], "dune": {}})
                item["dune"]["smart_money"] = row
                wallets = row.get("smart_wallets")
                delta = row.get("position_delta_usd")
                if wallets is not None and delta is not None:
                    item["notes"].append(f"Dune dex positioning {int(wallets)} wallets, ${float(delta):,.0f} net")
        except Exception:
            pass
        for asset in uncached:
            self._save_cached_payload(
                "dune",
                asset,
                context_map.get(asset, {"notes": [], "risks": [], "dune": {}}),
                self.planner["research_dune_cache_ttl_sec"],
            )
        return context_map
