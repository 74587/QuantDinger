"""Shared safeguards for marketable limit prices."""

from __future__ import annotations


def is_marketable_limit_price(
    *,
    side: str,
    limit_price: float,
    reference_price: float,
) -> bool:
    """Return whether a limit would immediately cross the reference market."""
    price = float(limit_price or 0.0)
    reference = float(reference_price or 0.0)
    if price <= 0 or reference <= 0:
        return False
    normalized_side = str(side or "").strip().lower()
    if normalized_side == "buy":
        return price >= reference
    if normalized_side == "sell":
        return price <= reference
    return False


def normalize_marketable_limit_price(
    *,
    side: str,
    limit_price: float,
    reference_price: float,
) -> float:
    """Clamp a marketable limit to the reference without worsening its bound."""
    price = float(limit_price or 0.0)
    reference = float(reference_price or 0.0)
    if not is_marketable_limit_price(
        side=side,
        limit_price=price,
        reference_price=reference,
    ):
        return price
    return reference


def fetch_live_reference_price(client: object, *, symbol: str) -> float:
    """Fetch a best-effort current price from a live exchange client."""
    ticker = None
    getter = getattr(client, "get_ticker", None)
    if callable(getter):
        try:
            ticker = getter(symbol=str(symbol))
        except TypeError:
            ticker = None
        except Exception:
            ticker = None
    if isinstance(ticker, dict):
        for key in (
            "last",
            "lastPx",
            "lastPrice",
            "lastPr",
            "close",
            "markPrice",
            "mark_price",
            "price",
        ):
            try:
                value = float(ticker.get(key) or 0.0)
            except (TypeError, ValueError):
                value = 0.0
            if value > 0:
                return value
    mark_getter = getattr(client, "get_mark_price", None)
    if callable(mark_getter):
        try:
            value = float(mark_getter(symbol=str(symbol)) or 0.0)
        except Exception:
            value = 0.0
        if value > 0:
            return value
    return 0.0


__all__ = [
    "fetch_live_reference_price",
    "is_marketable_limit_price",
    "normalize_marketable_limit_price",
]
