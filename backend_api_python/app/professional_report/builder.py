"""Assemble the backward-compatible ProfessionalReportV1 payload."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from .features.equity import build_equity_features
from .narrative import normalize_report_text, validate_evidence_claims
from .providers import list_providers, provider_configuration_status
from .risk import build_risk_plan
from .snapshot import build_evidence_snapshot


def _dump(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"cannot serialize {type(value)!r}")


def _score(value: Any, default: float = 50.0) -> float:
    try:
        return round(max(0.0, min(100.0, float(value))), 2)
    except (TypeError, ValueError):
        return default


def _refs(observations: list[Mapping[str, Any]], *categories: str) -> list[str]:
    wanted = set(categories)
    return [
        str(item["evidence_id"])
        for item in observations
        if item.get("category") in wanted and item.get("evidence_id")
    ]


def _quality(snapshot: dict[str, Any]) -> dict[str, Any]:
    from .quality import assess_snapshot_quality

    try:
        result = assess_snapshot_quality(snapshot)
    except Exception:
        # The Pydantic contract is the canonical input when a caller wants to
        # instantiate it explicitly; accepting a plain mapping keeps legacy
        # fast-analysis integration lightweight.
        from .contracts import EvidenceSnapshotV1

        result = assess_snapshot_quality(EvidenceSnapshotV1.model_validate(snapshot))
    return _dump(result)


def _apply_gate(decision: str, confidence: int, quality: Mapping[str, Any]) -> tuple[str, int, list[str]]:
    from .quality import apply_quality_gate

    try:
        gated = apply_quality_gate(decision, confidence, quality)
    except Exception:
        from .contracts import DataQualitySummary

        gated = apply_quality_gate(decision, confidence, DataQualitySummary.model_validate(quality))
    if isinstance(gated, tuple) and len(gated) == 3:
        return str(gated[0]), int(gated[1]), list(gated[2])
    if isinstance(gated, Mapping):
        return (
            str(gated.get("decision") or decision),
            int(gated.get("confidence") or confidence),
            list(gated.get("reasons") or []),
        )
    raise TypeError("unexpected quality-gate result")


def _dimension(
    key: str,
    score: Any,
    observations: list[Mapping[str, Any]],
    categories: Iterable[str],
    narrative: str,
    *,
    missing: Iterable[str] = (),
) -> dict[str, Any]:
    refs = _refs(observations, *categories)
    missing_items = list(missing)
    return {
        "key": key,
        "score": _score(score),
        "score_kind": "deterministic_signal_strength",
        "status": "available" if refs else "insufficient_data",
        "narrative": normalize_report_text(narrative or ""),
        "evidence_refs": refs,
        "missing_data": missing_items,
    }


def _claim_refs(text: str, observations: list[Mapping[str, Any]]) -> list[str]:
    low = str(text or "").lower()
    if any(token in low for token in ("pe", "roe", "营收", "利润", "估值", "财务", "cash flow", "revenue")):
        categories = ("fundamental",)
    elif any(token in low for token in ("新闻", "事件", "政策", "宏观", "vix", "dxy", "news", "rate")):
        categories = ("news", "macro")
    elif any(token in low for token in ("funding", "资金费率", "持仓量", "oi", "清算", "链上", "netflow")):
        categories = ("crypto",)
    else:
        categories = ("technical", "market")
    refs = _refs(observations, *categories)
    return refs[:8]


def _build_claims(items: Iterable[Any], kind: str, observations: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    claims = []
    for item in items or []:
        text = normalize_report_text(str(item or ""))
        if not text:
            continue
        refs = _claim_refs(text, observations)
        if not refs:
            continue
        claims.append({"kind": kind, "text": text, "evidence_refs": refs})
    return claims


def _validated_llm_claims(
    items: Iterable[Any], observations: list[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Retain only explicitly grounded model claims at the report boundary."""
    available = {
        str(item.get("evidence_id"))
        for item in observations
        if item.get("evidence_id")
    }
    claims: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, Mapping):
            continue
        text = normalize_report_text(str(item.get("text") or ""))
        refs = list(dict.fromkeys(
            str(ref) for ref in item.get("evidence_refs") or [] if str(ref) in available
        ))
        if text and refs:
            claims.append({
                "kind": str(item.get("kind") or "thesis"),
                "text": text,
                "evidence_refs": refs,
            })
    return claims


