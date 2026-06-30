# ScriptStrategy 复杂策略运行时改造实施方案

## 1. 目标

让脚本策略从“按 K 线生成买卖信号”升级为“可承载复杂状态机和算法执行”的运行时，优先支持以下用户场景：

- 多层分仓，例如 5 个大分仓，每层 3 个子单。
- 层内/层间价格间距可调。
- 每个子单按马丁倍数或自定义序列放大。
- 按实际成交均价止盈，而不是按脚本计划价止盈。
- 只做多、只做空、多空双向 basket 独立运行。
- 合约场景支持按杠杆后的名义价值换算下单量。
- 后端重启、网络失败、部分成交、拒单后不重复补仓。

核心判断：现在的脚本 API 已经有基础，真正要补的是可信状态源、订单生命周期、恢复和风控。先把运行时地基打牢，再开放更复杂模板。

## 2. 当前代码基础

现有链路已经可复用：

- `app/services/strategy_script_runtime.py`
  - `StrategyScriptContext` 已支持 `open_long/add_long/open_short/add_short/close_long/close_short`。
  - `ScriptPosition` 已有 long/short 独立腿，并保留旧版 net position 兼容视图。
- `app/services/trading_executor.py`
  - 脚本产生 `ctx._orders` 后转成执行信号。
  - `_enqueue_pending_order()` 写入 `pending_orders`。
  - `_hydrate_script_ctx_from_positions()` 会从 `qd_strategy_positions` 恢复持仓视图。
- `app/services/pending_order_worker.py`
  - `PendingOrderWorker` 拉取 `pending_orders`，执行 live/signal 模式派单。
  - 已有 live order context、client order id、成交回填等基础。
- `app/services/pending_orders/fill_records.py`
  - `persist_strategy_fill()` 按成交更新 `qd_strategy_trades` 和 `qd_strategy_positions`。
- `app/services/live_trading/records.py`
  - `apply_fill_to_local_position()` 已经按成交更新均价和部分减仓。
- `migrations/init.sql`
  - 已有 `pending_orders`、`qd_strategy_positions`、`qd_strategy_trades`、`qd_grid_resting_orders` 等基础表。

现有不足：

- `pending_orders` 更像队列表，不是完整 order intent ledger。
- `script_runtime_state` 存在 `trading_config` JSON 里，适合轻量参数，不适合作为复杂策略状态可信源。
- 缺少 `strategy_run_id`、代码快照、参数快照和运行 epoch。
- 缺少 basket / child order / fill / recovery event 的标准模型。
- 多空 position API 已具备雏形，但 basket 层还没独立。
- 订单幂等当前主要靠 `(strategy_id, symbol, signal_type, signal_ts)`，不够表达层级分仓的 `layer/order/action`。
- 回测还没有完全复用 live 的 order intent、fill、fee、slippage 语义。

## 3. 总体架构

建议增加一层“策略运行时内核”，位于脚本和下单队列之间：

```text
ScriptStrategy
  -> StrategyRuntimeContext
  -> BasketRuntime / RuntimeStateStore
  -> OrderIntentService
  -> ExecutionScheduler
  -> PendingOrderWorker / LiveTradingClient
  -> FillLedger / PositionLedger
  -> RecoveryService / RiskGuard
```

原则：

- 脚本只表达意图和状态机，不直接操作数据库和交易所。
- 数据库是恢复可信源，内存只做当前循环缓存。
- 所有真实下单先落 `order_intent`，再提交交易所。
- basket 均价、层级、TP、风险状态由实际 fill 驱动。
- live、paper、backtest 尽量复用同一套 order intent 和 fill 语义。

## 4. 数据库改造

新增表建议：

```sql
strategy_runs
strategy_runtime_state
strategy_baskets
strategy_basket_orders
strategy_order_intents
strategy_order_fills
strategy_runtime_events
strategy_runtime_locks
```

### 4.1 strategy_runs

记录每一次启动，不再只靠 `strategy_id` 表示运行实例。

关键字段：

