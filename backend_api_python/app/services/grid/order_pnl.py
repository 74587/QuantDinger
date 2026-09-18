"""Grid-cycle P&L derived from linked exchange executions, never grid prices."""
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import json
import re

_GRID_REF = re.compile(r"^grid-(\d+)-(long|short)-(entry|exit)-(\d+)$")


def _decimal(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _json(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


def execution_fee(row):
    """Only confirmed quote-denominated costs can determine net P&L."""
    if row.get("fee_status") not in {"actual", "actual_zero"}:
        return None
    fee = _decimal(row.get("commission_quote"))
    if fee is not None:
        return fee
    if row.get("fee_status") == "actual_zero":
        return Decimal(0)
    from app.services.live_trading.fee_quote import symbol_currencies
    base, quote = symbol_currencies(row.get("symbol") or "")
    native = _decimal(row.get("commission"))
    currency = str(row.get("commission_ccy") or "").upper()
    if native is not None and currency and currency == quote:
        return native
    if native is not None and currency and currency == base:
        price = _decimal(row.get("price"))
        return native * price if price is not None else None
    return None


def inventory_quantity(row):
    quantity = _decimal(row.get("amount")) or Decimal(0)
    if str(row.get("market_type") or "").lower() not in {"spot", "crypto"}:
        return quantity
    from app.services.live_trading.fee_quote import symbol_currencies
    base, _ = symbol_currencies(row.get("symbol") or "")
    fees = _json(row.get("commission_breakdown"))
    native = fees.get(base)
    if native is None and str(row.get("commission_ccy") or "").upper() == base:
        native = row.get("commission")
    base_fee = _decimal(native) or Decimal(0)
    action = str(row.get("type") or "")
    if action in {"open_long", "add_long"}:
        return max(Decimal(0), quantity - base_fee)
    if action.startswith(("close_long", "reduce_long")):
        return quantity + base_fee
    return quantity


def _scope(row):
    return (row.get("strategy_id"), row.get("credential_id") or 0,
            str(row.get("market_type") or ""), str(row.get("symbol") or ""))


def _identity(row):
    reason = str(row.get("close_reason") or "").lower()
    action = str(row.get("type") or "").lower()
    if reason in {"grid_initial_long", "grid_initial_short"} and action in {
        "open_long", "add_long", "open_short", "add_short",
    }:
        side = "long" if reason.endswith("long") else "short"
        return side, "entry", [("initial", int(row.get("id") or 0))]
    if row.get("grid_order_id") and row.get("grid_order_purpose"):
        purpose = str(row["grid_order_purpose"])
        if purpose in {"long_entry", "short_entry", "long_exit", "short_exit"}:
            side, kind = purpose.split("_")
            if kind == "entry":
                return side, kind, [("resting", int(row["grid_order_id"]))]
            extra = _json(row.get("grid_order_extra"))
            ids = extra.get("entry_grid_order_ids")
            ids = ids if isinstance(ids, list) else []
            keys = [("resting", int(i)) for i in ids if str(i).isdigit() and int(i) > 0]
            return side, kind, list(dict.fromkeys(keys))
    reference = str(row.get("grid_client_reference") or "")
    match = _GRID_REF.fullmatch(reference)
    if match:
        cell, side, kind, cycle = match.groups()
        return side, kind, [("v2", int(row.get("strategy_run_id") or 0), int(cell), side, int(cycle))]
    if str(row.get("close_reason") or "") in {"long_exit", "short_exit"}:
        return str(row["close_reason"]).split("_")[0], "exit", []
    return None


def enrich_grid_order_pnl(trades):
    """Replay explicit order pairs without consuming lots from unrelated cells.

    This projection is repeatable and incorporates delayed fee reports. Original
    account-cost P&L remains in account_profit_gross for separate reconciliation.
    """
    groups = defaultdict(list)
    initial_keys = defaultdict(list)
    identities = {}
    for row in sorted(trades, key=lambda item: int(item.get("id") or 0)):
        identity = _identity(row)
        identities[id(row)] = identity
        if identity and identity[1] == "entry":
            for key in identity[2]:
                groups[(_scope(row), key)].append(row)
                if key[0] == "initial" and key[1] > 0:
                    initial_keys[(_scope(row), int(row.get("strategy_run_id") or 0), identity[0])].append(key)
    consumed = defaultdict(lambda: Decimal(0))
    exits = sorted(trades, key=lambda r: int(r.get("id") or 0))
    for row in exits:
        identity = identities[id(row)]
        if not identity or identity[1] != "exit":
            continue
        side, _, keys = identity
        purpose = str(row.get("grid_order_purpose") or "")
        if not keys and row.get("grid_order_id") and purpose == f"{side}_exit":
            keys = initial_keys.get(
                (_scope(row), int(row.get("strategy_run_id") or 0), side),
                [],
            )
        row["account_profit_gross"] = row.get("profit_gross", row.get("profit"))
        row["pnl_source"] = "grid_exchange_order_pairs"
        row["pnl_status"] = "unmatched"
        row["matched_orders"] = []
        for field in ("profit", "profit_gross", "net_pnl", "grid_matched_profit", "matched_entry_price",
                      "open_commission_allocated", "close_commission", "total_commission"):
            row[field] = None
        close_price = _decimal(row.get("price"))
        needed = inventory_quantity(row)
        if not row.get("exchange_order_id") or close_price is None or close_price <= 0 or needed <= 0:
            continue
        remaining, gross, opening_fee, entry_notional = needed, Decimal(0), Decimal(0), Decimal(0)
        fee_known = True
        allocation = []
        for key in keys:
            scope_key = (_scope(row), key)
            entries = groups.get(scope_key, [])
            if not entries or any(identities[id(e)][0] != side or not e.get("exchange_order_id") for e in entries):
                continue
            if any(_decimal(e.get("price")) is None or _decimal(e["price"]) <= 0 for e in entries):
                continue
            total = sum((inventory_quantity(e) for e in entries), Decimal(0))
            available = max(Decimal(0), total - consumed[scope_key])
            take = min(remaining, available)
            if take <= 0:
                continue
            entry_value = sum((inventory_quantity(e) * _decimal(e["price"]) for e in entries), Decimal(0))
            price = entry_value / total
            gross += (close_price - price) * take * (1 if side == "long" else -1)
            entry_notional += price * take
            fees = [execution_fee(e) for e in entries]
            if any(f is None for f in fees):
                fee_known = False
            else:
                opening_fee += sum(fees, Decimal(0)) * take / total
            consumed[scope_key] += take
            allocation.append({"entry_order_ids": sorted({str(e["exchange_order_id"]) for e in entries}),
                               "exit_order_id": str(row["exchange_order_id"]),
                               "quantity": float(take), "entry_price": float(price),
                               "exit_price": float(close_price)})
            remaining -= take
            if remaining <= Decimal("1e-12"):
                break
        row["matched_orders"] = allocation
        if remaining > max(Decimal("1e-12"), needed * Decimal("1e-10")):
            continue
        row["profit_gross"] = float(gross)
        row["matched_entry_price"] = float(entry_notional / needed)
        close_fee = execution_fee(row)
        row["pnl_status"] = "fees_pending"
        if not fee_known or close_fee is None:
            continue
        net = gross - opening_fee - close_fee
        row.update(pnl_status="matched", profit=float(net), net_pnl=float(net), grid_matched_profit=float(net),
                   open_commission_allocated=float(opening_fee), close_commission=float(close_fee),
                   total_commission=float(opening_fee + close_fee))
    for row in trades:
        for field in ("grid_client_reference", "grid_order_purpose", "grid_order_extra"):
            row.pop(field, None)
    return trades
