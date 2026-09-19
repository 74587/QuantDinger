"""Grid resting engine must resolve credential_id before limit/cancel/close paths."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.exchange_execution import _load_credential_config, resolve_exchange_config
from app.services.grid.config import GridBotConfig
from app.services.grid.runner import GridRestingRunner
from app.services.grid.validator import validate_grid_config


def test_resolve_exchange_config_merges_credential_id():
    base = {"exchange_id": "okx", "api_key": "k", "secret_key": "s", "passphrase": "p"}
    merged = resolve_exchange_config({"credential_id": 9, "market_type": "swap"}, user_id=1)
    # Without DB this stays credential-only; with mock below we verify merge logic separately.
    assert merged.get("credential_id") == 9


def test_load_credential_config_restores_exchange_id_from_credential_row(monkeypatch):
    class Cursor:
        def execute(self, *_args):
            return None

        def fetchone(self):
            return {"exchange_id": "Gate", "encrypted_config": "encrypted"}

        def close(self):
            return None

    class Connection:
        def cursor(self):
            return Cursor()

    class Context:
        def __enter__(self):
            return Connection()

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(
        "app.services.exchange_execution.get_db_connection",
        lambda: Context(),
    )
    monkeypatch.setattr(
        "app.services.exchange_execution.decrypt_credential_blob",
        lambda _raw: '{"api_key":"key","environment":"testnet"}',
    )

    config = _load_credential_config(7, user_id=1)

    assert config == {
        "api_key": "key",
        "environment": "testnet",
        "exchange_id": "gate",
    }


def test_grid_startup_fails_before_initial_market_when_client_missing():
    calls = {"market": 0}

    def _enqueue(sig, usdt, px, reason):
        calls["market"] += 1
        return True

    def _create_client():
        raise RuntimeError("Missing OKX api_key/secret_key/passphrase")

    runner = GridRestingRunner(
        1,
        "BTC/USDT",
        {
            "leverage": 5,
            "market_type": "swap",
            "initial_capital": 1000,
            "bot_params": {
                "upperPrice": 100000,
                "lowerPrice": 90000,
                "gridCount": 5,
                "amountPerGrid": 50,
                "gridDirection": "long",
                "initialPositionPct": 0,
            },
        },
        {"exchange_id": "okx", "api_key": "", "secret_key": "", "passphrase": ""},
        user_id=1,
        initial_capital=1000,
        enqueue_market_fn=_enqueue,
        create_client_fn=_create_client,
    )
    ok, msg = runner.startup(95000.0)
    assert ok is False
    assert "Missing OKX" in msg
    assert calls["market"] == 0


def test_grid_startup_places_limits_when_client_ok():
    calls = {"limits": 0}

    def _enqueue(sig, usdt, px, reason):
        return True

    client = MagicMock()
    client.place_limit_order.return_value = MagicMock(exchange_order_id="ex1")

    def _create_client():
        return client

    with patch("app.services.grid.engine.place_grid_limit_order") as place:
        place.return_value = MagicMock(exchange_order_id="ex1")
        with patch(
            "app.services.grid.engine.GridEngine._grid_entry_ownership_allowed",
            return_value=(True, {}),
        ), patch("app.services.grid.engine.GridRestingOrderRepository") as repo_cls, patch(
            "app.services.grid.engine.GridCellRepository"
        ) as cell_repo_cls:
            repo = repo_cls.return_value
            repo.has_open_for_cell.return_value = False
            repo.insert.return_value = 1
            cell_repo_cls.return_value.list_cells.return_value = []
            runner = GridRestingRunner(
                2,
                "BTC/USDT",
                {
                    "leverage": 5,
                    "market_type": "swap",
                    "initial_capital": 1000,
                    "bot_params": {
                        "upperPrice": 100000,
                        "lowerPrice": 90000,
                        "gridCount": 5,
                        "amountPerGrid": 50,
                        "gridDirection": "long",
                        "initialPositionPct": 0,
                    },
                },
                {
                    "exchange_id": "okx",
                    "credential_id": 9,
                    "api_key": "k",
                    "secret_key": "s",
                    "passphrase": "p",
                },
                user_id=1,
                initial_capital=1000,
                enqueue_market_fn=_enqueue,
                create_client_fn=_create_client,
            )
            ok, msg = runner.startup(95000.0)
    assert ok is True
    assert msg == ""
    assert place.called


def test_grid_startup_rolls_back_new_seed_without_resting_coverage(monkeypatch):
    runner = GridRestingRunner(
        3,
        "ETH/USDT",
        {
            "market_type": "spot",
            "initial_capital": 1000,
            "bot_params": {
                "upperPrice": 3000,
                "lowerPrice": 2000,
                "gridCount": 20,
                "amountPerGrid": 10,
                "gridDirection": "long",
                "initialPositionPct": 20,
                "maxOpenOrders": 10,
            },
        },
        {"exchange_id": "bybit", "credential_id": 9},
        user_id=1,
        initial_capital=1000,
        enqueue_market_fn=lambda *_args, **_kwargs: True,
        create_client_fn=lambda: object(),
    )
    engine = runner.engine
    monkeypatch.setattr(engine, "bootstrap", lambda _price: (True, ""))
    monkeypatch.setattr(engine, "handle_boundary", lambda _price: False)

    def seed(_price):
        engine._initial_done = True
        engine._startup_initial_fills = [{"signal_type": "open_long", "quantity": 0.08}]
        return True

    monkeypatch.setattr(engine, "run_initial_market_position", seed)
    monkeypatch.setattr(engine, "sync_grid_orders", lambda _price: 0)
    monkeypatch.setattr(engine, "sync_exit_coverage", lambda _price: 0)
    monkeypatch.setattr(engine._orders, "list_open", lambda *_args, **_kwargs: [])
    cancel_all = MagicMock()
    rollback = MagicMock(return_value=True)
    monkeypatch.setattr(engine, "cancel_all_orders_on_exchange", cancel_all)
    monkeypatch.setattr(engine, "rollback_startup_initial_fills", rollback)
    monkeypatch.setattr(
        "app.services.grid.exchange_requirements.validate_neutral_grid_exchange_support",
        lambda *_args, **_kwargs: (True, ""),
    )
    monkeypatch.setattr(
        "app.services.grid.exchange_requirements.fetch_exchange_dual_leg_snapshot",
        lambda *_args, **_kwargs: {
            "long_size": 0.0,
            "short_size": 0.0,
            "position_mode_label": "spot",
        },
    )

    ok, message = runner.startup(2500.0)

    assert ok is False
    assert message == "strategyRuntime.gridStartupCoverageFailedRolledBack"
    cancel_all.assert_called_once_with()
    rollback.assert_called_once_with(2500.0)


def test_grid_tick_stops_processing_after_boundary_trigger(monkeypatch):
    from types import SimpleNamespace

    calls = []

    class FakeEngine:
        cfg = SimpleNamespace(initial_position_pct=0.0, grid_direction="long")
        stop_requested = False

        def set_runtime_params(self, _params):
            calls.append("params")

        def handle_boundary(self, _price):
            calls.append("boundary")
            return True

        def sync_exit_coverage(self, _price):
            calls.append("exits")

        def sync_grid_orders(self, _price):
            calls.append("entries")

    monkeypatch.setattr(
        "app.services.grid.runner.prepare_bot_market_guards",
        lambda *args, **kwargs: None,
    )
    runner = GridRestingRunner.__new__(GridRestingRunner)
    runner._started = True
    runner._engine = FakeEngine()
    runner._runtime_params = {}
    runner._risk_exit_fn = None
    runner._last_exit_sync_ts = 0.0
    runner._last_sync_ts = 0.0

    runner.tick(50.0)

    assert calls == ["params", "boundary"]


def test_grid_config_rejects_spacing_that_cannot_cover_round_trip_fees():
    cfg = GridBotConfig.from_trading_config(
        {
            "leverage": 5,
            "market_type": "swap",
            "initial_capital": 100,
            "commission": 0.1,
            "bot_params": {
                "upperPrice": 1647.07,
                "lowerPrice": 1644.47,
                "gridCount": 2,
                "amountPerGrid": 5,
                "gridDirection": "long",
                "initialPositionPct": 0,
            },
        }
    )
    ok, msg, warnings = validate_grid_config(cfg, initial_capital=100, fee_rate=0.001)

    assert ok is False
    assert warnings == []
    assert "too narrow after fees" in msg
