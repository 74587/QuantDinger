import pytest

from app.services.ai_report_pdf import _report_pdf_labels, build_ai_report_pdf


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
