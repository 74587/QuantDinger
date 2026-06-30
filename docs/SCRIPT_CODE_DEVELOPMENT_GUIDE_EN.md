# QuantDinger Script Code Development Guide

This guide explains how to write QuantDinger script code that can be backtested, deployed live, and maintained safely. Script code is for stateful strategies such as layered entries, basket average-cost take profit, trailing stops, pyramiding, cooldowns, and duplicate-order protection.

## 1. Core Boundary

Script code owns strategy logic only. Values chosen by the user at run time should not be duplicated as code parameters.

The run panel owns:

- Symbol, such as BTC/USDT
- Market type, spot or swap
- Trade direction, long, short, or both
- Investment amount
- Contract leverage
- Account, notifications, and live risk controls

Script code owns:

- Entry conditions
- Add, reduce, take-profit, and stop-loss rules
- Layer count, spacing, multipliers, periods, and cooldowns
- Persistent state and duplicate-order protection
- Logs and basket checkpoints

Do not write these as script parameters:

```python
ctx.param('direction', 'long')
ctx.param('market_type', 'swap')
ctx.param('investment_amount', 1000)
ctx.param('leverage', 3)
ctx.param('base_notional', 50)
```

Read run-panel values directly when needed:

```python
direction = ctx.direction
market_type = ctx.market_type
budget = ctx.investment_amount
leverage = ctx.leverage
```

## 2. Lifecycle

Every script must define:

```python
def on_init(ctx):
    pass

def on_bar(ctx, bar):
    pass
```

`on_init(ctx)` runs once when the script starts. Use it to read strategy parameters and initialize defaults.

`on_bar(ctx, bar)` runs once per K-line bar. The platform uses a fixed 1m bar stream for script strategies; live execution also checks the latest price every 10 seconds to reduce take-profit and stop-loss latency. Backtests are K-line based, so do not write tick-level strategies that require every market tick.

`bar` supports:

```python
bar['open']
bar['high']
bar['low']
bar['close']
bar['volume']
bar['timestamp']
```

## 3. Parameter Design

Only put strategy knobs into `ctx.param(...)`:

```python
def on_init(ctx):
    ctx.fast_period = ctx.param('fast_period', 12)
    ctx.slow_period = ctx.param('slow_period', 36)
    ctx.take_profit_pct = ctx.param('take_profit_pct', 0.006)
    ctx.max_layers = ctx.param('max_layers', 5)
```

Percent defaults in Python code use 0-1 ratios:

- `0.006` means 0.6%
- `0.02` means 2%
- `0.8` means 80%

The frontend may display 0-100 percent values, but the generated Python default literal should remain a ratio.

## 4. Investment Amount and Order Sizing

For stateful scripts, prefer `ctx.basket(side).open_child_order(..., notional=quote_amount)`.

`notional` means quote-currency amount, for example USDT. Backtest and live execution convert it into base quantity using market type, price, and leverage.

Example:

```python
def _run_budget(ctx):
    try:
        budget = float(ctx.investment_amount or 0.0)
    except Exception:
        budget = 0.0
    if budget > 0:
        return budget
    return 0.0

def _planned_base_notional(ctx):
    total_weight = 1 + 1.8 + 3.24
    return _run_budget(ctx) / total_weight

def on_bar(ctx, bar):
    price = float(bar['close'])
    side = 'short' if str(ctx.direction).lower() == 'short' else 'long'
    basket = ctx.basket(side)
    quote_amount = _planned_base_notional(ctx)
    basket.open_child_order(
        layer=1,
        order=1,
        notional=quote_amount,
        price=price,
        action='open',
        payload={'reason': 'first_entry'},
    )
```

Do not expose "base order amount" as a template parameter. A clearer model is: the user enters one investment amount, and the script derives child order amounts from layer count, multipliers, and total weights.

## 5. Direction Handling

Direction is selected in the run panel. The script reads it, but should not hard-code it.

Recommended helper:

```python
def _side(ctx):
    try:
        direction = str(ctx.direction)
    except Exception:
        direction = 'long'
    return 'short' if direction.lower() == 'short' else 'long'
```

