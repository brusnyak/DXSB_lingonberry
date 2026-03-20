import argparse
import glob
import json
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.adapters.market_adapters import ParquetAdapter
from src.analysis.ict_analyst import ICTAnalyst, Candle


@dataclass
class TradeResult:
    symbol: str
    entry_ts: int
    entry: float
    stop: float
    target: float
    exit: float
    outcome: str
    pnl_pct: float


def _parse_target_potential_pct(v: str) -> float:
    try:
        return float(v.split("~")[1].split("%")[0])
    except Exception:
        return 0.0


def _evaluate_trade(future: List[Candle], entry: float, stop: float, target: float) -> (str, float):
    if not future:
        return "NO_DATA", entry

    for c in future:
        if c.low <= stop:
            return "SL", stop
        if c.high >= target:
            return "TP", target

    return "TIME", future[-1].close


def run_backtest(
    files: List[str],
    benchmark_file: Optional[str],
    lookback: int,
    horizon: int,
    step: int,
    min_score: float,
    min_target_potential: float,
    min_upside_to_target: float,
):
    adapter = ParquetAdapter()
    analyst = ICTAnalyst()

    benchmark = adapter.fetch_candles(benchmark_file) if benchmark_file else []

    all_trades: List[TradeResult] = []

    for file_path in files:
        candles = adapter.fetch_candles(file_path)
        if len(candles) < lookback + horizon + 5:
            continue

        symbol = os.path.basename(file_path).replace(".parquet", "")
        local_trades = 0

        for i in range(lookback, len(candles) - horizon, step):
            window = candles[i - lookback:i]
            future = candles[i:i + horizon]
            benchmark_window = []
            if benchmark and len(benchmark) >= i:
                benchmark_window = benchmark[i - lookback:i]

            res = analyst.calculate_investment_score(window, symbol, benchmark_candles=benchmark_window)
            meta = res.extra_metadata or {}

            if res.score < min_score:
                continue
            if _parse_target_potential_pct(res.target_potential) < min_target_potential:
                continue
            if meta.get("entry_state") != "READY":
                continue
            if bool(meta.get("overextended", False)):
                continue
            if float(meta.get("upside_to_target_pct", 0.0) or 0.0) < min_upside_to_target:
                continue

            entry = window[-1].close
            stop = float(res.inv_level)
            target = float(res.target_level)
            if stop <= 0 or target <= 0 or target <= entry or stop >= entry:
                continue

            outcome, exit_price = _evaluate_trade(future, entry, stop, target)
            pnl_pct = ((exit_price / entry) - 1) * 100

            all_trades.append(
                TradeResult(
                    symbol=symbol,
                    entry_ts=window[-1].timestamp,
                    entry=entry,
                    stop=stop,
                    target=target,
                    exit=exit_price,
                    outcome=outcome,
                    pnl_pct=pnl_pct,
                )
            )
            local_trades += 1

        print(f"{symbol}: {local_trades} trades")

    total = len(all_trades)
    if total == 0:
        print(json.dumps({"trades": 0, "note": "No trades matched filter"}, indent=2))
        return

    wins = [t for t in all_trades if t.outcome == "TP"]
    losses = [t for t in all_trades if t.outcome == "SL"]
    timed = [t for t in all_trades if t.outcome == "TIME"]
    time_positive = [t for t in timed if t.pnl_pct > 0]
    decided = len(wins) + len(losses)

    gross_win = sum(t.pnl_pct for t in wins)
    gross_loss_abs = abs(sum(t.pnl_pct for t in losses if t.pnl_pct < 0))
    profit_factor = (gross_win / gross_loss_abs) if gross_loss_abs > 0 else None

    summary = {
        "trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "time_exits": len(timed),
        "time_positive": len(time_positive),
        "win_rate_pct": round((len(wins) / total) * 100, 2),
        "decision_win_rate_pct": round((len(wins) / decided) * 100, 2) if decided else None,
        "avg_pnl_pct": round(sum(t.pnl_pct for t in all_trades) / total, 4),
        "net_pnl_pct": round(sum(t.pnl_pct for t in all_trades), 3),
        "profit_factor": round(profit_factor, 3) if profit_factor is not None else None,
        "params": {
            "lookback": lookback,
            "horizon": horizon,
            "step": step,
            "min_score": min_score,
            "min_target_potential": min_target_potential,
            "min_upside_to_target": min_upside_to_target,
        },
    }
    print(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Backtest current investment scanner logic on parquet data")
    parser.add_argument("--glob", default="data/parquet/crypto/*1440.parquet", help="Glob for parquet files")
    parser.add_argument("--benchmark", default="data/parquet/crypto/BTCUSD1440.parquet", help="Benchmark parquet")
    parser.add_argument("--lookback", type=int, default=100)
    parser.add_argument("--horizon", type=int, default=20, help="How many bars after signal to evaluate")
    parser.add_argument("--step", type=int, default=1)
    parser.add_argument("--min-score", type=float, default=70.0)
    parser.add_argument("--min-target-potential", type=float, default=5.0)
    parser.add_argument("--min-upside-to-target", type=float, default=4.0)
    args = parser.parse_args()

    files = sorted(glob.glob(args.glob))
    if not files:
        print(json.dumps({"trades": 0, "note": f"No files matched {args.glob}"}, indent=2))
        return

    benchmark = args.benchmark if os.path.exists(args.benchmark) else None
    run_backtest(
        files=files,
        benchmark_file=benchmark,
        lookback=args.lookback,
        horizon=args.horizon,
        step=args.step,
        min_score=args.min_score,
        min_target_potential=args.min_target_potential,
        min_upside_to_target=args.min_upside_to_target,
    )


if __name__ == "__main__":
    main()
