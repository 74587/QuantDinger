from datetime import datetime, timedelta

from app.data_sources import us_stock
from app.data_sources.us_stock import USStockDataSource


class _EmptyChartResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"chart": {"result": []}}


def test_yahoo_chart_intraday_request_does_not_extend_end_date(monkeypatch):
    captured = {}

    def fake_get(_url, **kwargs):
        captured.update(kwargs["params"])
        return _EmptyChartResponse()

    monkeypatch.setattr(us_stock.requests, "get", fake_get)
    source = USStockDataSource.__new__(USStockDataSource)
    start = datetime(2026, 9, 8, 13, 30)
    end = datetime(2026, 9, 14, 15, 30)

    source._fetch_yahoo_chart("NVDA", "1m", start, end, 500)

    assert captured["period1"] == int(start.timestamp())
    assert captured["period2"] == int(end.timestamp())


def test_yahoo_chart_daily_request_keeps_inclusive_end_date(monkeypatch):
    captured = {}

    def fake_get(_url, **kwargs):
        captured.update(kwargs["params"])
        return _EmptyChartResponse()

    monkeypatch.setattr(us_stock.requests, "get", fake_get)
    source = USStockDataSource.__new__(USStockDataSource)
    start = datetime(2026, 9, 8)
    end = datetime(2026, 9, 14)

    source._fetch_yahoo_chart("NVDA", "1d", start, end, 500)

    assert captured["period2"] == int((end + timedelta(days=1)).timestamp())


def test_yahoo_chart_splits_long_one_minute_windows(monkeypatch):
    requests = []

    def fake_get(_url, **kwargs):
        requests.append(dict(kwargs["params"]))
        return _EmptyChartResponse()

    monkeypatch.setattr(us_stock.requests, "get", fake_get)
    source = USStockDataSource.__new__(USStockDataSource)
    start = datetime(2026, 9, 1, 13, 30)
    end = datetime(2026, 9, 14, 15, 30)

    source._fetch_yahoo_chart("NVDA", "1m", start, end, 5000)

    assert len(requests) == 2
    assert requests[0]["period1"] == int(start.timestamp())
    assert requests[0]["period2"] == int((start + timedelta(days=7)).timestamp())
    assert requests[1]["period1"] == int((start + timedelta(days=7)).timestamp())
    assert requests[1]["period2"] == int(end.timestamp())


def test_yfinance_intraday_request_preserves_datetime_bounds(monkeypatch):
    captured = {}

    class _Ticker:
        def history(self, **kwargs):
            captured.update(kwargs)
            return None

    monkeypatch.setattr(us_stock.yf, "Ticker", lambda _symbol: _Ticker())
    source = USStockDataSource.__new__(USStockDataSource)
    start = datetime(2026, 9, 8, 13, 30)
    end = datetime(2026, 9, 14, 15, 30)

    source._fetch_yfinance("NVDA", "1m", start, end)

    assert captured["start"] == start
    assert captured["end"] == end


class _MinuteChartResponse:
    def __init__(self, timestamps):
        self._timestamps = timestamps

    def raise_for_status(self):
        return None

    def json(self):
        count = len(self._timestamps)
        return {"chart": {"result": [{
            "timestamp": self._timestamps,
            "indicators": {"quote": [{
                "open": [100.0 + index for index in range(count)],
                "high": [101.0 + index for index in range(count)],
                "low": [99.0 + index for index in range(count)],
                "close": [100.5 + index for index in range(count)],
                "volume": [10] * count,
            }]},
        }]}}


def test_three_minute_yahoo_bars_are_aligned_before_the_result_is_limited(monkeypatch):
    session_open = int(datetime(2026, 9, 14, 13, 30).timestamp())
    timestamps = [session_open + 60 * index for index in range(8)]
    captured = {}

    def fake_get(_url, **kwargs):
        captured.update(kwargs["params"])
        return _MinuteChartResponse(timestamps)

    monkeypatch.setattr(us_stock.requests, "get", fake_get)
    source = USStockDataSource.__new__(USStockDataSource)

    bars = source.get_kline("NVDA", "3m", 2, before_time=session_open + 3600)

    assert captured["interval"] == "1m"
    assert [bar["time"] for bar in bars] == [session_open, session_open + 180]
    assert bars[0] == {
        "time": session_open,
        "open": 100.0,
        "high": 103.0,
        "low": 99.0,
        "close": 102.5,
        "volume": 30,
    }
    assert bars[1]["close"] == 105.5


def test_three_minute_yahoo_bars_do_not_bridge_a_missing_minute(monkeypatch):
    session_open = int(datetime(2026, 9, 14, 13, 30).timestamp())
    timestamps = [
        session_open,
        session_open + 60,
        session_open + 120,
        session_open + 240,
        session_open + 300,
        session_open + 360,
    ]

    monkeypatch.setattr(
        us_stock.requests,
        "get",
        lambda *_args, **_kwargs: _MinuteChartResponse(timestamps),
    )
    source = USStockDataSource.__new__(USStockDataSource)

    bars = source.get_kline("NVDA", "3m", 3, before_time=session_open + 3600)

    assert [bar["time"] for bar in bars] == [session_open]
