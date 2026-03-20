import csv
import json
import os
from datetime import datetime, timezone
from typing import Dict, Iterable, List

from src.planner.models import utc_now_iso
from src.planner.storage import PlannerRepository


SUPPORTED_EVENT_TYPES = {
    "alpha_spotlight",
    "hodler_airdrop",
    "spot_listing",
    "academy_project_post",
}


class EventIngestService:
    def __init__(self, repository: PlannerRepository):
        self.repository = repository

    def _normalize_row(self, row: Dict) -> Dict:
        event_type = str(row["event_type"]).strip().lower()
        if event_type not in SUPPORTED_EVENT_TYPES:
            raise ValueError(f"Unsupported event_type: {event_type}")
        return {
            "symbol": str(row["symbol"]).upper().replace("/", "").replace("-", ""),
            "event_type": event_type,
            "source": str(row.get("source") or "manual"),
            "event_ts": row.get("event_ts") or utc_now_iso(),
            "headline": str(row["headline"]).strip(),
            "url": row.get("url"),
            "strength": float(row.get("strength", 1.0)),
        }

    def _load_rows(self, path: str) -> List[Dict]:
        if path.endswith(".csv"):
            with open(path, "r", newline="") as handle:
                return list(csv.DictReader(handle))
        with open(path, "r") as handle:
            content = handle.read().strip()
        if not content:
            return []
        if content.startswith("["):
            return json.loads(content)
        return [json.loads(line) for line in content.splitlines() if line.strip()]

    def ingest_file(self, path: str) -> int:
        rows = [self._normalize_row(row) for row in self._load_rows(path)]
        assets = [
            {
                "symbol": f"{row['symbol']}USDT" if not row["symbol"].endswith("USDT") else row["symbol"],
                "base_asset": row["symbol"].replace("USDT", ""),
                "quote_asset": "USDT",
                "tags": json.dumps([row["event_type"]]),
                "is_major": 0,
                "is_seed": 1 if row["event_type"] == "spot_listing" else 0,
                "status": "ACTIVE",
                "updated_ts": utc_now_iso(),
            }
            for row in rows
        ]
        self.repository.upsert_assets(assets)
        return self.repository.insert_events(rows)