def _warning_codes(items: Iterable[Any]) -> list[str]:
    codes: list[str] = []
    for item in items or []:
        if isinstance(item, Mapping):
            value = item.get("code") or item.get("message")
        else:
            value = item
        text = str(value or "").strip()
        if text:
            codes.append(text)
    return codes


def _build_scenarios(
    decision: str,
    current_price: float,
    trading_plan: Mapping[str, Any],
    market_data: Mapping[str, Any],
) -> list[dict[str, Any]]:
    stop = trading_plan.get("stop_loss") or trading_plan.get("stopLoss")
    target = trading_plan.get("take_profit") or trading_plan.get("takeProfit")
    support = market_data.get("support")
    resistance = market_data.get("resistance")
    if decision == "SELL":
        bull_target, bear_target = stop or resistance, target or support
        base_target = support or current_price
    elif decision == "BUY":
        bull_target, bear_target = target or resistance, stop or support
        base_target = resistance or current_price
    else:
        bull_target, bear_target = resistance, support
        base_target = current_price
    return [
        {
            "case": "bull",
            "probability": None,
            "target_price": bull_target,
            "trigger": "Price and evidence confirm the upside thesis.",
            "invalidation": bear_target,
        },
        {
            "case": "base",
            "probability": None,
            "target_price": base_target,
            "trigger": "Current evidence remains mixed or follows the central path.",
            "invalidation": None,
        },
        {
            "case": "bear",
            "probability": None,
            "target_price": bear_target,
            "trigger": "Downside catalyst or technical breakdown is confirmed.",
            "invalidation": bull_target,
        },
    ]


def _provider_payload(market: str) -> dict[str, Any]:
    rows = []
    for provider in list_providers(market=market):
        status = provider_configuration_status(provider, environ=os.environ)
        rows.append({
            "key": provider.key,
            "name": provider.name,
            "tier": provider.tier,
            "capabilities": sorted(provider.capabilities),
            "configured": bool(status["configured"]),
            "keyless": provider.keyless,
            "cost_level": provider.cost_level,
            "license_warning": provider.license_warning,
            "missing_env_keys": list(status["missing_env_keys"]),
            "integration_status": provider.integration_status,
        })
    return {
        "community": [row for row in rows if row["tier"] == "community"],
        "professional": [row for row in rows if row["tier"] == "professional"],
    }


def _effective_data_tier(
    requested_tier: str, observations: list[Mapping[str, Any]]
) -> tuple[str, list[str]]:
    professional_tokens = {
        provider.key.replace("_", " ")
        for provider in list_providers(tier="professional")
    } | {"polygon", "coin metrics", "hkex omd", "hkex data marketplace"}
    observed_sources = " ".join(
        str(item.get("source") or "").lower().replace("_", " ")
        for item in observations
    )
    has_professional_evidence = any(
        token and token in observed_sources for token in professional_tokens
    )
    effective = "professional" if has_professional_evidence else "community"
    warnings = []
    if requested_tier == "professional" and effective != "professional":
        warnings.append("professional_tier_requested_but_no_professional_evidence")
    return effective, warnings


def _typed_crypto_factors(
    factors: Mapping[str, Any], observations: list[Mapping[str, Any]]
) -> dict[str, Any]:
    """Attach the collector's explicit unit/scope metadata to legacy scalars."""
    metadata = factors.get("metric_metadata") or {}
    ref_by_metric = {
        str(item.get("metric") or "").removeprefix("crypto."): item.get("evidence_id")
        for item in observations
        if str(item.get("metric") or "").startswith("crypto.")
    }
    result: dict[str, Any] = {}
    for key in (
        "funding_rate",
        "open_interest",
        "basis",
        "liquidations",
        "long_short_ratio",
        "market_cap",
        "volume_24h",
        "turnover_24h",
    ):
        value = factors.get(key)
        if value is None:
            continue
        meta = metadata.get(key) or {}
        result[key] = {
            "value": value,
            "unit": meta.get("unit"),
            "currency": meta.get("currency"),
            "venue": meta.get("venue"),
            "product_type": meta.get("product_type"),
            "evidence_ref": ref_by_metric.get(key),
        }
    return result


