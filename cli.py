import argparse
import json

from src.planner.binance_gateway import BinanceGateway
from src.planner.config import load_config
from src.planner.events import EventIngestService
from src.planner.backtest import BacktestService
from src.planner.portfolio import PortfolioService
from src.planner.research import BinanceResearchService
from src.planner.reporting import ReportingService
from src.planner.storage import PlannerRepository
from src.planner.strategy import SpotStrategyService
from src.planner.telegram import send_plain_text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Binance two-sleeve research planner CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    portfolio = subparsers.add_parser("portfolio")
    portfolio_sub = portfolio.add_subparsers(dest="portfolio_command", required=True)
    portfolio_sub.add_parser("sync")
    reconcile = portfolio_sub.add_parser("reconcile-spot")
    reconcile.add_argument("--id", type=int)
    reconcile.add_argument("--symbol", required=True)
    reconcile.add_argument("--entry-ts", required=True)
    reconcile.add_argument("--entry-price", type=float, required=True)
    reconcile.add_argument("--qty", type=float, required=True)
    reconcile.add_argument("--cost-usd", type=float, required=True)
    reconcile.add_argument("--stop-price", type=float)
    reconcile.add_argument("--tp1-price", type=float)
    reconcile.add_argument("--tp2-price", type=float)
    reconcile.add_argument("--status", default="OPEN")
    reconcile.add_argument("--max-hold-until")
    reconcile.add_argument("--last-price", type=float)
    reconcile.add_argument("--unrealized-pnl-usd", type=float, default=0.0)
    reconcile.add_argument("--realized-pnl-usd", type=float, default=0.0)
    reconcile.add_argument("--close-ts")
    reconcile.add_argument("--close-price", type=float)
    reconcile.add_argument("--notes", default="")

    research = subparsers.add_parser("research")
    research_sub = research.add_subparsers(dest="research_command", required=True)
    ingest = research_sub.add_parser("ingest-events")
    ingest.add_argument("--file", required=True)
    research_sub.add_parser("sync-earn")

    strategy = subparsers.add_parser("strategy")
    strategy_sub = strategy.add_subparsers(dest="strategy_command", required=True)
    strategy_sub.add_parser("scan-spot")
    strategy_sub.add_parser("scan-research")

    report = subparsers.add_parser("report")
    report_sub = report.add_subparsers(dest="report_command", required=True)
    daily = report_sub.add_parser("daily")
    daily.add_argument("--telegram", action="store_true")
    research_report = report_sub.add_parser("research")
    research_report.add_argument("--telegram", action="store_true")

    backtest = subparsers.add_parser("backtest")
    backtest_sub = backtest.add_subparsers(dest="backtest_command", required=True)
    bt = backtest_sub.add_parser("run-spot")
    bt.add_argument("--limit-events", type=int)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    config = load_config()
    repo = PlannerRepository(config["database_path"])

    if args.command == "portfolio":
        if args.portfolio_command == "sync":
            state = PortfolioService(repo, BinanceGateway(), config).sync()
            print(json.dumps(state.__dict__, indent=2))
            return
        if args.portfolio_command == "reconcile-spot":
            payload = {
                "id": args.id,
                "symbol": args.symbol,
                "entry_ts": args.entry_ts,
                "entry_price": args.entry_price,
                "qty": args.qty,
                "cost_usd": args.cost_usd,
                "stop_price": args.stop_price,
                "tp1_price": args.tp1_price,
                "tp2_price": args.tp2_price,
                "status": args.status,
                "max_hold_until": args.max_hold_until,
                "catalyst_event_id": None,
                "last_price": args.last_price,
                "unrealized_pnl_usd": args.unrealized_pnl_usd,
                "realized_pnl_usd": args.realized_pnl_usd,
                "close_ts": args.close_ts,
                "close_price": args.close_price,
                "notes": args.notes,
            }
            repo.reconcile_spot_position(payload)
            print(json.dumps({"status": "ok", "symbol": args.symbol}, indent=2))
            return

    if args.command == "research":
        if args.research_command == "ingest-events":
            inserted = EventIngestService(repo).ingest_file(args.file)
            print(json.dumps({"inserted_events": inserted, "file": args.file}, indent=2))
            return
        if args.research_command == "sync-earn":
            synced = BinanceResearchService(repo, BinanceGateway(), config).sync_earn_products()
            print(json.dumps(synced, indent=2))
            return
        return

    if args.command == "strategy":
        if args.strategy_command == "scan-spot":
            rows = SpotStrategyService(repo, BinanceGateway(), config).scan()
            print(json.dumps(rows, indent=2))
            return
        if args.strategy_command == "scan-research":
            rows = BinanceResearchService(repo, BinanceGateway(), config).scan_earn_opportunities()
            print(json.dumps(rows, indent=2))
            return

    if args.command == "report":
        reporting = ReportingService(repo, config)
        if args.report_command == "daily":
            text = reporting.daily_report_text()
            print(text)
            if args.telegram:
                send_plain_text(text)
            return
        if args.report_command == "research":
            text = reporting.research_alert_text()
            print(text)
            if args.telegram:
                send_plain_text(text)
            return

    if args.command == "backtest":
        metrics = BacktestService(repo, BinanceGateway(), config).run_spot_backtest(limit_events=args.limit_events)
        print(json.dumps(metrics, indent=2))
        return


if __name__ == "__main__":
    main()
