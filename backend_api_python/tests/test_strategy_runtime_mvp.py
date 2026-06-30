from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from app.services.backtest import BacktestService
from app.services.strategy_runtime.order_intents import OrderIntent, OrderIntentService
from app.services.strategy_runtime.state import RuntimeStateProxy
from app.services.strategy_script_runtime import StrategyScriptContext
from app.services.trading_executor import TradingExecutor


def _make_executor() -> TradingExecutor:
    return TradingExecutor.__new__(TradingExecutor)


@dataclass
class _MemoryStore:
    saved: dict | None = None

    def load(self):
        return {"cooldown": 1}

    def save(self, values):
        self.saved = dict(values)


def test_runtime_state_proxy_loads_sets_and_flushes():
    store = _MemoryStore()
    state = RuntimeStateProxy(store=store)

    assert state.get("cooldown") == 1
    state.set("cooldown", 3)
    state["last_price"] = 101.5
    state.flush()

    assert store.saved == {"cooldown": 3, "last_price": 101.5}


def test_order_intent_key_is_stable_for_basket_child_order():
    key1 = OrderIntentService.build_signal_idempotency_key(
        strategy_run_id=8,
        strategy_id=2,
        symbol="BTC/USDT",
        signal_type="add_long",
        signal_ts=0,
        basket_id="BTC/USDT:long",
        layer_index=2,
        order_index=3,
        action="add",
    )
    key2 = OrderIntentService.build_signal_idempotency_key(
        strategy_run_id=8,
        strategy_id=2,
        symbol="BTC/USDT",
        signal_type="add_long",
        signal_ts=123,
        basket_id="BTC/USDT:long",
        layer_index=2,
        order_index=3,
        action="add",
    )

    assert key1 == key2
    assert "L2:O3:add" in key1


def test_ctx_basket_open_child_order_emits_script_order(monkeypatch):
    def fake_create_intent(self, **kwargs):
        return OrderIntent(id=123, idempotency_key=kwargs["idempotency_key"], status="intent_created")

    monkeypatch.setattr(OrderIntentService, "create_intent", fake_create_intent)

    ctx = StrategyScriptContext(
        pd.DataFrame({"close": [100.0]}),
        1000.0,
        strategy_id=0,
        strategy_run_id=77,
        symbol="BTC/USDT",
    )
    result = ctx.basket("long").open_child_order(
        layer=2,
        order=3,
        notional=50,
        price=99.5,
        action="add",
    )

    assert result["order_intent_id"] == 123
    assert len(ctx._orders) == 1
    emitted = ctx._orders[0]
    assert emitted["intent"] == "add_long"
    assert emitted["action"] == "buy"
    assert emitted["strategy_run_id"] == 77
    assert emitted["basket_id"] == "BTC/USDT:long"
    assert emitted["layer_index"] == 2
    assert emitted["order_index"] == 3
    assert emitted["order_intent_id"] == 123
    assert emitted["idempotency_key"]
    assert emitted["script_quote_amount"] == 50


def test_script_context_exposes_simple_runtime_contract():
    ctx = StrategyScriptContext(
        pd.DataFrame({"close": [100.0]}),
        2500.0,
        symbol="BTC/USDT",
    )
    ctx.set_runtime_config({
        "runtime_contract_version": "simple_script_v1",
        "symbol": "BTC/USDT",
        "trade_direction": "short",
        "market_type": "swap",
        "leverage": 5,
        "investment_amount": 800,
        "timeframe": "1m",
        "tick_interval_sec": 10,
    })

    assert ctx.direction == "short"
    assert ctx.trade_direction == "short"
    assert ctx.market_type == "swap"
    assert ctx.leverage == 5
    assert ctx.investment_amount == 800
    assert ctx.runtime["timeframe"] == "1m"
    assert ctx.runtime["tick_interval_sec"] == 10


def test_script_context_limits_bars_per_call(monkeypatch):
    monkeypatch.setenv("STRATEGY_SCRIPT_MAX_BARS_PER_CALL", "3")
    df = pd.DataFrame(
        {
            "open": list(range(10)),
            "high": list(range(10)),
            "low": list(range(10)),
            "close": list(range(10)),
            "volume": [1.0] * 10,
        },
        index=pd.date_range("2026-06-01", periods=10, freq="min"),
    )
    ctx = StrategyScriptContext(df, 1000.0)
    ctx.current_index = 9

    bars = ctx.bars(999999)

    assert len(bars) == 3
    assert bars[0]["close"] == 7.0
    assert bars[-1]["close"] == 9.0


