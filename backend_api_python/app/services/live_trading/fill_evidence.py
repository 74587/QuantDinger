"""Execution evidence must never fall back to order instructions."""
from math import isfinite

from app.services.live_trading.base import LiveTradingError


def positive_number(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if isfinite(number) and number > 0 else None


def require_execution(quantity, price):
    if positive_number(quantity) is None or positive_number(price) is None:
        raise LiveTradingError("strategyRuntime.fillSnapshotNotReady")


def binance_execution_average(order):
    average = positive_number(order.get("avgPrice"))
    if average is not None:
        return average
    quantity = positive_number(order.get("executedQty"))
    quote = positive_number(order.get("cumQuote"))
    if quantity is not None and quote is not None:
        return positive_number(quote / quantity) or 0.0
    return 0.0
