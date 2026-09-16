"""
Recover live fill quantity when wait_for_fill returns zero but the exchange filled.

Used by PendingOrderWorker (indicator / script strategies) and shares the same
exchange-documented unit conversion as grid ``fill_units.parse_grid_order_fill``.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from app.services.grid.exchange_orders import query_grid_order_fill
from app.services.live_trading.fill_evidence import positive_number
from app.utils.logger import get_logger

logger = get_logger(__name__)

def try_recover_zero_fill(
    client: Any,
    *,
    symbol: str,
    market_type: str,
    exchange_config: Optional[Dict[str, Any]],
    exchange_order_id: str,
    client_order_id: str,
    requested_qty: float,
    signal_type: str,
    pos_side: str,
    pre_position_qty: float,
    ref_price: float,
) -> Tuple[float, float, str]:
    """Recover only execution quantities and prices returned for this order."""
    ex_oid = str(exchange_order_id or "").strip()
    coid = str(client_order_id or "").strip()
    ex_cfg = exchange_config if isinstance(exchange_config, dict) else {}

    if ex_oid or coid:
        try:
            filled, avg, status = query_grid_order_fill(
                client,
                symbol=str(symbol),
                market_type=str(market_type or "swap"),
                exchange_order_id=ex_oid,
                client_order_id=coid,
                exchange_config=ex_cfg,
            )
            if positive_number(filled) is not None and positive_number(avg) is not None:
                use_avg = float(avg)
                logger.info(
                    "fill_recovery order_requery: symbol=%s oid=%s filled=%s avg=%s status=%s",
                    symbol,
                    ex_oid or coid,
                    filled,
                    use_avg,
                    status,
                )
                return float(filled), use_avg, "order_requery"
        except Exception as e:
            logger.debug("fill_recovery order_requery failed symbol=%s: %s", symbol, e)

    return 0.0, 0.0, ""