- `id`
- `strategy_id`
- `user_id`
- `source_version_id`
- `code_hash`
- `parameter_snapshot_json`
- `exchange_id`
- `credential_id`
- `symbol`
- `market_type`
- `position_mode`
- `runtime_status`: `running/recovering/paused/needs_review/stopping/stopped/failed`
- `runtime_epoch`
- `started_at`
- `stopped_at`
- `stop_reason`

### 4.2 strategy_runtime_state

替代把复杂状态塞进 `trading_config.script_runtime_state`。

关键字段：

- `strategy_run_id`
- `strategy_id`
- `state_key`
- `state_json`
- `version`
- `updated_at`

用途：

- 保存轻量脚本状态：冷却计数、上次触发价、用户自定义变量。
- 由运行时托管 `ctx.state.get/set/flush()`。
- 不保存成交和订单真相。

### 4.3 strategy_baskets

复杂分仓策略的核心状态。

关键字段：

- `basket_id`
- `strategy_run_id`
- `strategy_id`
- `symbol`
- `side`: `long/short`
- `status`: `idle/opening/active/closing/closed/failed/needs_review`
- `current_layer`
- `current_order_in_layer`
- `total_qty`
- `total_notional`
- `avg_entry_price`
- `next_entry_trigger`
- `take_profit_price`
- `max_layer`
- `max_orders_per_layer`
- `risk_state_json`
- `created_at`
- `updated_at`

### 4.4 strategy_basket_orders

记录每个子单在 basket 内的归属。

关键字段：

- `basket_order_id`
- `basket_id`
- `side`
- `layer_index`
- `order_index`
- `action`: `open/add/reduce/close`
- `planned_price`
- `planned_qty`
- `planned_notional`
- `status`: `planned/intent_created/submitted/accepted/partially_filled/filled/rejected/cancelled/expired/unknown`
- `order_intent_id`
- `exchange_order_id`
- `client_order_id`
- `filled_qty`
- `avg_fill_price`
- `fee`
- `error`

唯一约束：

```text
strategy_run_id + basket_id + side + layer_index + order_index + action
```

### 4.5 strategy_order_intents

统一订单意图。后续 TWAP、BestLimit、Iceberg 都从这里开始。

关键字段：

- `order_intent_id`
- `strategy_run_id`
- `strategy_id`
- `basket_id`
- `basket_order_id`
- `idempotency_key`
- `symbol`
- `market_type`
- `side`
- `position_side`
- `reduce_only`
- `order_type`
- `quantity`
- `notional`
- `limit_price`
- `execution_algo`: `market/limit/best_limit/twap/stop/iceberg`
- `status`
- `client_order_id`
- `exchange_order_id`
- `payload_json`
- `created_at`
- `updated_at`

### 4.6 strategy_order_fills

成交流水是均价、TP 和审计的真实来源。

关键字段：

- `fill_id`
- `order_intent_id`
- `basket_id`
- `exchange_order_id`
- `exchange_fill_id`
- `side`
- `position_side`
- `price`
- `quantity`
- `notional`
- `fee`
- `fee_ccy`
- `filled_at`
- `raw_json`

唯一约束：

```text
exchange_id + exchange_fill_id
```

没有交易所 fill id 的场景，用 `order_intent_id + price + quantity + filled_at` 做近似去重。

## 5. 运行时 API 改造

保留现有 `ctx.open_long()` 等 API，同时新增更适合复杂策略的托管接口。

### 5.1 ctx.state

```python
ctx.state.get("cooldown_bars", 0)
ctx.state.set("cooldown_bars", 3)
ctx.state.flush()
```

用途：

- 轻量脚本变量。
- 自动绑定 `strategy_run_id`。
- 后端定期或关键动作前 checkpoint。

### 5.2 ctx.basket

```python
long_basket = ctx.basket("long")

if long_basket.is_idle():
    long_basket.open_child_order(layer=1, order=1, notional=100)

if long_basket.should_add(current_price):
    long_basket.open_child_order(layer=2, order=1, notional=200)

if long_basket.should_take_profit(current_price):
    long_basket.close_all(reason="avg_take_profit")
```

运行时负责：

