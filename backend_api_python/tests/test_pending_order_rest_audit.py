import sys
import threading
from types import SimpleNamespace

import pytest

from app.services import pending_order_worker as module


@pytest.fixture
def worker(monkeypatch):
    worker = object.__new__(module.PendingOrderWorker)
    worker._lock = threading.Lock()
    worker._exchange_catchups = set()
    worker._last_stream_audit = {}
    worker._stream_audit_sec = 30
    worker._fee_sync_batch_per_account = 5
    worker._clock = 100.0
    monkeypatch.setattr(module.time, "monotonic", lambda: worker._clock)
    supervisor = SimpleNamespace(is_healthy=lambda **kw: True)
    monkeypatch.setitem(sys.modules, "app.startup", SimpleNamespace(get_execution_stream_supervisor=lambda: supervisor))
    return worker


def row(order_id, market="swap", credential=1):
    return {"id": order_id, "exchange_id": "binance", "credential_id": credential, "market_type": market}


def test_all_orders_are_audited_without_consuming_account_budget(worker):
    rows = [row(i) for i in range(1, 4)]
    checked = []
    worker._fetch_live_sent_orders = lambda **kw: rows
    worker._sync_one_live_sent_order = lambda r: checked.append(r["id"])
    worker._sync_live_sent_orders()
    assert checked == [1, 2, 3]
    worker._sync_live_sent_orders()
    assert checked == [1, 2, 3]
    worker._clock += 30
    worker._sync_live_sent_orders()
    assert checked == [1, 2, 3, 1, 2, 3]


def test_later_query_page_does_not_wait_another_account_interval(worker):
    assert all(worker._should_rest_reconcile(row(i)) for i in range(1, 51))
    assert worker._should_rest_reconcile(row(51))
    assert not worker._should_rest_reconcile(row(1))


def test_catchup_invalidates_all_matching_orders_and_later_pages(worker):
    rows = [row(1), row(2), row(3, market="spot"), row(4, credential=2)]
    assert all(worker._should_rest_reconcile(r) for r in rows)
    worker.request_exchange_catchup(exchange_id="binance", credential_id=1, market_type="swap")
    assert worker._should_rest_reconcile(rows[0])
    assert worker._should_rest_reconcile(rows[1])
    assert not worker._should_rest_reconcile(rows[2])
    assert not worker._should_rest_reconcile(rows[3])
    worker.request_exchange_catchup(exchange_id="binance", credential_id=1, market_type="all")
    assert all(worker._should_rest_reconcile(r) for r in rows[:3])
    assert not worker._should_rest_reconcile(rows[3])


def test_new_order_is_audited_even_early_in_process_uptime(worker):
    worker._clock = 1.0
    assert worker._should_rest_reconcile(row(1))


def test_failure_does_not_skip_later_orders(worker):
    checked = []
    worker._fetch_live_sent_orders = lambda **kw: [row(1), row(2)]

    def check(r):
        checked.append(r["id"])
        if r["id"] == 1:
            raise RuntimeError("temporary exchange failure")

    worker._sync_one_live_sent_order = check
    worker._sync_live_sent_orders()
    assert checked == [1, 2]


def test_unhealthy_stream_bypasses_per_order_interval(worker, monkeypatch):
    assert worker._should_rest_reconcile(row(1))
    supervisor = SimpleNamespace(is_healthy=lambda **kw: False)
    monkeypatch.setitem(sys.modules, "app.startup", SimpleNamespace(get_execution_stream_supervisor=lambda: supervisor))
    assert worker._should_rest_reconcile(row(1))
    assert worker._should_rest_reconcile(row(2))


def test_fee_check_does_not_consume_normal_order_audit(worker):
    assert worker._should_rest_reconcile({**row(1), "fee_reconciliation_needed": True})
    assert worker._should_rest_reconcile(row(2))
