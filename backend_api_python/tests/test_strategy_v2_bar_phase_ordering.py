import pandas as pd
import pytest

from app.services.strategy_v2 import StrategyV2BacktestRunner


SYMBOL = "Crypto:BTC/USDT@spot"


def _run(code, rows, frequency="1d"):
    frame = pd.DataFrame(
        rows,
        columns=["open", "high", "low", "close", "volume"],
        index=pd.date_range("2026-01-01", periods=len(rows), freq=frequency),
    )
    runner = StrategyV2BacktestRunner(
        code=code,
        frames={SYMBOL: frame},
        initial_capital=10_000,
        commission=0,
        slippage=0,
    )
    return runner, runner.run()


@pytest.mark.parametrize("frequency", ["1d", "4h"])
@pytest.mark.parametrize("callback", ["before_trading_start", "rebalance", "on_rebalance"])
@pytest.mark.parametrize(
    "high,low,protection,reason,exit_price",
    [
        (101, 90, "stop_loss_pct=0.05", "stop_loss", 95),
        (110, 99, "take_profit_pct=0.05", "take_profit", 105),
    ],
)
def test_opening_callback_entry_is_protected_on_its_entry_bar(
    frequency, callback, high, low, protection, reason, exit_price,
):
    schedule = '    run_daily(rebalance, time="00:00")' if callback == "rebalance" else ""
    code = f'''
def initialize(context):
    context.set_universe(["{SYMBOL}"])
    context.subscribe(frequency="{frequency}")
{schedule}

def {callback}(context, data):
    order("{SYMBOL}", 1, reason="opening_entry", {protection})

def handle_data(context, data):
    g.close_position = get_position("{SYMBOL}").amount
'''
    runner, result = _run(code, [(100, high, low, 100, 10000)], frequency)
    fills = [event for event in result["orderLedger"] if event["status"] == "filled"]
    assert [(event["reason"], event["price"]) for event in fills] == [
        ("opening_entry", 100), (reason, pytest.approx(exit_price)),
    ]
    assert fills[0]["eventTime"] == fills[1]["eventTime"]
    assert runner.program.state.close_position == 0
    assert result["positions"] == {}


def test_intrabar_stop_is_visible_at_close_but_cannot_trigger_same_open_reentry():
    code = f'''
def initialize(context):
    context.set_universe(["{SYMBOL}"])
    context.subscribe(frequency="1d")
    g.sent = False
    g.opening_positions = []
    g.closing_positions = []

def before_trading_start(context, data):
    g.opening_positions.append(get_position("{SYMBOL}").amount)
    reason = consume_last_exit_reason("{SYMBOL}")
    if reason:
        order("{SYMBOL}", 1, reason="reentry_after_" + reason)

def handle_data(context, data):
    g.closing_positions.append(get_position("{SYMBOL}").amount)
    if not g.sent:
        order("{SYMBOL}", 1, stop_loss_pct=0.05, reason="prior_close_entry")
        g.sent = True
'''
    runner, result = _run(code, [(100, 101, 90, 100, 10000)] * 3)
    fills = [event for event in result["orderLedger"] if event["status"] == "filled"]
    assert [(event["reason"], event["price"], event["eventTime"][:10]) for event in fills] == [
        ("prior_close_entry", 100, "2026-01-02"),
        ("stop_loss", 95, "2026-01-02"),
        ("reentry_after_stop_loss", 100, "2026-01-03"),
    ]
    assert runner.program.state.opening_positions == [0, 1, 0]
    assert runner.program.state.closing_positions == [0, 0, 1]


def test_close_callback_can_consume_stop_reason_and_queues_for_next_bar():
    code = f'''
def initialize(context):
    context.set_universe(["{SYMBOL}"])
    context.subscribe(frequency="1d")
    g.sent = False

def before_trading_start(context, data):
    if not g.sent:
        order("{SYMBOL}", 1, stop_loss_pct=0.05, reason="opening_entry")
        g.sent = True

def handle_data(context, data):
    reason = consume_last_exit_reason("{SYMBOL}")
    if reason:
        order("{SYMBOL}", 1, reason="close_reentry_after_" + reason)
'''
    _, result = _run(code, [(100, 101, 90, 100, 10000)] * 2)
    fills = [event for event in result["orderLedger"] if event["status"] == "filled"]
    assert [(event["reason"], event["eventTime"][:10]) for event in fills] == [
        ("opening_entry", "2026-01-01"),
        ("stop_loss", "2026-01-01"),
        ("close_reentry_after_stop_loss", "2026-01-02"),
    ]
