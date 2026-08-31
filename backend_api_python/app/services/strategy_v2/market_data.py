"""Market-data loading for Strategy API V2 backtests."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from app.data_sources import DataSourceFactory
from app.data_sources.errors import MarketDataUnavailableError
from app.services.backtest_cache import KlineCache
from app.utils.logger import get_logger

logger = get_logger(__name__)
_cache = KlineCache()

TIMEFRAME_SECONDS = {
    "1m": 60,
    "3m": 180,
    "5m": 300,
    "15m": 900,
    "30m": 1800,
    "1h": 3600,
    "4h": 14400,
    "1d": 86400,
    "1w": 604800,
}

PROVIDER_TIMEFRAMES = {
    "1h": "1H",
    "4h": "4H",
    "1d": "1D",
    "1w": "1W",
}


def _normalize_utc_datetime(value: datetime) -> datetime:
    """Return an aware UTC datetime, interpreting naive inputs as UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _covers_crypto_window(
    frame: pd.DataFrame,
    requested_start: pd.Timestamp,
    requested_end: pd.Timestamp,
    timeframe_seconds: int,
) -> bool:
    """Crypto trades continuously, so a historical frame must cover both endpoints."""
    if frame is None or frame.empty:
        return False
    tolerance = pd.Timedelta(seconds=max(1, timeframe_seconds) * 3)
    expected_rows = max(
        1,
        int((requested_end - requested_start).total_seconds() / max(1, timeframe_seconds)) + 1,
    )
    coverage_ratio = len(frame) / expected_rows
    return bool(
        frame.index.min() <= requested_start + tolerance
        and frame.index.max() >= requested_end - tolerance
        and coverage_ratio >= 0.98
    )


def load_strategy_frame(
    market: str,
    symbol: str,
    timeframe: str,
    start_date: datetime,
    end_date: datetime,
    *,
    market_type: Optional[str] = None,
    exchange_id: Optional[str] = None,
) -> pd.DataFrame:
    start_utc = _normalize_utc_datetime(start_date)
    end_utc = _normalize_utc_datetime(end_date)
    total_seconds = max(1.0, (end_utc - start_utc).total_seconds())
    normalized_timeframe = str(timeframe or "1d").strip().lower()
    timeframe_seconds = TIMEFRAME_SECONDS.get(normalized_timeframe, 86400)
    provider_timeframe = PROVIDER_TIMEFRAMES.get(normalized_timeframe, normalized_timeframe)
    limit = int(math.ceil(total_seconds / timeframe_seconds * 1.15) + 200)
    after_time = int((start_utc - timedelta(seconds=timeframe_seconds)).timestamp())
    before_time = int((end_utc + timedelta(seconds=timeframe_seconds)).timestamp())
    cache_key = ":".join((
        str(market),
        str(symbol),
        str(timeframe),
        str(market_type or ""),
        str(exchange_id or ""),
        start_utc.isoformat(),
        end_utc.isoformat(),
    ))
    requested_start = pd.Timestamp(start_utc).tz_localize(None)
    requested_end = pd.Timestamp(end_utc).tz_localize(None)
    closed_bar_cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=timeframe_seconds)
    coverage_end = min(requested_end, pd.Timestamp(closed_bar_cutoff))
    cached = _cache.get(cache_key)
    if cached is not None and not cached.empty:
        if str(market or "").strip().lower() != "crypto" or _covers_crypto_window(
            cached,
            requested_start,
            coverage_end,
            timeframe_seconds,
        ):
            return cached.copy()
        logger.warning(
            "Ignored incomplete cached crypto history for %s %s: requested=%s~%s, actual=%s~%s",
            symbol,
            timeframe,
            requested_start,
            coverage_end,
            cached.index.min(),
            cached.index.max(),
        )
    try:
        kwargs = {
            "market": market,
            "symbol": symbol,
            "timeframe": provider_timeframe,
            "limit": limit,
            "before_time": before_time,
            "after_time": after_time,
            "exchange_id": exchange_id,
            "market_type": market_type,
        }
        if exchange_id:
            rows, failure = DataSourceFactory.get_kline_with_diagnostics(**kwargs)
            if not rows and failure is not None:
                raise MarketDataUnavailableError(failure)
        else:
            rows = DataSourceFactory.get_kline(**kwargs)
    except MarketDataUnavailableError:
        raise
    except Exception as exc:
        logger.warning(
            "Strategy market-data fetch failed for %s:%s %s via %s/%s: %s",
            market,
            symbol,
            timeframe,
            exchange_id or "default",
            market_type or "default",
            exc,
        )
        return pd.DataFrame()
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    time_column = next((name for name in ("time", "timestamp", "datetime", "date") if name in frame.columns), "")
    if not time_column:
        return pd.DataFrame()
    raw_time = frame.pop(time_column)
    numeric = pd.to_numeric(raw_time, errors="coerce")
    if numeric.notna().any():
        unit = "ms" if float(numeric.dropna().abs().median()) > 10_000_000_000 else "s"
        converted = pd.to_datetime(numeric, unit=unit, errors="coerce", utc=True)
        frame.index = pd.DatetimeIndex(converted).tz_convert(None)
    else:
        converted = pd.to_datetime(raw_time, errors="coerce", utc=True)
        frame.index = pd.DatetimeIndex(converted).tz_convert(None)
    frame = frame[~frame.index.isna()].sort_index()
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    if any(column not in frame.columns for column in ("open", "high", "low", "close")):
        return pd.DataFrame()
    for column in ("open", "high", "low", "close", "volume"):
        if column not in frame.columns:
            frame[column] = 0.0
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame[(frame.index >= requested_start) & (frame.index <= requested_end)].dropna(
        subset=["open", "high", "low", "close"]
    )
    if requested_end >= closed_bar_cutoff:
        frame = frame[frame.index <= pd.Timestamp(closed_bar_cutoff)]
    if (
        str(market or "").strip().lower() == "crypto"
        and not _covers_crypto_window(frame, requested_start, coverage_end, timeframe_seconds)
    ):
        if not frame.empty:
            logger.error(
                "Rejected incomplete crypto history for %s %s: requested=%s~%s, actual=%s~%s",
                symbol,
                timeframe,
                requested_start,
                coverage_end,
                frame.index.min(),
                frame.index.max(),
            )
        return pd.DataFrame()
    if not frame.empty:
        _cache.put(cache_key, frame, timeframe)
    return frame.copy()
