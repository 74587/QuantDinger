"""Resolve durable robot types across current and legacy deployments."""

from __future__ import annotations

import json
from typing import Any, Mapping


KNOWN_BOT_TYPES = {"grid", "dca", "martingale", "layered_martingale", "trend"}


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return {}


def resolve_bot_type(
    strategy: Mapping[str, Any] | None,
    trading_config: Mapping[str, Any] | None = None,
) -> str:
    """Return the bot type without silently downgrading legacy robots.

    Early Strategy API V2 robot deployments persisted ``executor_type`` and
    source metadata but not the later top-level ``bot_type`` field.  Treating
    those rows as ordinary bar strategies is unsafe for grids because their
    exchange-resting order engine would never start.
    """
    row = dict(strategy or {})
    config = dict(trading_config or _object(row.get("trading_config")))
    metadata = _object(row.get("metadata"))
    manifest = _object(config.get("strategy_manifest"))

    candidates = (
        row.get("bot_type"),
        config.get("bot_type"),
        config.get("executor_type"),
        metadata.get("executor_type"),
        manifest.get("executor_type"),
    )
    for candidate in candidates:
        value = str(candidate or "").strip().lower().replace("-", "_")
        if value in KNOWN_BOT_TYPES:
            return value

    template_key = str(row.get("template_key") or metadata.get("template_key") or "").strip().lower()
    for value in ("layered_martingale", "martingale", "grid", "dca", "trend"):
        if value in template_key:
            return value
    return ""


__all__ = ["KNOWN_BOT_TYPES", "resolve_bot_type"]
