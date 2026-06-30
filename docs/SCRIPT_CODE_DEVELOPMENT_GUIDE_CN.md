# QuantDinger 脚本代码开发指南

本文说明如何编写可回测、可实盘、可维护的 QuantDinger 脚本代码。脚本代码适合有运行状态的策略，例如分层建仓、篮子均价止盈、追踪止损、金字塔加仓、冷却期、重复下单防护等。

## 1. 核心边界

脚本代码只负责策略逻辑。用户运行时填写的内容不应该再写进代码参数。

运行面板负责：

- 标的，例如 BTC/USDT
- 市场类型，现货或合约
- 交易方向，做多、做空或双向
- 投入金额
- 合约杠杆
- 账户、通知、实盘风控开关

脚本代码负责：

- 入场条件
- 加仓、减仓、止盈、止损规则
- 分层数量、间距、倍数、周期、冷却期
- 状态持久化和防重复下单
- 日志与篮子状态 checkpoint

不要在脚本中写：

```python
ctx.param('direction', 'long')
ctx.param('market_type', 'swap')
ctx.param('investment_amount', 1000)
ctx.param('leverage', 3)
ctx.param('base_notional', 50)
```

这些值应由运行面板传入，可在脚本中读取：

```python
direction = ctx.direction
market_type = ctx.market_type
budget = ctx.investment_amount
leverage = ctx.leverage
```

## 2. 生命周期

脚本必须包含：

```python
def on_init(ctx):
    pass

def on_bar(ctx, bar):
    pass
```

`on_init(ctx)` 在脚本启动时执行一次，用于读取策略参数和初始化默认值。

`on_bar(ctx, bar)` 每根 K 线执行一次。当前统一使用 1m K 线作为脚本粒度；实盘还会每 10 秒检查一次最新价格，用于降低止盈止损响应延迟。回测只基于历史 K 线，因此极高频 tick 级逻辑不应该写在脚本里。

`bar` 支持：

```python
bar['open']
bar['high']
bar['low']
bar['close']
bar['volume']
bar['timestamp']
```

## 3. 参数设计

只把策略结构参数放进 `ctx.param(...)`：

```python
def on_init(ctx):
    ctx.fast_period = ctx.param('fast_period', 12)
    ctx.slow_period = ctx.param('slow_period', 36)
    ctx.take_profit_pct = ctx.param('take_profit_pct', 0.006)
    ctx.max_layers = ctx.param('max_layers', 5)
```

百分比默认值在 Python 里使用 0-1 小数：

- `0.006` 表示 0.6%
- `0.02` 表示 2%
- `0.8` 表示 80%

前端可以用 0-100 的显示方式，但写回代码时应保持 Python 小数。

## 4. 投入金额和下单金额

推荐所有状态型脚本使用 `ctx.basket(side).open_child_order(..., notional=quote_amount)`。

`notional` 表示计价货币金额，例如 USDT 金额。回测和实盘会根据市场类型、价格和杠杆换算为实际下单数量。

示例：

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

不要把“基础下单金额”作为模板参数暴露给用户。更清晰的模型是：用户填投入金额，脚本根据层数、倍数和总权重自动拆分每个子单的计划金额。

## 5. 方向处理

方向由运行面板选择。脚本只读取，不写死。

推荐写法：

```python
def _side(ctx):
    try:
        direction = str(ctx.direction)
    except Exception:
        direction = 'long'
    return 'short' if direction.lower() == 'short' else 'long'
```

现货只能做多；这个限制由运行面板和执行层处理。脚本里不需要再做一套复杂分支。

## 6. 状态管理

有分层、篮子、冷却期的策略必须使用 `ctx.state`。

常见状态：

- 当前层数：`layer`
- 当前子单：`order`
- 均价：`avg_cost`
- 总数量：`qty`
- 下一次触发价格：`next_trigger`
- 冷却到哪根 K 线：`cooldown_until`
- 上次下单 K 线：`last_order_bar`

示例：

```python
bar_no = int(ctx.current_index)
last_order_bar = int(ctx.state.get('last_order_bar', -999999) or -999999)
if last_order_bar == bar_no:
    return

ctx.state.set('last_order_bar', bar_no)
```

这样可以防止同一根 K 线重复发单。

## 7. Basket API

`ctx.basket(side)` 适合所有有篮子概念的策略。

常用方法：

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

`checkpoint` 用于展示策略当前状态：

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

## 8. 回测和实盘对齐

脚本回测和实盘使用同一套 `on_init/on_bar` 语义。需要注意：

- 回测基于历史 K 线，不模拟每 10 秒 tick 细节。
- 实盘会额外拉取最新价格用于更及时地检查价格条件。
- 下单金额建议使用 basket `notional`，这样合约杠杆在回测和实盘中口径一致。
- 策略不能依赖未来数据，只能使用 `ctx.bars(n)` 获取当前及历史 K 线。
- 每次加仓必须有价格间距、最大层数和防重复下单。

