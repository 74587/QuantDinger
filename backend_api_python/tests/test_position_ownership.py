"""Protected manual inventory and ownership-drift calculations."""

import pytest

from app.services.live_trading.account_positions import reconcile_strategy_vs_account
from app.services.live_trading.position_ownership import (
    ADVANCED_MODE,
    STATUS_BLOCKED,
    STATUS_OK,
    calculate_position_ownership,
)


def test_advanced_manual_baseline_allows_matching_account_position():
    snapshot = calculate_position_ownership(
        symbol="BTC/USDT",
        side="long",
        account_qty=0.025,
        strategy_qty=0.015,
        protected_qty=0.01,
        coexistence_mode=ADVANCED_MODE,
    )
    assert snapshot.status == STATUS_OK
    assert snapshot.allowed is True
    assert snapshot.unknown_qty == pytest.approx(0.0)


def test_strict_mode_blocks_unallocated_manual_position_once():
    first = calculate_position_ownership(
        symbol="BTC/USDT",
        side="long",
        account_qty=0.01,
        strategy_qty=0.0,
    )
    duplicate = calculate_position_ownership(
        symbol="BTC/USDT",
        side="long",
        account_qty=0.01,
        strategy_qty=0.0,
        previous_status=first.status,
        previous_reason=first.reason,
    )
    assert first.status == STATUS_BLOCKED
    assert first.should_log is True
    assert duplicate.should_log is False


def test_manual_reduction_below_protected_total_blocks_entries():
    snapshot = calculate_position_ownership(
        symbol="BTC/USDT",
        side="long",
        account_qty=0.015,
        strategy_qty=0.015,
        protected_qty=0.01,
        coexistence_mode=ADVANCED_MODE,
    )
    assert snapshot.status == STATUS_BLOCKED
    assert snapshot.reason == "account_below_protected_allocation"
    assert snapshot.unknown_qty == pytest.approx(-0.01)


def test_account_reconciliation_counts_protected_manual_inventory():
    result = reconcile_strategy_vs_account(
        local_rows=[{"symbol": "BTC/USDT", "side": "long", "size": 0.015}],
        account_rows=[{"symbol": "BTC/USDT", "side": "long", "size": 0.025}],
        allocated_rows=[{"symbol": "BTC/USDT", "side": "long", "size": 0.015}],
        protected_rows=[{
            "symbol_canonical": "BTC/USDT",
            "side": "long",
            "coexistence_mode": "advanced",
            "manual_reserved_qty": 0.01,
        }],
    )
    assert result["status"] == "ok"
    assert result["strategy_allocations"][0]["protected_size"] == pytest.approx(0.01)
