from app.routes import fast_analysis


def test_professional_analysis_uses_gate_hk_underlying(monkeypatch):
    monkeypatch.setattr(fast_analysis, "get_catalog_product", lambda **kwargs: {
        "product_type": "direct_equity",
        "underlying_market": "HKStock",
        "underlying_symbol": "00700",
    })

    assert fast_analysis._resolve_analysis_instrument(
        market="Crypto",
        symbol="00700/HKD",
        exchange_id="gate",
        market_type="spot",
        instrument_id="00700",
    ) == ("HKStock", "00700")


def test_professional_analysis_keeps_native_crypto(monkeypatch):
    monkeypatch.setattr(fast_analysis, "get_catalog_product", lambda **kwargs: {
        "product_type": "crypto",
    })

    assert fast_analysis._resolve_analysis_instrument(
        market="Crypto",
        symbol="BTC/USDT",
        exchange_id="gate",
        market_type="spot",
    ) == ("Crypto", "BTC/USDT")
