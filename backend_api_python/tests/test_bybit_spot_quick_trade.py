from decimal import Decimal
from unittest.mock import MagicMock, patch

from app.services.live_trading.bybit import BybitClient


def test_bybit_spot_get_positions_delegates_to_wallet_holdings():
    client = BybitClient(api_key="k", secret_key="s", category="spot")
    with patch.object(client, "get_spot_holdings", return_value={"result": {"list": []}}) as mock_hold:
        out = client.get_positions(symbol="SOL/USDT")
    mock_hold.assert_called_once_with(symbol="SOL/USDT")
    assert out == {"result": {"list": []}}


@patch.object(BybitClient, "get_instrument_info")
def test_bybit_normalize_quantity_floors_to_qty_step(mock_info):
    mock_info.return_value = {
        "lotSizeFilter": {"qtyStep": "0.001", "minOrderQty": "0.001"},
    }
    client = BybitClient(api_key="k", secret_key="s", category="spot")
    dec, prec = client._normalize_quantity(symbol="SOL/USDT", quantity=0.06173602)
    assert dec == Decimal("0.061")
    assert prec is not None


@patch.object(BybitClient, "get_instrument_info")
def test_bybit_spot_normalize_quantity_uses_base_precision(mock_info):
    mock_info.return_value = {
        "lotSizeFilter": {"basePrecision": "0.000001", "minOrderAmt": "5"},
    }
    client = BybitClient(api_key="k", secret_key="s", category="spot")
    dec, prec = client._normalize_quantity(symbol="ETH/USDT", quantity=0.004364876)
    assert dec == Decimal("0.004364")
    assert prec == 6


@patch.object(BybitClient, "get_instrument_info")
def test_bybit_spot_limit_validates_minimum_notional_before_submission(mock_info):
    mock_info.return_value = {
        "lotSizeFilter": {"basePrecision": "0.000001", "minOrderAmt": "5"},
        "priceFilter": {"tickSize": "0.01"},
    }
    client = BybitClient(api_key="k", secret_key="s", category="spot")
    with patch.object(client, "_signed_request") as request:
        try:
            client.place_limit_order(symbol="ETH/USDT", side="buy", qty=0.001, price=2500)
        except Exception as exc:
            assert "minOrderAmt" in str(exc)
        else:
            raise AssertionError("Below-minimum order must be rejected locally")
    request.assert_not_called()


@patch.object(BybitClient, "get_instrument_info")
def test_bybit_spot_limit_body_uses_exchange_precision(mock_info):
    mock_info.return_value = {
        "lotSizeFilter": {
            "basePrecision": "0.000001",
            "minOrderAmt": "5",
            "maxLimitOrderQty": "100",
        },
        "priceFilter": {"tickSize": "0.01"},
    }
    client = BybitClient(api_key="k", secret_key="s", category="spot")
    with patch.object(client, "_signed_request", return_value={"result": {"orderId": "1"}}) as request:
        client.place_limit_order(symbol="ETH/USDT", side="sell", qty=0.004364876, price=2750.129)

    body = request.call_args.kwargs["json_body"]
    assert body["qty"] == "0.004364"
    assert body["price"] == "2750.12"
    assert "reduceOnly" not in body


@patch.object(BybitClient, "get_instrument_info")
def test_bybit_place_market_order_qty_string_respects_step(mock_info):
    mock_info.return_value = {
        "lotSizeFilter": {"qtyStep": "0.001", "minOrderQty": "0.001"},
    }
    client = BybitClient(api_key="k", secret_key="s", category="spot")
    with patch.object(client, "_signed_request") as mock_req:
        mock_req.return_value = {"result": {"orderId": "1"}}
        client.place_market_order(symbol="SOL/USDT", side="buy", qty=0.06173602)
    body = mock_req.call_args.kwargs.get("json_body") or mock_req.call_args[1].get("json_body")
    assert body["category"] == "spot"
    assert body["qty"] == "0.061"
