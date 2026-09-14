"""Canonical parameter schema for Strategy API V2 source code."""

from __future__ import annotations

from typing import Any

from app.services.indicator_params import IndicatorParamsParser


_TYPE_MAP = {
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "str": "text",
    "string": "text",
}


def canonical_strategy_param_schema(
    code: str,
    schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Make declared ``# @param`` defaults authoritative for saved sources."""
    existing = dict(schema or {})
    declared = IndicatorParamsParser.parse_params(code or "")
    if not declared:
        return existing

    existing_rows = existing.get("params")
    previous_by_name = {
        str(item.get("name") or ""): dict(item)
        for item in (existing_rows if isinstance(existing_rows, list) else [])
        if isinstance(item, dict) and str(item.get("name") or "")
    }
    params: list[dict[str, Any]] = []
    for declaration in declared:
        name = str(declaration.get("name") or "")
        row = previous_by_name.get(name, {})
        declared_type = str(declaration.get("type") or "").lower()
        previous_type = str(row.get("type") or "").lower()
        compatible_types = {
            "int": {"int", "integer"},
            "float": {"float", "number", "percent"},
            "bool": {"bool", "boolean"},
            "str": {"str", "string", "text"},
        }
        row.update({
            "name": name,
            "type": (
                previous_type
                if previous_type in compatible_types.get(declared_type, set())
                else _TYPE_MAP.get(declared_type, declared_type or "text")
            ),
            "default": declaration.get("default"),
            "source": "code_param",
        })
        description = str(declaration.get("description") or "").strip()
        if description:
            row["description"] = description
        if row["type"] == "integer":
            row.setdefault("step", 1)
        elif row["type"] == "number":
            row.setdefault("step", 0.1)
        values = declaration.get("values")
        if isinstance(values, list) and values:
            row["values"] = list(values)
        params.append(row)

    return {**existing, "params": params}