Spot can only run long. That constraint is enforced by the run panel and execution layer; scripts do not need a second complicated branch.

## 6. State Management

Layered, basket, or cooldown-based strategies must use `ctx.state`.

Common state keys:

- Current layer: `layer`
- Current child order: `order`
- Average cost: `avg_cost`
- Total quantity: `qty`
- Next trigger price: `next_trigger`
- Cooldown-until bar: `cooldown_until`
- Last order bar: `last_order_bar`

Example:

```python
bar_no = int(ctx.current_index)
last_order_bar = int(ctx.state.get('last_order_bar', -999999) or -999999)
if last_order_bar == bar_no:
    return

ctx.state.set('last_order_bar', bar_no)
```

This prevents duplicate orders on the same bar.

## 7. Basket API

`ctx.basket(side)` is the preferred API for strategies with basket semantics.

Common usage:

```python
basket = ctx.basket('long')

basket.open_child_order(
    layer=1,
    order=1,
    notional=50,
    price=price,
    action='open',
    payload={'reason': 'entry'},
)

basket.open_child_order(
    layer=2,
    order=1,
    notional=80,
    price=price,
    action='add',
    payload={'reason': 'add_layer'},
)

basket.close_all(reason='take_profit')
```

Use `checkpoint` to expose the current strategy state:

```python
basket.checkpoint(
    status='opening',
    current_layer=layer,
    current_order_in_layer=order,
    total_qty=qty,
    total_notional=qty * avg_cost,
    avg_entry_price=avg_cost,
    next_entry_trigger=next_trigger,
    take_profit_price=take_profit,
    max_layer=max_layers,
    max_orders_per_layer=orders_per_layer,
)
```

## 8. Backtest and Live Alignment

Script backtest and live execution share the same `on_init/on_bar` semantics. Keep these points in mind:

- Backtests are based on historical K-line bars and do not simulate every 10-second live price check.
- Live execution additionally checks latest price for faster price-condition handling.
- Use basket `notional` sizing so leverage behavior stays consistent across backtest and live.
- Do not use future data. Use `ctx.bars(n)` for current and historical bars only.
- Every scale-in needs a price distance, max layer/order limit, and duplicate-order guard.

## 9. Sandbox Restrictions

Scripts run inside a safety sandbox. Do not use:

- `getattr`, `setattr`, `delattr`
- `eval`, `exec`, `open`, `compile`
- `globals`, `vars`, `dir`
- `__builtins__` or dunder attributes
- File, network, database, process, or thread APIs
- `os`, `sys`, `requests`, `urllib`, `socket`, `subprocess`, `threading`, `multiprocessing`, `sqlite3`, `psycopg`, `sqlalchemy`, `pathlib`, `tempfile`, `glob`, `io`, `operator`, `pickle`, or `ctypes`

For optional fields, use direct access with `try/except`:

```python
try:
    direction = str(ctx.direction)
except Exception:
    direction = 'long'
```

Do not write:

```python
direction = getattr(ctx, 'direction', 'long')
```

## 10. Recommended Template Types

Professional script templates should cover different market regimes instead of repeating the same scale-in idea:

- EMA ATR trend risk: trend following with ATR hard stop and ATR trailing stop.
- Donchian breakout pyramid: channel breakout entry and favorable pyramiding.
- Bollinger mean reversion basket: layered entries around volatility-band extremes and average-cost reversion exit.
- Layered basket martingale: multiple layers, martingale child sizing, average-cost take profit, and hard stop.

These four cover trend, breakout, range reversion, and high-risk basket models without showing several duplicate "add-on-dip" templates.

## 11. Recommended Architecture for Complex Scripts

Do not write complex scripts as one large `if/else` block. Split the logic into five layers:

1. Signal layer: decide whether entry, add, or exit is allowed.
2. Sizing layer: split the run-panel investment amount into planned child order amounts.
3. State layer: persist phase, layer, child order, average cost, trigger price, and cooldown.
4. Execution layer: emit only `basket.open_child_order` or `basket.close_all`.
5. Risk layer: hard stop, max layers, max child orders, cooldown, and duplicate-order guards.

