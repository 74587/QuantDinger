# Execution price evidence audit

## Findings and corrections

Live trade rows must be based on exchange execution evidence. Order acceptance, an order limit price, a signal reference price, or an account position change is not a fill.

Removed the following substitutions:

- Alpaca worker: signal reference price when the broker returned quantity but no fill average.
- Binance futures placement and polling: order `price` when execution `avgPrice` was missing. A confirmed `cumQuote / executedQty` remains a valid execution average.
- Grid parsing and posting: requested order price or quantity when actual execution fields were missing.
- Recovery: inferred account position delta recorded at the signal reference price.
- Pending WebSocket projection: previous pending-order average reused for a new execution without a price.
- Executors: quantity from one cumulative snapshot paired with an average from another snapshot with a different quantity; composite average calculated with a missing leg price.

Invalid or incomplete execution prices cannot advance position/trade accounting. Actual cumulative quantity and notional determine each incremental fill; repeated reports remain idempotent. Existing REST reconciliation and private streams provide subsequent evidence.

## Trade record display

The existing price and amount remain execution fields. The API additionally returns `reference_price`, `reference_kind`, `price_deviation_pct`, and exchange order/fill identifiers. Reference data comes only from the linked pending order or grid order in the same strategy. Raw instruction payloads are never returned.

Grid references are submitted limit prices. Pending-order references prefer the saved signal reference, otherwise the original instruction price. Historical records without reference data remain blank. Positive directional deviation means worse execution, negative means better execution. This comparison excludes fees and includes price changes while orders wait; a limit-price comparison is not necessarily market slippage.

Prices and quantities use significant-digit formatting instead of rounding small fills to four decimals. The order identifier is available in the fill-price tooltip.

## Limits

This change does not reconcile historical rows with a live account or rewrite old trades. Existing records previously written using fallback prices still need exchange order/fill evidence before correction. P&L is calculated by the system; exchange fill provenance does not establish that grid-cell matching and account-average P&L are the same measure. Unknown fees remain unconfirmed. Strategy parsing, Broker ID attribution, and order entry/exit rules are unchanged.

## Verification

- Backend local suite: 2744 passed, 7 skipped, 23 deselected. Skips cover POSIX-only checks and unavailable TA-Lib; external integration/stress cases are deselected.
- Real disposable PostgreSQL tests cover rollback/replay with missing prices, REST/WS deduplication, partial fills, and the trade API reference join.
- Frontend: 280 unit tests passed, including compiled Vue rendering for populated, empty, and loading states; production build passed.
- Ruff and backend quality checks passed. No real-account orders were placed and no running deployment was changed.

## Official field references

- [Binance USD-M futures order API](https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Query-Order)
- [Alpaca orders](https://docs.alpaca.markets/us/docs/orders-at-alpaca)
