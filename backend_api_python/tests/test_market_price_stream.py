import time

from app.services.market_price_stream import PublicMarketPriceFeed


def _feed(exchange_id="binance", market_type="swap", fallback=None):
    return PublicMarketPriceFeed(
        exchange_id=exchange_id,
        market_type=market_type,
        instruments=[{
            "key": "Crypto:BTC/USDT@binance:swap",
            "symbol": "BTC/USDT",
        }],
        rest_fallback=fallback or (lambda: {}),
    )


def test_public_price_feed_normalizes_binance_and_okx_symbols():
    binance = _feed("binance")
    for symbol, price in binance._parse({"data": {"s": "BTCUSDT", "p": "101.5"}}):
        binance._update(symbol, price)
    snapshot = binance.snapshot(max_age_seconds=5)
    assert snapshot.prices["Crypto:BTC/USDT@binance:swap"] == 101.5
    assert snapshot.source == "public_websocket"

    okx = PublicMarketPriceFeed(
        exchange_id="okx",
        market_type="swap",
        instruments=[{"key": "Crypto:BTC/USDT@okx:swap", "symbol": "BTC/USDT"}],
        rest_fallback=lambda: {},
    )
    for symbol, price in okx._parse({"data": [{"instId": "BTC-USDT-SWAP", "last": "102"}]}):
        okx._update(symbol, price)
    assert okx.snapshot().prices["Crypto:BTC/USDT@okx:swap"] == 102


def test_binance_spot_ticker_uses_last_price_instead_of_price_change():
    feed = _feed("binance", market_type="spot")

    rows = feed._parse({
        "data": {
            "s": "BTCUSDT",
            "p": "118.52",
            "c": "2590.81",
        },
    })

    assert rows == [("BTCUSDT", 2590.81)]


def test_spot_uses_last_trade_while_derivatives_prefer_mark_price():
    fixtures = {
        "okx": ({"data": [{"instId": "BTC-USDT-SWAP", "last": "100", "markPx": "101"}]}, 100, 101),
        "bybit": ({"data": {"symbol": "BTCUSDT", "lastPrice": "100", "markPrice": "101"}}, 100, 101),
        "bitget": ({"data": [{"instId": "BTCUSDT", "lastPr": "100", "markPrice": "101"}]}, 100, 101),
        "gate": ({"result": {"contract": "BTC_USDT", "currency_pair": "BTC_USDT", "last": "100", "mark_price": "101"}}, 100, 101),
    }

    for exchange_id, (payload, spot_price, swap_price) in fixtures.items():
        assert _feed(exchange_id, "spot")._parse(payload)[0][1] == spot_price
        assert _feed(exchange_id, "swap")._parse(payload)[0][1] == swap_price


def test_price_payload_without_a_supported_price_is_ignored_by_the_cache():
    feed = _feed("bybit", "spot")
    rows = feed._parse({"data": {"symbol": "BTCUSDT"}})

    assert rows == [("BTCUSDT", 0.0)]
    for symbol, price in rows:
        feed._update(symbol, price)
    assert feed.snapshot(max_age_seconds=5).prices == {}


def test_public_price_feed_uses_rest_only_for_missing_or_stale_prices():
    feed = _feed(fallback=lambda: {"Crypto:BTC/USDT@binance:swap": 99.0})
    fallback = feed.snapshot(max_age_seconds=1)
    assert fallback.source == "rest_fallback"
    assert fallback.prices["Crypto:BTC/USDT@binance:swap"] == 99.0

    feed._prices["Crypto:BTC/USDT@binance:swap"] = (101.0, time.monotonic())
    streamed = feed.snapshot(max_age_seconds=1)
    assert streamed.source == "public_websocket"
    assert streamed.prices["Crypto:BTC/USDT@binance:swap"] == 101.0


def test_reality_feed_uses_rest_until_reality_websocket_is_verified():
    feed = PublicMarketPriceFeed(
        exchange_id="bitget",
        market_type="spot",
        instruments=[{
            "key": "Crypto:RAAPL/USDT@bitget:spot",
            "symbol": "RAAPL/USDT",
            "instrument_id": "rAAPLUSDT",
            "api_family": "reality",
        }],
        rest_fallback=lambda: {},
    )

    assert feed.supported is False
    assert feed._symbols() == ["rAAPLUSDT"]


def test_gate_stock_feed_does_not_subscribe_to_crypto_spot_channel():
    feed = PublicMarketPriceFeed(
        exchange_id="gate",
        market_type="spot",
        instruments=[{
            "key": "Crypto:AAPL/USD@gate:spot",
            "symbol": "AAPL/USD",
            "instrument_id": "AAPL",
            "api_family": "stock",
        }],
        rest_fallback=lambda: {"Crypto:AAPL/USD@gate:spot": 200.0},
    )

    assert feed.supported is False
    assert feed.snapshot().prices["Crypto:AAPL/USD@gate:spot"] == 200.0
