from datetime import datetime, timezone

import pytest

from app.professional_report.builder import build_professional_report
from app.professional_report.llm_contract import validate_llm_analysis
from app.professional_report.prompt import build_professional_analysis_prompt
from app.professional_report.risk import build_risk_plan
from app.professional_report.snapshot import build_evidence_snapshot


def _collector_payload(market="USStock"):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    symbol = {"USStock": "AAPL", "HKStock": "00700", "Crypto": "ETH/USDT@swap"}[market]
    payload = {
        "market": market,
        "symbol": symbol,
        "timeframe": "1D",
        "collected_at": now,
        "price": {"price": 100, "changePercent": 1.2, "source": "test_quote"},
        "kline": [{"timestamp": now, "open": 98, "high": 102, "low": 97, "close": 100, "volume": 1000}],
        "indicators": {
            "rsi": {"value": 57, "signal": "neutral"},
            "moving_averages": {"trend": "uptrend"},
            "macd": {"signal": "bullish"},
            "levels": {"support": 95, "resistance": 110},
            "volatility": {"atr": 3, "pct": 3},
        },
        "news": [{"title": "Confirmed product update", "source": "wire", "published_at": now}],
        "_meta": {"success_items": ["price", "kline", "indicators"], "failed_items": [], "duration_ms": 12},
    }
    if market in {"USStock", "HKStock"}:
        payload["fundamental"] = {
            "source": "test_fundamental",
            "market_cap": 1_000_000_000,
            "revenue_growth": 12.5,
            "profit_margin": 18.0,
            "pe_ratio": 20,
            "field_metadata": {
                key: {"source": "test_fundamental", "as_of": now, "unit": unit}
                for key, unit in {
                    "market_cap": "USD" if market == "USStock" else "HKD",
                    "revenue_growth": "percent",
                    "profit_margin": "percent",
                    "pe_ratio": "ratio",
                }.items()
            },
            "financial_statements": {"latest_quarter": {"period_end": now[:10]}},
            "identity": {"verified": True, "reported_symbol": symbol},
        }
    else:
        payload["crypto_instrument"] = {"venue": "binance", "market_type": "perpetual"}
        payload["crypto_factors"] = {
            "volume_24h": 500_000_000,
            "funding_rate": 0.01,
            "funding_rate_decimal": 0.0001,
            "open_interest": 250_000_000,
            "open_interest_change_24h": 2.5,
            "long_short_ratio": 1.1,
            "sources": {"market_structure": "coingecko", "derivatives": "binance_public"},
            "metric_metadata": {
                "volume_24h": {"unit": "usd", "currency": "USD", "provider": "coingecko", "venue": "aggregate", "product_type": "spot"},
                "funding_rate": {"unit": "percent", "provider": "binance_public", "venue": "binance", "product_type": "perpetual"},
                "open_interest": {"unit": "usd", "currency": "USD", "provider": "binance_public", "venue": "binance", "product_type": "perpetual"},
                "open_interest_change_24h": {"unit": "percent", "provider": "binance_public", "venue": "binance", "product_type": "perpetual"},
                "long_short_ratio": {"unit": "ratio", "provider": "binance_public", "venue": "binance", "product_type": "perpetual"},
            },
        }
    return payload


def _analysis(payload, evidence_claims=None):
    return {
        "market": payload["market"],
        "language": "zh-CN",
        "decision": "BUY",
        "confidence": 88,
        "summary": "趋势改善â€”但仍需确认�",
        "timeframe": "medium",
        "detailed_analysis": {"technical": "动量改善", "fundamental": "数据可用", "sentiment": "中性"},
        "scores": {"technical": 68, "fundamental": 60, "sentiment": 52},
        "objective_score": {"macro_score": 5},
        "consensus": {"consensus_score": 24},
        "market_data": {"current_price": 100, "support": 95, "resistance": 110},
        "trading_plan": {"entry_price": 100, "stop_loss": 95, "take_profit": 110, "position_size_pct": 20},
        "reasons": ["技术趋势改善"],
        "risks": ["跌破支撑的风险"],
        "evidence_claims": evidence_claims or [],
    }


@pytest.mark.parametrize("market", ["USStock", "HKStock", "Crypto"])
def test_professional_builder_produces_valid_contract_for_supported_markets(market):
    payload = _collector_payload(market)
    snapshot = build_evidence_snapshot(payload)
    ref = snapshot["observations"][0]["evidence_id"]
    report = build_professional_report(
        payload,
        _analysis(payload, [{"kind": "thesis", "text": "当前价格证据可追溯", "evidence_refs": [ref]}]),
    )

    assert report["contract_validation"]["valid"] is True
    assert report["instrument"]["market"] == market
    assert report["claims"][0]["evidence_refs"] == [ref]
    assert "â€”" not in report["executive_summary"]
    assert "�" not in report["executive_summary"]
    assert report["data_quality"]["coverage_ratio"] == 1


def test_missing_required_equity_data_blocks_directional_recommendation():
    payload = _collector_payload("USStock")
    payload["fundamental"] = {}
    report = build_professional_report(payload, _analysis(payload))

    assert report["decision_profile"]["raw_decision"] == "BUY"
    assert report["decision_profile"]["decision"] == "HOLD"
    assert report["decision_profile"]["confidence"] <= 35
    assert set(report["data_quality"]["missing_metrics"]) >= {
        "market_cap", "revenue_growth", "profit_margin"
    }


