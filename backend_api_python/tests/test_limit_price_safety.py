from app.services.live_trading.limit_price_safety import (
    fetch_live_reference_price,
    is_marketable_limit_price,
    normalize_marketable_limit_price,
)
from app.services.quick_trade.orders import limit_order_kwargs


def test_marketable_limit_detection_is_side_aware():
    assert is_marketable_limit_price(side="buy", limit_price=101, reference_price=100)
    assert not is_marketable_limit_price(side="buy", limit_price=99, reference_price=100)
    assert is_marketable_limit_price(side="sell", limit_price=99, reference_price=100)
    assert not is_marketable_limit_price(side="sell", limit_price=101, reference_price=100)


def test_marketable_limit_is_clamped_without_worsening_bound():
    assert normalize_marketable_limit_price(
        side="buy", limit_price=101, reference_price=100
    ) == 100
    assert normalize_marketable_limit_price(
        side="sell", limit_price=99, reference_price=100
    ) == 100
    assert normalize_marketable_limit_price(
        side="buy", limit_price=99, reference_price=100
    ) == 99


def test_reference_price_supports_exchange_ticker_shapes():
    class Client:
        def get_ticker(self, *, symbol):
            assert symbol == "ETH/USDT"
            return {"lastPr": "2645.25"}

    assert fetch_live_reference_price(Client(), symbol="ETH/USDT") == 2645.25


def test_quick_trade_clamps_crossed_limit_before_building_exchange_kwargs():
    class Client:
        def get_ticker(self, *, symbol):
            assert symbol == "ETH/USDT"
            return {"last": "2645"}

    kwargs = limit_order_kwargs(
        Client(),
        "ETH/USDT",
        0.01,
        2686.5,
        "buy",
        "spot",
        "quick-1",
    )

    assert kwargs["price"] == 2645.0
    assert kwargs["size"] == 0.01
