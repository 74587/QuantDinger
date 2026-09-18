# AI Research guide

AI Research organizes market data, instrument context, and model analysis into a reviewable research process. It can speed up research, but it does not replace data checks, risk judgment, or investment decisions.

## Start a research task

1. Select the correct market and instrument; avoid a similarly named product on another venue.
2. Check quote time, currency, venue, and data frequency.
3. Choose a goal such as trend, fundamentals, risk, or cross-instrument comparison.
4. Run the analysis and wait for data and model stages to finish.
5. Save useful findings or continue into indicator and strategy development.

## Decide whether a result is usable

- **Data time:** check quote, filing, and news timestamps; do not present old data as current.
- **Evidence:** model conclusions should agree with charts, indicators, and structured data.
- **Market identity:** the researched instrument must match the intended execution product. Exchange equities, tokenized equities, and traditional broker securities are different identities.
- **Missing data:** shorten the range, change provider, or stop when required history or fundamentals are absent. Empty data is not a no-signal result.
- **Model variation:** models may disagree. A person should review important conclusions.

## Continue from research to a strategy

Research can define a hypothesis, screen a universe, or produce a code draft. In the strategy editor you still need to:

- Define entry, exit, sizing, and risk rules.
- Use canonical market identifiers and data frequencies.
- Pass Strategy API V2 validation.
- Backtest on an independent range and inspect execution assumptions.

Continue with the [strategy workflow](STRATEGY_WORKFLOW.md). See the [indicator development guide](../trading/INDICATOR_DEV_GUIDE.md) for indicator contracts.

## Result boundaries

AI output may contain errors, omissions, or unsupported inferences. Remove account details, secrets, and personal data before sharing a report. Before live use, verify source data, product identity, costs, liquidity, and account risk.