- 检查幂等键。
- 创建 `strategy_basket_orders`。
- 创建 `strategy_order_intents`。
- 将 intent 推进到 `pending_orders` 或算法调度器。
- 成交后刷新 basket 均价、TP、层级和风险状态。

### 5.3 ctx.long_position / ctx.short_position

`ctx.position` 保持兼容，新增更明确接口：

```python
ctx.long_position.size
ctx.long_position.avg_entry
ctx.short_position.size
ctx.short_position.avg_entry
```

多空双开时，脚本不能再依赖单一 net position 判断。

## 6. LayeredMartingaleBasket 官方模板

先内置一个官方模板，不先开放用户自由组合所有底层能力。

参数：

```text
symbol
direction: long | short | both
base_order_value
leverage
layers = 5
orders_per_layer = 3
martingale_multiplier = 2.0
intra_spacing_pct
inter_spacing_pct
take_profit_pct
max_total_notional
max_margin_pct
hard_stop_pct
cooldown_bars
restart_after_take_profit
```

运行逻辑：

```text
idle:
  创建第 1 层第 1 子单

active:
  如果价格逆向达到层内/层间触发价，创建下一个子单
  如果实际成交均价达到 TP，close basket
  如果达到最大层数，只等 TP 或风险退出
  如果触发 hard stop / margin risk，停止补仓并按配置减仓或平仓
```

第一版限制：

- `direction=long` 或 `direction=short` 先稳定上线。
- `direction=both` 内部拆成 `long basket` 和 `short basket`，要求交易所能力矩阵确认 hedge mode。
- 不支持无限马丁，必须配置最大名义价值或最大保证金占用。

## 7. 订单生命周期改造

统一状态：

```text
intent_created
submitted
accepted
partially_filled
filled
rejected
cancelled
expired
unknown
reconciled
```

现有 `pending_orders.status` 可以继续承载队列阶段，但不要作为专业订单状态的唯一来源。

推荐落地方式：

1. `OrderIntentService.create_intent()` 先写 `strategy_order_intents`。
2. 根据 `execution_algo`：
   - `market/limit`：直接桥接到 `pending_orders`。
   - `twap/best_limit`：交给 `ExecutionScheduler` 拆 child order。
3. `PendingOrderWorker` 执行后回写 intent 状态和 fill。
4. `persist_strategy_fill()` 同步升级：除写 `qd_strategy_trades/positions` 外，也写 `strategy_order_fills` 并刷新 basket。

## 8. 幂等和单写入者

幂等键格式：

```text
strategy_run_id:basket_id:side:L{layer_index}:O{order_index}:{action}
```

策略运行锁：

```text
strategy_id + account_id/credential_id + symbol + side
```

机制：

- 启动策略时创建 `strategy_runs`，拿到 `runtime_epoch`。
- 每个运行线程写状态和订单时必须带 `runtime_epoch`。
- 新线程抢锁成功后，旧线程即使还活着，也因为 epoch 不匹配不能继续写库。
- 单机可先用数据库行锁；多实例部署再接 Redis lock + DB fencing token。

## 9. 重启恢复流程

启动或进程崩溃后恢复时：

1. 将 run 标记为 `recovering`。
2. 读取 `strategy_runs`、`strategy_runtime_state`、`strategy_baskets`、未完成 `strategy_order_intents`。
3. 拉取交易所当前持仓、未成交订单、近期成交。
4. 用交易所事实修正本地：
   - open order 状态。
   - filled quantity。
   - avg fill price。
   - basket avg entry。
   - pending TP/close 状态。
5. 对没有 `exchange_order_id` 的 intent 做幂等判断：
   - 确认未提交才允许重试。
   - 状态未知则进入 `needs_review`。
6. 重建 `ctx.state`、`ctx.basket`、`ctx.long_position/short_position`。
7. 写 `recovery_completed` 事件。
8. 切回 `running`。

恢复优先级：

```text
交易所事实 > strategy_order_fills/order_intents > basket checkpoint > 内存状态
```

## 10. 风控改造

新增 `StrategyRuntimeRiskGuard`，在创建 intent 前检查：