def build_professional_report(
    collector_payload: Mapping[str, Any],
    analysis_result: Mapping[str, Any],
    *,
    data_tier: str = "community",
    account_risk_budget_pct: float = 1.0,
) -> dict[str, Any]:
    """Build an evidence-first report while preserving the legacy response.

    ``confidence`` is deliberately labelled as model strength.  It must not be
    presented as a calibrated probability until the outcome-calibration layer
    has sufficient point-in-time samples.
    """
    if data_tier not in {"community", "professional"}:
        raise ValueError("data_tier must be community or professional")
    snapshot = build_evidence_snapshot(collector_payload)
    observations = snapshot["observations"]
    effective_data_tier, tier_warnings = _effective_data_tier(data_tier, observations)
    quality = _quality(snapshot)
    market = str(collector_payload.get("market") or analysis_result.get("market") or "")
    prebuilt_market_features: dict[str, Any] | None = None
    hard_gate_reasons: list[str] = []
    if market in {"USStock", "HKStock"}:
        prebuilt_market_features = build_equity_features(market, collector_payload, observations)
        if (prebuilt_market_features.get("identity") or {}).get("verified") is False:
            hard_gate_reasons.append("instrument_identity_unverified")
    elif market == "Crypto":
        from .features.crypto import build_crypto_features

        legacy_crypto_factors = collector_payload.get("crypto_factors") or {}
        prebuilt_market_features = build_crypto_features({
            "crypto_factors": _typed_crypto_factors(legacy_crypto_factors, observations),
            "instrument": snapshot["instrument"],
        })
        if not bool(
            (prebuilt_market_features.get("quality_flags") or {}).get(
                "usable_for_directional_analysis"
            )
        ):
            hard_gate_reasons.append("crypto_scope_or_unit_validation_failed")
    raw_decision = str(analysis_result.get("decision") or "HOLD").upper()
    raw_confidence = int(_score(analysis_result.get("confidence"), 50))
    decision, confidence, gate_reasons = _apply_gate(raw_decision, raw_confidence, quality)
    if hard_gate_reasons:
        if decision != "HOLD":
            decision = "HOLD"
            gate_reasons.append("directional_decision_blocked")
        confidence = min(confidence, 35)
        gate_reasons.extend(hard_gate_reasons)
    gate_reasons = list(dict.fromkeys(gate_reasons))
    market_data = analysis_result.get("market_data") or {}
    current_price = float(market_data.get("current_price") or (collector_payload.get("price") or {}).get("price") or 0)
    trading_plan = analysis_result.get("trading_plan") or {}
    risk_plan = build_risk_plan(
        decision,
        current_price,
        trading_plan,
        data_quality_score=float(quality.get("overall_score") or quality.get("score") or 0),
        market=market,
        account_risk_budget_pct=account_risk_budget_pct,
    )
    if decision != "HOLD" and not risk_plan.get("valid", False):
        decision = "HOLD"
        confidence = min(confidence, 35)
        gate_reasons = list(dict.fromkeys(
            gate_reasons + ["directional_decision_blocked", "invalid_risk_plan"]
        ))

    detailed = analysis_result.get("detailed_analysis") or {}
    scores = analysis_result.get("scores") or {}
    objective = analysis_result.get("objective_score") or {}
    dimensions = [
        _dimension("technical", scores.get("technical"), observations, ("technical", "market"), detailed.get("technical", "")),
        _dimension("fundamental", scores.get("fundamental"), observations, ("fundamental",), detailed.get("fundamental", "")),
        _dimension("news_sentiment", scores.get("sentiment"), observations, ("news",), detailed.get("sentiment", "")),
        _dimension(
            "macro",
            50.0 + float(objective.get("macro_score") or 0.0) * 0.5,
            observations,
            ("macro",),
            "",
        ),
    ]

    if market in {"USStock", "HKStock"}:
        market_features = prebuilt_market_features or build_equity_features(
            market, collector_payload, observations
        )
        market_missing = market_features.get("missing_capabilities") or []
        market_dimension = _dimension(
            "market_specific",
            0 if market_missing else 50,
            observations,
            ("fundamental", "news"),
            "",
            missing=market_missing,
        )
        if market_missing:
            market_dimension["status"] = "insufficient_data"
        dimensions.append(market_dimension)
    elif market == "Crypto":
        market_features = prebuilt_market_features or {}
        crypto_quality = market_features.get("quality_flags") or {}
        crypto_usable = bool(crypto_quality.get("usable_for_directional_analysis"))
        crypto_dimension = _dimension(
            "crypto_market_structure",
            (50.0 + float(analysis_result.get("crypto_factor_score") or 0.0) * 0.5)
            if crypto_usable else 0,
            observations,
            ("crypto",),
            analysis_result.get("crypto_factor_summary") or "",
            missing=[
                item.get("code")
                for item in market_features.get("warnings") or []
                if isinstance(item, Mapping) and str(item.get("code") or "").startswith("MISSING")
            ],
        )
        if not crypto_usable:
            crypto_dimension["status"] = "insufficient_data"
        dimensions.append(crypto_dimension)
    else:
        market_features = {"market": market, "warnings": ["unsupported_professional_report_market"]}

    claims = _validated_llm_claims(analysis_result.get("evidence_claims") or [], observations)
    if not claims:
        claims = _build_claims(analysis_result.get("reasons") or [], "thesis", observations)
        claims.extend(_build_claims(analysis_result.get("risks") or [], "risk", observations))
    claim_errors = validate_evidence_claims(claims, observations)
    warnings = sorted(set(
        _warning_codes(quality.get("warnings") or [])
        + list(gate_reasons)
        + _warning_codes(market_features.get("warnings") or [])
        + _warning_codes((analysis_result.get("llm_contract") or {}).get("warnings") or [])
        + tier_warnings
        + claim_errors
    ))
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    report = {
        "schema_version": "professional_report_v1",
        "report_id": f"{market}:{snapshot['instrument']['canonical_symbol']}:{generated_at}",
        "generated_at": generated_at,
        "as_of": snapshot["as_of"],
        "language": analysis_result.get("language") or "en-US",
        "data_tier": effective_data_tier,
        "instrument": snapshot["instrument"],
        "decision_profile": {
            "decision": decision,
            "raw_decision": raw_decision,
            "confidence": confidence,
            "raw_confidence": raw_confidence,
            "confidence_kind": "calibrated_probability"
            if os.getenv("ENABLE_CONFIDENCE_CALIBRATION", "false").lower() == "true"
            else "model_strength",
            "quality_gate_reasons": gate_reasons,
            "conclusion_strength": quality.get("max_conclusion_strength") or "none",
            "rationale": normalize_report_text(analysis_result.get("summary") or ""),
            "horizon": analysis_result.get("timeframe"),
            "score": float((analysis_result.get("consensus") or {}).get("consensus_score") or 0.0),
            "evidence_ids": _refs(observations, "market", "technical")[:12],
        },
        "executive_summary": normalize_report_text(analysis_result.get("summary") or ""),
        "dimensions": dimensions,
        "claims": claims,
        "scenarios": _build_scenarios(decision, current_price, trading_plan, market_data),
        "risk_plan": risk_plan,
        "data_quality": quality,
        "market_features": market_features,
        "evidence_snapshot": snapshot,
        "provider_options": _provider_payload(market) if market in {"USStock", "HKStock", "Crypto"} else {},
        "warnings": warnings,
        "methodology": {
            "scoring_version": analysis_result.get("score_source") or "deterministic_objective_v2",
            "report_builder_version": "professional_report_builder_v1",
            "llm_role": "evidence_explanation_only",
            "probabilities_calibrated": os.getenv("ENABLE_CONFIDENCE_CALIBRATION", "false").lower() == "true",
            "requested_data_tier": data_tier,
            "effective_data_tier": effective_data_tier,
        },
        "model_version": analysis_result.get("model"),
        "prompt_version": "professional_analysis_prompt_v1",
        "scoring_version": analysis_result.get("score_source") or "deterministic_objective_v2",
    }
    # Validate when the strict contract is available. Returning ``model_dump``
    # keeps the Flask response JSON-compatible and avoids leaking model objects.
    try:
        from .contracts import ProfessionalReportV1

        report = ProfessionalReportV1.model_validate(report).model_dump(mode="json")
    except Exception as exc:
        # Contract mismatches are visible in the payload and logs rather than
        # silently dropping the new report during the compatibility rollout.
        report["contract_validation"] = {"valid": False, "error": str(exc)}
    else:
        report["contract_validation"] = {"valid": True, "error": None}
    return normalize_report_text(report)


__all__ = ["build_professional_report"]