## 9. 沙箱限制

脚本在安全沙箱中执行。不要使用：

- `getattr`、`setattr`、`delattr`
- `eval`、`exec`、`open`、`compile`
- `globals`、`vars`、`dir`
- `__builtins__`、dunder 属性
- 文件、网络、数据库、进程、线程相关 API
- `os`、`sys`、`requests`、`urllib`、`socket`、`subprocess`、`threading`、`multiprocessing`、`sqlite3`、`psycopg`、`sqlalchemy`、`pathlib`、`tempfile`、`glob`、`io`、`operator`、`pickle`、`ctypes`

读取可选字段时，用 `try/except` 直接访问：

```python
try:
    direction = str(ctx.direction)
except Exception:
    direction = 'long'
```

不要写：

```python
direction = getattr(ctx, 'direction', 'long')
```

## 10. 推荐模板类型

经典可落地的脚本模板包括：

- EMA ATR 趋势风控：趋势跟随、ATR 止损、ATR 追踪止损。
- Donchian 突破金字塔：通道突破入场，盈利后顺势加仓。
- 布林均值回归篮子：触及布林外轨后分层建仓，均价回归止盈。
- 阶梯分仓马丁篮子：多层分仓、子单马丁、均价止盈、硬止损。

这些模板覆盖趋势、突破、震荡均值回归和高风险篮子模型，避免把多个相似的“加仓模板”重复展示给用户。

## 11. 复杂策略的推荐架构

复杂脚本不要写成一大坨 `if/else`。推荐拆成五层：

1. 信号层：判断是否允许入场、是否允许加仓、是否应该退出。
2. 资金层：把运行面板的投入金额拆成每一层、每一单的计划金额。
3. 状态层：保存当前阶段、层数、子单、均价、触发价、冷却期。
4. 执行层：只负责发出 `basket.open_child_order` 或 `basket.close_all`。
5. 风控层：硬止损、最大层数、最大订单数、冷却期、同 K 线防重复。

推荐文件结构虽然仍然是一个脚本，但代码内部应保持这种顺序：

```python
def on_init(ctx):
    # 1. 读取策略参数
    pass

def _side(ctx):
    # 2. 读取运行面板方向
    pass

def _run_budget(ctx):
    # 3. 读取运行面板投入金额
    pass

def _planned_notional(ctx, layer, order):
    # 4. 计算每一单计划金额
    pass

def _entry_signal(ctx, bar, bars):
    # 5. 入场信号
    pass

def _risk_exit(ctx, price, avg_cost):
    # 6. 风控退出
    pass

def _place_child(ctx, basket, layer, order, price, action):
    # 7. 发单并更新状态
    pass

def on_bar(ctx, bar):
    # 8. 主流程，只编排，不塞复杂公式
    pass
```

这样用户后续加新条件、换资金模型、换退出逻辑时，不需要重写整份策略。

## 12. 状态机模型

复杂策略应该先设计状态机。推荐状态：

| 状态 | 含义 | 允许动作 |
| --- | --- | --- |
| `idle` | 空仓等待 | 判断入场 |
| `opening` | 已开首单或正在建仓 | 加仓、止盈、止损 |
| `active` | 仓位完整运行中 | 止盈、止损、追踪退出 |
| `closing` | 已触发平仓 | 等待执行层完成 |
| `cooldown` | 平仓后冷却 | 不允许重新入场 |

脚本里可以不用显式保存字符串状态，但逻辑上必须有这套概念。最少要保存：

```python
ctx.state.set('layer', layer)
ctx.state.set('order', order)
ctx.state.set('avg_cost', avg_cost)
ctx.state.set('qty', qty)
ctx.state.set('next_trigger', next_trigger)
ctx.state.set('cooldown_until', cooldown_until)
ctx.state.set('last_order_bar', bar_no)
```

主流程建议固定为：

```python
def on_bar(ctx, bar):
    # 1. 数据不足直接返回
    # 2. 读取运行面板方向、价格、状态
    # 3. 如果空仓，检查是否需要重置状态
    # 4. 如果冷却中，直接返回
    # 5. 如果空仓，判断入场
    # 6. 如果持仓，先判断止盈/止损
    # 7. 如果仍持仓，再判断加仓
    # 8. 发单后更新 checkpoint 和 state
```

不要先加仓再判断止损。复杂策略里这个顺序很重要。

## 13. 资金拆分模型

用户只填一个“投入金额”。脚本需要根据策略结构拆分每个子单。

### 13.1 等额分层

适合突破金字塔：

```python
base_notional = ctx.investment_amount / ctx.max_layers
```

如果投入 1000 USDT、4 层，则每层 250 USDT。

### 13.2 温和递增分层

适合布林均值回归：

