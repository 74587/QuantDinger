from app.services.live_trading.factory import create_client
from app.services.live_trading.gate import GateStockClient
from app.services.pending_orders.live_order_phases import place_live_market_order


def _client() -> GateStockClient:
    return GateStockClient(
        api_key="key",
        secret_key="secret",
        product_meta={
            "trade_mode": 4,
            "min_order_volume": "0.0001",
            "max_order_volume": "1000",
            "step_order_volume": "0.0001",
            "volume_precision": 4,
        },
    )


def test_factory_selects_gate_stock_api_family():
    client = create_client(
        {
            "exchange_id": "gate",
            "api_key": "key",
            "secret_key": "secret",
            "api_family": "stock",
        },
        market_type="spot",
    )

    assert isinstance(client, GateStockClient)


def test_gate_stock_market_order_uses_share_quantity(monkeypatch):
    client = _client()
    captured = {}

    def request(method, path, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})
        return {"data": {"id": "123"}, "timestamp": 1}

    monkeypatch.setattr(client, "_signed_request", request)
    monkeypatch.setattr(client, "get_symbol_details", lambda **kwargs: {})

    result = place_live_market_order(
        client=client,
        symbol="AAPL/USD",
        side="buy",
        amount=2.5,
        reduce_only=False,
        pos_side="long",
        client_order_id="client-1",
        market_type="spot",
        payload={},
        exchange_config={"api_family": "stock"},
        leverage=1,
        ref_price=200,
        spot_quote_amt=500,
        spot_market_buy_uses_quote=False,
    )

    assert result.exchange_order_id == "123"
    assert captured["path"] == "/api/v4/stock/orders"
    assert captured["json_body"]["volume"] == "2.5000"
    assert captured["json_body"]["symbol"] == "AAPL"
    assert captured["json_body"]["side"] == 2


def test_gate_stock_order_applies_symbol_step_and_side_rules(monkeypatch):
    client = _client()
    captured = {}
    monkeypatch.setattr(client, "get_symbol_details", lambda **kwargs: {"trade_mode": 1})
    monkeypatch.setattr(
        client,
        "_signed_request",
        lambda method, path, **kwargs: captured.update(kwargs) or {"data": {"id": "1"}},
    )

    client.place_market_order(symbol="AAPL/USD", side="buy", size=2.50009)

    assert captured["json_body"]["volume"] == "2.5000"


def test_gate_stock_order_rejects_disallowed_side(monkeypatch):
    client = _client()
    monkeypatch.setattr(client, "get_symbol_details", lambda **kwargs: {"trade_mode": 1})

    try:
        client.place_market_order(symbol="AAPL/USD", side="sell", size=1)
    except Exception as exc:
        assert "sell is disabled" in str(exc)
    else:
        raise AssertionError("sell-only validation did not run")


def test_gate_stock_fill_reports_actual_commission(monkeypatch):
    client = _client()
    monkeypatch.setattr(
        client,
        "get_order",
        lambda **kwargs: {
            "order_id": "123",
            "status_desc": "filled",
            "fill_volume": "2.5",
            "avg_fill_price": "200.10",
            "commission": "0.50",
            "quote_currency": "USD",
        },
    )

    fill = client.wait_for_fill(order_id="123", symbol="AAPL/USD", max_wait_sec=0)

    assert fill["filled"] == 2.5
    assert fill["avg_price"] == 200.10
    assert fill["fee"] == 0.5
    assert fill["fee_ccy"] == "USD"


def test_gate_hk_stock_rules_and_fee_currency_keep_exchange_identity(monkeypatch):
    client = GateStockClient(
        api_key="key",
        secret_key="secret",
        product_meta={
            "stock_exchange": "hk",
            "quote_currency": "HKD",
            "trade_mode": 4,
        },
    )
    captured = {}

    def public_request(method, path, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})
        return {"data": {"list": [{"symbol": "00700", "trade_mode": 4}]}}

    monkeypatch.setattr(client, "_public_request", public_request)
    assert client.get_symbol_details(symbol="00700/HKD")["symbol"] == "00700"
    assert captured["params"]["exchange"] == "hk"

    monkeypatch.setattr(
        client,
        "get_order",
        lambda **kwargs: {
            "order_id": "123",
            "status_desc": "filled",
            "fill_volume": "1",
            "avg_fill_price": "500",
            "commission": "0.5",
        },
    )
    fill = client.wait_for_fill(order_id="123", symbol="00700/HKD", max_wait_sec=0)
    assert fill["fee_ccy"] == "HKD"
