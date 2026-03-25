import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional

from src.planner.config import load_config
from src.planner.indicators import max_drawdown
from src.planner.storage import PlannerRepository


class ReportingService:
    def __init__(self, repository: PlannerRepository, config: Optional[Dict] = None):
        self.repository = repository
        self.config = config or load_config()

    def _rolling_return(self, snapshots: List[Dict], days: int) -> float:
        if len(snapshots) < 2:
            return 0.0
        latest = snapshots[0]
        latest_ts = datetime.fromisoformat(latest["snapshot_ts"].replace("Z", "+00:00"))
        for row in snapshots[1:]:
            row_ts = datetime.fromisoformat(row["snapshot_ts"].replace("Z", "+00:00"))
            if (latest_ts - row_ts).total_seconds() >= days * 86400:
                if row["total_equity"] > 0:
                    return ((latest["total_equity"] / row["total_equity"]) - 1.0) * 100.0
                break
        return 0.0

    def analytics_summary(self) -> Dict:
        closed = self.repository.closed_spot_positions()
        snapshots = []
        latest = self.repository.latest_snapshot()
        if latest:
            conn = self.repository._connect()
            snapshots = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM portfolio_snapshots ORDER BY snapshot_ts DESC LIMIT 60"
                ).fetchall()
            ]
            conn.close()
        profits = [row["realized_pnl_usd"] for row in closed if row["realized_pnl_usd"] > 0]
        losses = [abs(row["realized_pnl_usd"]) for row in closed if row["realized_pnl_usd"] < 0]
        win_count = len(profits)
        total_count = len(closed)
        expectancy = (sum(profits) - sum(losses)) / total_count if total_count else 0.0
        profit_factor = (sum(profits) / sum(losses)) if losses else None
        equity_curve = [row["total_equity"] for row in reversed(snapshots)] if snapshots else []
        earn_positions = self.repository.latest_earn_positions()
        locked_days = 0.0
        unlocked_days = 0.0
        now = datetime.now(timezone.utc)
        for row in earn_positions:
            locked_until = row.get("locked_until")
            if locked_until:
                delta = datetime.fromisoformat(locked_until.replace("Z", "+00:00")) - now
                locked_days += max(delta.total_seconds() / 86400.0, 0.0)
            else:
                unlocked_days += 1.0
        apr_weighted_value = sum(row["apr"] * row["value_usd"] for row in earn_positions)
        earn_value = sum(row["value_usd"] for row in earn_positions)
        effective_apr = (apr_weighted_value / earn_value) if earn_value else 0.0
        return {
            "win_rate_pct": (win_count / total_count) * 100.0 if total_count else 0.0,
            "avg_win_usd": (sum(profits) / len(profits)) if profits else 0.0,
            "avg_loss_usd": (sum(losses) / len(losses)) if losses else 0.0,
            "expectancy_usd": expectancy,
            "profit_factor": profit_factor,
            "max_drawdown_pct": max_drawdown(equity_curve),
            "rolling_7d_pct": self._rolling_return(snapshots, 7),
            "rolling_30d_pct": self._rolling_return(snapshots, 30),
            "realized_yield_usd": sum(row["accrued_yield_usd"] for row in earn_positions),
            "effective_apr": effective_apr,
            "locked_days": locked_days,
            "unlocked_days": unlocked_days,
        }

    def daily_report_text(self) -> str:
        snapshot = self.repository.latest_snapshot()
        if not snapshot:
            return "No portfolio snapshot found. Run `portfolio sync` first."
        earn_positions = self.repository.latest_earn_positions()
        earn_products = self.repository.latest_earn_products()
        cash_balances = self.repository.latest_cash_balances()
        spot_positions = self.repository.open_spot_positions()
        recs = self.repository.recent_recommendations(limit=60)
        analytics = self.analytics_summary()

        recs = sorted(recs, key=lambda row: (row["priority"], row["ts"]), reverse=True)
        deduped = []
        seen = set()
        for row in recs:
            key = (row["sleeve"], row["symbol_or_asset"], row["action"], row["status"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(row)
        recs = deduped
        blocked = [row for row in recs if row["status"] == "blocked"]
        actionable = [row for row in recs if row["status"] == "actionable"]
        research_rows = self._collapse_research_rows([row for row in recs if row["sleeve"] == "research"])
        research_actionable = [row for row in research_rows if row["status"] == "actionable"]
        research_blocked = [row for row in research_rows if row["status"] == "blocked"]
        research_watchlist = [row for row in research_rows if row["status"] == "watchlist"]
        concentration = defaultdict(float)
        for row in earn_positions:
            concentration[f"earn:{row['asset']}"] += row["value_usd"]
        for row in cash_balances:
            concentration[f"cash:{row['asset']}"] += row["value_usd"]
        for row in spot_positions:
            concentration[f"spot:{row['symbol']}"] += row["cost_usd"]
        concentration_lines = sorted(concentration.items(), key=lambda item: item[1], reverse=True)[:5]
        unlocks = [
            f"{row['asset']} {row['status']} until {row['locked_until']}"
            for row in earn_positions
            if row.get("locked_until")
        ]

        lines = [
            "💼 Lingonberry Investing",
            "Binance Two-Sleeve Daily Report",
            "================================",
            f"🕒 Snapshot: {snapshot['snapshot_ts']}",
            f"💰 Total equity: ${snapshot['total_equity']:,.2f} | EUR {snapshot.get('total_equity_eur', 0.0):,.2f}",
            f"🏦 Earn sleeve: ${snapshot['earn_equity']:,.2f} | APR-weighted est: {analytics['effective_apr'] * 100:.2f}% | accrued yield: ${snapshot['accrued_yield_usd']:,.2f}",
            f"🎯 Spot sleeve: ${snapshot['spot_equity']:,.2f} | free cash: ${snapshot['free_cash']:,.2f} | EUR {snapshot.get('free_cash_eur', 0.0):,.2f} | buying power: ${snapshot['buying_power']:,.2f}",
            f"🔒 Locked cash: ${snapshot['locked_cash']:,.2f} | active spot positions: {len(spot_positions)}",
            f"📊 Realized PnL: ${snapshot['realized_pnl_usd']:,.2f} | Unrealized PnL: ${snapshot['unrealized_pnl_usd']:,.2f}",
            f"📈 Rolling returns: 7d {analytics['rolling_7d_pct']:.2f}% | 30d {analytics['rolling_30d_pct']:.2f}%",
            "",
            "💶 Cash balances:",
        ]
        if cash_balances:
            lines.extend([f"- {row['asset']}: ${row['value_usd']:,.2f} | EUR {row['value_eur']:,.2f}" for row in cash_balances])
        else:
            lines.append("- No free cash balances recorded.")
        lines += [
            "",
            "🧱 Top concentration:",
        ]
        if concentration_lines:
            lines.extend([f"- {name}: ${value:,.2f}" for name, value in concentration_lines])
        else:
            lines.append("- No active exposure recorded.")
        lines += [
            "",
            "🗓️ Next unlock dates:",
        ]
        if unlocks:
            lines.extend([f"- {item}" for item in unlocks])
        else:
            lines.append("- No locked Earn positions.")
        lines += [
            "",
            "🚀 Actionable ideas:",
        ]
        if actionable:
            lines.extend(
                [
                    f"- {row['sleeve']} {row['symbol_or_asset']} {row['action']} ${row['capital_required_usd']:,.2f}: {self._compact_reason(row['reason'], max_parts=3)}"
                    for row in actionable[:5]
                ]
            )
        else:
            lines.append("- No actionable recommendations.")
        lines += [
            "",
            "⛔ Blocked ideas:",
        ]
        if blocked:
            lines.extend(
                [
                    f"- {row['sleeve']} {row['symbol_or_asset']} ${row['capital_required_usd']:,.2f}: {self._compact_reason(row['reason'], max_parts=3)}"
                    for row in blocked[:5]
                ]
            )
        else:
            lines.append("- No blocked recommendations.")
        lines += [
            "",
            "🔎 Binance research monitor:",
        ]
        if research_actionable:
            lines.extend(
                [
                    f"- 🚀 {row['symbol_or_asset']} ${row['capital_required_usd']:,.2f}: {self._compact_reason(self._research_line(row), max_parts=4)}"
                    for row in research_actionable[:5]
                ]
            )
        else:
            lines.append("- No actionable research setups.")
        if research_blocked:
            lines.extend(
                [
                    f"- ⛔ {row['symbol_or_asset']} ${row['capital_required_usd']:,.2f}: {self._compact_reason(self._research_line(row), max_parts=4)}"
                    for row in research_blocked[:3]
                ]
            )
        if research_watchlist:
            lines.extend(
                [
                    f"- 👀 watch {row['symbol_or_asset']}: {self._compact_reason(self._research_line(row), max_parts=4)}"
                    for row in research_watchlist[:5]
                ]
            )
        else:
            lines.append("- No research watchlist items.")
        lines += [
            "",
            "💰 Simple Earn board:",
        ]
        if earn_products:
            for row in earn_products[:5]:
                extra = f" + {row['extra_reward_apr'] * 100:.2f}% extra" if row.get("extra_reward_apr") else ""
                duration = f" {row['duration_days']}d" if row.get("duration_days") else ""
                lines.append(
                    f"- {row['asset']} {row['product_type']}{duration}: {row['apr'] * 100:.2f}% APR{extra}"
                )
        else:
            lines.append("- No Simple Earn offers synced yet.")
        lines += [
            "",
            "📈 Spot analytics:",
            f"- Win rate: {analytics['win_rate_pct']:.2f}%",
            f"- Avg win/loss: ${analytics['avg_win_usd']:,.2f} / ${analytics['avg_loss_usd']:,.2f}",
            f"- Expectancy: ${analytics['expectancy_usd']:,.2f}",
            f"- Profit factor: {analytics['profit_factor']:.2f}" if analytics["profit_factor"] is not None else "- Profit factor: n/a",
            f"- Max drawdown: {analytics['max_drawdown_pct']:.2f}%",
            "",
            "🏦 Earn analytics:",
            f"- Realized yield proxy: ${analytics['realized_yield_usd']:,.2f}",
            f"- Effective APR: {analytics['effective_apr'] * 100:.2f}%",
            f"- Locked vs unlocked days: {analytics['locked_days']:.1f} / {analytics['unlocked_days']:.1f}",
        ]
        return "\n".join(lines)

    def research_alert_text(self) -> str:
        recs = self.repository.recent_recommendations(limit=80)
        recs = sorted(recs, key=lambda row: (row["ts"], row["priority"]), reverse=True)
        seen = set()
        research_rows = []
        for row in recs:
            if row["sleeve"] != "research":
                continue
            key = (row["symbol_or_asset"], row["action"])
            if key in seen:
                continue
            seen.add(key)
            research_rows.append(row)
        research_rows = self._collapse_research_rows(research_rows)
        if not research_rows:
            return "Binance Research Alert\n======================\nNo research candidates recorded yet."

        stats = self.repository.research_candidate_stats()
        prior_state = self.repository.research_alert_state_map()
        delta_rows = []
        state_updates = []
        for row in research_rows:
            label, fingerprint = self._research_alert_label(row, prior_state)
            if label is None:
                continue
            enriched = dict(row)
            enriched["_alert_label"] = label
            delta_rows.append(enriched)
            state_updates.append(
                {
                    "symbol_or_asset": row["symbol_or_asset"],
                    "action": row["action"],
                    "last_sent_ts": row["ts"],
                    "last_status": row["status"],
                    "last_priority": row["priority"],
                    "fingerprint": fingerprint,
                }
            )
        if not delta_rows:
            return "🔎 Binance Research Alert\n======================\n😴 No material research changes since last alert."

        actionable = [row for row in delta_rows if row["status"] == "actionable"][:3]
        blocked = [row for row in delta_rows if row["status"] == "blocked"][:4]
        watchlist = [row for row in delta_rows if row["status"] == "watchlist"][:4]

        lines = [
            "💼 Lingonberry Investing",
            "Binance Research Alert",
            "======================",
            f"🧠 Candidates changed: {len(delta_rows)}",
        ]
        if actionable:
            lines.append("🚀 Actionable:")
            lines.extend([self._research_alert_line(row, stats) for row in actionable])
        else:
            lines.append("🚀 Actionable:")
            lines.append("- No actionable research setups.")

        if blocked:
            lines.append("")
            lines.append("⛔ Blocked:")
            lines.extend([self._research_alert_line(row, stats) for row in blocked])

        if watchlist:
            lines.append("")
            lines.append("👀 Watchlist:")
            lines.extend([self._research_alert_line(row, stats) for row in watchlist])

        self.repository.upsert_research_alert_state(state_updates)
        return "\n".join(lines)

    @classmethod
    def _collapse_research_rows(cls, rows: List[Dict]) -> List[Dict]:
        best_by_asset: Dict[str, Dict] = {}
        for row in rows:
            symbol = row["symbol_or_asset"]
            current = best_by_asset.get(symbol)
            if current is None:
                best_by_asset[symbol] = row
                continue
            row_score = (cls._display_rank(row["status"]), row["priority"], row["ts"])
            current_score = (cls._display_rank(current["status"]), current["priority"], current["ts"])
            if row_score > current_score:
                best_by_asset[symbol] = row
        return sorted(
            best_by_asset.values(),
            key=lambda row: (cls._display_rank(row["status"]), row["priority"], row["ts"]),
            reverse=True,
        )

    @staticmethod
    def _research_alert_key(row: Dict) -> str:
        return f"{row['symbol_or_asset']}::{row['action']}"

    @staticmethod
    def _status_rank(status: str) -> int:
        return {
            "blocked": 0,
            "watchlist": 1,
            "actionable": 2,
        }.get(status, -1)

    @staticmethod
    def _display_rank(status: str) -> int:
        return {
            "watchlist": 0,
            "blocked": 1,
            "actionable": 2,
        }.get(status, -1)

    @classmethod
    def _research_fingerprint(cls, row: Dict) -> str:
        metadata = {}
        try:
            metadata = json.loads(row.get("metadata_json") or "{}")
        except json.JSONDecodeError:
            metadata = {}
        return json.dumps(
            {
                "status": row["status"],
                "priority": row["priority"],
                "capital_required_usd": round(float(row.get("capital_required_usd") or 0.0), 2),
                "reason": row["reason"],
                "setup_type": metadata.get("setup_type"),
                "entry_price": round(float(metadata.get("entry_price") or 0.0), 6),
                "ret_24h_pct": round(float(metadata.get("ret_24h_pct") or 0.0), 2),
                "ret_7d_pct": round(float(metadata.get("ret_7d_pct") or 0.0), 2),
            },
            sort_keys=True,
        )

    @classmethod
    def _research_alert_label(cls, row: Dict, prior_state: Dict[str, Dict]) -> tuple[Optional[str], str]:
        fingerprint = cls._research_fingerprint(row)
        previous = prior_state.get(cls._research_alert_key(row))
        if not previous:
            return "fresh", fingerprint
        if row["status"] != previous["last_status"]:
            current_rank = cls._status_rank(row["status"])
            previous_rank = cls._status_rank(previous["last_status"])
            if current_rank > previous_rank:
                return "improving", fingerprint
            if current_rank < previous_rank:
                return "deteriorating", fingerprint
        if fingerprint != previous["fingerprint"]:
            return "recurring", fingerprint
        return None, fingerprint

    @staticmethod
    def _research_line(row: Dict) -> str:
        reason = row["reason"]
        if "CoinGecko" in reason:
            return reason
        metadata = {}
        try:
            metadata = json.loads(row.get("metadata_json") or "{}")
        except json.JSONDecodeError:
            metadata = {}
        context = metadata.get("external_context") or {}
        coingecko = context.get("coingecko") or {}
        extras = []
        if coingecko.get("market_cap_rank"):
            extras.append(f"CG rank #{int(coingecko['market_cap_rank'])}")
        if coingecko.get("trending"):
            extras.append("CG trending")
        if coingecko.get("market_cap_band"):
            extras.append(coingecko["market_cap_band"])
        categories = coingecko.get("categories") or []
        if categories:
            extras.append(categories[0])
        if extras:
            return f"{reason} | {'; '.join(extras)}"
        return reason

    @staticmethod
    def _compact_reason(reason: str, max_parts: int = 3) -> str:
        parts = [item.strip() for item in reason.split(";") if item.strip()]
        if not parts:
            return reason
        compact = parts[:max_parts]
        if len(parts) > max_parts:
            compact.append("more context on demand")
        return "; ".join(compact)

    @staticmethod
    def _label_badge(label: Optional[str]) -> Optional[str]:
        if not label:
            return None
        return {
            "fresh": "🆕 fresh",
            "recurring": "🔁 recurring",
            "improving": "⬆️ improving",
            "deteriorating": "⬇️ deteriorating",
        }.get(label, label)

    @classmethod
    def _research_alert_line(cls, row: Dict, stats: Dict[str, Dict]) -> str:
        symbol = row["symbol_or_asset"]
        reason = cls._compact_reason(cls._research_line(row), max_parts=4)
        history = stats.get(symbol) or {}
        suffix = []
        label = cls._label_badge(row.get("_alert_label"))
        if label:
            suffix.append(label)
        scans = history.get("scans")
        if scans:
            suffix.append(f"{int(scans)} scans")
        actionable_count = history.get("actionable_count")
        if actionable_count:
            suffix.append(f"{int(actionable_count)} actionable")
        blocked_count = history.get("blocked_count")
        if blocked_count and row["status"] == "blocked":
            suffix.append(f"{int(blocked_count)} blocked")
        history_text = f" [{', '.join(suffix)}]" if suffix else ""
        capital = f" ${row['capital_required_usd']:,.2f}" if row["capital_required_usd"] else ""
        status_icon = {
            "actionable": "🚀",
            "blocked": "⛔",
            "watchlist": "👀",
        }.get(row["status"], "•")
        return f"- {status_icon} {symbol}{capital}: {reason}{history_text}"