- 最大层数。
- 最大子单数。
- 最大名义价值。
- 最大保证金占用。
- 最大账户权益占比。
- 最大浮亏。
- 距离强平价格最小安全距离。
- 单策略最大错误次数。
- 单交易所/全局 kill switch。

触发后写事件：

```text
risk_guard_triggered
```

并进入以下之一：

- `paused`: 暂停新增开仓。
- `needs_review`: 状态不确定，需要人工确认。
- `stopping`: 自动减仓或平仓中。
- `failed`: 无法安全处理。

## 11. 算法交易第一版

新增目录：

```text
app/services/algo_trading/
  order_intent.py
  scheduler.py
  child_order.py
  execution_algorithms/
    twap.py
    best_limit.py
    stop.py
  order_state.py
  reconciliation.py
  risk.py
```

P0 支持：

- `MarketIntent`: 现有 market order 的标准化入口。
- `LimitIntent`: 限价单标准化入口。
- `BestLimit`: 使用 best bid/ask 挂单，超时撤单重挂。
- `TWAP`: 按时间切片拆成多个 child order。
- `Stop/StopLimit`: 交易所支持则原生，不支持则本地触发。

P1 再做：

- Iceberg。
- Sniper。
- 更细的 order book 驱动。

## 12. 交易所能力矩阵

现有 `app/services/live_trading/capabilities.py` 只有市场类型能力，需要扩展为：

```text
supports_hedge_mode
supports_reduce_only
supports_post_only
supports_stop_order
supports_iceberg
supports_client_order_id
supports_order_query_by_client_id
supports_fills_query
min_notional
min_quantity
price_tick
quantity_step
rate_limit
```

策略启动前做 preflight：

- 交易所是否支持该 market type。
- 是否支持 hedge mode。
- API key 是否有交易、订单查询、成交查询权限。
- 合约杠杆和保证金模式是否可配置。
- symbol 精度和最小下单量是否满足模板参数。

失败时不启动策略，给用户明确错误。

## 13. 回测一致性

复杂策略不能只靠布尔信号回测。建议新增运行时回测模式：

```text
ScriptStrategy -> RuntimeContext(backtest) -> OrderIntentService(backtest) -> SimulatedFillEngine -> BasketRuntime
```

模拟能力：

- 最小下单量。
- 数量步进。
- 价格 tick。
- 手续费。
- 滑点。
- 部分成交。
- 下根 K 成交 / 当前 tick 成交差异。
- 子单级成交记录。

验收目标：

- 同一份 `LayeredMartingaleBasket` 模板在 backtest/paper/live 中的子单路径一致。
- 回测报告能展示每层、每个子单、均价、TP、费用和滑点。

## 14. 前端需要配合的能力

第一版 UI 不要让用户直接编辑底层 runtime 表，而是提供模板化表单：

- 方向：只做多 / 只做空 / 多空双向。
- 分仓层数。
- 每层子单数。
- 层内间距。
- 层间间距。
- 马丁倍数或自定义序列。
- 基础下单金额。
- 杠杆。
- 均价止盈。
- 最大名义价值。
- 最大保证金占用。
- 硬止损。
- 启动前预估最大风险。

策略详情页增加：

- 当前 run id。
- 当前 basket 状态。
- 子单列表。
- 未完成订单。
- 最近成交。
- 恢复事件。
- 风控状态。
- `needs_review` 人工处理面板。

## 15. 分期落地

### Phase 0：补齐可追踪运行身份

目标：先让每次运行可追溯。

任务：

- 新增 `strategy_runs`。
- 启动策略时生成 `strategy_run_id`。
- 保存代码 hash、参数快照、交易所配置摘要。
- `pending_orders.payload_json` 增加 `strategy_run_id`。
- `qd_strategy_trades` 和 `qd_strategy_positions` 增加 `strategy_run_id` 可选字段。

验收：

- 任意一笔订单能追到哪次运行、哪版代码、哪组参数。

### Phase 1：Basket runtime MVP

目标：支持单向 `LayeredMartingaleBasket` 稳定运行。

