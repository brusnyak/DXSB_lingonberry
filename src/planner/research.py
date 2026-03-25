import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from src.planner.binance_gateway import BinanceGateway, parse_binance_rows
from src.planner.config import load_config
from src.planner.context_enrichment import ExternalContextService
from src.planner.indicators import ema, pct_change
from src.planner.models import utc_now_iso
from src.planner.storage import PlannerRepository


class BinanceResearchService:
    def __init__(
        self,
        repository: PlannerRepository,
        gateway: Optional[BinanceGateway] = None,
        config: Optional[Dict] = None,
        context_service: Optional[ExternalContextService] = None,
    ):
        self.repository = repository
        self.gateway = gateway
        self.config = config or load_config()
        self.planner = self.config["planner"]
        self.context_service = context_service or ExternalContextService(repository=repository, config=self.config)

    def _is_excluded_asset(self, asset: str) -> bool:
        if asset in self.planner["spot_excluded_assets"]:
            return True
        if asset in self.planner["stable_assets"]:
            return True
        for suffix in ("UP", "DOWN", "BULL", "BEAR"):
            if asset.endswith(suffix):
                return True
        return False

    @staticmethod
    def _ema_close(candles: List[Dict], period: int = 20) -> float:
        values = ema([c["close"] for c in candles], period)
        return values[-1] if values else 0.0

    def _exchange_symbols(self) -> Dict[str, Dict]:
        info = self.gateway.get_exchange_info() if self.gateway else {"symbols": []}
        return {row["symbol"]: row for row in info.get("symbols", [])}

    @staticmethod
    def _normalize_flexible_product(snapshot_ts: str, row: Dict) -> Dict:
        return {
            "snapshot_ts": snapshot_ts,
            "asset": str(row.get("asset") or "").upper(),
            "product_type": "FLEXIBLE",
            "apr": float(row.get("latestAnnualPercentageRate") or row.get("apr") or 0.0),
            "duration_days": None,
            "min_purchase_amount": float(row.get("minPurchaseAmount") or 0.0),
            "can_purchase": 1 if row.get("canPurchase", False) else 0,
            "can_redeem": 1 if row.get("canRedeem", True) else 0,
            "is_sold_out": 1 if row.get("isSoldOut", False) else 0,
            "is_hot": 1 if row.get("hot", False) else 0,
            "status": row.get("status"),
            "extra_reward_asset": None,
            "extra_reward_apr": float(row.get("airDropPercentageRate") or 0.0),
            "raw_json": json.dumps(row),
        }

    @staticmethod
    def _normalize_locked_product(snapshot_ts: str, row: Dict) -> Dict:
        detail = row.get("detail") or {}
        quota = row.get("quota") or {}
        return {
            "snapshot_ts": snapshot_ts,
            "asset": str(detail.get("asset") or row.get("asset") or "").upper(),
            "product_type": "LOCKED",
            "apr": float(detail.get("apr") or row.get("apr") or 0.0),
            "duration_days": int(detail.get("duration") or 0) or None,
            "min_purchase_amount": float(quota.get("minimum") or 0.0),
            "can_purchase": 1 if detail.get("status") in {"CREATED", "PURCHASING"} else 0,
            "can_redeem": 0,
            "is_sold_out": 1 if detail.get("isSoldOut", False) else 0,
            "is_hot": 0,
            "status": detail.get("status"),
            "extra_reward_asset": detail.get("extraRewardAsset"),
            "extra_reward_apr": float(detail.get("extraRewardAPR") or 0.0),
            "raw_json": json.dumps(row),
        }

    def sync_earn_products(self) -> Dict:
        if not self.gateway:
            raise RuntimeError("Binance gateway is required for live research sync")
        snapshot_ts = utc_now_iso()
        rows = []
        for row in parse_binance_rows(self.gateway.get_simple_earn_flexible_product_list(size=100)):
            normalized = self._normalize_flexible_product(snapshot_ts, row)
            if normalized["asset"]:
                rows.append(normalized)
        for row in parse_binance_rows(self.gateway.get_simple_earn_locked_product_list(size=100)):
            normalized = self._normalize_locked_product(snapshot_ts, row)
            if normalized["asset"]:
                rows.append(normalized)
        self.repository.replace_earn_products(snapshot_ts, rows)
        return {"snapshot_ts": snapshot_ts, "offers": len(rows)}

    def _latest_offer_by_asset(self) -> Dict[str, Dict]:
        rows = self.repository.latest_earn_products()
        best = {}
        for row in rows:
            asset = row["asset"]
            current = best.get(asset)
            rank = (
                row["can_purchase"],
                -row["is_sold_out"],
                row["is_hot"],
                row["apr"],
                1 if row["product_type"] == "FLEXIBLE" else 0,
            )
            if current is None:
                best[asset] = row
                continue
            current_rank = (
                current["can_purchase"],
                -current["is_sold_out"],
                current["is_hot"],
                current["apr"],
                1 if current["product_type"] == "FLEXIBLE" else 0,
            )
            if rank > current_rank:
                best[asset] = row
        return best

    def _ranked_offers(self) -> List[Dict]:
        rows = list(self._latest_offer_by_asset().values())
        rows.sort(
            key=lambda row: (
                row["can_purchase"],
                -row["is_sold_out"],
                row["is_hot"],
                1 if row["product_type"] == "FLEXIBLE" else 0,
                row["apr"],
            ),
            reverse=True,
        )
        return rows[: self.planner["research_max_assets_per_scan"]]

    def _event_map(self) -> Dict[str, List[Dict]]:
        items: Dict[str, List[Dict]] = {}
        for event in self.repository.recent_events(14):
            symbol = event["symbol"].replace("USDT", "")
            items.setdefault(symbol, []).append(event)
        return items

    def _btc_regime_ok(self) -> bool:
        btc_daily = self.gateway.get_klines("BTCUSDT", "1d", limit=3)
        if len(btc_daily) < 2:
            return True
        ret = pct_change(btc_daily[-1]["close"], btc_daily[-2]["close"])
        return ret > self.planner["btc_risk_off_daily_return_pct"]

    def _evaluate_asset(self, asset: str, offer: Dict, event_notes: List[Dict], exchange_symbols: Dict[str, Dict]) -> Optional[Dict]:
        if self._is_excluded_asset(asset):
            return None
        pair = f"{asset}USDT"
        symbol_info = exchange_symbols.get(pair)
        if not symbol_info:
            return None
        if symbol_info.get("status") != "TRADING":
            return None
        if not symbol_info.get("isSpotTradingAllowed", True):
            return None
        ticker = self.gateway.get_ticker_24h(pair)
        current_price = float(ticker.get("lastPrice", 0) or 0.0)
        quote_volume = float(ticker.get("quoteVolume", 0) or 0.0)
        ret_24h = float(ticker.get("priceChangePercent", 0) or 0.0)
        if current_price <= 0:
            return None

        daily = self.gateway.get_klines(pair, "1d", limit=40)
        four_hour = self.gateway.get_klines(pair, "4h", limit=120)
        if len(daily) < 20 or len(four_hour) < 20:
            return None

        ema20_1d = self._ema_close(daily, 20)
        ema20_4h = self._ema_close(four_hour, 20)
        ret_7d = pct_change(daily[-1]["close"], daily[-8]["close"]) if len(daily) >= 8 else 0.0
        extension_above_ema20_pct = pct_change(current_price, ema20_1d) if ema20_1d else 0.0
        recent_high = max(c["high"] for c in daily[-30:])
        drawdown_from_high = ((recent_high / current_price) - 1.0) * 100.0 if current_price else 0.0

        setup_type = None
        reasons = []
        if offer["product_type"] == "FLEXIBLE" and offer["apr"] >= self.planner["research_min_apr"]:
            reasons.append(f"Simple Earn APR {offer['apr'] * 100:.2f}%")
        elif offer["product_type"] == "LOCKED":
            duration = offer.get("duration_days") or 0
            if (
                offer["apr"] >= self.planner["research_min_locked_apr"]
                and duration <= self.planner["research_locked_max_duration_days"]
            ):
                reasons.append(f"Locked Earn APR {offer['apr'] * 100:.2f}% for {duration}d")
        if offer["is_hot"]:
            reasons.append("featured on Binance Earn")
        if current_price > ema20_4h and quote_volume >= self.planner["min_quote_volume_usd_24h"] and 3.0 <= ret_24h <= 25.0:
            setup_type = "continuation"
            reasons.append("price is above 4h EMA20 with healthy continuation")
        elif ret_7d > 0 and 5.0 <= drawdown_from_high <= 18.0 and current_price > ema20_1d:
            setup_type = "pullback"
            reasons.append("price is pulling back constructively above 1d EMA20")
        elif reasons and (
            offer["is_hot"]
            or ret_7d > 0
            or (quote_volume >= 1_000_000 and -3.0 <= ret_24h <= 10.0)
        ):
            setup_type = "watch"
            if ret_7d > 0:
                reasons.append("7d trend is still positive")

        if setup_type is None:
            return None

        risk_notes = []
        for event in event_notes:
            if event["event_type"] in {"unlock_event", "ai_insight"}:
                risk_notes.append(event["headline"])
        external_context = self.context_service.get_asset_context(asset)
        reasons.extend(external_context.get("notes", []))
        risk_notes.extend(external_context.get("risks", []))
        return {
            "asset": asset,
            "pair": pair,
            "setup_type": setup_type,
            "apr": offer["apr"],
            "product_type": offer["product_type"],
            "duration_days": offer.get("duration_days"),
            "current_price": current_price,
            "quote_volume_usd_24h": quote_volume,
            "ret_24h_pct": ret_24h,
            "ret_7d_pct": ret_7d,
            "extension_above_ema20_pct": extension_above_ema20_pct,
            "drawdown_from_high_pct": drawdown_from_high,
            "reasons": reasons,
            "risk_notes": risk_notes,
            "external_context": external_context,
        }

    def scan_earn_opportunities(self) -> List[Dict]:
        if not self.gateway:
            raise RuntimeError("Binance gateway is required for live research scans")
        snapshot = self.repository.latest_snapshot()
        if not snapshot:
            raise RuntimeError("No portfolio snapshot found. Run `portfolio sync` first.")

        total_equity = snapshot["total_equity"]
        free_cash = snapshot["free_cash"]
        reserve_buffer = total_equity * self.planner["min_free_cash_buffer_pct_total_equity"]
        spot_target_equity = total_equity * self.planner["spot_target_pct"]
        max_position_size = min(
            total_equity * self.planner["spot_max_position_pct_total_equity"],
            spot_target_equity * self.planner["spot_max_position_pct_spot_sleeve"],
        )
        btc_regime_ok = self._btc_regime_ok()
        exchange_symbols = self._exchange_symbols()
        event_map = self._event_map()
        batch_dune_context = self.context_service.get_batch_dune_context([offer["asset"] for offer in self._ranked_offers()])
        rows = []

        for offer in self._ranked_offers():
            asset = offer["asset"]
            evaluated = self._evaluate_asset(asset, offer, event_map.get(asset, []), exchange_symbols)
            if evaluated is None:
                continue
            dune_context = batch_dune_context.get(asset) or {}
            evaluated["external_context"]["dune"].update(dune_context.get("dune") or {})
            evaluated["external_context"]["notes"].extend(dune_context.get("notes") or [])
            evaluated["external_context"]["risks"].extend(dune_context.get("risks") or [])
            reason_parts = list(dict.fromkeys(list(evaluated["reasons"]) + list(dune_context.get("notes") or [])))

            status = "watchlist"
            action = "WATCH_SPOT"
            if evaluated["risk_notes"]:
                reason_parts.append("risks: " + " | ".join(evaluated["risk_notes"][:2]))
            external_risks = evaluated["external_context"].get("risks") or []
            if external_risks:
                reason_parts.append("external risks: " + " | ".join(external_risks[:2]))

            if evaluated["setup_type"] in {"continuation", "pullback"}:
                action = "BUY_SPOT"
                if not btc_regime_ok:
                    status = "blocked"
                    reason_parts.append("blocked because BTC daily regime is risk-off")
                elif evaluated["extension_above_ema20_pct"] > self.planner["asset_max_extension_above_ema20_pct"]:
                    status = "blocked"
                    reason_parts.append("blocked because the asset is too extended above 1d EMA20")
                elif free_cash - reserve_buffer < max_position_size:
                    status = "blocked"
                    reason_parts.append("blocked because free cash would breach the reserve buffer")
                else:
                    status = "actionable"

            metadata = {
                "pair": evaluated["pair"],
                "setup_type": evaluated["setup_type"],
                "apr": evaluated["apr"],
                "product_type": evaluated["product_type"],
                "duration_days": evaluated["duration_days"],
                "entry_price": evaluated["current_price"],
                "ret_24h_pct": evaluated["ret_24h_pct"],
                "ret_7d_pct": evaluated["ret_7d_pct"],
                "quote_volume_usd_24h": evaluated["quote_volume_usd_24h"],
                "extension_above_ema20_pct": evaluated["extension_above_ema20_pct"],
                "drawdown_from_high_pct": evaluated["drawdown_from_high_pct"],
                "risk_notes": evaluated["risk_notes"],
                "external_context": evaluated["external_context"],
            }
            rows.append(
                {
                    "ts": utc_now_iso(),
                    "sleeve": "research",
                    "symbol_or_asset": asset,
                    "action": action,
                    "priority": 90 if status == "actionable" else 60 if status == "blocked" else 40,
                    "status": status,
                    "reason": "; ".join(reason_parts),
                    "capital_required_usd": round(max_position_size if action == "BUY_SPOT" else 0.0, 2),
                    "expires_ts": (datetime.now(timezone.utc) + timedelta(days=2)).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
                    "metadata_json": json.dumps(metadata),
                }
            )

        self.repository.add_recommendations(rows)
        self.repository.record_research_candidates(rows)
        outcome_rows = []
        for row in rows:
            try:
                metadata = json.loads(row.get("metadata_json") or "{}")
            except json.JSONDecodeError:
                metadata = {}
            outcome_rows.append(
                {
                    "ts": row["ts"],
                    "symbol_or_asset": row["symbol_or_asset"],
                    "action": row["action"],
                    "status": row["status"],
                    "entry_price": metadata.get("entry_price"),
                    "ret_24h_pct": metadata.get("ret_24h_pct"),
                    "ret_7d_pct": metadata.get("ret_7d_pct"),
                    "quote_volume_usd_24h": metadata.get("quote_volume_usd_24h"),
                    "metadata_json": row.get("metadata_json") or "{}",
                }
            )
        self.repository.record_research_outcome_snapshots(outcome_rows)
        return rows
