import copy
import threading

from app.services.fast_analysis import FastAnalysisService
from app.services.market_data_collector import MarketDataCollector


def test_fundamental_fetch_is_cached_across_timeframes(monkeypatch):
    collector = MarketDataCollector.__new__(MarketDataCollector)
    collector._fundamental_cache = {}
    collector._fundamental_cache_lock = threading.RLock()
    calls = []
    payload = {
        "source": "test",
        "financial_statements": {"latest_quarter": {"period_end": "2026-06-30"}},
    }

    def fetch(market, symbol):
        calls.append((market, symbol))
        return copy.deepcopy(payload)

    collector._fetch_fundamental_uncached = fetch

    first = collector._get_fundamental("USStock", "spcx")
    first["source"] = "mutated-by-caller"
    second = collector._get_fundamental("USStock", "SPCX")

    assert calls == [("USStock", "SPCX")]
    assert second == payload


def test_collect_all_honours_caller_core_timeout(monkeypatch):
    from app.services import market_data_collector as module

    collector = MarketDataCollector.__new__(MarketDataCollector)
    collector._get_price = lambda *_args: {"price": 10}
    collector._get_kline = lambda *_args: [{"close": 10}]
    collector._get_fundamental = lambda *_args: {"source": "test"}
    collector._get_company = lambda *_args: {"name": "Test"}
    collector._calculate_indicators = lambda *_args: {"current_price": 10}
    captured = {}
    real_as_completed = module.as_completed

    def recording_as_completed(futures, timeout=None):
        captured["timeout"] = timeout
        return real_as_completed(futures, timeout=timeout)

    monkeypatch.setattr(module, "as_completed", recording_as_completed)

    result = collector.collect_all(
        "USStock", "TEST", include_macro=False, include_news=False, timeout=25
    )

    assert captured["timeout"] == 25.0
    assert result["fundamental"] == {"source": "test"}
    assert result["_meta"]["failed_items"] == []


def test_later_timeframe_backfills_primary_fundamentals_and_repairs_meta():
    primary = {
        "fundamental": {},
        "company": {},
        "_meta": {
            "success_items": ["price", "kline"],
            "failed_items": ["fundamental", "company"],
        },
    }
    candidate = {
        "fundamental": {"source": "yfinance", "revenue": 123},
        "company": {"name": "Test Corp"},
    }

    FastAnalysisService._backfill_primary_enrichment(primary, candidate)

    assert primary["fundamental"]["revenue"] == 123
    assert primary["company"]["name"] == "Test Corp"
    assert set(primary["_meta"]["success_items"]) >= {"fundamental", "company"}
    assert "fundamental" not in primary["_meta"]["failed_items"]
    assert "company" not in primary["_meta"]["failed_items"]
