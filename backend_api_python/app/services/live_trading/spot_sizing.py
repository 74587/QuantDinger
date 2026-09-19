"""
Spot sizing helpers: align close quantity with exchange free base balance (fees/reserve).

Full-position buys often leave recorded size slightly above sellable free balance.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Any, Dict, Optional, Tuple

from app.services.live_trading.base import BaseRestClient, LiveTradingError
from app.services.live_trading.symbols import _split_base_quote

logger = logging.getLogger(__name__)

# Position ownership is recorded net of base-asset fees. Applying an additional
# 0.2% haircut on every close compounds into visible residual balances.
_DEFAULT_CLOSE_SAFETY = 1.0
_DEFAULT_OPEN_BUFFER = 0.995


def _close_safety_ratio() -> float:
    try:
        v = float(os.getenv("SPOT_CLOSE_SAFETY_RATIO", str(_DEFAULT_CLOSE_SAFETY)))
    except Exception:
        v = _DEFAULT_CLOSE_SAFETY
    if v <= 0 or v > 1.0:
        v = _DEFAULT_CLOSE_SAFETY
    return v


def _open_quote_buffer() -> float:
    try:
        v = float(os.getenv("SPOT_OPEN_QUOTE_BUFFER", str(_DEFAULT_OPEN_BUFFER)))
    except Exception:
        v = _DEFAULT_OPEN_BUFFER
    if v <= 0 or v > 1.0:
        v = _DEFAULT_OPEN_BUFFER
    return v


def scale_spot_open_notional(usdt_notional: float) -> float:
    """Reserve a small USDT buffer so spot buys do not consume 100% of quote (fees)."""
    amt = float(usdt_notional or 0.0)
    if amt <= 0:
        return 0.0
    return amt * _open_quote_buffer()


def _pick_free_from_row(row: Dict[str, Any], *keys: str) -> float:
    for k in keys:
        if k in row and row.get(k) is not None:
            try:
                v = float(row.get(k) or 0.0)
                if v >= 0:
                    return v
            except Exception:
                continue
    return 0.0


def _pick_cost_from_row(row: Dict[str, Any], *keys: str) -> float:
    for k in keys:
        if k in row and row.get(k) is not None:
            try:
                v = float(row.get(k) or 0.0)
                if v > 0:
                    return v
            except Exception:
                continue
    return 0.0


def _spot_holding(
    total: float,
    available: Optional[float],
    avg_cost: float = 0.0,
) -> Dict[str, float]:
    t = max(0.0, float(total or 0.0))
    # ``0`` is a valid available balance when the whole holding is locked.
    # Only a genuinely absent value may fall back to total.
    a = t if available is None else max(0.0, float(available or 0.0))
    if t <= 0 and a <= 0:
        return {"total": 0.0, "available": 0.0, "avg_cost": 0.0}
    if t <= 0:
        t = a
    return {
        "total": t,
        "available": a,
        "avg_cost": max(0.0, float(avg_cost or 0.0)),
    }


def get_spot_base_holding(
    client: BaseRestClient,
    *,
    symbol: str,
    strict: bool = False,
    require_available: bool = False,
) -> Dict[str, float]:
    """
    Best-effort spot base-asset holding (total + available/free).

    Used by Quick Trade spot position display and close sizing.
    """
    strict = strict or require_available
    balance_read = False

    def rows(value):
        if require_available and (
            not isinstance(value, list) or any(not isinstance(row, dict) for row in value)
        ):
            raise LiveTradingError("strategyRuntime.spotBalanceUnavailable")
        return value or []

    def available(row, *keys):
        if not require_available:
            return _pick_free_from_row(row, *keys)
        for key in keys:
            value = row.get(key)
            if value is None or value == "":
                continue
            try:
                result = float(value)
            except (TypeError, ValueError):
                continue
            if math.isfinite(result) and result >= 0:
                return result
        raise LiveTradingError("strategyRuntime.spotBalanceUnavailable")

    base, _ = _split_base_quote(str(symbol or ""))
    if not base:
        if require_available:
            raise LiveTradingError("strategyRuntime.spotBalanceUnavailable")
        return {"total": 0.0, "available": 0.0, "avg_cost": 0.0}
    base_u = base.upper()

    try:
        from app.services.live_trading.gate import GateStockClient

        if isinstance(client, GateStockClient):
            raw = client.get_positions(symbol=base_u)
            balance_read = True
            data = raw.get("data") if isinstance(raw, dict) else None
            for row in rows(data.get("list") if isinstance(data, dict) else None):
                if str(row.get("symbol") or "").upper() != base_u:
                    continue
                total = _pick_free_from_row(row, "volume")
                avail = available(row, "available")
                avg_cost = _pick_cost_from_row(row, "avg_cost_price", "diluted_cost_price")
                return _spot_holding(total, avail, avg_cost)
    except Exception as e:
        if strict:
            raise
        logger.warning("spot base holding (gate stock): %s", e)

    try:
        from app.services.live_trading.binance_spot import BinanceSpotClient

        if isinstance(client, BinanceSpotClient):
            raw = client.get_account() or {}
            balance_read = True
            for b in rows(raw.get("balances")):
                if not isinstance(b, dict):
                    continue
                if str(b.get("asset") or "").upper() == base_u:
                    free = available(b, "free")
                    locked = _pick_free_from_row(b, "locked")
                    return _spot_holding(free + locked, free)
    except Exception as e:
        if strict:
            raise
        logger.warning("spot base holding (binance): %s", e)

    try:
        from app.services.live_trading.okx import OkxClient

        if isinstance(client, OkxClient):
            raw = client.get_balance() or {}
            balance_read = True
            data = rows(raw.get("data") if isinstance(raw, dict) else None)
            first = data[0] if isinstance(data, list) and data else {}
            if isinstance(first, dict):
                for det in rows(first.get("details")):
                    if not isinstance(det, dict):
                        continue
                    if str(det.get("ccy") or "").upper() == base_u:
                        keys = ("availBal",) if require_available else ("availBal", "cashBal")
                        avail = available(det, *keys)
                        total = _pick_free_from_row(det, "eq", "cashBal", "availBal")
                        frozen = _pick_free_from_row(det, "frozenBal")
                        if total <= 0:
                            total = avail + frozen
                        avg_cost = _pick_cost_from_row(
                            det, "openAvgPx", "accAvgPx", "avgPx", "avgCost"
                        )
                        return _spot_holding(total, avail, avg_cost)
    except Exception as e:
        if strict:
            raise
        logger.warning("spot base holding (okx): %s", e)

    try:
        from app.services.live_trading.gate import GateSpotClient

        if isinstance(client, GateSpotClient):
            raw = client.get_accounts()
            balance_read = True
            account_rows = rows(raw if isinstance(raw, list) else raw.get("data") if isinstance(raw, dict) else None)
            for row in account_rows:
                if not isinstance(row, dict):
                    continue
                if str(row.get("currency") or "").upper() == base_u:
                    avail = available(row, "available", "available_balance")
                    locked = _pick_free_from_row(row, "locked", "freeze")
                    return _spot_holding(avail + locked, avail)
    except Exception as e:
        if strict:
            raise
        logger.warning("spot base holding (gate): %s", e)

    try:
        from app.services.live_trading.bitget_spot import BitgetSpotClient

        if isinstance(client, BitgetSpotClient):
            raw = client.get_assets() or {}
            balance_read = True
            data = rows(raw.get("data") if isinstance(raw, dict) else None)
            for row in data if isinstance(data, list) else []:
                if not isinstance(row, dict):
                    continue
                if str(row.get("coin") or row.get("currency") or "").upper() == base_u:
                    avail = available(row, "available", "avail", "free")
                    frozen = _pick_free_from_row(row, "frozen", "lock")
                    total = _pick_free_from_row(row, "total", "balance")
                    if total <= 0:
                        total = avail + frozen
                    avg_cost = _pick_cost_from_row(
                        row, "averageOpenPrice", "avgOpenPrice", "avgCost", "openAvgPx"
                    )
                    return _spot_holding(total, avail, avg_cost)
    except Exception as e:
        if strict:
            raise
        logger.warning("spot base holding (bitget): %s", e)

    try:
        from app.services.live_trading.bybit import BybitClient

        if isinstance(client, BybitClient) and (getattr(client, "category", "") or "").strip().lower() == "spot":
            last_error: Optional[Exception] = None
            for account_type in ("UNIFIED", "SPOT"):
                try:
                    raw = client.get_wallet_balance(account_type=account_type) or {}
                    balance_read = True
                except Exception as account_error:
                    last_error = account_error
                    continue
                lst = rows((raw.get("result") or {}).get("list") if isinstance(raw, dict) else None)
                for acct in lst:
                    if not isinstance(acct, dict):
                        continue
                    for coin in rows(acct.get("coin")):
                        if not isinstance(coin, dict):
                            continue
                        if str(coin.get("coin") or "").upper() == base_u:
                            keys = ("availableToWithdraw", "availableBalance", "free")
                            if not require_available:
                                keys += ("walletBalance",)
                            total = _pick_free_from_row(
                                coin,
                                "walletBalance",
                                "equity",
                                "availableToWithdraw",
                                "availableBalance",
                            )
                            try:
                                avail = available(coin, *keys)
                            except LiveTradingError:
                                explicit_available = any(
                                    key in coin
                                    for key in ("free", "availableBalance")
                                ) or coin.get("availableToWithdraw") not in (None, "")
                                if account_type != "UNIFIED" or total <= 0 or explicit_available:
                                    raise
                                locked = _pick_free_from_row(coin, "locked", "frozen")
                                avail = max(0.0, total - locked)
                            avg_cost = _pick_cost_from_row(
                                coin, "avgPrice", "sessionAvgPrice", "accAvgPx", "avgCost"
                            )
                            return _spot_holding(total, avail, avg_cost)
            if strict and not balance_read and last_error is not None:
                raise last_error
    except Exception as e:
        if strict:
            raise
        logger.warning("spot base holding (bybit): %s", e)

    try:
        from app.services.live_trading.htx import HtxClient

        if isinstance(client, HtxClient) and getattr(client, "market_type", "") == "spot":
            balance = client.get_balance()
            balance_read = True
            items = rows((balance.get("data") or {}).get("list") if isinstance(balance, dict) else None)
            # HTX splits one currency over several rows: ``trade`` is the
            # sellable part, ``frozen`` is locked by resting orders and still
            # owned.  Order is not guaranteed, so accumulate instead of
            # returning on the first row that matches the base asset.
            tradable = 0.0
            frozen = 0.0
            avail = 0.0
            matched = False
            for item in items:
                if not isinstance(item, dict):
                    continue
                if str(item.get("currency") or "").upper() != base_u:
                    continue
                balance_type = str(item.get("type") or "").strip().lower()
                if balance_type == "frozen":
                    matched = True
                    frozen += _pick_free_from_row(item, "balance")
                elif balance_type == "trade":
                    matched = True
                    tradable += _pick_free_from_row(item, "balance")
                    avail += available(item, "available", "balance")
                # Other balance types are not part of this spot trading inventory.
            if matched:
                return _spot_holding(tradable + frozen, avail)
    except Exception as e:
        if strict:
            raise
        logger.warning("spot base holding (htx): %s", e)

    if require_available and not balance_read:
        raise LiveTradingError("strategyRuntime.spotBalanceUnavailable")
    return {"total": 0.0, "available": 0.0, "avg_cost": 0.0}


def get_spot_free_base_balance(client: BaseRestClient, *, symbol: str, strict: bool = False) -> float:
    """
    Best-effort free/available base asset on the connected spot account.
    Strict execution reads reject unknown balances; display reads remain best-effort.
    """
    holding = get_spot_base_holding(client, symbol=symbol, strict=strict, require_available=strict)
    return max(0.0, float(holding.get("available") or 0.0))


def get_spot_total_base_balance(
    client: BaseRestClient,
    *,
    symbol: str,
    strict: bool = False,
) -> float:
    """Best-effort total base inventory, including exchange-locked quantity.

    Ownership and drift checks must use the whole account inventory.  Open
    limit orders can move quantity from ``available`` to ``locked`` without
    changing ownership, so using the sellable balance here would create a
    false negative drift.
    """
    holding = get_spot_base_holding(client, symbol=symbol, strict=strict)
    return max(0.0, float(holding.get("total") or 0.0))


def fetch_spot_last_price(client: BaseRestClient, *, symbol: str) -> float:
    """Best-effort last price for USDT -> base conversion (supports Bitget ``lastPr``)."""
    if not hasattr(client, "get_ticker"):
        return 0.0
    try:
        ticker = client.get_ticker(symbol=symbol)
    except Exception:
        return 0.0
    if not isinstance(ticker, dict):
        return 0.0
    for key in ("last", "lastPr", "lastPx", "lastPrice", "close", "price"):
        try:
            px = float(ticker.get(key) or 0.0)
        except Exception:
            px = 0.0
        if px > 0:
            return px
    return 0.0


def prepare_spot_live_order_sizes(
    client: BaseRestClient,
    *,
    symbol: str,
    side: str,
    reduce_only: bool,
    base_qty: float,
    ref_price: float = 0.0,
) -> Tuple[float, float, bool]:
    """
    Normalize spot sizes for PendingOrderWorker (strategy live path).

    Returns:
        (base_qty, quote_amount, market_buy_uses_quote)
        ``market_buy_uses_quote`` is True when market BUY should send USDT notional
        (Bitget / Gate spot).
    """
    from app.services.live_trading.binance_spot import BinanceSpotClient
    from app.services.live_trading.bitget_spot import BitgetSpotClient
    from app.services.live_trading.gate import GateSpotClient

    qty = float(base_qty or 0.0)
    sd = (side or "").strip().lower()
    quote_amt = 0.0
    market_buy_uses_quote = False

    if sd == "sell" and reduce_only:
        qty = normalize_spot_base_quantity(
            client, symbol=symbol, quantity=qty, for_market=True
        )
        return max(0.0, qty), 0.0, False

    if sd == "buy" and not reduce_only:
        rp = float(ref_price or 0.0)
        if rp <= 0:
            rp = fetch_spot_last_price(client, symbol=symbol)
        if rp > 0 and qty > 0:
            quote_amt = qty * rp
        quote_amt = normalize_spot_quote_amount(
            client, symbol=symbol, quote_amount=quote_amt
        )
        if isinstance(client, (BitgetSpotClient, GateSpotClient)):
            market_buy_uses_quote = quote_amt > 0
        if isinstance(client, BinanceSpotClient) or not market_buy_uses_quote:
            qty = normalize_spot_base_quantity(
                client, symbol=symbol, quantity=qty, for_market=True
            )
        return max(0.0, qty), max(0.0, quote_amt), market_buy_uses_quote

    qty = normalize_spot_base_quantity(
        client, symbol=symbol, quantity=qty, for_market=True
    )
    return max(0.0, qty), 0.0, False


def normalize_spot_quote_amount(
    client: BaseRestClient,
    *,
    symbol: str,
    quote_amount: float,
) -> float:
    """Floor USDT notional for spot market buy (Bitget/Gate quote-sized orders)."""
    amt = float(quote_amount or 0.0)
    if amt <= 0:
        return 0.0
    norm = getattr(client, "_normalize_quote_size", None)
    if callable(norm):
        try:
            dec, _prec = norm(symbol=str(symbol), quote_size=amt)
            return float(dec or 0.0)
        except Exception as e:
            logger.warning("spot quote normalize failed (%s): %s", symbol, e)
    return amt


def normalize_spot_base_quantity(
    client: BaseRestClient,
    *,
    symbol: str,
    quantity: float,
    for_market: bool = True,
) -> float:
    """Floor quantity to exchange step when client supports _normalize_quantity."""
    qty = float(quantity or 0.0)
    if qty <= 0:
        return 0.0
    norm_qty = getattr(client, "_normalize_quantity", None)
    if callable(norm_qty):
        try:
            dec, _prec = norm_qty(symbol=str(symbol), quantity=qty, for_market=for_market)
            return float(dec or 0.0)
        except Exception as e:
            logger.warning("spot quantity normalize failed (%s): %s", symbol, e)
    norm_base = getattr(client, "_normalize_base_size", None)
    if callable(norm_base):
        try:
            dec, _prec = norm_base(symbol=str(symbol), base_size=qty)
            return float(dec or 0.0)
        except Exception as e:
            logger.warning("spot base normalize failed (%s): %s", symbol, e)
    return qty


def clamp_spot_close_quantity(
    client: BaseRestClient,
    *,
    symbol: str,
    requested_qty: float,
    safety_ratio: Optional[float] = None,
) -> Tuple[float, Dict[str, Any]]:
    """
    Cap sell size to exchange free base (with safety ratio) and normalize down to lot step.
    """
    req = float(requested_qty or 0.0)
    if not math.isfinite(req):
        raise LiveTradingError("strategyRuntime.spotCloseQuantityInvalid")
    meta: Dict[str, Any] = {"requested": req}
    if req <= 0:
        return 0.0, meta

    ratio = float(safety_ratio) if safety_ratio is not None else _close_safety_ratio()
    if not math.isfinite(ratio) or not 0 < ratio <= 1:
        raise LiveTradingError("strategyRuntime.spotCloseQuantityInvalid")
    try:
        free = get_spot_free_base_balance(client, symbol=symbol, strict=True)
        if not math.isfinite(free) or free < 0:
            raise LiveTradingError("strategyRuntime.spotBalanceUnavailable")
    except Exception as exc:
        raise LiveTradingError("strategyRuntime.spotBalanceUnavailable") from exc
    meta["exchange_free"] = free
    meta["safety_ratio"] = ratio

    cap = min(req, free * ratio)
    meta["capped_before_normalize"] = cap

    final = normalize_spot_base_quantity(client, symbol=symbol, quantity=cap, for_market=True)
    if not math.isfinite(final) or final < 0 or final > cap:
        raise LiveTradingError("strategyRuntime.spotCloseQuantityInvalid")
    meta["final"] = final
    if final < req * 0.999:
        meta["adjusted"] = True
        logger.info(
            "Spot close qty adjusted: symbol=%s requested=%s free=%s final=%s ratio=%s",
            symbol,
            req,
            free,
            final,
            ratio,
        )
    return max(0.0, final), meta