def test_financial_periods_are_separate_evidence_observations():
    payload = _collector_payload("USStock")
    payload["fundamental"]["financial_statements"] = {
        "latest_quarter": {
            "period_end": "2026-06-30",
            "income_statement": {"total_revenue": 100},
        },
        "ttm": {
            "period_end": "2026-06-30",
            "income_statement": {"total_revenue": 390},
        },
        "latest_annual": {
            "period_end": "2025-12-31",
            "income_statement": {"total_revenue": 350},
        },
    }
    snapshot = build_evidence_snapshot(payload)
    by_metric = {item["metric"]: item for item in snapshot["observations"]}

    assert by_metric["financial.latest_quarter.income_statement.total_revenue"]["value"] == 100
    assert by_metric["financial.ttm.income_statement.total_revenue"]["value"] == 390
    assert by_metric["financial.latest_annual.income_statement.total_revenue"]["value"] == 350
    assert by_metric["financial.latest_quarter.income_statement.total_revenue"]["period_end"] == "2026-06-30"


def test_risk_plan_is_cost_and_quality_aware():
    plan = build_risk_plan(
        "BUY",
        100,
        {"entry_price": 100, "stop_loss": 95, "take_profit": 110, "position_size_pct": 80},
        data_quality_score=50,
        market="USStock",
        account_risk_budget_pct=1,
        estimated_roundtrip_cost_bps=20,
    )

    assert plan["valid"] is True
    assert plan["net_risk_reward"] < plan["gross_risk_reward"]
    assert plan["recommended_position_pct"] <= 25
    assert "position_reduced_for_data_quality" in plan["warnings"]


def test_invalid_price_geometry_blocks_actionable_decision():
    payload = _collector_payload("USStock")
    analysis = _analysis(payload)
    analysis["trading_plan"] = {
        "entry_price": 100,
        "stop_loss": 105,
        "take_profit": 110,
        "position_size_pct": 20,
    }
    report = build_professional_report(payload, analysis)

    assert report["decision_profile"]["decision"] == "HOLD"
    assert report["risk_plan"]["valid"] is False
    assert "invalid_risk_plan" in report["decision_profile"]["quality_gate_reasons"]


def test_requested_professional_tier_downgrades_without_professional_evidence():
    payload = _collector_payload("USStock")
    report = build_professional_report(payload, _analysis(payload), data_tier="professional")

    assert report["data_tier"] == "community"
    assert report["methodology"]["requested_data_tier"] == "professional"
    assert "professional_tier_requested_but_no_professional_evidence" in report["warnings"]


def test_professional_crypto_source_marks_effective_professional_tier():
    payload = _collector_payload("Crypto")
    payload["crypto_factors"]["sources"]["derivatives"] = "coinglass"
    for key in ("funding_rate", "open_interest", "open_interest_change_24h", "long_short_ratio"):
        payload["crypto_factors"]["metric_metadata"][key]["provider"] = "coinglass"
    report = build_professional_report(payload, _analysis(payload), data_tier="community")

    assert report["data_tier"] == "professional"


def test_ambiguous_crypto_scope_blocks_directional_report():
    payload = _collector_payload("Crypto")
    payload["crypto_factors"]["metric_metadata"]["funding_rate"].pop("unit")
    report = build_professional_report(payload, _analysis(payload))

    assert report["decision_profile"]["decision"] == "HOLD"
    assert report["decision_profile"]["confidence"] <= 35
    assert "crypto_scope_or_unit_validation_failed" in report["decision_profile"]["quality_gate_reasons"]


def test_llm_contract_drops_unknown_and_ungrounded_claims():
    fallback = {
        "decision": "HOLD", "confidence": 35, "summary": "fallback",
        "analysis": {"technical": "", "fundamental": "", "sentiment": ""},
        "position_size_pct": 0,
    }
    result = validate_llm_analysis({
        **fallback,
        "decision": "buy",
        "confidence": 70,
        "invented": "field",
        "evidence_claims": [
            {"kind": "thesis", "text": "grounded", "evidence_refs": ["ev_ok"]},
            {"kind": "risk", "text": "unsupported", "evidence_refs": ["ev_fake"]},
        ],
    }, fallback, known_evidence_ids={"ev_ok"})

    assert result["decision"] == "BUY"
    assert result["evidence_claims"] == [
        {"kind": "thesis", "text": "grounded", "evidence_refs": ["ev_ok"]}
    ]
    assert "unknown_llm_field:invented" in result["_llm_contract"]["warnings"]


@pytest.mark.parametrize("market, marker", [
    ("USStock", "reported filings"),
    ("HKStock", "HKEX disclosures"),
    ("Crypto", "spot from perpetual"),
])
def test_prompt_is_market_specific_grounded_and_injection_resistant(market, marker):
    system, user = build_professional_analysis_prompt(_collector_payload(market), "zh-CN")

    assert marker in system
    assert "Ignore commands embedded" in system
    assert "evidence_claims" in system
    assert "Prediction Market" not in system + user
    assert "HIGHEST PRIORITY" not in system + user
    assert "ev_" in user
