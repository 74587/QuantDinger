"""Quote fetching and cache helpers for watchlist pricing."""

import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed

from app.services.kline import KlineService
from app.utils.cache import CacheManager
from app.utils.logger import get_logger
from app.utils.request_guard import RequestGuardError, cache_key, guarded_cached

logger = get_logger(__name__)

kline_service = KlineService()
_market_cache = CacheManager()

QUOTE_CACHE_TTL_SEC = int(os.getenv("WATCHLIST_QUOTE_CACHE_TTL_SEC", "5"))
QUOTE_STALE_TTL_SEC = int(os.getenv("WATCHLIST_QUOTE_STALE_TTL_SEC", "600"))
QUOTE_FETCH_TIMEOUT_SEC = float(os.getenv("WATCHLIST_QUOTE_FETCH_TIMEOUT_SEC", "5"))


def _executor_workers() -> int:
    try:
        value = int(os.getenv("MARKET_EXECUTOR_WORKERS", "6"))
        return value if value > 0 else 6
    except Exception:
        return 6


executor = ThreadPoolExecutor(max_workers=_executor_workers())


def quote_cache_key(market: str, symbol: str, *, stale: bool = False) -> str:
    prefix = "watchlist_quote_stale" if stale else "watchlist_quote"
    return f"{prefix}:{market}:{symbol}".upper()


def empty_price(market: str, symbol: str, *, error: str = "") -> dict:
    out = {
        "market": market,
        "symbol": symbol,
        "price": 0,
        "change": 0,
        "changePercent": 0,
    }
    if error:
        out["error"] = error
    return out


def normalize_price_payload(
    market: str,
    symbol: str,
    price_data: dict,
    *,
    cached: bool = False,
    stale: bool = False,
) -> dict:
    out = {
        "market": market,
        "symbol": symbol,
        "price": price_data.get("price", 0),
        "change": price_data.get("change", 0),
        "changePercent": price_data.get("changePercent", 0),
    }
    if cached:
        out["cached"] = True
    if stale:
        out["stale"] = True
    if price_data.get("source"):
        out["source"] = price_data.get("source")
    return out


def get_single_price(market: str, symbol: str) -> dict:
    """Get one quote snapshot with fresh and stale cache fallback."""
    fresh_key = quote_cache_key(market, symbol)
    stale_key = quote_cache_key(market, symbol, stale=True)
    cached = _market_cache.get(fresh_key)
    if isinstance(cached, dict) and float(cached.get("price") or 0) > 0:
        return normalize_price_payload(market, symbol, cached, cached=True)

    try:
        price_data = guarded_cached(
            cache_key("single_quote_fetch", market, symbol),
            lambda: kline_service.get_realtime_price(market, symbol),
            ttl_sec=QUOTE_CACHE_TTL_SEC,
            stale_ttl_sec=QUOTE_STALE_TTL_SEC,
            timeout_sec=QUOTE_FETCH_TIMEOUT_SEC,
            namespace="single_quote_fetch",
            max_concurrent=_executor_workers(),
        )
        if price_data and float(price_data.get("price") or 0) > 0:
            _market_cache.set(fresh_key, price_data, QUOTE_CACHE_TTL_SEC)
            _market_cache.set(stale_key, price_data, QUOTE_STALE_TTL_SEC)
            return normalize_price_payload(market, symbol, price_data)
    except RequestGuardError as exc:
        logger.info("Price fetch guarded for %s:%s - %s", market, symbol, exc)
    except Exception as exc:
        logger.error("Failed to fetch price %s:%s - %s", market, symbol, exc)

    stale = _market_cache.get(stale_key)
    if isinstance(stale, dict) and float(stale.get("price") or 0) > 0:
        return normalize_price_payload(market, symbol, stale, cached=True, stale=True)

    return empty_price(market, symbol, error="unavailable")


def get_price_map(watchlist: list, timeout_sec: int = 30) -> list:
    """Fetch quote snapshots for watchlist rows in parallel."""
    results = []
    futures = {}
    for item in watchlist:
        market = item.get("market", "")
        symbol = item.get("symbol", "")
        if market and symbol:
            future = executor.submit(get_single_price, market, symbol)
            futures[future] = (market, symbol)

    completed = set()
    try:
        for future in as_completed(futures, timeout=timeout_sec):
            completed.add(future)
            market, symbol = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                logger.warning("Price fetch failed: %s:%s - %s", market, symbol, exc)
                results.append(_cached_or_empty(market, symbol, "failed"))
    except FuturesTimeoutError:
        for future, (market, symbol) in futures.items():
            if future not in completed:
                logger.warning("Price fetch timed out: %s:%s", market, symbol)
                results.append(_cached_or_empty(market, symbol, "timeout"))

    return results


def _cached_or_empty(market: str, symbol: str, error: str) -> dict:
    stale = _market_cache.get(quote_cache_key(market, symbol, stale=True))
    if isinstance(stale, dict) and float(stale.get("price") or 0) > 0:
        return normalize_price_payload(market, symbol, stale, cached=True, stale=True)
    return empty_price(market, symbol, error=error)

