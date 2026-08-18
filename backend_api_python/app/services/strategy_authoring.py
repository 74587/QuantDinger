"""Machine-readable Strategy API V2 authoring contract for external agents."""

from __future__ import annotations

from typing import Any

from app.services.ai_generation_contracts import SCRIPT_STRATEGY_SYSTEM_PROMPT


_STARTER_TEMPLATE = '''"""
Daily Moving Average Regime
Trades a long-only SPY regime from completed daily bars with bounded exposure.
"""

# @param period int 20 Moving-average period range=5:100:5
# @param target_pct float 0.5 Target portfolio weight range=0.1:1.0:0.05


def initialize(context):
    context.set_universe(["USStock:SPY"])
    context.subscribe(frequency="1d", fields=["close"])
    context.set_warmup(22)
    context.set_metadata(direction_mode="long_only", strategy_family="trend")


def handle_data(context, data):
    period = int(context.params.get("period", 20))
    target_pct = float(context.params.get("target_pct", 0.5))
    bars = get_history(period + 1, "1d", "close", "USStock:SPY")
    if len(bars) < period:
        return
    close = float(bars["close"].iloc[-1])
    average = float(bars["close"].tail(period).mean())
    order_target_percent("USStock:SPY", target_pct if close > average else 0.0)
'''

_MULTI_TIMEFRAME_TEMPLATE = '''"""
Three-Timeframe Trend Confirmation
Uses completed daily and four-hour trend filters with one-hour execution.
"""


def initialize(context):
    g.symbol = "Crypto:BTC/USDT@swap"
    context.set_universe([g.symbol])
    context.subscribe(frequency="1d")
    context.subscribe(frequency="4h")
    context.subscribe(frequency="1h")
    context.set_warmup(52)
    context.allow_leverage(max_leverage=5)


def handle_data(context, data):
    bars_1d = get_history(52, "1d", "close", g.symbol)
    bars_4h = get_history(52, "4h", "close", g.symbol)
    bars_1h = get_history(22, "1h", "close", g.symbol)
    if len(bars_1d) < 50 or len(bars_4h) < 50 or len(bars_1h) < 20:
        return
    daily_up = float(bars_1d["close"].tail(20).mean()) > float(bars_1d["close"].tail(50).mean())
    four_hour_up = float(bars_4h["close"].tail(20).mean()) > float(bars_4h["close"].tail(50).mean())
    hourly_trigger = float(bars_1h["close"].iloc[-1]) > float(bars_1h["close"].tail(20).mean())
    target = 0.5 if daily_up and four_hour_up and hourly_trigger else 0.0
    position = get_position(g.symbol)
    if (target > 0 and float(position.amount or 0.0) <= 0) or (target == 0 and float(position.amount or 0.0) != 0):
        order_target_percent(g.symbol, target, reason="three_timeframe_confirmation")
'''


def get_strategy_authoring_contract() -> dict[str, Any]:
    """Return the canonical source-ownership and runtime API contract."""
    return {
        "version": "strategy-api-v2-native-multitimeframe-2026-08",
        "doc": "docs/trading/STRATEGY_DEV_GUIDE.md",
        "workflow": [
            "1. Fetch this contract before generating Strategy API V2 source.",
            "2. Generate complete Python source; never send natural language as code.",
            "3. Compile with /api/agent/v1/strategy-sources/compile and repair every validation error.",
            "4. Save the validated draft with /api/agent/v1/strategy-sources.",
            "5. Backtest the saved or validated source before creating a stopped deployment.",
        ],
        "ownership": {
            "source": [
                "universe",
                "market",
                "instrument_type",
                "frequency",
                "frequencies",
                "subscriptions",
                "direction",
                "sizing",
                "entries",
                "exits",
                "risk",
                "schedules",
            ],
            "run_panel": ["initial_capital", "date_range", "permitted_swap_leverage"],
        },
        "required": [
            "A metadata docstring whose first non-empty line is the strategy name",
            "initialize(context) with context.set_universe(...) and one context.subscribe(...) call per used timeframe",
            "At least one executable handler or registered schedule callback",
            "Canonical instruments such as Crypto:SOL/USDT@spot or USStock:SPY",
        ],
        "forbidden": [
            "get_current_data; use data.current(symbol, field='close')",
            "Position.quantity or Position.cost_basis; use amount and avg_cost",
            "context.run_daily/context.run_weekly/context.run_monthly; schedule helpers are global",
            "context.params reads inside initialize(context)",
            "Run-panel overrides for symbol, market type, frequency, or leverage permission",
            "File, network, process, reflection, or dynamic execution APIs",
        ],
        "timeframes": {
            "native": ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"],
            "maximum_subscriptions": 8,
            "weekly_literal": "1w",
            "monthly_supported": False,
            "driver": "fastest subscribed timeframe",
            "higher_timeframe_visibility": "completed bars only",
            "rules": [
                "Preserve every timeframe explicitly requested by the user.",
                "Subscribe every timeframe read by history, current, indicator, or factor APIs.",
                "Never resample the driving frame to emulate a native higher timeframe.",
                "Guard each timeframe's returned history length independently.",
            ],
        },
        "system_contract": SCRIPT_STRATEGY_SYSTEM_PROMPT,
        "starter_template": _STARTER_TEMPLATE,
        "multi_timeframe_template": _MULTI_TIMEFRAME_TEMPLATE,
    }
