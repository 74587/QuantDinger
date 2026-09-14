"""Canonical live-trading venue capability matrix.

Keep exchange support decisions here instead of repeating raw string lists in
routes, policy checks, smoke tests, and execution helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterable, Set


@dataclass(frozen=True)
class VenueCapability:
    exchange_id: str
    market_types: FrozenSet[str]
    aliases: FrozenSet[str] = frozenset()
    equity_product_types: FrozenSet[str] = frozenset()
    equity_api_families: FrozenSet[tuple[str, str, str]] = frozenset()

    @property
    def supports_spot(self) -> bool:
        return "spot" in self.market_types

    @property
    def supports_swap(self) -> bool:
        return "swap" in self.market_types


CRYPTO_VENUE_CAPABILITIES: Dict[str, VenueCapability] = {
    "binance": VenueCapability(
        "binance", frozenset({"spot", "swap"}),
        equity_product_types=frozenset({"tokenized_equity", "stock_perpetual"}),
        equity_api_families=frozenset({
            ("tokenized_equity", "spot", "spot"),
            ("stock_perpetual", "swap", "swap"),
        }),
    ),
    "okx": VenueCapability(
        "okx", frozenset({"spot", "swap"}),
        equity_product_types=frozenset({"tokenized_equity", "stock_perpetual"}),
        equity_api_families=frozenset({
            ("tokenized_equity", "spot", "spot"),
            ("stock_perpetual", "swap", "swap"),
        }),
    ),
    "bitget": VenueCapability(
        "bitget", frozenset({"spot", "swap"}),
        equity_product_types=frozenset({"tokenized_equity", "stock_perpetual"}),
        equity_api_families=frozenset({
            ("tokenized_equity", "spot", "reality"),
            ("stock_perpetual", "swap", "swap"),
        }),
    ),
    "bybit": VenueCapability(
        "bybit", frozenset({"spot", "swap"}),
        equity_product_types=frozenset({"tokenized_equity", "stock_perpetual"}),
        equity_api_families=frozenset({
            ("tokenized_equity", "spot", "spot"),
            ("stock_perpetual", "swap", "swap"),
        }),
    ),
    "gate": VenueCapability(
        "gate", frozenset({"spot", "swap"}),
        equity_product_types=frozenset({"direct_equity", "stock_perpetual"}),
        equity_api_families=frozenset({
            ("direct_equity", "spot", "stock"),
            ("stock_perpetual", "swap", "swap"),
        }),
    ),
    "htx": VenueCapability("htx", frozenset({"spot", "swap"})),
}


def canonical_exchange_id(exchange_id: str) -> str:
    raw = str(exchange_id or "").strip().lower()
    if raw in CRYPTO_VENUE_CAPABILITIES:
        return raw
    for canonical, capability in CRYPTO_VENUE_CAPABILITIES.items():
        if raw in capability.aliases:
            return canonical
    return raw


def supported_crypto_exchange_ids(*, include_aliases: bool = False) -> Set[str]:
    ids: Set[str] = set(CRYPTO_VENUE_CAPABILITIES)
    if include_aliases:
        for capability in CRYPTO_VENUE_CAPABILITIES.values():
            ids.update(capability.aliases)
    return ids


def crypto_exchange_ids_for_market_type(market_type: str) -> Set[str]:
    mt = normalize_market_type(market_type)
    return {
        exchange_id
        for exchange_id, capability in CRYPTO_VENUE_CAPABILITIES.items()
        if mt in capability.market_types
    }


def supports_equity_product(
    exchange_id: str,
    product_type: str,
    market_type: str = "",
    api_family: str = "",
) -> bool:
    capability = CRYPTO_VENUE_CAPABILITIES.get(canonical_exchange_id(exchange_id))
    product = str(product_type or "").strip().lower()
    if not capability or product not in capability.equity_product_types:
        return False
    if not market_type and not api_family:
        return True
    mt = normalize_market_type(market_type)
    family = str(api_family or mt).strip().lower()
    return (product, mt, family) in capability.equity_api_families


def normalize_market_type(market_type: str) -> str:
    mt = str(market_type or "swap").strip().lower()
    if mt in ("futures", "future", "perp", "perpetual"):
        return "swap"
    if mt not in ("spot", "swap"):
        return mt
    return mt


def assert_supported_crypto_exchange_ids(exchange_ids: Iterable[str]) -> None:
    """Fail fast when a copied list drifts away from this matrix."""
    expected = supported_crypto_exchange_ids()
    actual = {canonical_exchange_id(v) for v in exchange_ids}
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        raise AssertionError(f"crypto exchange list drift: missing={missing} extra={extra}")
