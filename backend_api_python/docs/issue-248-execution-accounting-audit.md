# Issue 248: execution accounting audit and repair

审计日期：2026-09-16。范围：仓库支持的 Binance、OKX、Bybit、Bitget、Gate、HTX、Alpaca、IBKR 的成交读取、单位转换、手续费、订单归属、持仓和成交入账。实现以代码和交易所官方 API 契约为依据。

## 已复现的根因

Issue 中 OKX 的 0.52 是合约张数，合约面值为 0.1 ETH，实际成交是 0.052 ETH。旧 WebSocket 路径把张数直接当成 ETH；REST 路径进行了换算，两条路径写入同一套本地账本，造成数量、成本和盈亏漂移。

用问题中的数据可精确复现平台错误值：

- 错误：`(2388.13 - 2376.11) * 0.52 - 0.02471154 - 0.06209138 = 6.16359708 USDT`。
- 正确数量：`(2388.13 - 2376.11) * 0.052 - 0.02471154 - 0.06209138 = 0.53823708 USDT`。

这解释了约十倍毛利润偏差。与交易所展示到分的数值完全核对，还需要对应成交明细；不能据此推断资金费、其他账户交易或其他费用。

## 本次修复

1. OKX、Gate、HTX 合约成交先按产品元数据换算为基础资产数量，再进入统一入账。元数据缺失、无效或不支持的反向合约不能默认按面值 1 记账。
2. REST 和私有事件统一按账本中已经入账的数量计算差额；增量成交价通过累计成交金额之差计算，不把累计均价当成本次成交价。限价转市价的多个交易所订单按各自范围合并。
3. 策略级事务锁覆盖成交明细、持仓、网格状态和消费游标；异常时一起回滚。重复、乱序、REST/WS 并发更新可重放。补挂单在数据库提交后执行，失败交由周期性挂单检查重试。
4. 累计手续费只补差额，保留币种、返佣和明确的零费用。多币种费用不直接相加。现货基础币扣费会减少本地库存；已成交但手续费延迟到达的网格订单仍参与对账。
5. 修复 HTX USDT 合约通知地址、现货认证字段和合约成交数组解析；过滤非交易事件和无成交数量的确认消息。修复 Bitget REST/WS 字段及费用符号差异、成交历史分页、订单数量误当成交数量的问题。
6. 修复 OKX REST 查询参数分派、Gate 股票 REST 分派、Gate 小数合约请求头；同一账户的网格客户端按策略、市场和标的隔离。订单绑定检查账户、交易所、市场及标的，防止串账。
7. Alpaca 股票/加密资产分别识别；累计成交与累计均价用于碎股入账。Alpaca 已完成但本地明细缺失的订单可重新对账。IBKR 延迟佣金回报保留独立去重；IBKR TWS 是 socket 回调，不是 WebSocket。
8. 持仓、成交及消费数量等数据库数值列扩展到 `NUMERIC(38,18)`，避免小额加密成交和碎股在持久化时被八位小数截断。应用层仍使用 float，不宣称任意精度运算。
9. 初始网格恢复不再用账户仓位变化和当前行情价伪造成交；必须查到策略订单的真实成交。存在尚未归属的新增仓位时阻止再次初始开仓。暂停开仓期间收到的已成交回报仍必须更新网格状态。
10. Gate 股票缺失成交均价时不使用委托价格替代；港股费用保留 HKD，不默认成 USD。

## 官方接口核对矩阵

以下链接为本次核对使用的官方来源。验证含义是文档契约检查与本地固定回报测试，不代表每个交易所都完成了真实账户下单验收。

