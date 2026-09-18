"""Order-linked grid accounting regression cases."""
from copy import deepcopy

import pytest

from app.services.grid.order_pnl import enrich_grid_order_pnl
from app.utils.trade_net_pnl import enrich_trades_net_pnl


def trade(id, action, price, quantity=1, *, cell=0, cycle=1, fee=0.1, **kwargs):
    side = "long" if "long" in action else "short"
    phase = "entry" if action.startswith("open") else "exit"
    return dict(id=id, strategy_id=1, strategy_run_id=1, credential_id=7, market_type="swap",
        symbol="BTC/USDT", type=action, price=price, amount=quantity,
        exchange_order_id=f"exchange-{id}", grid_client_reference=f"grid-{cell}-{side}-{phase}-{cycle}",
        commission_quote=fee, fee_status="actual", profit=-4 if phase == "exit" else None, **kwargs)


def project(rows):
    rows = deepcopy(rows)
    enrich_trades_net_pnl(rows)
    enrich_grid_order_pnl(rows)
    return rows


def test_two_cells_close_their_own_order_not_whole_position_average_or_fifo():
    rows = [trade(1,"open_long",110,cell=0,fee=0.11),
            trade(2,"open_long",100,cell=1,fee=0.10),
            trade(3,"close_long",101,cell=1,fee=0.101)]
    close = project(rows)[-1]
    assert close["account_profit_gross"] == -4
    assert close["profit_gross"] == 1
    assert close["profit"] == pytest.approx(0.799)
    assert close["matched_orders"][0]["entry_order_ids"] == ["exchange-2"]
    assert close["pnl_status"] == "matched"


def test_partial_entries_and_multiple_exits_allocate_actual_cost_and_fee_once():
    rows = [trade(1,"open_long",100,quantity=.4,fee=.04),
            trade(2,"open_long",110,quantity=.6,fee=.066),
            trade(3,"close_long",112,quantity=.3,fee=.0336),
            trade(4,"close_long",113,quantity=.7,fee=.0791),
            trade(5,"close_long",114,quantity=.1,fee=.0114)]
    result = project(rows)
    assert result[2]["matched_entry_price"] == 106
    assert result[2]["open_commission_allocated"] == pytest.approx(.0318)
    assert result[3]["open_commission_allocated"] == pytest.approx(.0742)
    assert sum(r["profit"] for r in result[2:4]) == pytest.approx(6.4813)
    assert result[4]["profit"] is None
    assert result[4]["pnl_status"] == "unmatched"


@pytest.mark.parametrize("changed", [{"credential_id":8}, {"strategy_run_id":2},
    {"market_type":"spot"}, {"symbol":"ETH/USDT"}, {"grid_client_reference":"grid-0-long-entry-2"}])
def test_account_market_symbol_run_and_cycle_do_not_mix(changed):
    opening = trade(1,"open_long",100)
    opening.update(changed)
    closing = project([opening,trade(2,"close_long",101)])[-1]
    assert closing["profit"] is None
    assert closing["pnl_status"] == "unmatched"


def test_short_and_negative_maker_fee_are_accounted():
    closing = project([trade(1,"open_short",110,fee=-.01),trade(2,"close_short",100,fee=.1)])[-1]
    assert closing["profit"] == pytest.approx(9.91)


def test_delayed_fee_and_third_currency_fee_do_not_look_like_zero_fee():
    rows = [trade(1,"open_long",100),trade(2,"close_long",101)]
    rows[0].update(fee_status="pending", commission_quote=None, commission=0)
    assert project(rows)[-1]["pnl_status"] == "fees_pending"
    assert project(rows)[-1]["profit"] is None
    rows[0].update(fee_status="actual", commission=.001, commission_ccy="BNB")
    assert project(rows)[-1]["profit"] is None
    rows[0]["commission_quote"] = .3
    assert project(rows)[-1]["profit"] == pytest.approx(.6)


def test_resting_grid_uses_persisted_entry_order_ids_not_cell_price():
    opening = trade(1,"open_long",100)
    closing = trade(2,"close_long",101)
    opening.update(grid_order_id=10, grid_order_purpose="long_entry")
    closing.update(grid_order_id=11,grid_order_purpose="long_exit", grid_order_extra={"entry_grid_order_ids":[10]})
    assert project([opening,closing])[-1]["profit"] == pytest.approx(.8)
    closing["grid_order_extra"] = {}
    assert project([opening,closing])[-1]["profit"] is None


def test_seed_inventory_without_explicit_pairing_is_not_assigned_an_unrelated_buy():
    opening = trade(1,"open_long",100)
    opening["grid_client_reference"] = "grid-initial-long"
    assert project([opening,trade(2,"close_long",101)])[-1]["profit"] is None


def test_seed_exits_pair_only_with_the_explicit_grid_initial_inventory():
    unrelated = trade(1, "open_long", 90, quantity=.5, fee=.045)
    initial = trade(2, "open_long", 100, quantity=1, fee=.1)
    initial.update(close_reason="grid_initial_long", grid_client_reference="grid-initial-long")
    first_exit = trade(3, "close_long", 110, quantity=.4, fee=.044)
    second_exit = trade(4, "close_long", 120, quantity=.6, fee=.072)
    overflow = trade(5, "close_long", 130, quantity=.1, fee=.013)
    for index, row in enumerate((first_exit, second_exit, overflow), start=11):
        row.update(grid_order_id=index, grid_order_purpose="long_exit", grid_order_extra={})

    result = project([unrelated, initial, first_exit, second_exit, overflow])

    assert result[2]["matched_entry_price"] == 100
    assert result[2]["profit"] == pytest.approx(3.916)
    assert result[3]["matched_entry_price"] == 100
    assert result[3]["profit"] == pytest.approx(11.868)
    assert result[4]["pnl_status"] == "unmatched"
    assert result[2]["matched_orders"][0]["entry_order_ids"] == ["exchange-2"]


def test_seed_pairing_does_not_cross_strategy_runs():
    initial = trade(1, "open_long", 100)
    initial.update(close_reason="grid_initial_long", grid_client_reference="grid-initial-long")
    closing = trade(2, "close_long", 110)
    closing.update(strategy_run_id=2, grid_order_id=11, grid_order_purpose="long_exit", grid_order_extra={})

    assert project([initial, closing])[-1]["pnl_status"] == "unmatched"


def test_spot_base_fee_quantity_and_cost_allocation_use_actual_received_inventory():
    opening = trade(1,"open_long",100,quantity=1,fee=1)
    opening.update(market_type="spot",commission_ccy="BTC",commission=.01,commission_breakdown={"BTC":.01})
    closing = trade(2,"close_long",110,quantity=.99,fee=0)
    closing.update(market_type="spot",fee_status="actual_zero")
    result = project([opening,closing])[-1]
    assert result["profit"] == pytest.approx(8.9)


def test_replay_is_repeatable_and_input_order_does_not_change_pairing():
    rows = [trade(1,"open_long",100),trade(2,"close_long",101,quantity=.5),trade(3,"close_long",102,quantity=.5)]
    first = project(rows)
    second = sorted(project(list(reversed(rows))),key=lambda row:row["id"])
    assert first == second
