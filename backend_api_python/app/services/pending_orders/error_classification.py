"""Stable categories for exchange order failures shown to users and health checks."""

from __future__ import annotations

import re
from typing import Any


def is_exchange_price_band_error(error: Any) -> bool:
    """Recognize dynamic exchange price-band rejections across adapters."""
    lower = str(error or "").strip().lower()
    if not lower:
        return False
    price_band_codes = (
        "51137",
        "51138",
        "-4016",
        "-4024",
        "110003",
        "30208",
        "30209",
        "110120",
        "110121",
        "25205",
        "25206",
        "22047",
    )
    message_tokens = (
        "highest price limit for the buy leg",
        "lowest price limit for the sell leg",
        "price exceeds the allowable range",
        "price is higher than the maximum",
        "price is lower than the minimum",
        "price higher than multiplier up",
        "price lower than multiplier down",
        "price_highter_than_multiplier_up",
        "price_lower_than_multiplier_down",
        "filter failure: percent_price",
        "filter failure: percent_price_by_side",
        "trading price cannot be below",
        "trading price cannot exceed",
        "order price exceeds the maximum price limit",
        "order price is higher than the maximum buying price",
        "order price is lower than the minimum selling price",
        "order price cannot be smaller than",
        "order price cannot be higher than",
        "price_too_deviated",
        "order price deviates too much from mark price",
        "outside the price band",
        "outside price band",
        "exceeds price limit",
    )
    has_known_code = any(
        re.search(
            rf"(?:s?code|retcode|error)\s*['\" :=-]*{re.escape(code)}(?!\d)",
            lower,
        )
        for code in price_band_codes
    )
    return has_known_code or any(token in lower for token in message_tokens)


def classify_exchange_order_error(error: Any) -> dict[str, Any]:
    raw = str(error or "").strip()
    lower = raw.lower()
    http_match = re.search(r"\bhttp\s+(\d{3})\b|\b(5\d{2})\s+(?:bad gateway|gateway timeout|service unavailable)\b", lower)
    http_status = int(next((value for value in (http_match.groups() if http_match else ()) if value), 0) or 0)
    if http_status >= 500 or any(token in lower for token in (
        "bad gateway", "gateway timeout", "service unavailable", "connection reset",
        "connection timed out", "timeout waiting for response", "temporarily unavailable",
    )):
        return {"category": "transport", "retryable": True, "http_status": http_status, "raw": raw}
    if is_exchange_price_band_error(raw):
        return {"category": "price_band", "retryable": True, "http_status": http_status, "raw": raw}
    if any(token in lower for token in (
        "insufficient_available", "insufficient balance", "insufficient margin",
        "not enough balance", "margin insufficient",
    )):
        return {"category": "insufficient_funds", "retryable": False, "http_status": http_status, "raw": raw}
    if re.search(r"below|step|minqty|min qty|minsize|min size|min_notional|minnotional|invalid (qty|quantity|size|amount)", lower):
        return {"category": "order_size", "retryable": False, "http_status": http_status, "raw": raw}
    if any(token in lower for token in ("position mode", "margin mode", "leverage")):
        return {"category": "account_configuration", "retryable": False, "http_status": http_status, "raw": raw}
    return {"category": "exchange_rejected", "retryable": False, "http_status": http_status, "raw": raw}


__all__ = ["classify_exchange_order_error", "is_exchange_price_band_error"]