| 接入 | REST 与私有推送的关键区别 | 本次处理及边界 | 官方依据 |
| --- | --- | --- | --- |
| Binance Spot / USD-M | Spot `z/l` 是累计/本次基础币数量，`Z/z` 是累计均价；USD-M 使用 `z/l/ap`，确认事件可能没有有效 trade ID | 保持基础币数量；过滤无成交确认；保留负佣金返佣 | [Spot REST](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/trade)、[Spot user data](https://github.com/binance/binance-spot-api-docs/blob/master/user-data-stream.md)、[USD-M stream schemas](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/ws-streams/~schemas) |
| OKX Spot / linear SWAP | SWAP `fillSz/accFillSz` 是张；`ctVal/ctMult/ctValCcy` 定义面值；`fillFee` 本次、`fee` 累计；费用支出为负值 | 转换张数一次；累计数量、金额及费用差额入账；拒绝不支持的反向单位 | [OKX API v5](https://www.okx.com/docs-v5/en/) |
| Bybit Spot / linear | `execQty/execFee` 为执行级；REST `cumExecQty/avgPrice/cumFeeDetail` 为订单累计；非 Trade 类型不等于成交 | 过滤执行类型；读取新费用映射及额外费用，保留币种；inverse 不套用 linear 模型 | [Execution](https://bybit-exchange.github.io/docs/v5/websocket/private/execution)、[Order](https://bybit-exchange.github.io/docs/v5/order/open-order) |
| Bitget Spot / USDT futures | Spot 订单 `size` 不是已成交基础币数量；合约 `baseVolume` 已是币；REST `totalFee` 支出为负，Spot fill WS 示例费用支出为正 | 不猜测合约倍数；订单、成交推送分别解析；多币种费用、零费用、返佣和分页保留 | [Spot REST](https://www.bitget.com/docs/catalog/classic-spot-trade/classic-spot-trade)、[Contract REST](https://www.bitget.com/docs/catalog/classic-contract-trade/classic-contract-trade)、[Spot fill WS](https://www.bitget.site/api-doc/spot/websocket/private/Fill-Channel)、[Contract fill WS](https://www.bitget.com/api-doc/classic/contract/websocket/private/Fill-Channel) |
| Gate Spot / USDT futures | Spot 成交为基础币；futures `size` 是合约量，乘 `quanto_multiplier`；小数 size 使用 `X-Gate-Size-Decimal: 1` | REST/WS 使用一致单位；保留多币种费用和真实零费用；客户端不跨市场复用 | [REST](https://www.gate.com/docs/developers/apiv4/en/)、[Spot WS](https://www.gate.com/docs/developers/apiv4/ws/en/)、[Futures WS](https://www.gate.com/docs/developers/futures/ws/en/) |
| Gate Direct Equity | `/stock/orders/history` 使用 `fill_volume/avg_fill_price/commission/quote_currency/status_desc` | 产品契约绑定股票客户端。`Crypto:00700/HKD@gate:spot`、`Crypto:AAPL/USD@gate:spot` 与普通证券标的分开；无官方证据证明普通 `spot.usertrades` 覆盖股票，股票以专用 REST 查询为依据，不能将普通现货 WS 健康视为股票推送验收通过 | [Gate Stock API](https://www.gate.com/docs/developers/apiv4/en/stock/) |
| HTX Spot / USDT swap | Spot `trade.clearing` 与 swap `matchOrders` 格式不同；swap `trade[]/trade_volume` 是张；使用全局成交 `id`；费用符号不同 | 修复数组、认证、USDT 通知地址、单位及费用符号；委托 volume 不作为已成交数量 | [Spot](https://huobiapi.github.io/docs/spot/v1/en/)、[USDT swap](https://huobiapi.github.io/docs/usdt_swap/v1/en/) |
| Alpaca US equities / crypto | `qty/price` 为事件级，`order.filled_qty/filled_avg_price` 为累计，`asset_class` 区分资产 | 碎股累计差额入账、按账户隔离、REST 兜底恢复 | [Trading stream](https://docs.alpaca.markets/us/docs/websocket-streaming)、[REST order](https://docs.alpaca.markets/us/reference/getorderbyorderid-1) |
| IBKR equities | execution `shares/price` 与 `cumQty/avgPrice` 分别为增量、累计，commission report 可能稍后到达 | 沿用 TWS 执行回调与订单对账适配，不将其描述为 WebSocket；延迟佣金独立去重 | [TWS execution](https://www.interactivebrokers.com/docs/tws-api/ref/execution) |

费用原币种明细作为核对依据；第三币种折算会使用现有换汇报价，基础币累计费用使用可用成交价，不能将其声称为逐笔历史汇率审计。

币本位/反向合约没有被扩展成新的受支持交易产品。账户级资金费、税费、借贷费用和分红也不等于订单佣金；不能通过修改成交佣金将其强行并入。

## REST 调度与限流

新增 `EXECUTION_FILL_SNAPSHOT_MIN_SEC=2`（同订单快照缓存间隔）和 `EXECUTION_FILL_SNAPSHOT_MAX_PER_MIN=30`（每个进程内交易所/凭据/市场的快照尝试上限）。它们仅约束私有事件需要补全成交快照的路径，不是交易所账户所有 HTTP 请求的总限额；一次快照可能调用订单和分页成交接口。网格及 pending worker 仍使用各自既有的审计间隔和请求预算。明确缺失的快照持久化退避重试，不用猜测数据记账。

## 验证

见提交工作区的 `tests/test_fill_accounting_contracts.py`、`tests/integration/test_grid_fill_accounting.py`、`tests/integration/test_execution_projection_atomic.py` 及相关回归测试。

- 实际 PostgreSQL 隔离 schema 测试，覆盖 Issue 248 数量与净利润、部分成交均价、手续费迟到、重复及并发 REST/WS、事务失败重放、网格单元写入失败、暂停开仓状态、碎股持久化。
- 官方字段 fixture 覆盖上述支持的接入类型及关键差异。
- 测试不连接用户交易账户、不发送真实订单。
- 提交前扩大验证：后端顶层 CI 测试、release gates 及本次 PostgreSQL 集成测试共 **2716 项通过、7 项跳过、23 项未选择**（85.84 秒）。7 项因 Windows 缺少 POSIX 能力或未安装 TA-Lib 跳过；23 项为 CI 默认排除的外部 integration / stress 测试。前端 **276 项单测通过**，生产构建通过。Ruff、Python 编译、仓库结构限制、依赖锁、文档和编码检查通过。
- 已修复部署遗漏：将 `20260916_fill_accounting.sql` 注册到正式 bootstrap 入口；在新测试数据库先建立旧结构，再通过 `python -m app.commands.migrate` 升级并重复执行，确认新字段及 18 位小数精度实际生效。
- PostgreSQL 成交事务测试已接入 `.github/workflows/basic-ci.yml`。核心成交回归清单见 `docs/issue-248-regression-tests.txt`；以上扩大验证还包含全部顶层测试及 release gates。真实账户沙盒/小额验收尚未执行。

## 部署和历史账本处理

1. 先保留数据库备份及问题策略的交易所原始订单/成交导出，避免丢失修复证据。
2. 在部署窗口停止旧版入账 worker，执行现有迁移入口 `python -m app.commands.migrate`（工作目录 `backend_api_python`），再启动新版 API/worker，并发布对应前端本地化资源。本次新增迁移为 `migrations/20260916_fill_accounting.sql`。数值列类型变更可能锁表，需按实际数据库大小安排窗口。本次仅在隔离测试数据库应用迁移。
3. 核对执行事件积压、错误及手续费 pending 状态；不能以页面显示零费用判定费用已到齐。
4. **历史已污染数据不会自动纠正。** 不能把全部历史记录统一除以 10，也不能清空消费记录后全量重放：不同合约面值不同，旧 REST/WS 可能交错且重复，已处理事件可能已产生后续订单。
5. 历史修复应按账户 + 市场 + 产品 + 交易所订单/成交 ID 导出并重建独立账本，复核数量、均价、原币种费用、仓位、网格状态及盈亏后，再准备限定策略和时间范围的迁移。本次未改写生产历史数据，也未改变用户正在运行的策略。

以下只读检查可以发现“订单观察数量与成交账本不一致”，但不能证明面值和全部历史成本正确。执行前将策略 ID 替换为实际待核对列表：

```sql
BEGIN READ ONLY;
SELECT po.strategy_id, po.id, po.exchange_id, po.credential_id, po.market_type,
       po.symbol, po.exchange_order_id, po.filled AS observed,
       COALESCE(SUM(t.amount), 0) AS posted
FROM pending_orders po
LEFT JOIN qd_strategy_trades t ON t.pending_order_id = po.id
WHERE po.strategy_id IN (123)
GROUP BY po.id
HAVING ABS(COALESCE(po.filled, 0) - COALESCE(SUM(t.amount), 0)) > 0.000000000001;
ROLLBACK;
```
