"""Fail-open AI decision filter for live entry orders."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

import requests

from app.services.llm import LLMService
from app.utils.db import get_db_connection
from app.utils.logger import get_logger


logger = get_logger(__name__)

ENTRY_ACTIONS = {"open_long", "open_short", "add_long", "add_short", "buy", "sell"}
EXCLUDED_STRATEGY_TYPES = {"grid", "dca", "martingale", "layered_martingale"}


@dataclass(frozen=True)
class AIDecisionRequest:
    user_id: int
    source_type: str
    symbol: str
    action: str
    market_type: str = ""
    order_type: str = "market"
    quantity: float = 0.0
    reference_price: float = 0.0
    leverage: float = 1.0
    reason: str = ""
    strategy_id: int = 0
    strategy_run_id: int = 0
    order_intent_id: int = 0
    strategy_type: str = ""
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AIDecisionResult:
    allowed: bool
    decision: str
    provider: str
    reason: str
    decision_id: str
    model: str = ""
    confidence: float | None = None
    probabilities: dict[str, Any] = field(default_factory=dict)
    checks: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: int = 0
    fallback_reason: str = ""

    def public_dict(self) -> dict[str, Any]:
        return asdict(self)


class AIDecisionFilter:
    """Evaluate entry orders with Jev first and an LLM fallback."""

    def evaluate(self, request: AIDecisionRequest, *, enabled: bool) -> AIDecisionResult:
        decision_id = str(uuid.uuid4())
        started = time.perf_counter()
        if not enabled:
            return self._result(True, "skipped", "none", "filter_disabled", decision_id, started)
        action = str(request.action or "").strip().lower()
        strategy_type = str(request.strategy_type or "").strip().lower()
        if action not in ENTRY_ACTIONS:
            result = self._result(True, "skipped", "none", "exit_orders_are_not_filtered", decision_id, started)
            self._persist(request, result)
            return result
        if strategy_type in EXCLUDED_STRATEGY_TYPES:
            result = self._result(True, "skipped", "none", "strategy_type_not_supported", decision_id, started)
            self._persist(request, result)
            return result

        failures: list[str] = []
        jev_config = self._jev_config()
        if jev_config["api_key"]:
            try:
                result = self._evaluate_jev(request, decision_id, started, jev_config)
                self._persist(request, result)
                return result
            except Exception as exc:
                failures.append(f"jev:{self._safe_error(exc)}")
                logger.warning("Jev decision failed open: %s", exc)

        llm = LLMService()
        if llm.is_configured():
            try:
                result = self._evaluate_llm(request, decision_id, started, failures)
                self._persist(request, result)
                return result
            except Exception as exc:
                failures.append(f"llm:{self._safe_error(exc)}")
                logger.warning("LLM decision failed open: %s", exc)

        reason = "ai_not_configured" if not failures else "ai_provider_unavailable"
        result = self._result(
            True,
            "error_allowed" if failures else "skipped",
            "none",
            reason,
            decision_id,
            started,
            fallback_reason="; ".join(failures),
        )
        self._persist(request, result)
        return result

    def _evaluate_jev(
        self,
        request: AIDecisionRequest,
        decision_id: str,
        started: float,
        config: dict[str, str],
    ) -> AIDecisionResult:
        base_url = config["base_url"].strip().rstrip("/")
        url = base_url if base_url.endswith("/systemone") else f"{base_url}/systemone"
        model = config["model"].strip() or "jev-latest"
        timeout = max(1.0, min(float(config["timeout_seconds"] or 8), 30.0))
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {config['api_key']}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "state": self._state_payload(request),
                "questions": {
                    "entry_decision": {
                        "type": "choice",
                        "instructions": (
                            "Decide whether this new trading exposure should be allowed. "
                            "Reject only when the supplied state shows a concrete risk, invalid execution, "
                            "or a conflict with the strategy intent. Uncertainty alone is not a rejection."
                        ),
                        "criteria": {
                            "pass": "The order is consistent and has no concrete blocking risk.",
                            "reject": "A concrete risk or contradiction makes the new exposure unsuitable.",
                        },
                    },
                    "risk_check": {
                        "type": "choice",
                        "instructions": "Classify the strongest execution or exposure concern in the supplied state.",
                        "criteria": {
                            "clear": "No material concern is visible.",
                            "caution": "A concern exists but does not justify blocking the order.",
                            "block": "A material concern justifies blocking the order.",
                        },
                    },
                },
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        answers = payload.get("answers") or payload.get("result") or payload.get("data") or {}
        decision_answer = self._answer(answers, "entry_decision")
        risk_answer = self._answer(answers, "risk_check")
        choice, probabilities = self._validate_choice_answer(
            decision_answer,
            question="entry_decision",
            options={"pass", "reject"},
        )
        confidence = self._confidence(decision_answer, probabilities, choice)
        risk_choice, risk_probabilities = self._validate_choice_answer(
            risk_answer,
            question="risk_check",
            options={"clear", "caution", "block"},
        )
        allowed = choice == "pass" and risk_choice != "block"
        final_choice = "pass" if allowed else "reject"
        if allowed:
            reason = "jev_entry_approved"
        elif risk_choice == "block":
            reason = "jev_entry_rejected:risk_block"
        else:
            reason = "jev_entry_rejected:entry_reject"
        checks = [
            {
                "name": "entry_decision",
                "result": choice,
                "confidence": confidence,
                "probabilities": probabilities,
            },
            {
                "name": "risk_check",
                "result": risk_choice,
                "confidence": self._confidence(risk_answer, risk_probabilities, risk_choice),
                "probabilities": risk_probabilities,
            },
        ]
        return self._result(
            allowed,
            final_choice,
            "jev",
            reason,
            decision_id,
            started,
            model=model,
            confidence=confidence,
            probabilities=probabilities,
            checks=checks,
        )

    def _evaluate_llm(
        self,
        request: AIDecisionRequest,
        decision_id: str,
        started: float,
        failures: list[str],
    ) -> AIDecisionResult:
        service = LLMService()
        model = service.get_default_model()
        content = service.call_llm_api(
            [
                {
                    "role": "system",
                    "content": (
                        "You are a conservative pre-trade entry filter. Evaluate only the supplied order and state. "
                        "Reject only for a concrete, stated risk or contradiction. Return strict JSON with keys "
                        "decision (pass or reject), confidence (0 to 1), reason, and checks (array)."
                    ),
                },
                {"role": "user", "content": self._state_text(request)},
            ],
            model=model,
            temperature=0,
            use_fallback=True,
            use_json_mode=True,
            try_alternative_providers=True,
            timeout_seconds=max(1.0, min(float(os.getenv("AI_DECISION_TIMEOUT_SECONDS", "10") or 10), 30.0)),
        )
        payload = self._json_object(content)
        decision = str(payload.get("decision") or "").strip().lower()
        if decision not in {"pass", "reject"}:
            raise ValueError("LLM response did not contain a valid decision")
        confidence = self._bounded_float(payload.get("confidence"))
        checks = payload.get("checks") if isinstance(payload.get("checks"), list) else []
        return self._result(
            decision == "pass",
            decision,
            "llm",
            str(payload.get("reason") or "llm_decision"),
            decision_id,
            started,
            model=model,
            confidence=confidence,
            checks=[item for item in checks if isinstance(item, dict)],
            fallback_reason="; ".join(failures),
        )

    @staticmethod
    def _state_payload(request: AIDecisionRequest) -> dict[str, Any]:
        state = {
            "source_type": request.source_type,
            "symbol": request.symbol,
            "action": request.action,
            "market_type": request.market_type,
            "order_type": request.order_type,
            "quantity": request.quantity,
            "reference_price": request.reference_price,
            "notional": request.quantity * request.reference_price,
            "leverage": request.leverage,
            "strategy_type": request.strategy_type,
            "signal_reason": request.reason,
            "context": request.context,
        }
        return json.loads(json.dumps(state, ensure_ascii=False, default=str))

    @staticmethod
    def _state_text(request: AIDecisionRequest) -> str:
        return json.dumps(
            AIDecisionFilter._state_payload(request),
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )

    @staticmethod
    def _answer(answers: Any, key: str) -> dict[str, Any]:
        if isinstance(answers, dict):
            value = answers.get(key)
            if isinstance(value, dict):
                return value
            nested = answers.get("answers")
            if isinstance(nested, dict) and isinstance(nested.get(key), dict):
                return nested[key]
        return {}

    @staticmethod
    def _probabilities(answer: dict[str, Any]) -> dict[str, Any]:
        value = answer.get("probabilities") or answer.get("probability") or {}
        return dict(value) if isinstance(value, dict) else {}

    @classmethod
    def _validate_choice_answer(
        cls,
        answer: dict[str, Any],
        *,
        question: str,
        options: set[str],
    ) -> tuple[str, dict[str, float]]:
        choice = str(answer.get("choice") or answer.get("selected") or "").strip().lower()
        if choice not in options:
            raise ValueError(f"Jev response did not contain a valid {question}")
        raw_probabilities = cls._probabilities(answer)
        if set(raw_probabilities) != options:
            raise ValueError(f"Jev response probabilities were incomplete for {question}")
        probabilities: dict[str, float] = {}
        for option, value in raw_probabilities.items():
            try:
                probability = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Jev response probability was invalid for {question}") from exc
            if probability < 0 or probability > 1:
                raise ValueError(f"Jev response probability was out of range for {question}")
            probabilities[str(option)] = probability
        if abs(sum(probabilities.values()) - 1.0) > 0.001:
            raise ValueError(f"Jev response probabilities did not sum to one for {question}")
        maximum = max(probabilities.values())
        if probabilities.get(choice) != maximum:
            raise ValueError(f"Jev response choice was not the highest probability for {question}")
        confidence = cls._bounded_float(answer.get("confidence"))
        if confidence is None:
            raise ValueError(f"Jev response confidence was invalid for {question}")
        return choice, probabilities

    @classmethod
    def _confidence(cls, answer: dict[str, Any], probabilities: dict[str, Any], choice: str) -> float | None:
        direct = cls._bounded_float(answer.get("confidence"))
        if direct is not None:
            return direct
        return cls._bounded_float(probabilities.get(choice))

    @staticmethod
    def _bounded_float(value: Any) -> float | None:
        try:
            return max(0.0, min(float(value), 1.0))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _json_object(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        text = str(value or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lstrip().startswith("json"):
                text = text.lstrip()[4:].lstrip()
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("AI decision response must be a JSON object")
        return parsed

    @staticmethod
    def _jev_config() -> dict[str, str]:
        values: dict[str, str] = {}
        try:
            from app.services.settings.env_file import read_env_file

            values = read_env_file()
        except Exception as exc:
            logger.debug("Jev settings file refresh skipped: %s", exc)

        def setting(key: str, default: str = "") -> str:
            if key in values:
                return str(values.get(key) or "").strip()
            return str(os.getenv(key, default) or default).strip()

        return {
            "api_key": setting("JEV_API_KEY"),
            "base_url": setting("JEV_BASE_URL", "https://api.typesafe.ai/v1"),
            "model": setting("JEV_MODEL", "jev-latest"),
            "timeout_seconds": setting("JEV_TIMEOUT_SECONDS", "8"),
        }

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        return " ".join(str(exc or exc.__class__.__name__).split())[:300]

    @staticmethod
    def _result(
        allowed: bool,
        decision: str,
        provider: str,
        reason: str,
        decision_id: str,
        started: float,
        *,
        model: str = "",
        confidence: float | None = None,
        probabilities: dict[str, Any] | None = None,
        checks: list[dict[str, Any]] | None = None,
        fallback_reason: str = "",
    ) -> AIDecisionResult:
        return AIDecisionResult(
            allowed=allowed,
            decision=decision,
            provider=provider,
            reason=reason,
            decision_id=decision_id,
            model=model,
            confidence=confidence,
            probabilities=probabilities or {},
            checks=checks or [],
            latency_ms=max(0, int((time.perf_counter() - started) * 1000)),
            fallback_reason=fallback_reason,
        )

    @staticmethod
    def _persist(request: AIDecisionRequest, result: AIDecisionResult) -> None:
        try:
            with get_db_connection() as db:
                cur = db.cursor()
                cur.execute(
                    """
                    INSERT INTO qd_ai_decisions
                      (decision_uid, user_id, source_type, source_id, strategy_run_id,
                       order_intent_id, symbol, action, market_type, provider, model,
                       decision, allowed, confidence, reason, fallback_reason,
                       probabilities_json, checks_json, request_snapshot, latency_ms, created_at)
                    VALUES
                      (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (decision_uid) DO NOTHING
                    """,
                    (
                        result.decision_id,
                        int(request.user_id or 0),
                        str(request.source_type or ""),
                        int(request.strategy_id or 0),
                        int(request.strategy_run_id or 0),
                        int(request.order_intent_id or 0),
                        str(request.symbol or ""),
                        str(request.action or ""),
                        str(request.market_type or ""),
                        result.provider,
                        result.model,
                        result.decision,
                        bool(result.allowed),
                        result.confidence,
                        result.reason,
                        result.fallback_reason,
                        json.dumps(result.probabilities, ensure_ascii=False, default=str),
                        json.dumps(result.checks, ensure_ascii=False, default=str),
                        AIDecisionFilter._state_text(request),
                        int(result.latency_ms),
                    ),
                )
                db.commit()
                cur.close()
        except Exception as exc:
            logger.warning("AI decision audit persistence skipped: %s", exc)


def list_ai_decisions(*, user_id: int, source_type: str, source_id: int = 0, limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 100), 500))
    clauses = ["user_id = %s", "source_type = %s"]
    params: list[Any] = [int(user_id), str(source_type)]
    if source_id:
        clauses.append("source_id = %s")
        params.append(int(source_id))
    params.append(limit)
    with get_db_connection() as db:
        cur = db.cursor()
        cur.execute(
            f"""
            SELECT decision_uid, source_type, source_id, strategy_run_id, symbol, action,
                   market_type, provider, model, decision, allowed, confidence, reason,
                   fallback_reason, probabilities_json, checks_json, latency_ms, created_at
            FROM qd_ai_decisions
            WHERE {' AND '.join(clauses)}
            ORDER BY id DESC
            LIMIT %s
            """,
            tuple(params),
        )
        rows = cur.fetchall() or []
        cur.close()
    return [dict(row) for row in rows if isinstance(row, dict)]
