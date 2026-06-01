"""Tests for professional grid engine."""

from __future__ import annotations

import pytest

from app.services.grid.config import GridBotConfig
from app.services.grid.levels import generate_cells, generate_levels
from app.services.grid.validator import validate_grid_config


def test_generate_levels_arithmetic():
    levels = generate_levels(90000, 100000, 10, "arithmetic")
    assert len(levels) == 10
    assert levels[0] == 90000
    assert abs(levels[-1] - 100000) < 1e-6


def test_generate_cells_count():
    levels = generate_levels(100, 200, 5, "arithmetic")
    cells = generate_cells(levels)
    assert len(cells) == 4


def test_validate_long_grid_ok():
    cfg = GridBotConfig(
        upper_price=100000,
        lower_price=90000,
        grid_count=10,
        amount_per_grid=100,
        grid_mode="arithmetic",
        grid_direction="long",
        initial_position_pct=0.3,
        order_mode="maker",
        boundary_action="pause",
        leverage=5,
        market_type="swap",
        margin_mode="cross",
    )
    ok, msg, _ = validate_grid_config(cfg, initial_capital=10000)
    assert ok is True
    assert msg == ""


def test_validate_rejects_bad_bounds():
    cfg = GridBotConfig(
        upper_price=100,
        lower_price=200,
        grid_count=10,
        amount_per_grid=50,
        grid_mode="arithmetic",
        grid_direction="long",
        initial_position_pct=0,
        order_mode="maker",
        boundary_action="pause",
        leverage=1,
        market_type="swap",
        margin_mode="cross",
    )
    ok, msg, _ = validate_grid_config(cfg)
    assert ok is False
    assert "upperPrice" in msg


def test_config_from_trading_config_initial_pct():
    tc = {
        "leverage": 5,
        "market_type": "swap",
        "bot_params": {
            "upperPrice": 100000,
            "lowerPrice": 90000,
            "gridCount": 10,
            "amountPerGrid": 100,
            "gridDirection": "long",
            "initialPositionPct": 30,
        },
    }
    cfg = GridBotConfig.from_trading_config(tc)
    assert cfg.initial_position_pct == 0.3
    assert cfg.grid_direction == "long"


def test_initial_market_target_qty_100u_20pct_20x():
    """100 USDT * 20% margin * 20x leverage ≈ 400 USDT notional at 72710."""
    from app.services.grid.engine import GridEngine
    from app.services.grid.exchange_orders import make_grid_initial_client_order_id

    tc = {
        "initial_capital": 100,
        "leverage": 20,
        "market_type": "swap",
        "bot_params": {
            "upperPrice": 80200,
            "lowerPrice": 69800,
            "gridCount": 24,
            "amountPerGrid": 4,
            "gridDirection": "long",
            "initialPositionPct": 20,
        },
    }
    engine = GridEngine(
        42,
        "BTC/USDT",
        tc,
        {},
        create_client_fn=lambda: None,
        enqueue_market=lambda *a, **k: False,
    )
    qty = engine._target_initial_base_qty(72710.0)
    assert qty == pytest.approx(400.0 / 72710.0, rel=1e-4)
    assert make_grid_initial_client_order_id(42, leg="long") == make_grid_initial_client_order_id(42, leg="long")
    assert make_grid_initial_client_order_id(42, leg="long") != make_grid_initial_client_order_id(42, leg="short")


def test_initial_market_recovers_from_exchange_without_new_order(monkeypatch):
    from app.services.grid.engine import GridEngine

    tc = {
        "initial_capital": 100,
        "leverage": 20,
        "market_type": "swap",
        "bot_params": {
            "upperPrice": 80200,
            "lowerPrice": 69800,
            "gridCount": 24,
            "amountPerGrid": 4,
            "gridDirection": "long",
            "initialPositionPct": 20,
        },
    }
    recorded = {"calls": 0}

    def fake_record(*args, **kwargs):
        recorded["calls"] += 1

    monkeypatch.setattr("app.services.grid.engine.record_grid_market_fill", fake_record)
    monkeypatch.setattr("app.services.grid.engine.append_strategy_log", lambda *a, **k: None)
    monkeypatch.setattr("app.services.grid.engine.persist_grid_resting_state", lambda *a, **k: None)
    monkeypatch.setattr("app.services.grid.engine.GridEngine._has_initial_market_trade", lambda self: False)

    engine = GridEngine(
        7,
        "BTC/USDT",
        tc,
        {},
        create_client_fn=lambda: object(),
        enqueue_market=lambda *a, **k: False,
    )
    target = engine._target_initial_base_qty(72710.0)
    monkeypatch.setattr("app.services.grid.engine.GridEngine._leg_position_qty", lambda self, side: target)

    ok = engine.run_initial_market_position(72710.0)
    assert ok is True
    assert engine._initial_done is True
    assert recorded["calls"] == 1
