"""Bitget Reality spot-equity client using the UTA v3 API family."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from app.services.live_trading.base import LiveOrderResult, LiveTradingError
from app.services.live_trading.bitget_spot import BitgetSpotClient
from app.services.live_trading.symbols import to_bitget_um_symbol
from app.utils.numeric_precision import format_decimal


class BitgetRealityClient(BitgetSpotClient):
    """Execute Bitget Reality instruments without falling back to spot v2."""

    _CHANNEL_API_CODE_ORDER_PATHS = BitgetSpotClient._CHANNEL_API_CODE_ORDER_PATHS | {
        "/api/v3/trade/place-reality-order",
        "/api/v3/trade/cancel-reality-order",
    }

    def __init__(self, *, instrument_id: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.instrument_id = str(instrument_id or "").strip().upper()

    def _native_symbol(self, symbol: str) -> str:
        return self.instrument_id or to_bitget_um_symbol(symbol)

    def get_symbol_meta(self, *, symbol: str) -> Dict[str, Any]:
        sym = self._native_symbol(symbol)
        if not sym:
            return {}
        now = time.time()
        cached = self._sym_meta_cache.get(sym)
        if cached and cached[1] and now - float(cached[0] or 0.0) <= self._sym_meta_cache_ttl_sec:
            return cached[1]
        raw = self._public_request(
            "GET",
            "/api/v3/market/instruments",
            params={"category": "SPOT", "symbol": sym},
        )
        data = raw.get("data") if isinstance(raw, dict) else None
        items = data if isinstance(data, list) else data.get("list", []) if isinstance(data, dict) else []
        found = next(
            (
                dict(item)
                for item in items
                if isinstance(item, dict)
                and str(item.get("symbol") or "").strip().upper() == sym.upper()
            ),
            {},
        )
        if found:
            found.setdefault("quantityPrecision", found.get("quantityScale"))
            found.setdefault("pricePrecision", found.get("priceScale"))
            found.setdefault("minTradeAmount", found.get("minOrderQty"))
            found.setdefault("minTradeUSDT", found.get("minOrderAmount"))
            self._sym_meta_cache[sym] = (now, found)
        return found

    def get_ticker(self, *, symbol: str) -> Dict[str, Any]:
        sym = self._native_symbol(symbol)
        raw = self._public_request(
            "GET",
            "/api/v3/market/tickers",
            params={"category": "SPOT", "symbol": sym},
        )
        data = raw.get("data") if isinstance(raw, dict) else None
        items = data if isinstance(data, list) else data.get("list", []) if isinstance(data, dict) else []
        result = dict(items[0]) if items and isinstance(items[0], dict) else dict(data) if isinstance(data, dict) else {}
        result.setdefault("last", result.get("lastPrice"))
        result.setdefault("high", result.get("highPrice24h"))
        result.setdefault("low", result.get("lowPrice24h"))
        result.setdefault("open", result.get("openPrice24h"))
        return result

    def place_limit_order(
        self,
        *,
        symbol: str,
        side: str,
        size: float,
        price: float,
        client_order_id: Optional[str] = None,
    ) -> LiveOrderResult:
        sym = self._native_symbol(symbol)
        sd = str(side or "").strip().lower()
        if sd not in {"buy", "sell"}:
            raise LiveTradingError(f"Invalid side: {side}")
        size_value, size_precision = self._normalize_base_size(symbol=symbol, base_size=float(size or 0.0))
        price_value, price_precision = self._normalize_limit_price(symbol=symbol, price=float(price or 0.0))
        if size_value <= 0:
            raise LiveTradingError(f"Invalid size (below step/min): requested={format_decimal(size)}")
        if price_value <= 0:
            raise LiveTradingError(f"Invalid price (below tick/min): requested={format_decimal(price)}")
        body: Dict[str, Any] = {
            "category": "SPOT",
            "symbol": sym,
            "side": sd,
            "orderType": "limit",
            "qty": self._dec_str(size_value, strict_precision=size_precision),
            "price": self._dec_str(price_value, strict_precision=price_precision),
        }
        if client_order_id:
            body["clientOid"] = str(client_order_id)
        raw = self._signed_request("POST", "/api/v3/trade/place-reality-order", json_body=body)
        return self._order_result(raw)

    def place_market_order(
        self,
        *,
        symbol: str,
        side: str,
        size: float,
        client_order_id: Optional[str] = None,
    ) -> LiveOrderResult:
        sym = self._native_symbol(symbol)
        sd = str(side or "").strip().lower()
        if sd not in {"buy", "sell"}:
            raise LiveTradingError(f"Invalid side: {side}")
        if sd == "buy":
            size_value, precision = self._normalize_quote_size(symbol=symbol, quote_size=float(size or 0.0))
        else:
            size_value, precision = self._normalize_base_size(symbol=symbol, base_size=float(size or 0.0))
        if size_value <= 0:
            raise LiveTradingError(f"Invalid size (below step/min): requested={format_decimal(size)}")
        body: Dict[str, Any] = {
            "category": "SPOT",
            "symbol": sym,
            "side": sd,
            "orderType": "market",
            "qty": self._dec_str(size_value, strict_precision=precision),
        }
        if client_order_id:
            body["clientOid"] = str(client_order_id)
        raw = self._signed_request("POST", "/api/v3/trade/place-reality-order", json_body=body)
        return self._order_result(raw)

    def cancel_order(self, *, symbol: str, order_id: str = "", client_order_id: str = "") -> Dict[str, Any]:
        body: Dict[str, Any] = {"category": "SPOT", "symbol": self._native_symbol(symbol)}
        if order_id:
            body["orderId"] = str(order_id)
        elif client_order_id:
            body["clientOid"] = str(client_order_id)
        else:
            raise LiveTradingError("Bitget Reality cancel_order requires order_id or client_order_id")
        return self._signed_request("POST", "/api/v3/trade/cancel-reality-order", json_body=body)

    def get_order(self, *, symbol: str, order_id: str = "", client_order_id: str = "") -> Dict[str, Any]:
        del symbol
        params: Dict[str, Any] = {}
        if order_id:
            params["orderId"] = str(order_id)
        elif client_order_id:
            params["clientOid"] = str(client_order_id)
        else:
            raise LiveTradingError("Bitget Reality get_order requires order_id or client_order_id")
        raw = self._signed_request("GET", "/api/v3/trade/order-info", params=params)
        row = self._first_row(raw.get("data") if isinstance(raw, dict) else None)
        return {**raw, "data": self._normalize_order_row(row)}

    def get_fills(self, *, symbol: str, order_id: str) -> Dict[str, Any]:
        raw = self._signed_request(
            "GET",
            "/api/v3/trade/fills",
            params={
                "category": "SPOT",
                "orderId": str(order_id),
            },
        )
        data = raw.get("data") if isinstance(raw, dict) else None
        items = data if isinstance(data, list) else data.get("list", []) if isinstance(data, dict) else []
        fills = []
        for item in items:
            if not isinstance(item, dict):
                continue
            normalized = dict(item)
            normalized.setdefault("size", item.get("execQty"))
            normalized.setdefault("priceAvg", item.get("execPrice"))
            normalized.setdefault("fee", item.get("execFee"))
            fills.append(normalized)
        return {**raw, "data": fills}

    def get_assets(self) -> Dict[str, Any]:
        raw = self._signed_request("GET", "/api/v3/account/assets")
        data = raw.get("data") if isinstance(raw, dict) else None
        assets = data if isinstance(data, list) else data.get("assets", []) if isinstance(data, dict) else []
        return {**raw, "data": assets}

    @staticmethod
    def _first_row(data: Any) -> Dict[str, Any]:
        if isinstance(data, dict):
            values = data.get("list")
            if isinstance(values, list) and values and isinstance(values[0], dict):
                return dict(values[0])
            return dict(data)
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return dict(data[0])
        return {}

    @staticmethod
    def _normalize_order_row(row: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(row)
        normalized.setdefault("baseVolume", row.get("cumExecQty"))
        normalized.setdefault("quoteVolume", row.get("cumExecValue"))
        normalized.setdefault("priceAvg", row.get("avgPrice"))
        normalized.setdefault("status", row.get("orderStatus"))
        return normalized

    @staticmethod
    def _order_result(raw: Dict[str, Any]) -> LiveOrderResult:
        data = raw.get("data") if isinstance(raw, dict) else None
        row = data if isinstance(data, dict) else {}
        order_id = str(row.get("orderId") or row.get("order_id") or "")
        return LiveOrderResult(
            exchange_id="bitget",
            exchange_order_id=order_id,
            filled=0.0,
            avg_price=0.0,
            raw=raw,
        )
