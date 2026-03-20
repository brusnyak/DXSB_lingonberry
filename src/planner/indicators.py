from typing import Iterable, List, Sequence


def ema(values: Sequence[float], period: int) -> List[float]:
    if len(values) < period:
        return []
    multiplier = 2 / (period + 1)
    result = [sum(values[:period]) / period]
    for value in values[period:]:
        result.append((value - result[-1]) * multiplier + result[-1])
    return result


def atr(candles: Sequence[dict], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 0.0
    trs: List[float] = []
    for idx in range(1, len(candles)):
        current = candles[idx]
        previous = candles[idx - 1]
        tr = max(
            float(current["high"]) - float(current["low"]),
            abs(float(current["high"]) - float(previous["close"])),
            abs(float(current["low"]) - float(previous["close"])),
        )
        trs.append(tr)
    window = trs[-period:]
    return sum(window) / len(window) if window else 0.0


def pct_change(current: float, previous: float) -> float:
    if previous == 0:
        return 0.0
    return ((current / previous) - 1.0) * 100.0


def max_drawdown(equity_curve: Iterable[float]) -> float:
    peak = None
    max_dd = 0.0
    for value in equity_curve:
        if peak is None or value > peak:
            peak = value
        if peak and peak > 0:
            drawdown = ((peak - value) / peak) * 100.0
            max_dd = max(max_dd, drawdown)
    return max_dd