def test_script_context_limits_user_logs(monkeypatch):
    monkeypatch.setenv("STRATEGY_SCRIPT_MAX_LOGS_PER_FLUSH", "3")
    monkeypatch.setenv("STRATEGY_SCRIPT_MAX_LOG_CHARS", "8")
    ctx = StrategyScriptContext()

    ctx.log("123456789abcdef")
    ctx.log("second")
    ctx.log("third")
    ctx.log("fourth")
    logs = ctx.flush_logs()

    assert len(logs) == 3
    assert logs[0] == "12345678... [truncated]"
    assert logs[-1] == "ctx.log limit reached; further logs dropped (max=3 per flush)"
    assert ctx.flush_logs() == []


def test_script_order_runtime_metadata_survives_signal_conversion():
    ex = _make_executor()
    ctx = StrategyScriptContext(pd.DataFrame({"close": [100.0]}), 1000.0)
    ctx._orders.append(
        {
            "action": "buy",
            "intent": "open_long",
            "price": 100.0,
            "amount": 25.0,
            "strategy_run_id": 77,
            "basket_id": "BTC/USDT:long",
            "basket_order_db_id": 9,
            "order_intent_id": 123,
            "idempotency_key": "run:77:basket:BTC/USDT:long:L1:O1:open",
            "layer_index": 1,
            "order_index": 1,
        }
    )

    sigs = ex._script_orders_to_execution_signals(
        ctx,
        trade_direction="long",
        bar_close=100.0,
        closed_ts=pd.Timestamp("2026-06-30T00:00:00Z"),
        trading_config={"market_type": "swap", "leverage": 2, "bot_type": "martingale"},
    )

    assert len(sigs) == 1
    sig = sigs[0]
    assert sig["type"] == "open_long"
    assert sig["strategy_run_id"] == 77
    assert sig["basket_id"] == "BTC/USDT:long"
    assert sig["basket_order_db_id"] == 9
    assert sig["order_intent_id"] == 123
    assert sig["idempotency_key"] == "run:77:basket:BTC/USDT:long:L1:O1:open"
    assert sig["layer_index"] == 1
    assert sig["order_index"] == 1


def test_script_backtest_user_direction_is_outer_gate(monkeypatch):
    def fake_create_intent(self, **kwargs):
        return OrderIntent(id=123, idempotency_key=kwargs["idempotency_key"], status="intent_created")

    monkeypatch.setattr(OrderIntentService, "create_intent", fake_create_intent)

    df = pd.DataFrame(
        {
            "open": [100.0, 100.0],
            "high": [101.0, 101.0],
            "low": [99.0, 99.0],
            "close": [100.0, 100.0],
            "volume": [1.0, 1.0],
        },
        index=pd.date_range("2026-06-01", periods=2, freq="15min"),
    )
    code = """
def on_bar(ctx, bar):
    if int(ctx.current_index) == 0:
        ctx.basket('long').open_child_order(
            layer=1,
            order=1,
            notional=50,
            price=bar['close'],
            action='open',
        )
"""
    svc = BacktestService()
    signals = svc._execute_script_strategy(
        code,
        df,
        {
            "initial_capital": 1000,
            "leverage": 2,
            "trade_direction": "short",
            "strategy_config": {
                "market_type": "swap",
                "script_template_params": {"direction": "long"},
            },
        },
    )

    assert int(signals["open_long"].sum()) == 0
    assert float(signals["open_long_quote_amount"].sum()) == 0.0


def test_script_backtest_basket_quote_amount_sizes_trade(monkeypatch):
    def fake_create_intent(self, **kwargs):
        return OrderIntent(id=123, idempotency_key=kwargs["idempotency_key"], status="intent_created")

    monkeypatch.setattr(OrderIntentService, "create_intent", fake_create_intent)

    df = pd.DataFrame(
        {
            "open": [100.0, 100.0, 110.0],
            "high": [101.0, 101.0, 111.0],
            "low": [99.0, 99.0, 109.0],
            "close": [100.0, 100.0, 110.0],
            "volume": [1.0, 1.0, 1.0],
        },
        index=pd.date_range("2026-06-01", periods=3, freq="15min"),
    )
    code = """
def on_bar(ctx, bar):
    if int(ctx.current_index) == 0:
        ctx.basket('long').open_child_order(
            layer=1,
            order=1,
            notional=50,
            price=bar['close'],
            action='open',
        )
"""
    svc = BacktestService()
    signals = svc._execute_script_strategy(
        code,
        df,
        {
            "initial_capital": 1000,
            "leverage": 2,
            "trade_direction": "long",
            "strategy_config": {"market_type": "swap"},
        },
    )
    _, trades, _ = svc._simulate_trading(
        df,
        signals,
        1000,
        0,
        0,
        2,
        "long",
        {"market_type": "swap"},
    )

    assert trades[0]["type"] == "open_long"
    assert trades[0]["amount"] == 1.0