```python
weights = [ctx.layer_multiplier ** i for i in range(ctx.max_layers)]
base_notional = ctx.investment_amount / sum(weights)
layer_notional = base_notional * (ctx.layer_multiplier ** (layer - 1))
```

如果投入 1000 USDT、4 层、倍数 1.25，则每层按权重 1、1.25、1.56、1.95 拆分。

### 13.3 分仓马丁

适合 5 个分仓、每仓 3 单：

```python
one_layer_weight = sum([ctx.martingale_multiplier ** i for i in range(ctx.orders_per_layer)])
total_weight = one_layer_weight * ctx.max_layers
base_notional = ctx.investment_amount / total_weight
child_notional = base_notional * (ctx.martingale_multiplier ** (order - 1))
```

如果投入金额是 1000 USDT、5 层、每层 3 单、倍数 1.8：

- 单层权重：`1 + 1.8 + 3.24 = 6.04`
- 总权重：`6.04 * 5 = 30.2`
- 基础子单金额：`1000 / 30.2 = 33.11 USDT`
- 每层三单约为：`33.11 / 59.60 / 107.27 USDT`

这能避免“代码里写了基础下单金额，用户又填投入金额”的冲突。

## 14. 信号层设计

复杂策略的入场信号最好是“事件”，不是“状态”。

不推荐：

```python
if not has_position and fast > slow:
    open_position()
```

这样会在趋势状态持续时频繁尝试入场，必须依赖其他防线兜底。

推荐：

```python
cross_up = prev_fast <= prev_slow and fast > slow
if not has_position and cross_up:
    open_position()
```

常见信号模型：

- 趋势：EMA 金叉/死叉、价格突破均线并确认。
- 突破：当前收盘价突破过去 N 根最高/最低。
- 均值回归：价格触及布林带外轨，并用 RSI 过滤极端状态。
- 分仓马丁：首单可以无信号启动，也可以加趋势/震荡过滤；后续加仓只能由价格间距触发。

## 15. 风控层设计

复杂策略必须至少有三类风控：

1. 结构风控：最大层数、每层最大子单数、单 K 线只允许一次下单。
2. 价格风控：硬止损、均价止盈、追踪止损、通道退出。
3. 时间风控：冷却期、超时退出、长时间未成交后的状态重置。

示例：

```python
if last_order_bar == bar_no:
    return

if layer >= ctx.max_layers and order >= ctx.orders_per_layer:
    # 不再继续加仓，只等待止盈或硬止损
    return

if pnl <= -ctx.hard_stop_pct:
    basket.close_all(reason='hard_stop')
    _reset_cycle(ctx, bar_no + ctx.cooldown_bars)
    return
```

## 16. 回测前检查清单

用户写完复杂脚本后，先检查：

- 是否定义了 `on_init(ctx)` 和 `on_bar(ctx, bar)`。
- 是否没有使用 `getattr`、文件、网络、数据库、进程等沙箱禁止能力。
- 是否没有把方向、市场类型、投入金额、杠杆写成 `ctx.param`。
- 是否所有百分比参数在代码里都是 0-1 小数。
- 是否所有加仓都有最大次数和价格间距。
- 是否所有发单都有同 K 线防重复。
- 是否下单金额来自 `ctx.investment_amount` 的拆分。
- 是否使用 `basket.open_child_order(..., notional=...)` 表示计价金额。
- 是否在止盈/止损后重置状态并进入冷却。
- 是否能解释每一个状态变量的含义。

## 17. 实盘前检查清单

回测通过不等于可以直接实盘。实盘前还要检查：

- 现货策略是否只做多。
- 合约策略的杠杆是否符合交易所限制。
- 投入金额是否足够覆盖最大计划层数。
- 最大单数是否会超过交易所限频或最小下单金额限制。
- 硬止损是否存在，且不是过大到没有意义。
- 是否设置了账户级风控、通知和异常停机策略。
- 是否用小金额或模拟盘跑过至少一个完整开仓、加仓、平仓周期。

## 18. AI 助手提示词建议

让 AI 生成复杂脚本时，提示词要明确边界。推荐这样写：

```text
写一个 QuantDinger 脚本代码：
1. 使用 on_init/on_bar。
2. 运行面板负责标的、现货/合约、方向、投入金额和杠杆，代码里不要写成 ctx.param。
3. 使用 ctx.basket(side).open_child_order(..., notional=...) 下单。
4. 投入金额按 5 层、每层 3 单、马丁倍数 1.8 自动拆分。
5. 每个子单之间有价格间距，均价止盈，硬止损，同 K 线防重复。
6. 不要使用 getattr、文件、网络、数据库、导入危险模块。
```

如果要改现有模板，建议说：

```text
基于当前模板，只调整参数和风控，不要改变运行面板边界。
把止盈改为 0.8%，层间距改成逐层扩大，最大亏损 12% 硬止损。
```

## 19. 最小骨架

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
