"""
Grid fill quantity normalization: convert exchange order fields to base-asset qty.

Sources (official API docs):
- OKX v5: SWAP sz/accFillSz are contracts; base = contracts * ctVal
  https://www.okx.com/docs-v5/en/#order-book-trading-trade-get-order-details
- Bitget mix order detail: baseVolume = "Amount of coins traded" (base currency)
  https://www.bitget.com/api-doc/contract/trade/Get-Order-Details
- Binance USDT-M futures: executedQty is base-asset quantity
  https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/Query-Order
- Bybit v5: cumExecQty = cumulative executed order qty (base for linear)
  https://bybit-exchange.github.io/docs/v5/order/open-order
- Gate v4 futures: size/filled_size are contracts; base = contracts * quanto_multiplier
  https://www.gate.com/docs/developers/apiv4/en/
- HTX USDT swap: trade_volume is in contracts (cont); base = trade_volume * contract_size
  https://huobiapi.github.io/docs/usdt_swap/v1/en/#get-order-information
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
from math import isfinite

from app.services.live_trading.base import BaseRestClient
from app.services.live_trading.binance import BinanceFuturesClient
from app.services.live_trading.binance_spot import BinanceSpotClient
from app.services.live_trading.bitget import BitgetMixClient
from app.services.live_trading.bitget_spot import BitgetSpotClient
from app.services.live_trading.bybit import BybitClient
from app.services.live_trading.gate import GateSpotClient, GateStockClient, GateUsdtFuturesClient, to_gate_currency_pair
from app.services.live_trading.fill_accounting import contract_multiplier
from app.services.live_trading.gate_spot_fill import parse_gate_spot_fill
from app.services.live_trading.htx import HtxClient
from app.services.live_trading.okx import OkxClient
from app.services.live_trading.symbols import to_okx_spot_inst_id, to_okx_swap_inst_id
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _float(v: Any) -> float:
    try:
        value = float(v or 0)
        return value if isfinite(value) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _okx_ct_val(client: OkxClient, symbol: str, market_type: str) -> float:
    mt = str(market_type or "swap").strip().lower()
    if mt == "spot":
        return 1.0
    return contract_multiplier(client, "okx", symbol)


def okx_swap_position_base_size(
    pos: Dict[str, Any],
    *,
    client: Optional[OkxClient] = None,
) -> float:
    """Convert OKX SWAP ``pos`` field (contracts) to base-asset size."""
    contracts = abs(_float(pos.get("pos")))
    if contracts <= 0:
        return 0.0
    ct_val = _float(pos.get("ctVal"))
    if ct_val <= 0 and client is not None:
        inst_id = str(pos.get("instId") or "").strip()
        sym = inst_id.replace("-SWAP", "").replace("-", "/") if inst_id else ""
        if sym:
            ct_val = _okx_ct_val(client, sym, "swap")
    if ct_val <= 0:
        return 0.0
    return contracts * ct_val


def _gate_quanto_multiplier(client: GateUsdtFuturesClient, symbol: str) -> float:
    return contract_multiplier(client, "gate", symbol)


def _htx_contract_size(client: HtxClient, symbol: str) -> float:
    return contract_multiplier(client, "htx", symbol)


def extract_grid_fill_base_qty(
    client: BaseRestClient,
    *,
    symbol: str,
    market_type: str,
    exchange_config: Optional[Dict[str, Any]],
    data: Dict[str, Any],
) -> float:
    """Return filled quantity in base-asset units for one grid order snapshot."""
    if not isinstance(data, dict) or not data:
        return 0.0
    mt = str(market_type or "swap").strip().lower()
    if mt in ("futures", "future", "perp", "perpetual"):
        mt = "swap"
    ex_cfg = exchange_config if isinstance(exchange_config, dict) else {}

    if isinstance(client, (BinanceFuturesClient, BinanceSpotClient)):
        return _float(data.get("executedQty"))

    if isinstance(client, BybitClient):
        return _float(data.get("cumExecQty"))

    if isinstance(client, BitgetMixClient):
        # Official: baseVolume = amount of coins traded (base currency).
        base_vol = _float(data.get("baseVolume"))
        if base_vol > 0:
            return base_vol
        return _float(data.get('filled') or data.get('filledQty'))

    if isinstance(client, BitgetSpotClient):
        return _float(data.get("baseVolume") or data.get("dealSize") or data.get("filled"))

    if isinstance(client, OkxClient):
        contracts = _float(data.get("accFillSz") or data.get("fillSz"))
        if mt == "spot":
            return contracts
        return contracts * _okx_ct_val(client, symbol, mt)

    if isinstance(client, GateUsdtFuturesClient):
        contracts = abs(_float(data.get("filled_size") or data.get("filledSize")))
        if contracts <= 0:
            size = abs(_float(data.get("size")))
            left = abs(_float(data.get("left")))
            if size > 0:
                contracts = max(0.0, size - left)
        if contracts <= 0:
            return 0.0
        return abs(contracts) * _gate_quanto_multiplier(client, symbol)

    if isinstance(client, GateStockClient):
        return _float(data.get("fill_volume"))

    if isinstance(client, GateSpotClient):
        return parse_gate_spot_fill(data)[0]

    if isinstance(client, HtxClient):
        if mt == "spot":
            return _float(data.get("field-amount") or data.get("filled-amount") or data.get("filled_amount"))
        contracts = _float(
            data.get("trade_volume")
            or data.get("tradeVolume")
        )
        if contracts <= 0:
            return 0.0
        return abs(contracts) * _htx_contract_size(client, symbol)

    if client is None and "filled_amount" in data:
        return parse_gate_spot_fill(data)[0]

    # Generic fallback: legacy path, may be wrong for contract-denominated exchanges.
    return _float(
        data.get("filled")
        or data.get("executedQty")
        or data.get("cumExecQty")
        or data.get("baseVolume")
        or data.get("dealSize")
        or data.get("accFillSz")
        or data.get("filled_size")
    )


def extract_grid_fill_avg_price(
    client: BaseRestClient,
    *,
    data: Dict[str, Any],
    filled_base: float,
) -> float:
    if not isinstance(data, dict) or not data:
        return 0.0

    if isinstance(client, (BinanceFuturesClient, BinanceSpotClient)):
        quote = _float(data.get("cummulativeQuoteQty") or data.get("cumQuote"))
        return quote / filled_base if quote > 0 and filled_base > 0 else _float(data.get("avgPrice"))

    if isinstance(client, BybitClient):
        return _float(data.get("avgPrice"))

    if isinstance(client, (BitgetMixClient, BitgetSpotClient)):
        return _float(data.get("priceAvg") or data.get("avgPrice") or data.get("avg_price"))

    if isinstance(client, OkxClient):
        return _float(data.get("avgPx") or data.get("fillPx"))

    if isinstance(client, GateStockClient):
        return _float(data.get("avg_fill_price"))

    if isinstance(client, GateSpotClient):
        return parse_gate_spot_fill(data)[1]

    if isinstance(client, (GateUsdtFuturesClient,)):
        return _float(data.get("fill_price") or data.get("fillPrice"))

    if isinstance(client, HtxClient):
        cash = _float(data.get("field-cash-amount"))
        if cash > 0 and filled_base > 0:
            return cash / filled_base
        avg = _float(data.get("trade_avg_price") or data.get("tradeAvgPrice"))
        if avg > 0:
            return avg
        turnover = _float(data.get("trade_turnover") or data.get("tradeTurnover"))
        if turnover > 0 and filled_base > 0:
            return turnover / filled_base
        return 0.0

    if client is None and "filled_amount" in data:
        return parse_gate_spot_fill(data)[1]

    avg = _float(
        data.get("avgPx")
        or data.get("avgPrice")
        or data.get("avg_price")
        or data.get("fill_price")
        or data.get("trade_avg_price")
    )
    if avg <= 0 and data.get("filled_total") and data.get("filled_amount"):
        filled_amt = _float(data.get("filled_amount"))
        filled_total = _float(data.get("filled_total"))
        if filled_amt > 0 and filled_total > 0:
            return filled_total / filled_amt
    return avg


def order_status_from_data(data: Dict[str, Any]) -> str:
    """Normalize exchange order dict -> status: open | partial | filled | cancelled | unknown."""
    if not data:
        return "unknown"
    st_raw = str(
        data.get("status_desc")
        or data.get("state")
        or data.get("status")
        or data.get("orderStatus")
        or data.get("order_status")
        or ""
    ).lower()
    if st_raw in {"closed", "finished"} and str(data.get("finish_as") or "").lower() in {"cancelled", "canceled", "ioc", "stp", "reduce_only"}:
        return "cancelled"
    if st_raw in ("filled", "full_fill", "full-fill", "fullfill", "success", "done", "closed", "finished"):
        return "filled"
    if st_raw in ("canceled", "cancelled", "expired", "rejected", "deactivated"):
        return "cancelled"
    if st_raw in ("partially_filled", "partial_fill", "partial-fill", "partially-filled", "partial"):
        return "partial"
    if st_raw in ("live", "new", "open", "not_deal", "notdeal", "submitted"):
        return "open"
    if "fill" in st_raw and "partial" not in st_raw:
        return "filled"
    if "cancel" in st_raw:
        return "cancelled"
    # HTX numeric status: 4=partial, 5=partial cancel, 6=filled, 7=cancelled
    try:
        st_num = int(st_raw)
        if st_num == 6:
            return "filled"
        if st_num in (5, 7, 11):
            return "cancelled"
        if st_num == 4:
            return "partial"
        if st_num in (1, 2, 3):
            return "open"
    except (TypeError, ValueError):
        pass
    filled_hint = _float(
        data.get("accFillSz")
        or data.get("executedQty")
        or data.get("cumExecQty")
        or data.get("baseVolume")
        or data.get("dealSize")
        or data.get("trade_volume")
        or data.get("filled_size")
    )
    return "partial" if filled_hint > 0 else "open"


def parse_grid_order_fill(
    client: BaseRestClient,
    *,
    symbol: str,
    market_type: str,
    exchange_config: Optional[Dict[str, Any]],
    data: Dict[str, Any],
) -> Tuple[float, float, str]:
    """Exchange-aware (filled_base_qty, avg_price, status)."""
    filled = extract_grid_fill_base_qty(
        client,
        symbol=str(symbol),
        market_type=str(market_type or "swap"),
        exchange_config=exchange_config,
        data=data,
    )
    avg = extract_grid_fill_avg_price(client, data=data, filled_base=filled)
    status = order_status_from_data(data)
    return filled, avg, status
