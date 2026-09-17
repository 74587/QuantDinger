import inspect
from contextlib import contextmanager

from flask import Flask, g

from app.routes import quick_trade


class _Cursor:
    def __init__(self):
        self.query = ""
        self.params = ()

    def execute(self, query, params):
        self.query = query
        self.params = params

    def fetchall(self):
        return [{
            "id": 7,
            "credential_id": 305,
            "exchange_id": "okx",
            "symbol": "BTC/USDT",
            "side": "buy",
            "order_type": "market",
            "amount": 100,
            "price": 0,
            "leverage": 5,
            "market_type": "swap",
            "status": "filled",
            "exchange_order_id": "order-1",
            "filled_amount": 0.001,
            "avg_fill_price": 75000,
            "commission": 0.03,
            "commission_ccy": "USDT",
            "commission_quote": 0.03,
        }]

    def close(self):
        return None


class _Db:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def test_history_filters_by_account_symbol_and_market(monkeypatch):
    cursor = _Cursor()

    @contextmanager
    def fake_connection():
        yield _Db(cursor)

    monkeypatch.setattr(quick_trade, "get_db_connection", fake_connection)
    app = Flask(__name__)
    handler = inspect.unwrap(quick_trade.get_history)

    with app.test_request_context(
        "/api/quick-trade/history?limit=20&credential_id=305&symbol=BTC/USDT&market_type=perpetual"
    ):
        g.user_id = 99
        response = handler()

    payload = response.get_json()
    assert "credential_id = %s" in cursor.query
    assert "UPPER(symbol) = UPPER(%s)" in cursor.query
    assert "market_type = %s" in cursor.query
    assert cursor.params == (99, 305, "BTC/USDT", "swap", 20, 0)
    assert payload["data"]["trades"][0]["credential_id"] == 305
    assert payload["data"]["trades"][0]["commission_quote"] == 0.03
