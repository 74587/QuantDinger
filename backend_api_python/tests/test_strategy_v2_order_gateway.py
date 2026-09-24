from types import SimpleNamespace

from app.services.strategy_v2 import live_execution
from app.services.strategy_v2.live_execution import LiveOrderRequest, StrategyV2OrderGateway


class _Cursor:
    def __init__(self, row):
        self.row = row
        self.params = ()

    def execute(self, _query, params):
        self.params = tuple(params)

    def fetchone(self):
        return self.row

    def close(self):
        return None


class _Db:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def cursor(self):
        return self._cursor

    def commit(self):
        return None


def _request(action="open_long", **overrides):
    values = {
        "strategy_id": 7,
        "strategy_run_id": 42,
        "user_id": 12,
        "symbol": "BTC/USDT",
        "action": action,
        "quantity": 0.01,
        "reference_price": 60_000.0,
        "signal_timestamp": 123,
        "market_type": "swap",
        "execution_mode": "live",
    }
    values.update(overrides)
    return LiveOrderRequest(
        **values,
    )


def test_inflight_lookup_serializes_the_same_long_position_leg(monkeypatch):
    cursor = _Cursor({"id": 99})
    monkeypatch.setattr(live_execution, "get_db_connection", lambda: _Db(cursor))

    assert StrategyV2OrderGateway().has_inflight(_request("close_long")) is True
    assert cursor.params[:3] == (7, 42, "BTC/USDT")
    assert cursor.params[3:7] == (
        "open_long",
        "add_long",
        "reduce_long",
        "close_long",
    )
    assert cursor.params[7:] == ("pending", "processing", "sent", "syncing")


def test_inflight_lookup_keeps_short_hedge_leg_independent(monkeypatch):
    cursor = _Cursor({})
    monkeypatch.setattr(live_execution, "get_db_connection", lambda: _Db(cursor))

    assert StrategyV2OrderGateway().has_inflight(_request("open_short")) is False
    assert cursor.params[3:7] == (
        "open_short",
        "add_short",
        "reduce_short",
        "close_short",
    )


def test_submit_does_not_reconsider_an_ai_rejected_signal(monkeypatch):
    class _IntentService:
        def __init__(self, **_kwargs):
            pass

        def build_signal_idempotency_key(self, **_kwargs):
            return "same-signal"

        def create_intent(self, **_kwargs):
            return SimpleNamespace(id=91, existing=True, status="ai_rejected")

    monkeypatch.setattr(live_execution, "OrderIntentService", _IntentService)
    assert StrategyV2OrderGateway().submit(_request()) is None


def test_ai_rejection_is_latched_until_the_signal_disappears(monkeypatch):
    decisions = []
    next_intent_id = iter((91, 92))

    class _IntentService:
        def __init__(self, **_kwargs):
            pass

        @staticmethod
        def build_signal_idempotency_key(**kwargs):
            return f"signal-{kwargs['signal_ts']}"

        def create_intent(self, **_kwargs):
            return SimpleNamespace(
                id=next(next_intent_id),
                existing=False,
                status="intent_created",
            )

    class _RejectingFilter:
        @staticmethod
        def evaluate(request, *, enabled):
            decisions.append((request.action, enabled))
            return SimpleNamespace(allowed=False)

    monkeypatch.setattr(live_execution, "OrderIntentService", _IntentService)
    monkeypatch.setattr(
        live_execution,
        "get_db_connection",
        lambda: _Db(_Cursor({})),
    )
    gateway = StrategyV2OrderGateway(decision_filter_factory=_RejectingFilter)
    request = _request(ai_decision_filter=True, reason="dual_ma_open_long")

    gateway.begin_signal_cycle(42)
    assert gateway.submit(request) is None
    gateway.finish_signal_cycle(42)

    gateway.begin_signal_cycle(42)
    assert gateway.submit(_request(
        ai_decision_filter=True,
        reason="dual_ma_open_long",
        signal_timestamp=124,
    )) is None
    gateway.finish_signal_cycle(42)
    assert decisions == [("open_long", True)]

    gateway.begin_signal_cycle(42)
    gateway.finish_signal_cycle(42)

    gateway.begin_signal_cycle(42)
    assert gateway.submit(_request(
        ai_decision_filter=True,
        reason="dual_ma_open_long",
        signal_timestamp=125,
    )) is None
    gateway.finish_signal_cycle(42)
    assert decisions == [("open_long", True), ("open_long", True)]
