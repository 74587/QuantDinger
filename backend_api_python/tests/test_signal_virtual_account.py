from types import SimpleNamespace

import pytest

from app.services import pending_order_worker as worker_module
from app.services.virtual_trading import calculate_virtual_fill, execute_virtual_signal_order
from app.services.virtual_execution_costs import (
    VIRTUAL_COMMISSION_RATE,
    VIRTUAL_SLIPPAGE_RATE,
    resolve_virtual_execution_cost_policy,
)


def test_virtual_fill_opens_adds_and_closes_long_position():
    opened = calculate_virtual_fill(
        action="open_long",
        requested_quantity=2,
        fill_price=100,
    )
    assert opened.status == "filled"
    assert opened.next_size == pytest.approx(2)
    assert opened.next_entry_price == pytest.approx(100)

    added = calculate_virtual_fill(
        action="add_long",
        requested_quantity=1,
        fill_price=130,
        current_size=opened.next_size,
        current_entry_price=opened.next_entry_price,
    )
    assert added.next_size == pytest.approx(3)
    assert added.next_entry_price == pytest.approx(110)

    closed = calculate_virtual_fill(
        action="close_long",
        requested_quantity=0,
        fill_price=120,
        current_size=added.next_size,
        current_entry_price=added.next_entry_price,
    )
    assert closed.fill_quantity == pytest.approx(3)
    assert closed.next_size == pytest.approx(0)
    assert closed.gross_realized_pnl == pytest.approx(30)


def test_virtual_fill_short_pnl_and_over_reduce_are_bounded():
    reduced = calculate_virtual_fill(
        action="reduce_short",
        requested_quantity=10,
        fill_price=80,
        current_size=2,
        current_entry_price=100,
    )
    assert reduced.fill_quantity == pytest.approx(2)
    assert reduced.next_size == pytest.approx(0)
    assert reduced.gross_realized_pnl == pytest.approx(40)


def test_virtual_fill_without_position_is_not_fabricated():
    result = calculate_virtual_fill(
        action="close_long",
        requested_quantity=0,
        fill_price=100,
    )
    assert result.status == "no_position"
    assert result.fill_quantity == 0
    assert result.gross_realized_pnl == 0


@pytest.mark.parametrize(
    ("exchange_id", "market_type"),
    [
        ("", "spot"),
        ("", "swap"),
        ("binance", "spot"),
        ("okx", "swap"),
        ("bybit", "spot"),
        ("bitget", "swap"),
        ("gate", "spot"),
        ("htx", "swap"),
    ],
)
def test_virtual_cost_policy_uses_fixed_rate_independent_of_venue_and_product(
    exchange_id,
    market_type,
):
    policy = resolve_virtual_execution_cost_policy(
        payload={"exchange_id": exchange_id, "market_type": market_type, "leverage": 10},
        strategy={"market_category": "Crypto"},
    )

    assert policy.commission_rate == pytest.approx(VIRTUAL_COMMISSION_RATE)
    assert policy.slippage_rate == pytest.approx(VIRTUAL_SLIPPAGE_RATE)
    assert policy.leverage == pytest.approx(10)


def test_virtual_fee_uses_executed_notional_without_double_counting_leverage():
    policy = resolve_virtual_execution_cost_policy(
        payload={"exchange_id": "binance", "market_type": "swap", "leverage": 10},
        strategy={"market_category": "Crypto"},
    )

    assert policy.commission_for(quantity=0.1, fill_price=100_000) == pytest.approx(5)
    assert policy.slippage_quote_for(
        quantity=0.1,
        reference_price=100_000,
        fill_price=100_050,
    ) == pytest.approx(5)


def test_virtual_cost_policy_does_not_invent_a_venue_when_strategy_has_none():
    policy = resolve_virtual_execution_cost_policy(
        strategy={"market_category": "Crypto", "market_type": "swap", "leverage": 3},
    )

    assert policy.exchange_id == ""
    assert policy.commission_rate == pytest.approx(VIRTUAL_COMMISSION_RATE)
    assert policy.leverage == pytest.approx(3)


def test_virtual_execution_rejects_live_mode_before_database_access():
    with pytest.raises(ValueError, match="virtualTrading.signalModeRequired"):
        execute_virtual_signal_order(
            {"id": 1, "user_id": 2, "strategy_id": 3, "execution_mode": "live"},
            {"execution_mode": "live"},
        )


def test_signal_dispatch_fills_virtual_account_without_live_execution(monkeypatch):
    from app.services import virtual_trading
    from app.services.strategy_runtime import cancellations

    virtual_calls = []
    sent = []
    monkeypatch.setattr(cancellations, "intercept_cancelled_dispatch", lambda row: False)
    monkeypatch.setattr(worker_module, "load_strategy_configs", lambda strategy_id: {"execution_mode": "signal"})
    monkeypatch.setattr(worker_module, "append_strategy_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        virtual_trading,
        "execute_virtual_signal_order",
        lambda row, payload: virtual_calls.append((row, payload)) or {
            "virtual_order_id": 91,
            "status": "filled",
            "fill_quantity": 2,
            "fill_price": 101,
        },
    )

    worker = object.__new__(worker_module.PendingOrderWorker)
    worker._notifier = SimpleNamespace(notify_signal=lambda **kwargs: {"browser": {"ok": True}})
    worker._load_strategy_name = lambda strategy_id: "Test"
    worker._load_notification_config = lambda strategy_id: {"browser": True}
    worker._mark_sent = lambda **kwargs: sent.append(kwargs)
    worker._mark_failed = lambda **kwargs: pytest.fail(str(kwargs))
    worker._execute_live_order = lambda **kwargs: pytest.fail("signal mode reached live execution")

    worker._dispatch_one({
        "id": 12,
        "user_id": 7,
        "strategy_id": 3,
        "strategy_run_id": 4,
        "execution_mode": "signal",
        "symbol": "BTC/USDT",
        "signal_type": "open_long",
        "amount": 2,
        "price": 100,
        "payload_json": (
            '{"strategy_id":3,"strategy_run_id":4,"execution_mode":"signal",'
            '"symbol":"BTC/USDT","signal_type":"open_long","amount":2,"price":100}'
        ),
    })

    assert len(virtual_calls) == 1
    assert sent[0]["final_filled"] is True
    assert sent[0]["filled"] == pytest.approx(2)
    assert sent[0]["avg_price"] == pytest.approx(101)


def test_live_dispatch_never_calls_virtual_account(monkeypatch):
    from app.services import virtual_trading
    from app.services.strategy_runtime import cancellations

    live_calls = []
    monkeypatch.setattr(cancellations, "intercept_cancelled_dispatch", lambda row: False)
    monkeypatch.setattr(
        virtual_trading,
        "execute_virtual_signal_order",
        lambda *args, **kwargs: pytest.fail("live mode reached virtual execution"),
    )
    worker = object.__new__(worker_module.PendingOrderWorker)
    worker._execute_live_order = lambda **kwargs: live_calls.append(kwargs)

    worker._dispatch_one({
        "id": 13,
        "user_id": 7,
        "strategy_id": 3,
        "execution_mode": "live",
        "symbol": "BTC/USDT",
        "signal_type": "open_long",
        "amount": 2,
        "price": 100,
        "payload_json": "{}",
    })

    assert len(live_calls) == 1
