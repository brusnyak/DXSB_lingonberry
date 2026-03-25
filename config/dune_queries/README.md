# Dune Query Contracts

The planner reads the latest result of up to three saved Dune queries from `.env`:

- `DUNE_QUERY_ID_BINANCE_FLOWS`
- `DUNE_QUERY_ID_TOKEN_UNLOCKS`
- `DUNE_QUERY_ID_SMART_MONEY`

The queries can use any internal logic you want, but their output should expose these columns so the bot can match rows to Binance assets.

## 1. Binance flows

Required columns:

- `symbol`
- `netflow_usd`

Optional useful columns:

- `inflow_usd`
- `outflow_usd`
- `date`

Interpretation:

- positive `netflow_usd` can indicate exchange inflow / possible sell pressure
- negative `netflow_usd` can indicate net outflow / potential accumulation

## 2. Token unlocks

Required columns:

- `symbol`

Preferred columns:

- `unlock_date`
- `unlock_pct`
- `unlock_amount`

Interpretation:

- this is treated as a risk note in planner research output

## 3. Smart money

Required columns:

- `symbol`

Preferred columns:

- `smart_wallets`
- `position_delta_usd`
- `date`

Interpretation:

- positive `position_delta_usd` plus rising `smart_wallets` is treated as supportive context

## Matching rules

The planner currently matches rows by exact uppercase equality on one of these fields:

- `symbol`
- `asset`
- `token`
- `ticker`

Examples:

- `POLYX`
- `ONT`
- `GAS`

Do not return `POLYXUSDT`; return the base asset symbol only.
