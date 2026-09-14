from app.services.live_trading.bitget_reality import BitgetRealityClient
from app.services.live_trading.factory import create_client


def _client():
    return BitgetRealityClient(api_key="key", secret_key="secret", passphrase="pass")


def test_factory_selects_reality_api_family():
    client = create_client(
        {
            "exchange_id": "bitget",
            "api_key": "key",
            "secret_key": "secret",
            "passphrase": "pass",
            "environment": "live",
            "api_family": "reality",
            "instrument_id": "rAAPLUSDT",
        },
        market_type="spot",
    )

    assert isinstance(client, BitgetRealityClient)
    assert client.instrument_id == "RAAPLUSDT"


def test_reality_client_uses_bound_native_symbol(monkeypatch):
    client = BitgetRealityClient(
        api_key="key",
        secret_key="secret",
        passphrase="pass",
        instrument_id="rAAPLUSDT",
    )
    monkeypatch.setattr(client, "_normalize_base_size", lambda **kwargs: (client._to_dec("1"), 0))
    calls = []

    def signed(method, path, **kwargs):
        calls.append(kwargs["json_body"])
        return {"data": {"orderId": "native-1"}}

    monkeypatch.setattr(client, "_signed_request", signed)
    client.place_market_order(symbol="AAPLX/USDT", side="sell", size=1)

    assert calls[0]["symbol"] == "RAAPLUSDT"


def test_reality_limit_order_uses_v3_endpoint_and_qty(monkeypatch):
    client = _client()
    monkeypatch.setattr(client, "_normalize_base_size", lambda **kwargs: (client._to_dec("0.25"), 2))
    monkeypatch.setattr(client, "_normalize_limit_price", lambda **kwargs: (client._to_dec("185.12"), 2))
    calls = []

    def signed(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"code": "00000", "data": {"orderId": "reality-1"}}

    monkeypatch.setattr(client, "_signed_request", signed)
    result = client.place_limit_order(
        symbol="RAAPL/USDT",
        side="buy",
        size=0.25,
        price=185.12,
        client_order_id="client-1",
    )

    assert result.exchange_order_id == "reality-1"
    assert calls == [(
        "POST",
        "/api/v3/trade/place-reality-order",
        {"json_body": {
            "category": "SPOT",
            "symbol": "RAAPLUSDT",
            "side": "buy",
            "orderType": "limit",
            "qty": "0.25",
            "price": "185.12",
            "clientOid": "client-1",
        }},
    )]


def test_reality_order_and_fills_are_normalized_for_common_fill_logic(monkeypatch):
    client = _client()

    def signed(method, path, **kwargs):
        if path == "/api/v3/trade/order-info":
            return {"data": {"list": [{
                "orderId": "1",
                "cumExecQty": "0.4",
                "cumExecValue": "80",
                "avgPrice": "200",
                "orderStatus": "filled",
            }]}}
        return {"data": {"list": [{
            "execQty": "0.4",
            "execPrice": "200",
            "feeDetail": [{"totalFee": "-0.08", "feeCoin": "USDT"}],
        }]}}

    monkeypatch.setattr(client, "_signed_request", signed)

    order = client.get_order(symbol="RAAPL/USDT", order_id="1")["data"]
    fills = client.get_fills(symbol="RAAPL/USDT", order_id="1")["data"]

    assert order["baseVolume"] == "0.4"
    assert order["quoteVolume"] == "80"
    assert order["priceAvg"] == "200"
    assert order["status"] == "filled"
    assert fills[0]["size"] == "0.4"
    assert fills[0]["priceAvg"] == "200"
    assert fills[0]["feeDetail"][0]["feeCoin"] == "USDT"
