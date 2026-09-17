import pytest

from app.services.strategy import StrategyService


def test_deployment_payload_accepts_direction_mode():
    payload = StrategyService._deployment_payload(
        {
            "sourceId": 9,
            "name": "Dual strategy",
            "initialCapital": 1_000,
            "executionMode": "live",
            "directionMode": "both",
            "positionSide": "neutral",
        }
    )

    assert payload["directionMode"] == "both"
    assert payload["positionSide"] == "neutral"


def test_deployment_payload_still_rejects_unknown_fields():
    with pytest.raises(ValueError, match="strategyV2.unsupportedFields"):
        StrategyService._deployment_payload({"sourceId": 9, "unknown": True})


def test_deployment_payload_rejects_removed_shared_account_risk_controls():
    with pytest.raises(ValueError, match="strategyV2.unsupportedFields"):
        StrategyService._deployment_payload({"sourceId": 9, "accountRisk": {"max_gross_leverage": 2}})
