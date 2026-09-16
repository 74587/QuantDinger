"""Expose instruction benchmarks separately from recorded execution prices."""
import json

from app.services.live_trading.fill_evidence import positive_number


def enrich_execution_reference(row):
    result = dict(row)
    payload = result.pop("request_payload", None)
    pending_price = result.pop("request_price", None)
    grid_price = result.pop("grid_request_price", None)
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            payload = {}
    payload = payload if isinstance(payload, dict) else {}
    if not result.get("grid_client_reference"):
        result["grid_client_reference"] = payload.get("client_order_id") or ""
    reference = positive_number(grid_price)
    kind = "limit" if reference is not None else None
    if reference is None:
        reference = positive_number(payload.get("ref_price"))
        if reference is not None:
            kind = "signal"
        else:
            reference = (positive_number(payload.get("limit_price"))
                         or positive_number(payload.get("price")) or positive_number(pending_price))
            kind = "instruction" if reference is not None else None
    result["reference_price"] = reference
    result["reference_kind"] = kind
    result["price_deviation_pct"] = None
    actual = positive_number(result.get("price"))
    action = str(result.get("type") or "").lower()
    direction = {
        "open_long": 1, "add_long": 1, "close_short": 1, "reduce_short": 1,
        "open_short": -1, "add_short": -1, "close_long": -1, "reduce_long": -1,
    }.get(action)
    if reference is not None and actual is not None and direction is not None:
        result["price_deviation_pct"] = direction * (actual / reference - 1) * 100
    return result
