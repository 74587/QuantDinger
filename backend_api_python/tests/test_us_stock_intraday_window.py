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
