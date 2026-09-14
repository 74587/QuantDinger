from app.services.live_trading.symbols import (
    to_binance_futures_symbol,
    to_bitget_um_symbol,
    to_bybit_symbol,
    to_gate_currency_pair,
    to_htx_contract_code,
    to_okx_swap_inst_id,
)
from app.services.live_trading.capabilities import supports_equity_product


def test_equity_perpetual_native_instrument_ids_for_six_exchanges():
    symbol = "AAPL/USDT"

    assert to_binance_futures_symbol(symbol) == "AAPLUSDT"
    assert to_bitget_um_symbol(symbol) == "AAPLUSDT"
    assert to_bybit_symbol(symbol) == "AAPLUSDT"
    assert to_okx_swap_inst_id(symbol) == "AAPL-USDT-SWAP"
    assert to_gate_currency_pair(symbol) == "AAPL_USDT"
    assert to_htx_contract_code(symbol) == "AAPL-USDT"


def test_equity_product_capability_matrix_is_api_family_specific():
    assert supports_equity_product("binance", "tokenized_equity", "spot", "spot")
    assert supports_equity_product("binance", "stock_perpetual", "swap", "swap")
    assert supports_equity_product("okx", "tokenized_equity", "spot", "spot")
    assert supports_equity_product("okx", "stock_perpetual", "swap", "swap")
    assert supports_equity_product("gate", "stock_perpetual", "swap", "swap")
    assert supports_equity_product("bybit", "tokenized_equity", "spot", "spot")
    assert supports_equity_product("bybit", "stock_perpetual", "swap", "swap")
    assert supports_equity_product("bitget", "tokenized_equity", "spot", "reality")
    assert supports_equity_product("bitget", "stock_perpetual", "swap", "swap")
    assert supports_equity_product("gate", "direct_equity", "spot", "stock")

    assert not supports_equity_product("bitget", "tokenized_equity", "spot", "spot")
    assert not supports_equity_product("gate", "direct_equity", "spot", "spot")
    assert not supports_equity_product("htx", "stock_perpetual", "swap", "swap")
