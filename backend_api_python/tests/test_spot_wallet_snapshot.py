"""Spot wallet snapshot parsers for all supported exchanges."""

import pytest

from app.services.live_trading.base import LiveTradingError
from app.services.live_trading.bitget_spot import BitgetSpotClient
from app.services.live_trading.spot_wallet_snapshot import (
    _from_binance_spot_account,
    _from_bitget_assets,
    _from_bybit_spot_holdings,
    _from_gate_spot_accounts,
    _from_okx_balance,
    list_spot_wallet_positions,
)


def test_okx_spot_balance_parser():
    raw = {
        "data": [
            {
                "details": [
                    {"ccy": "ETH", "eq": "0.25", "availBal": "0.24", "openAvgPx": "2100"},
                    {"ccy": "USDT", "eq": "500", "availBal": "500"},
                ]
            }
        ]
    }
    rows = _from_okx_balance(raw)
    assert len(rows) == 2
    eth = next(r for r in rows if r["symbol"] == "ETH/USDT")
    assert eth["size"] == 0.25
    assert eth["entry_price"] == 2100.0


def test_binance_spot_balances_parser():
    raw = {
        "balances": [
            {"asset": "BTC", "free": "0.01", "locked": "0.002"},
            {"asset": "USDT", "free": "100", "locked": "0"},
        ]
    }
    rows = _from_binance_spot_account(raw)
    btc = next(r for r in rows if r["symbol"] == "BTC/USDT")
    assert btc["size"] == 0.012


def test_bitget_spot_assets_parser():
    raw = {
        "data": [
            {"coin": "BNB", "available": "1.5", "frozen": "0.1", "locked": "0.2", "averageOpenPrice": "600"},
        ]
    }
    rows = _from_bitget_assets(raw)
    assert rows[0]["symbol"] == "BNB/USDT"
    assert rows[0]["size"] == 1.8


@pytest.mark.parametrize(
    "symbol,expected_symbol,expected_inst_id",
    [
        ("ETH/USDT", "ETH/USDT", "ETH-USDT"),
        ("ETHUSDT", "ETH/USDT", "ETH-USDT"),
        ("BTCUSDT", "BTC/USDT", "BTC-USDT"),
        ("USDCUSDT", "USDC/USDT", "USDC-USDT"),
        ("USDT", "USDT", "USDT"),
    ],
)
def test_bybit_spot_holdings_parser(symbol, expected_symbol, expected_inst_id):
    raw = {"result": {"list": [{"symbol": symbol, "bal": "0.33"}]}}
    rows = _from_bybit_spot_holdings(raw)
    assert rows[0]["symbol"] == expected_symbol
    assert rows[0]["inst_id"] == expected_inst_id
    assert rows[0]["size"] == 0.33


def test_bybit_wallet_snapshot_matches_strategy_ownership(monkeypatch):
    from app.services.live_trading.account_positions import snapshot_rows_to_account_legs
    from app.services.live_trading.bybit import BybitClient
    from app.services.live_trading.position_ownership import build_ownership_rows

    client = BybitClient(api_key="test-key", secret_key="test-secret", category="spot")
    monkeypatch.setattr(
        client,
        "get_wallet_balance",
        lambda **kwargs: {
            "result": {"list": [{"coin": [{"coin": "ETH", "walletBalance": "1.2277699"}]}]},
        },
    )
    account_rows = snapshot_rows_to_account_legs(list_spot_wallet_positions(client))
    rows = build_ownership_rows(
        account_rows=account_rows,
        allocated_rows=[{"symbol": "ETH/USDT", "side": "long", "size": 0.2277699}],
        reservation_rows=[],
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["symbol"] == "ETH/USDT"
    assert row["account_qty"] == pytest.approx(1.2277699)
    assert row["protected_qty"] == pytest.approx(1.0)
    assert row["status"] == "ok"
    assert row["repair_kind"] == "none"


def test_gate_spot_accounts_parser():
    raw = [
        {"currency": "SOL", "available": "2", "locked": "0.5"},
    ]
    rows = _from_gate_spot_accounts(raw)
    assert rows[0]["symbol"] == "SOL/USDT"
    assert rows[0]["size"] == 2.5


def test_list_spot_wallet_unknown_client():
    assert list_spot_wallet_positions(object()) == []


def test_spot_wallet_exchange_errors_are_not_silenced(monkeypatch):
    client = BitgetSpotClient.__new__(BitgetSpotClient)

    def fail_get_assets(_self):
        raise LiveTradingError("spot assets unavailable")

    monkeypatch.setattr(BitgetSpotClient, "get_assets", fail_get_assets)
    with pytest.raises(LiveTradingError, match="spot assets unavailable"):
        list_spot_wallet_positions(client)