The script is still a single file, but the internal structure should look like this:

```python
def on_init(ctx):
    # 1. Read strategy knobs
    pass

def _side(ctx):
    # 2. Read run-panel direction
    pass

def _run_budget(ctx):
    # 3. Read run-panel investment amount
    pass

def _planned_notional(ctx, layer, order):
    # 4. Calculate planned quote amount for each child order
    pass

def _entry_signal(ctx, bar, bars):
    # 5. Entry signal
    pass

def _risk_exit(ctx, price, avg_cost):
    # 6. Risk exit
    pass

def _place_child(ctx, basket, layer, order, price, action):
    # 7. Place order and update state
    pass

def on_bar(ctx, bar):
    # 8. Main orchestration only
    pass
```

This makes it much easier to add conditions, change sizing, or replace exit logic without rewriting the whole strategy.

## 12. State Machine Model

Complex strategies should start with a state machine design. Recommended phases:

| State | Meaning | Allowed actions |
| --- | --- | --- |
| `idle` | Flat and waiting | Check entry |
| `opening` | First order placed or basket building | Add, take profit, stop |
| `active` | Position is running | Take profit, stop, trailing exit |
| `closing` | Close triggered | Wait for execution layer |
| `cooldown` | Post-exit cooldown | No re-entry |

The script does not have to store these exact strings, but the logic should follow this model. At minimum persist:

```python
ctx.state.set('layer', layer)
ctx.state.set('order', order)
ctx.state.set('avg_cost', avg_cost)
ctx.state.set('qty', qty)
ctx.state.set('next_trigger', next_trigger)
ctx.state.set('cooldown_until', cooldown_until)
ctx.state.set('last_order_bar', bar_no)
```

Recommended `on_bar` flow:

```python
def on_bar(ctx, bar):
    # 1. Return if not enough data
    # 2. Read direction, price, and state
    # 3. If flat, repair/reset stale state
    # 4. If in cooldown, return
    # 5. If flat, check entry
    # 6. If in position, check take-profit/stop first
    # 7. If still in position, check add logic
    # 8. After any order, update checkpoint and state
```

Do not add first and check stop later. In complex scripts, this order matters.

## 13. Sizing Models

Users enter one investment amount. The script should split it according to the strategy structure.

### 13.1 Equal Layers

Useful for breakout pyramids:

```python
base_notional = ctx.investment_amount / ctx.max_layers
```

If investment is 1000 USDT and there are 4 layers, each layer is 250 USDT.

### 13.2 Mild Geometric Layers

Useful for Bollinger mean reversion:

```python
weights = [ctx.layer_multiplier ** i for i in range(ctx.max_layers)]
base_notional = ctx.investment_amount / sum(weights)
layer_notional = base_notional * (ctx.layer_multiplier ** (layer - 1))
```

If investment is 1000 USDT, 4 layers, multiplier 1.25, weights are 1, 1.25, 1.56, and 1.95.

### 13.3 Layered Martingale

Useful for 5 layers and 3 child orders per layer:

```python
one_layer_weight = sum([ctx.martingale_multiplier ** i for i in range(ctx.orders_per_layer)])
total_weight = one_layer_weight * ctx.max_layers
base_notional = ctx.investment_amount / total_weight
child_notional = base_notional * (ctx.martingale_multiplier ** (order - 1))
```

If investment is 1000 USDT, 5 layers, 3 orders per layer, multiplier 1.8:

- One layer weight: `1 + 1.8 + 3.24 = 6.04`
- Total weight: `6.04 * 5 = 30.2`
- Base child order amount: `1000 / 30.2 = 33.11 USDT`
- Each layer has roughly `33.11 / 59.60 / 107.27 USDT`

This removes the conflict between "base order amount in code" and "investment amount in the run panel".

## 14. Signal Layer Design

Complex entries should usually be events, not persistent states.

