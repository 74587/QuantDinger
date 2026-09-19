from app.services import ai_decision_filter as module


def _request(**overrides):
    values = {
        "user_id": 7,
        "source_type": "strategy",
        "strategy_id": 12,
        "strategy_run_id": 21,
        "symbol": "BTC/USDT",
        "action": "open_long",
        "market_type": "swap",
        "quantity": 0.01,
        "reference_price": 80_000,
        "leverage": 2,
    }
    values.update(overrides)
    return module.AIDecisionRequest(**values)


def test_exit_orders_bypass_ai(monkeypatch):
    captured = []
    monkeypatch.setattr(module.AIDecisionFilter, "_persist", staticmethod(lambda request, result: captured.append(result)))
    result = module.AIDecisionFilter().evaluate(_request(action="close_long"), enabled=True)
    assert result.allowed is True
    assert result.decision == "skipped"
    assert result.reason == "exit_orders_are_not_filtered"
    assert captured and captured[0].decision_id == result.decision_id


def test_special_strategy_types_bypass_ai(monkeypatch):
    monkeypatch.setattr(module.AIDecisionFilter, "_persist", staticmethod(lambda request, result: None))
    result = module.AIDecisionFilter().evaluate(_request(strategy_type="grid"), enabled=True)
    assert result.allowed is True
    assert result.reason == "strategy_type_not_supported"


def test_jev_rejection_blocks_entry(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "answers": {
                    "entry_decision": {
                        "choice": "reject",
                        "probabilities": {"pass": 0.1, "reject": 0.9},
                        "confidence": 0.9,
                    },
                    "risk_check": {
                        "choice": "block",
                        "probabilities": {"clear": 0.05, "caution": 0.05, "block": 0.9},
                        "confidence": 0.9,
                    },
                }
            }

    captured = {}
    monkeypatch.setattr(module.AIDecisionFilter, "_jev_config", staticmethod(lambda: {
        "api_key": "secret",
        "base_url": "https://api.typesafe.ai/v1",
        "model": "jev-latest",
        "timeout_seconds": "8",
    }))
    monkeypatch.setattr(module.requests, "post", lambda *args, **kwargs: (captured.update(kwargs) or Response()))
    monkeypatch.setattr(module.AIDecisionFilter, "_persist", staticmethod(lambda request, result: None))
    result = module.AIDecisionFilter().evaluate(_request(), enabled=True)
    assert result.allowed is False
    assert result.provider == "jev"
    assert result.decision == "reject"
    assert result.reason == "jev_entry_rejected:risk_block"
    assert result.checks[1]["confidence"] == 0.9
    assert isinstance(captured["json"]["state"], dict)


def test_malformed_jev_answer_falls_back_to_llm(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "answers": {
                    "entry_decision": {
                        "choice": "pass",
                        "probabilities": {"pass": 0.8, "reject": 0.2},
                        "confidence": 0.6,
                    }
                }
            }

    class LLM:
        def is_configured(self):
            return True

        def get_default_model(self):
            return "fallback-model"

        def call_llm_api(self, *args, **kwargs):
            return '{"decision":"reject","confidence":0.7,"reason":"fallback_check","checks":[]}'

    monkeypatch.setattr(module.AIDecisionFilter, "_jev_config", staticmethod(lambda: {
        "api_key": "secret",
        "base_url": "https://api.typesafe.ai/v1",
        "model": "jev-latest",
        "timeout_seconds": "8",
    }))
    monkeypatch.setattr(module.requests, "post", lambda *args, **kwargs: Response())
    monkeypatch.setattr(module, "LLMService", LLM)
    monkeypatch.setattr(module.AIDecisionFilter, "_persist", staticmethod(lambda request, result: None))
    result = module.AIDecisionFilter().evaluate(_request(), enabled=True)
    assert result.allowed is False
    assert result.provider == "llm"
    assert result.fallback_reason.startswith("jev:")


def test_llm_is_used_when_jev_is_not_configured(monkeypatch):
    class LLM:
        def is_configured(self):
            return True

        def get_default_model(self):
            return "configured-model"

        def call_llm_api(self, *args, **kwargs):
            return '{"decision":"pass","confidence":0.8,"reason":"clear","checks":[]}'

    monkeypatch.setattr(module.AIDecisionFilter, "_jev_config", staticmethod(lambda: {
        "api_key": "",
        "base_url": "https://api.typesafe.ai/v1",
        "model": "jev-latest",
        "timeout_seconds": "8",
    }))
    monkeypatch.setattr(module, "LLMService", LLM)
    monkeypatch.setattr(module.AIDecisionFilter, "_persist", staticmethod(lambda request, result: None))
    result = module.AIDecisionFilter().evaluate(_request(), enabled=True)
    assert result.allowed is True
    assert result.provider == "llm"
    assert result.model == "configured-model"


def test_jev_config_reads_the_latest_persisted_settings(monkeypatch):
    from app.services.settings import env_file

    monkeypatch.setenv("JEV_API_KEY", "stale-process-key")
    monkeypatch.setattr(env_file, "read_env_file", lambda: {
        "JEV_API_KEY": "saved-key",
        "JEV_BASE_URL": "https://example.test/v1",
        "JEV_MODEL": "saved-model",
        "JEV_TIMEOUT_SECONDS": "5",
    })

    assert module.AIDecisionFilter._jev_config() == {
        "api_key": "saved-key",
        "base_url": "https://example.test/v1",
        "model": "saved-model",
        "timeout_seconds": "5",
    }
