import argparse
import json
import sqlite3
from datetime import datetime, timedelta, timezone


def compute_drawdown(equity_points):
    peak = float('-inf')
    max_dd = 0.0
    for x in equity_points:
        peak = max(peak, x)
        dd = peak - x
        max_dd = max(max_dd, dd)
    return max_dd


def main():
    parser = argparse.ArgumentParser(description="DXSB stats report")
    parser.add_argument("--db", default="dex_analytics.db", help="Path to sqlite db")
    parser.add_argument("--days", type=int, default=14, help="Lookback window in days")
    args = parser.parse_args()

    cutoff = (datetime.now(timezone.utc) - timedelta(days=args.days)).isoformat()
    conn = sqlite3.connect(args.db)
    try:
        rows = conn.execute(
            """
            SELECT pnl_r FROM signals
            WHERE status = 'CLOSED' AND close_ts_utc >= ?
            ORDER BY close_ts_utc ASC
            """,
            (cutoff,),
        ).fetchall()
    except sqlite3.OperationalError:
        print(json.dumps({"closed_signals": 0, "note": "signals table not found yet"}, indent=2))
        return

    rs = [float(r[0]) for r in rows if r[0] is not None]
    n = len(rs)
    if n == 0:
        print(json.dumps({"closed_signals": 0}, indent=2))
        return

    wins = [x for x in rs if x > 0]
    losses = [x for x in rs if x < 0]

    gross_profit = sum(wins)
    gross_loss_abs = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss_abs) if gross_loss_abs > 0 else None
    win_rate = len(wins) / n

    equity = []
    running = 0.0
    for x in rs:
        running += x
        equity.append(running)

    max_dd_r = compute_drawdown(equity)

    report = {
        "window_days": args.days,
        "closed_signals": n,
        "win_rate_pct": round(win_rate * 100, 2),
        "profit_factor": round(profit_factor, 3) if profit_factor is not None else None,
        "net_r": round(sum(rs), 3),
        "avg_r_per_trade": round(sum(rs) / n, 4),
        "max_drawdown_r": round(max_dd_r, 3),
        "gate": {
            "min_days": 14,
            "min_closed_signals": 60,
            "min_win_rate_pct": 70,
            "min_profit_factor": 2.0,
            "max_drawdown_r_note": "Convert R drawdown to account % with your risk-per-trade profile"
        }
    }

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