任务：

- 新增 basket 表、basket order 表、runtime event 表。
- 实现 `ctx.state` 和 `ctx.basket(side)`。
- 实现 `BasketRuntime.open_child_order/close_all/checkpoint`。
- 实现幂等键和 DB 级唯一约束。
- 官方模板先支持 `long` 或 `short`。

验收：

- 5 层、每层 3 单能按配置触发。
- 重启后不会重复开同一个 layer/order。
- 均价止盈基于实际成交均价。

### Phase 2：Order intent 与成交驱动

目标：把 `pending_orders` 从唯一状态源降级为执行队列。

任务：

- 新增 `strategy_order_intents` 和 `strategy_order_fills`。
- `TradingExecutor._enqueue_pending_order()` 前置创建 intent。
- `PendingOrderWorker` 执行后回写 intent 和 fill。
- `persist_strategy_fill()` 刷新 basket 均价、TP 和状态。
- 部分成交不再误判为完整开仓。

验收：

- 部分成交后 basket 数量、均价、TP 正确。
- 拒单不修改 basket 为已开仓。
- 同一幂等键不会重复提交。

### Phase 3：恢复与 needs_review

目标：重启、网络失败、未知订单状态可控。

任务：

- 实现 `RecoveryService`。
- 启动策略前自动恢复 active run。
- 未知状态进入 `needs_review`。
- UI 提供同步交易所状态、继续观察、关闭 basket、强制停止。

验收：

- 发单后模拟进程崩溃，恢复后不重复下单。
- 交易所和本地不一致时不会继续补仓。

### Phase 4：多空双 basket

目标：安全开放 `direction=both`。

任务：

- `ctx.long_position/short_position` 正式化。
- `ctx.basket("long")` 和 `ctx.basket("short")` 独立持久化。
- preflight 检查交易所 hedge mode。
- 单写入锁按 `strategy_id + credential_id + symbol + side` 切分。

验收：

- long basket 和 short basket 可同时存在，互不覆盖均价和层级。
- 单向交易所不允许启动 both 模式。

### Phase 5：基础 AlgoTrading

目标：把复杂策略的“如何成交”从策略逻辑里抽出来。

任务：

- 实现 `BestLimit`。
- 实现 `TWAP`。
- 实现 `Stop/StopLimit`。
- 子单调度器支持撤单、重挂、超时和最大滑点。

验收：

- 同一个 basket 子单可选择 market、best_limit、twap 执行。
- 执行报告展示计划成交和实际成交差异。

## 16. 测试清单

必须新增的测试：

- `test_strategy_run_identity.py`
- `test_basket_runtime_state.py`
- `test_basket_order_idempotency.py`
- `test_basket_partial_fill_avg_price.py`
- `test_basket_rejected_order_state.py`
- `test_basket_restart_recovery.py`
- `test_basket_long_short_independent.py`
- `test_order_intent_lifecycle.py`
- `test_algo_twap_scheduler.py`
- `test_algo_best_limit.py`
- `test_exchange_capability_preflight.py`
- `test_backtest_live_basket_consistency.py`

重点场景：

- 同一根 K 线重复触发，不重复开同一子单。
- 写库成功但交易所提交超时，恢复时不盲目重发。
- 部分成交后按成交数量更新均价。
- 拒单后 basket order 为 rejected，不增加层级。
- 交易所最小下单量不足，策略进入 `needs_review` 或拒绝启动。
- 多空双开时 long/short basket 独立恢复。

## 17. 最小可交付版本

建议最小版本不要一口气做完整算法交易平台，先交付：

- `strategy_run_id`。
- `ctx.state`。
- `ctx.basket("long"|"short")`。
- `strategy_baskets` / `strategy_basket_orders`。
- order intent 幂等键。
- fill 驱动 basket 均价。
- `LayeredMartingaleBasket` 单向模板。
- 重启后不重复下单。

这一步完成后，已经可以覆盖用户最核心的“多层分仓 + 马丁 + 均价止盈 + 可恢复”诉求。随后再扩展多空双向和 TWAP/BestLimit，会稳很多。
