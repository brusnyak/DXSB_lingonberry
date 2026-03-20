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
        cash_balances = self.repository.latest_cash_balances()
        spot_positions = self.repository.open_spot_positions()
        recs = self.repository.recent_recommendations(limit=20)
        analytics = self.analytics_summary()

        blocked = [row for row in recs if row["status"] == "blocked"]
        actionable = [row for row in recs if row["status"] == "actionable"]
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
            "Binance Two-Sleeve Daily Report",
            "================================",
            f"Snapshot: {snapshot['snapshot_ts']}",
            f"Total equity: ${snapshot['total_equity']:,.2f} | EUR {snapshot.get('total_equity_eur', 0.0):,.2f}",
            f"Earn sleeve: ${snapshot['earn_equity']:,.2f} | APR-weighted est: {analytics['effective_apr'] * 100:.2f}% | accrued yield: ${snapshot['accrued_yield_usd']:,.2f}",
            f"Spot sleeve: ${snapshot['spot_equity']:,.2f} | free cash: ${snapshot['free_cash']:,.2f} | EUR {snapshot.get('free_cash_eur', 0.0):,.2f} | buying power: ${snapshot['buying_power']:,.2f}",
            f"Locked cash: ${snapshot['locked_cash']:,.2f} | active spot positions: {len(spot_positions)}",
            f"Realized PnL: ${snapshot['realized_pnl_usd']:,.2f} | Unrealized PnL: ${snapshot['unrealized_pnl_usd']:,.2f}",
            f"Rolling returns: 7d {analytics['rolling_7d_pct']:.2f}% | 30d {analytics['rolling_30d_pct']:.2f}%",
            "",
            "Cash balances:",
        ]
        if cash_balances:
            lines.extend([f"- {row['asset']}: ${row['value_usd']:,.2f} | EUR {row['value_eur']:,.2f}" for row in cash_balances])
        else:
            lines.append("- No free cash balances recorded.")
        lines += [
            "",
            "Top concentration:",
        ]
        if concentration_lines:
            lines.extend([f"- {name}: ${value:,.2f}" for name, value in concentration_lines])
        else:
            lines.append("- No active exposure recorded.")
        lines += [
            "",
            "Next unlock dates:",
        ]
        if unlocks:
            lines.extend([f"- {item}" for item in unlocks])
        else:
            lines.append("- No locked Earn positions.")
        lines += [
            "",
            "Actionable ideas:",
        ]
        if actionable:
            lines.extend(
                [
                    f"- {row['sleeve']} {row['symbol_or_asset']} {row['action']} ${row['capital_required_usd']:,.2f}: {row['reason']}"
                    for row in actionable[:5]
                ]
            )
        else:
            lines.append("- No actionable recommendations.")
        lines += [
            "",
            "Blocked ideas:",
        ]
        if blocked:
            lines.extend(
                [
                    f"- {row['sleeve']} {row['symbol_or_asset']} ${row['capital_required_usd']:,.2f}: {row['reason']}"
                    for row in blocked[:5]
                ]
            )
        else:
            lines.append("- No blocked recommendations.")
        lines += [
            "",
            "Spot analytics:",
            f"- Win rate: {analytics['win_rate_pct']:.2f}%",
            f"- Avg win/loss: ${analytics['avg_win_usd']:,.2f} / ${analytics['avg_loss_usd']:,.2f}",
            f"- Expectancy: ${analytics['expectancy_usd']:,.2f}",
            f"- Profit factor: {analytics['profit_factor']:.2f}" if analytics["profit_factor"] is not None else "- Profit factor: n/a",
            f"- Max drawdown: {analytics['max_drawdown_pct']:.2f}%",
            "",
            "Earn analytics:",
            f"- Realized yield proxy: ${analytics['realized_yield_usd']:,.2f}",
            f"- Effective APR: {analytics['effective_apr'] * 100:.2f}%",
            f"- Locked vs unlocked days: {analytics['locked_days']:.1f} / {analytics['unlocked_days']:.1f}",
        ]
        return "\n".join(lines)
