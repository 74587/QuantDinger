from datetime import datetime, timedelta, timezone

import pandas as pd

from app.services.strategy_v2 import market_data


def test_market_data_normalizes_numeric_time_series_and_lowercase_timeframe(monkeypatch):
    captured = {}

    def get_kline(**kwargs):
        captured.update(kwargs)
        return [
            {
                "time": 1767225600000,
                "open": 100,
                "high": 102,
                "low": 99,
                "close": 101,
                "volume": 10,
            },
            {
                "time": 1767240000000,
                "open": 101,
                "high": 103,
                "low": 100,
                "close": 102,
                "volume": 11,
            },
        ]

    monkeypatch.setattr(market_data.DataSourceFactory, "get_kline", get_kline)
    monkeypatch.setattr(market_data._cache, "get", lambda _key: None)
    monkeypatch.setattr(market_data._cache, "put", lambda *_args: None)

    frame = market_data.load_strategy_frame(
        "Crypto",
        "BTC/USDT",
        "4h",
        datetime(2026, 1, 1),
        datetime(2026, 1, 1, 4),
        market_type="spot",
    )

    assert len(frame) == 2
    assert frame.index.tz is None
    assert captured["timeframe"] == "4H"
    assert captured["limit"] < 250
    assert captured["after_time"] == int(datetime(2025, 12, 31, 20, tzinfo=timezone.utc).timestamp())
    assert captured["before_time"] == int(datetime(2026, 1, 1, 8, tzinfo=timezone.utc).timestamp())


def test_four_hour_year_requests_enough_bars(monkeypatch):
    captured = {}

    def get_kline(**kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(market_data.DataSourceFactory, "get_kline", get_kline)
    monkeypatch.setattr(market_data._cache, "get", lambda _key: None)

    market_data.load_strategy_frame(
        "Crypto",
        "BTC/USDT",
        "4h",
        datetime(2025, 1, 1),
        datetime(2026, 1, 1),
        market_type="spot",
    )

    assert captured["limit"] > 2400


def test_market_data_normalizes_naive_and_aware_datetimes_to_utc():
    naive = datetime(2026, 7, 19, 4, 14, 13)
    shanghai = timezone(timedelta(hours=8))
    aware = datetime(2026, 7, 19, 12, 14, 13, tzinfo=shanghai)

    normalized_naive = market_data._normalize_utc_datetime(naive)
    normalized_aware = market_data._normalize_utc_datetime(aware)

    assert normalized_naive == datetime(2026, 7, 19, 4, 14, 13, tzinfo=timezone.utc)
    assert normalized_aware == normalized_naive
    assert normalized_naive.timestamp() == normalized_aware.timestamp()


def test_crypto_market_data_rejects_partial_historical_window(monkeypatch):
    monkeypatch.setattr(market_data._cache, "get", lambda _key: None)
    monkeypatch.setattr(market_data._cache, "put", lambda *_args: None)
    monkeypatch.setattr(
        market_data.DataSourceFactory,
        "get_kline",
        lambda **_kwargs: [
            {
                "time": int(datetime(2026, 8, 23, tzinfo=timezone.utc).timestamp()),
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "volume": 10,
            },
            {
                "time": int(datetime(2026, 8, 30, tzinfo=timezone.utc).timestamp()),
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "volume": 10,
            },
        ],
    )

    frame = market_data.load_strategy_frame(
        "Crypto",
        "ETH/USDT",
        "1m",
        datetime(2026, 8, 1),
        datetime(2026, 8, 30),
        market_type="swap",
    )

    assert frame.empty


def test_crypto_market_data_ignores_partial_cached_window(monkeypatch):
    partial = pd.DataFrame(
        {
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.0, 101.0],
            "volume": [10.0, 11.0],
        },
        index=pd.DatetimeIndex(["2026-07-23", "2026-07-30"]),
    )
    fresh_rows = [
        {
            "time": int(timestamp.timestamp()),
            "open": 100,
            "high": 101,
            "low": 99,
            "close": 100,
            "volume": 10,
        }
        for timestamp in pd.date_range("2026-07-01", "2026-07-30", freq="1D", tz="UTC")
    ]
    calls = []
    monkeypatch.setattr(market_data._cache, "get", lambda _key: partial)
    monkeypatch.setattr(market_data._cache, "put", lambda *_args: None)
    monkeypatch.setattr(
        market_data.DataSourceFactory,
        "get_kline",
        lambda **_kwargs: calls.append(True) or fresh_rows,
    )

    frame = market_data.load_strategy_frame(
        "Crypto",
        "ETH/USDT",
        "1d",
        datetime(2026, 7, 1),
        datetime(2026, 7, 30),
        market_type="swap",
    )

    assert calls == [True]
    assert frame.index.min() == pd.Timestamp("2026-07-01")
