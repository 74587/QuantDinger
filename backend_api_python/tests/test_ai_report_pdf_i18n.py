import pytest

from app.services.ai_report_pdf import _professional_pdf_projection, _report_pdf_labels, build_ai_report_pdf


def test_professional_report_v1_is_projected_for_pdf_without_legacy_input():
    projection = _professional_pdf_projection({
        "schema_version": "professional_report_v1",
        "instrument": {"market": "HKStock", "symbol": "00700", "canonical_symbol": "00700"},
        "decision_profile": {"decision": "HOLD", "confidence": 35},
        "executive_summary": "数据质量不足，保持观望。",
        "risk_plan": {"net_risk_reward": None, "warnings": ["no_directional_position"]},
        "dimensions": [{"key": "technical", "score": 42, "narrative": "趋势偏弱"}],
        "claims": [{"kind": "risk", "text": "关键数据缺失"}],
        "scenarios": [],
        "evidence_snapshot": {
            "observations": [{"metric": "quote.price", "value": 438.4, "source": "provider", "as_of": "2026-09-07T00:00:00Z"}],
        },
    })

    assert projection["market"] == "HKStock"
    assert projection["symbol"] == "00700"
    assert projection["market_data"]["current_price"] == 438.4
    assert projection["detailed_analysis"]["technical"] == "趋势偏弱"
    assert projection["risks"] == ["关键数据缺失"]


SUPPORTED_LANGUAGES = (
    "en-US",
    "zh-CN",
    "zh-TW",
    "ja-JP",
    "ko-KR",
    "de-DE",
    "fr-FR",
    "ru-RU",
    "ar-SA",
    "th-TH",
    "vi-VN",
)


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
def test_report_pdf_has_complete_labels_for_every_supported_language(language):
    labels = _report_pdf_labels(language)

    required = {
        "title",
        "subtitle",
        "target",
        "generated",
        "decision",
        "confidence",
        "summary",
        "plan",
        "scores",
        "trend",
        "crypto",
        "details",
        "reasons",
        "risks",
        "indicators",
        "rr_warning",
        "rr_warning_text",
        "disclaimer",
        "field_trend",
        "field_direction",
        "field_score",
        "field_strength",
        "field_summary",
        "field_value",
        "field_signal",
        "current_price",
        "change_24h",
        "entry",
        "stop_loss",
        "take_profit",
        "risk_reward",
        "horizon",
        "outlook",
    }

    assert required <= labels.keys()
    assert all(str(labels[key]).strip() for key in required)
    if language != "en-US":
        assert labels["title"] != _report_pdf_labels("en-US")["title"]
        assert labels["rr_warning"] != _report_pdf_labels("en-US")["rr_warning"]


@pytest.mark.parametrize("language", SUPPORTED_LANGUAGES)
def test_report_pdf_renders_for_every_supported_language(language):
    pdf = build_ai_report_pdf(
        {
            "market": "Crypto",
            "symbol": "BTC/USDT",
            "decision": "BUY",
            "confidence": 70,
            "summary": "Test summary",
            "trend_outlook": {"trend": "up", "strength": "moderate"},
            "trading_plan": {
                "entry_price": 100,
                "stop_loss": 92,
                "take_profit": 104,
                "risk_reward_ratio": 0.5,
                "rr_warning": {"code": "risk_reward_below_one"},
            },
        },
        language=language,
    )

    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 1_000