Not recommended:

```python
if not has_position and fast > slow:
    open_position()
```

That condition remains true for many bars and relies on other guards to avoid repeated entry attempts.

Recommended:

```python
cross_up = prev_fast <= prev_slow and fast > slow
if not has_position and cross_up:
    open_position()
```

Common signal models:

- Trend: EMA cross, price crossing and confirming above/below a moving average.
- Breakout: close breaks the highest high or lowest low of the past N bars.
- Mean reversion: price touches an outer Bollinger band with RSI confirmation.
- Layered martingale: first order may start immediately or use a filter; later orders must be triggered by price distance only.

## 15. Risk Layer Design

Every complex strategy needs at least three types of risk control:

1. Structure risk: max layers, max child orders, one order per bar.
2. Price risk: hard stop, average-cost take profit, trailing stop, channel exit.
3. Time risk: cooldown, timeout exit, stale-state reset.

Example:

```python
if last_order_bar == bar_no:
    return

if layer >= ctx.max_layers and order >= ctx.orders_per_layer:
    # No more adds. Wait for take-profit or hard stop.
    return

if pnl <= -ctx.hard_stop_pct:
    basket.close_all(reason='hard_stop')
    _reset_cycle(ctx, bar_no + ctx.cooldown_bars)
    return
```

## 16. Pre-Backtest Checklist

Before running a complex script backtest, check:

- `on_init(ctx)` and `on_bar(ctx, bar)` are defined.
- No `getattr`, file, network, database, process, or other sandbox-blocked capability is used.
- Direction, market type, investment amount, and leverage are not defined as `ctx.param`.
- Percent parameters in Python are 0-1 ratios.
- Every add has max count and price distance.
- Every order has a same-bar duplicate guard.
- Order sizing is derived from `ctx.investment_amount`.
- Orders use `basket.open_child_order(..., notional=...)` for quote amount sizing.
- State is reset after take-profit/stop and cooldown is set.
- Every state variable can be explained.

## 17. Pre-Live Checklist

A successful backtest does not mean the script is ready for live trading. Also check:

- Spot scripts only run long.
- Contract leverage fits exchange limits.
- Investment amount can cover the maximum planned layers.
- Max order count does not violate exchange rate limits or minimum order size.
- Hard stop exists and is not so wide that it is meaningless.
- Account-level risk controls, notifications, and emergency stop are configured.
- The script has completed at least one full open/add/close cycle with small capital or demo trading.

## 18. AI Assistant Prompt Examples

When asking AI to generate complex script code, state the boundary explicitly:

```text
Write a QuantDinger script code:
1. Use on_init/on_bar.
2. The run panel owns symbol, spot/swap, direction, investment amount, and leverage. Do not create ctx.param for these.
3. Use ctx.basket(side).open_child_order(..., notional=...) for orders.
4. Split the investment amount into 5 layers, 3 child orders per layer, martingale multiplier 1.8.
5. Use child-order spacing, average-cost take profit, hard stop, and same-bar duplicate protection.
6. Do not use getattr, file/network/database APIs, or unsafe imports.
```

When modifying an existing template:

```text
Based on the current template, only adjust parameters and risk controls. Do not change the run-panel boundary.
Change take-profit to 0.8%, make inter-layer spacing grow with depth, and add a 12% hard stop.
```

## 19. Minimal Skeleton

```python
"""
My Script Strategy
"""

def on_init(ctx):
    ctx.lookback = ctx.param('lookback', 20)
    ctx.take_profit_pct = ctx.param('take_profit_pct', 0.01)

def _side(ctx):
    try:
        direction = str(ctx.direction)
    except Exception:
        direction = 'long'
    return 'short' if direction.lower() == 'short' else 'long'

def on_bar(ctx, bar):
    bars = ctx.bars(ctx.lookback + 1)
    if len(bars) < ctx.lookback + 1:
        return

    side = _side(ctx)
    price = float(bar['close'])
    basket = ctx.basket(side)

    # Add entry, state, risk, and exit logic here.
```
