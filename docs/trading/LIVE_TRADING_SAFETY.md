# Live-trading safety guide

This guide defines the minimum checks before moving from backtest or signal mode to real capital. Venue, broker, region, and account type affect available products; the active catalog and account response take precedence over static examples.

## Support boundary

| Market | Current live venues | Key limit |
| --- | --- | --- |
| Crypto | Binance, Bitget, Bybit, OKX, Gate, HTX | spot and swap depend on venue and account capability |
| Exchange direct equities | Gate stock channel | retain exact currency and catalog identity; long-only |
| Exchange tokenized equities | OKX, Bybit, Bitget Reality | catalog and regional availability required; long-only |
| Exchange equity perpetuals | Binance, OKX, Bitget, Bybit, Gate | derivative exposure; exact native contract and swap rules required |
| Binance bStocks | Binance | exact catalog pair, spot semantics, and no leverage |
| USStock | Alpaca, IBKR | current broker strategy policy is long-only |
| Other parsed markets | none | data or backtest support does not imply live support |

HTX equity products are rejected until authoritative metadata and an execution contract are available. Mixed-market live deployment is unsupported. See [Section 18 of the Strategy API V2 guide](STRATEGY_DEV_GUIDE.md#18-deployment-and-live-boundaries) for canonical identifiers and the full boundary.

## Preflight checklist

1. **Account:** use a dedicated subaccount or low-balance account; grant required trading permissions only and disable withdrawals.
2. **Instrument:** verify venue, market type, settlement currency, native symbol, and API family.
3. **Strategy:** source, manifest, direction, and leverage declarations pass validation.
4. **Backtest:** a person has reviewed data, costs, slippage, funding, execution ledger, and maximum drawdown.
5. **Signal:** run `signal` first and check notification frequency, time zone, and state restoration after restart.
6. **Positions:** identify manual and other-strategy holdings; resolve every unknown delta.
7. **Limits:** set notional, per-symbol, gross exposure, leverage, and loss boundaries.
8. **Incident path:** confirm an operator can stop the deployment, cancel orders, and use emergency stop.

## While running

- Monitor runtime state, order status, fills, positions, available balance, and notifications.
- An unknown reconciliation delta pauses same-side entries or additions; do not bypass that protection.
- Minimum quantity, step size, minimum notional, and available margin can change the submitted quantity.
- WebSocket improves latency; REST reconciliation remains the recovery source after disconnects.
- A strategy manages only its allocated position and must not absorb manual or other-strategy inventory.

## Optional JEV System One entry filter

JEV is a System One model: it evaluates prepared state and typed questions into structured decisions instead of generating free-form text. Regular strategies and Quick Trade can use it before submitting entry orders. The result is reduced to an auditable `PASS` or `REJECT`; exits, stop loss, take profit, and emergency risk reduction bypass the filter. If JEV is unavailable, QuantDinger falls back to the configured LLM. If neither provider is available, the order proceeds and the unavailable provider is recorded so AI failure does not disable trading.

## Incident response

1. Stop new entries and additions.
2. Record deployment, account, instrument, order IDs, timestamps, and errors.
3. Compare the venue or broker's actual orders and positions; do not rely on cached UI state alone.
4. Before cancelling or reducing, confirm the action cannot cross protected manual inventory.
5. Stop the strategy or use emergency stop if risk continues to grow.
6. Do not restart until the root cause and ledger are reconciled.
