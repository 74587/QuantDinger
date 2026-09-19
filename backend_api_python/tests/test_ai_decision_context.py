from datetime import datetime, timezone

import pandas as pd

from app.services.ai_decision_context import (
    build_market_evidence,
    build_quick_trade_decision_context,
    build_strategy_decision_context,
    summarize_market_bars,
)


def _bars(count=80, start=2_000.0, step=2.0):
    now = datetime.now(timezone.utc).timestamp()
    return [
        {
            "time": now - (count - index) * 60,
            "open": start + index * step - 0.5,
            "high": start + index * step + 2.0,
            "low": start + index * step - 2.0,
            "close": start + index * step,
            "volume": 100 + index,
        }
        for index in range(count)
    ]


def test_market_summary_contains_directional_and_risk_evidence():
    summary = summarize_market_bars(_bars(), timeframe="15m", reference_price=2_160.0)

    assert summary["available"] is True
    assert summary["trend"] in {"uptrend", "strong_uptrend"}
    assert summary["return_20_bar_pct"] > 0
    assert summary["rsi14"] is not None
    assert summary["atr14_pct"] > 0
    assert summary["data_age_seconds"] >= 0
    assert summary["interval_seconds"] == 900
    assert summary["is_stale"] is False


def test_runtime_frequency_frames_are_reused_without_market_requests():
    class Klines:
        def __init__(self):
            self.cache = self
            self.keys = []

        def get(self, key):
            self.keys.append(key)
            return None

    service = Klines()
    frame = pd.DataFrame(_bars()).set_index("time")
    evidence = build_market_evidence(
        market="Crypto",
        symbol="ETH/USDT",
        timeframe="15m",
        exchange_id="binance",
        market_type="spot",
        reference_price=2_160.0,
        primary_frame=frame,
        frame_bundle={
            "15m": frame,
            "1h": frame,
            "4h": frame,
        },
        kline_service=service,
    )

    assert evidence["data_quality"] == "complete"
    assert set(evidence["available_timeframes"]) == {"15m", "1h", "4h"}
    assert service.keys == []


def test_missing_market_evidence_reads_cache_only():
    class Cache:
        def __init__(self):
            self.keys = []

        def get(self, key):
            self.keys.append(key)
            return _bars() if "kline:latest:Crypto:binance:spot::ETH/USDT:1h" == key else None

    class Klines:
        def __init__(self):
            self.cache = Cache()

        def get_kline(self, **kwargs):
            raise AssertionError("The order boundary must not fetch market data")

    service = Klines()
    evidence = build_market_evidence(
        market="Crypto",
        symbol="ETH/USDT",
        timeframe="15m",
        exchange_id="binance",
        market_type="spot",
        kline_service=service,
    )

    assert evidence["data_quality"] == "partial"
    assert evidence["available_timeframes"] == ["1h"]
    assert service.cache.keys


def test_strategy_context_includes_bound_parameters_and_freshness(monkeypatch):
    monkeypatch.setattr(
        "app.services.ai_decision_context._strategy_performance",
        lambda _strategy_id: {"completed_exits": 2},
    )
    frame = pd.DataFrame(_bars()).set_index("time")
    context = build_strategy_decision_context(
        values={
            "symbol": "ETH/USDT",
            "market_category": "Crypto",
            "market_type": "spot",
            "current_price": 2_160.0,
            "strategy_id": 9,
            "market_frame": frame,
            "market_frames": {"15m": frame, "1h": frame, "4h": frame},
            "trading_config": {
                "direction_mode": "long_only",
                "params": {"fast_period": 20, "slow_period": 60, "private": {"ignored": True}},
            },
        },
        strategy={"strategy_name": "Dual Moving Average", "timeframe": "15m"},
        order_budget={"allowed": True},
        strategy_equity=950.0,
        initial_capital=1_000.0,
        entry_percent=50.0,
    )

    assert context["strategy"]["parameters"] == {"fast_period": 20, "slow_period": 60}
    assert context["market_evidence"]["data_quality"] == "complete"
    assert context["market_evidence"]["stale_timeframes"] == []
    assert context["portfolio_risk"]["drawdown_from_initial_pct"] == -5.0


def test_quick_trade_context_includes_live_evidence_and_protection(monkeypatch):
    monkeypatch.setattr(
        "app.services.ai_decision_context._cached_market_rows",
        lambda *args, **kwargs: _bars(),
    )
    context = build_quick_trade_decision_context({
        "symbol": "ETH/USDT",
        "side": "buy",
        "market_type": "spot",
        "exchange_id": "binance",
        "base_qty": 0.1,
        "order_notional_usdt": 216.0,
        "usdt_amount": 216.0,
        "tp_price": 2_220.0,
        "sl_price": 2_120.0,
        "bal": {"available": 500.0, "total": 700.0},
    })

    assert context["context_version"] == 2
    assert context["market_evidence"]["data_quality"] == "complete"
    assert context["portfolio_risk"]["available_balance"] == 500.0
    assert context["portfolio_risk"]["risk_reward_ratio"] == 1.5
