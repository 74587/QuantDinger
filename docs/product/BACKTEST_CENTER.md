# Backtest Center guide

A backtest validates strategy behavior against specified historical data and execution assumptions. It is a research tool, not a promise of future returns or proof that live connectivity and venue rules are ready.

## Before running

Verify these inputs:

- Source and manifest are the intended strategy version.
- Market, instruments, and frequency use canonical identifiers.
- The start leaves enough warmup history for indicators and universe selection.
- Initial capital, fees, slippage, and position limits match the test.
- The benchmark is comparable to the strategy market and quote currency.

## Read a result

Review in this order:

1. **Data and status:** success does not prove complete data. Check first and last timestamps, bar counts, warmup, and missing fields.
2. **Execution assumptions:** inspect fees, slippage, liquidity, and unmodeled items. Strategy API V2 currently does not model Crypto funding payments.
3. **Risk:** review maximum drawdown, volatility, concentration, and the worst period.
4. **Execution ledger:** sample entries, exits, quantities, prices, fees, and position changes against the source.
5. **Benchmark:** compare both absolute return and relative performance.
6. **Robustness:** vary ranges, parameters, and regimes instead of keeping only the best run.

## Common misreadings

- Zero executions may mean missing data, insufficient warmup, or unreachable conditions.
- Intraday history is often shorter, so a long requested range may be unavailable.
- Leveraged results cannot be extrapolated without funding and liquidation risk.
- Tokenized equities, exchange equity perpetuals, and broker securities are different execution products.
- Historical data availability does not imply live support.

## Continue safely

Save the strategy version, parameters, data range, and result. Create a stopped deployment and then use `signal` mode. Complete the [live-trading safety checklist](../trading/LIVE_TRADING_SAFETY.md) before real capital. See the [Strategy API V2 guide](../trading/STRATEGY_DEV_GUIDE.md) for the programming contract and errors.

