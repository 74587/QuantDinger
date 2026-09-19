"""Audit persisted grid orders without depending on an execution worker's memory."""

from datetime import datetime, timezone

from app.services.exchange_execution import coalesce_exchange_config_from_payload, resolve_exchange_config
from app.services.live_trading.factory import create_client
from app.services.live_trading.open_orders import fetch_exchange_open_orders
from app.services.live_trading.records import normalize_strategy_symbol
from app.services.pending_orders.live_order_support import bind_instrument_product_contract
from app.utils.logger import get_logger

logger = get_logger(__name__)


def audit_grid_orders(strategy: dict, rows: list, *, user_id: int) -> dict:
    audit = {"completed": False, "active": 0, "unknown": len(rows), "error": "",
             "checked_at": None, "orders": {}}
    tc = strategy.get("trading_config") or {}
    mt = str(tc.get("market_type") or strategy.get("market_type") or "swap").lower()
    try:
        config = resolve_exchange_config(coalesce_exchange_config_from_payload(strategy), user_id=user_id)
        ex = str(config.get("exchange_id") or "").lower()
        symbols = sorted({str(row.symbol) for row in rows})
        for symbol in symbols:
            bound = bind_instrument_product_contract(config, tc, symbol=symbol, exchange_id=ex, market_type=mt)
            client = create_client(bound, market_type=mt)
            remote = fetch_exchange_open_orders(client, exchange_id=ex, market_type=mt, symbol=symbol)
            by_id = {str(item["exchange_order_id"]): item for item in remote
                     if normalize_strategy_symbol(item["symbol"]) == normalize_strategy_symbol(symbol)}
            for row in rows:
                if row.symbol != symbol:
                    continue
                item = by_id.get(str(row.exchange_order_id or ""))
                if item is None:
                    state = "not_open" if row.exchange_order_id else "unverified"
                else:
                    raw_status = str(item.get("status") or "").lower()
                    if raw_status in {"new", "open", "live", "created", "untriggered"}:
                        state = "open"
                    elif raw_status in {"partial", "partiallyfilled", "partially_filled"}:
                        state = "partial"
                    else:
                        state = "unverified"
                audit["orders"][row.id] = {"status": state, "price": item.get("price") if item else None,
                                           "quantity": item.get("amount") if item else None,
                                           "filled": item.get("filled") if item else None}
                if state in {"open", "partial"}:
                    audit["active"] += 1
        audit["unknown"] = len(rows) - audit["active"]
        audit["completed"] = True
        audit["checked_at"] = datetime.now(timezone.utc).isoformat()
        if audit["unknown"]:
            audit["error"] = "grid_exchange_orders_unverified"
    except Exception:
        logger.warning("Grid order audit failed sid=%s", strategy.get("id"), exc_info=True)
        audit["error"] = "grid_exchange_snapshot_failed"
    return audit
