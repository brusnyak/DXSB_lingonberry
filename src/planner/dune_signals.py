import time
from typing import Dict, List, Optional

from src.planner.context_clients import DuneClient
from src.planner.config import load_config


class DuneSignalsService:
    def __init__(self, client: Optional[DuneClient] = None, config: Optional[Dict] = None):
        self.client = client or DuneClient()
        self.config = config or load_config()
        self.planner = self.config["planner"]

    @staticmethod
    def _sanitize_symbols(symbols: List[str]) -> List[str]:
        cleaned = []
        for symbol in symbols:
            token = "".join(ch for ch in symbol.upper() if ch.isalnum())
            if token:
                cleaned.append(token)
        return sorted(set(cleaned))

    @staticmethod
    def _symbol_values(symbols: List[str]) -> str:
        return ", ".join(f"('{symbol}')" for symbol in symbols)

    def _execute_rows(self, sql: str, timeout_sec: Optional[int] = None) -> List[Dict]:
        timeout_sec = timeout_sec or self.planner["research_dune_query_timeout_sec"]
        execution = self.client.execute_sql(sql)
        execution_id = execution["execution_id"]
        started = time.time()
        while time.time() - started < timeout_sec:
            status = self.client.execution_status(execution_id)
            if status.get("is_execution_finished"):
                results = self.client.execution_results(execution_id)
                return (results.get("result") or {}).get("rows") or []
            time.sleep(2)
        return []

    def binance_flows(self, symbols: List[str]) -> Dict[str, Dict]:
        symbols = self._sanitize_symbols(symbols)
        if not symbols:
            return {}
        sql = f"""
with target_symbols(symbol) as (
    values {self._symbol_values(symbols)}
),
binance_addresses as (
    select blockchain, lower(address) as address
    from labels.addresses
    where lower(name) like 'binance%'
),
transfers as (
    select
        t.symbol,
        sum(case when concat('0x', lower(to_hex(t."to"))) = b.address then t.amount_usd else 0 end) as inflow_usd,
        sum(case when concat('0x', lower(to_hex(t."from"))) = b.address then t.amount_usd else 0 end) as outflow_usd
    from tokens.transfers t
    join target_symbols s on s.symbol = t.symbol
    join binance_addresses b
      on b.blockchain = t.blockchain
     and (
        concat('0x', lower(to_hex(t."to"))) = b.address
        or concat('0x', lower(to_hex(t."from"))) = b.address
     )
    where t.block_time > now() - interval '7' day
      and t.amount_usd >= 10000
    group by 1
)
select
    symbol,
    coalesce(inflow_usd, 0) as inflow_usd,
    coalesce(outflow_usd, 0) as outflow_usd,
    coalesce(inflow_usd, 0) - coalesce(outflow_usd, 0) as netflow_usd
from transfers
"""
        rows = self._execute_rows(sql)
        return {row["symbol"]: row for row in rows if row.get("symbol")}

    def dex_trader_positioning(self, symbols: List[str]) -> Dict[str, Dict]:
        symbols = self._sanitize_symbols(symbols)
        if not symbols:
            return {}
        sql = f"""
with target_symbols(symbol) as (
    values {self._symbol_values(symbols)}
),
buys as (
    select
        upper(token_bought_symbol) as symbol,
        tx_from as trader,
        sum(amount_usd) as buy_usd
    from dex.trades
    where block_time > now() - interval '7' day
      and upper(token_bought_symbol) in (select symbol from target_symbols)
      and amount_usd >= 1000
    group by 1, 2
),
sells as (
    select
        upper(token_sold_symbol) as symbol,
        tx_from as trader,
        sum(amount_usd) as sell_usd
    from dex.trades
    where block_time > now() - interval '7' day
      and upper(token_sold_symbol) in (select symbol from target_symbols)
      and amount_usd >= 1000
    group by 1, 2
),
netting as (
    select
        coalesce(b.symbol, s.symbol) as symbol,
        coalesce(b.trader, s.trader) as trader,
        coalesce(b.buy_usd, 0) - coalesce(s.sell_usd, 0) as net_usd
    from buys b
    full outer join sells s
      on b.symbol = s.symbol
     and b.trader = s.trader
)
select
    symbol,
    count_if(net_usd > 0) as smart_wallets,
    sum(net_usd) as position_delta_usd
from netting
group by 1
"""
        rows = self._execute_rows(sql)
        return {row["symbol"]: row for row in rows if row.get("symbol")}
