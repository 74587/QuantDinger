"""Prompt selection and post-generation enforcement for strategy AI."""
from __future__ import annotations

import json
from typing import Any, Callable

from app.services.ai_generation_contracts import (
    CTA_STRATEGY_SYSTEM_PROMPT,
    INDICATOR_TO_STRATEGY_SYSTEM_PROMPT,
    PORTFOLIO_STRATEGY_SYSTEM_PROMPT,
)
from app.services.strategy_ai_workspace import normalize_asset_type
from app.services.strategy_v2 import StrategyV2ContractError, compile_strategy_v2
from app.services.strategy_v2.instruments import normalize_frequency, parse_instrument


def select_strategy_system_prompt(asset_type: str, generation_mode: str = "authoring") -> str:
    normalized_type = normalize_asset_type(asset_type)
    mode = str(generation_mode or "authoring").strip().lower()
    if mode == "indicator_conversion":
        if normalized_type != "script":
            raise ValueError("strategyV2.indicatorConversionCtaOnly")
        return INDICATOR_TO_STRATEGY_SYSTEM_PROMPT
    if normalized_type == "portfolio_strategy":
        return PORTFOLIO_STRATEGY_SYSTEM_PROMPT
    return CTA_STRATEGY_SYSTEM_PROMPT


def _canonical_instrument(value: Any) -> str:
    if not str(value or "").strip():
        return ""
    return parse_instrument(value).key


def build_strategy_generation_request(
    *,
    prompt: str,
    asset_type: str,
    existing_code: str = "",
    generation_mode: str = "authoring",
    context: dict | None = None,
) -> str:
    normalized_type = normalize_asset_type(asset_type)
    mode = str(generation_mode or "authoring").strip().lower()
    context = dict(context or {})
    expected_manifest = "portfolio" if normalized_type == "portfolio_strategy" else "cta"
    instrument = _canonical_instrument(context.get("instrument") or context.get("sourceInstrument"))
    timeframe_raw = context.get("timeframe") or context.get("sourceTimeframe")
    timeframe = normalize_frequency(timeframe_raw) if str(timeframe_raw or "").strip() else ""
    constraints = {
        "workspace_asset_type": normalized_type,
        "required_manifest_strategy_type": expected_manifest,
        "generation_mode": mode,
        "required_instrument": instrument,
        "required_timeframe": timeframe,
        "current_source_is_truth": bool(str(existing_code or "").strip()),
    }
    parts = [
        "# Structured IDE constraints (machine-enforced after generation)",
        json.dumps(constraints, ensure_ascii=False, sort_keys=True),
        "",
        "# User request",
        str(prompt or "").strip(),
    ]
    if existing_code:
        parts.extend([
            "",
            "# Current Strategy API V2 source (source of truth)",
            str(existing_code).strip(),
            "",
            "Return one complete replacement candidate. Preserve behavior not explicitly changed by the user.",
        ])
    else:
        parts.extend(["", "Return one complete new Strategy API V2 candidate."])
    return "\n".join(parts)


def validate_generated_strategy(
    code: str,
    *,
    asset_type: str,
    generation_mode: str = "authoring",
    context: dict | None = None,
    compiler: Callable[[str], Any] = compile_strategy_v2,
):
    normalized_type = normalize_asset_type(asset_type)
    context = dict(context or {})
    program = compiler(code)
    manifest = program.manifest
    expected_type = "portfolio" if normalized_type == "portfolio_strategy" else "cta"
    if manifest.strategy_type != expected_type:
        raise StrategyV2ContractError(
            f"strategyV2.aiManifestTypeMismatch:{expected_type}:{manifest.strategy_type}"
        )

    expected_instrument = _canonical_instrument(
        context.get("instrument") or context.get("sourceInstrument")
    )
    if expected_instrument:
        actual = [item.key for item in manifest.universe.instruments]
        if actual != [expected_instrument]:
            raise StrategyV2ContractError(
                f"strategyV2.aiInstrumentMismatch:{expected_instrument}"
            )

    timeframe_raw = context.get("timeframe") or context.get("sourceTimeframe")
    if str(timeframe_raw or "").strip():
        expected_timeframe = normalize_frequency(timeframe_raw)
        if expected_timeframe not in manifest.frequencies:
            raise StrategyV2ContractError(
                f"strategyV2.aiTimeframeMismatch:{expected_timeframe}"
            )

    mode = str(generation_mode or "authoring").strip().lower()
    if mode == "indicator_conversion" and manifest.strategy_type != "cta":
        raise StrategyV2ContractError("strategyV2.indicatorConversionCtaOnly")
    return program
