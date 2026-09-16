# Exchange-reported and grid-paired P&L

Verified against venue documentation on 2026-09-16.

The trade-records endpoint adds `exchange_pnl` alongside the existing system-calculated `profit`, `net_pnl`, and grid matching fields. It never substitutes a locally calculated value for a missing venue report and never deducts fees from the original reported amount.

## Attribution

Reports are isolated by credential, exchange, market, symbol, and exchange order ID. Per-fill reports are deduplicated by fill ID; conflicting duplicate values or incomplete quantity coverage remain pending. Complete order totals appear only on the most recent local fill row for that order. Other rows point to that row; the order total is not proportionally allocated across local fills.

Grid paired return remains a separate calculation based on explicitly linked opening and closing executions. An exchange can report a loss using its account position cost basis while the grid pair is profitable. Neither value overwrites the other. The existing strategy-equity/performance calculations are not replaced by this column.

## Sources

| Venue | Source | Display basis |
|---|---|---|
| Binance linear futures | WS `rp`; REST `userTrades.realizedPnl` | Excluding trading fees |
| OKX linear swaps | WS/REST `fillPnl` | Excluding trading fees |
| Gate USDT futures | Order fills -> matching contract and `trade_id` in `account_book`, `type=pnl`, `change` | Excluding trading fees; funding/fees are not added |
| Bybit linear | WS `execPnl`; REST `closed-pnl.closedPnl` matched by order ID | Original venue basis; no additional fee deduction |
| Bitget classic futures | REST `fills.profit` | Original venue basis; no additional fee deduction |
| HTX USDT contracts | Per-fill `real_profit`; order-detail fallback when V5 lacks it | Realized trading P&L, including historical position settlement; fees separate |
| IBKR stocks | Commission report `realizedPNL` joined to its execution ID | Original reporting currency and venue basis |
| Spot / Alpaca without an equivalent order P&L field | No fabricated report | Unavailable; actual fills and system-calculated return remain visible |

For Bitget, order-channel `profit` is deliberately not summed as per-fill P&L. HTX order-level `real_profit` must not be inherited by every child fill. IBKR unset/nonfinite/sentinel values remain unknown rather than becoming zero.

## REST reconciliation and deployment

Apply `20260916_exchange_order_pnl.sql` through the normal migration entrypoint. The schema is also included in `init.sql`. The table stores only report metadata and identifiers, not credentials.

Opening the authenticated trade-records endpoint first reads stored WS events and cached reports. Incomplete reports trigger at most two order lookups per request and four newly claimed order lookups per credential per minute, enforced with a PostgreSQL transaction lock. This is an order-lookup budget; paginated venue APIs may require multiple HTTP calls. Complete REST reports are cached for five minutes. Quantity changes invalidate a cached total. Missing or truncated venue histories remain pending. Backfill progresses as the records endpoint is refreshed; it is not an independent historical account sweep.

Only supported linear settlement currencies are used; inverse contracts are not relabeled as quote-currency P&L. No live orders are submitted by reconciliation. Historical execution prices and strategy costs are not rewritten.

## References

- [Gate futures account book and trade history](https://www.gate.com/docs/developers/apiv4/en/futures/)
- [Binance account trade list](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Account-Trade-List)
- [OKX trading API](https://www.okx.com/docs-v5/en/)
- [Bybit execution stream](https://bybit-exchange.github.io/docs/v5/websocket/private/execution)
- [Bybit closed P&L](https://bybit-exchange.github.io/docs/v5/position/close-pnl)
- [Bitget fill details](https://www.bitget.com/api-doc/classic/contract/trade/Get-Order-Fills)
- [HTX USDT contract API](https://huobiapi.github.io/docs/usdt_swap/v1/en/)
- [IBKR commission report](https://www.interactivebrokers.com/docs/tws-api/ref/commission-and-fees-report)
- [Alpaca trade updates](https://docs.alpaca.markets/us/docs/websocket-streaming)

## Validation

Offline regression uses realistic venue response fixtures and an isolated PostgreSQL database, including REST/WS accounting, partial fills, duplicate reports, cross-account isolation, Gate bill matching, missing reports, fee double-count prevention, IBKR delayed reports, cache invalidation, migration bootstrap, and authenticated API serialization. The UI is checked with fixture records, not a live account. This does not certify a production account statement reconciliation.
