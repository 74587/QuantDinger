from types import SimpleNamespace

import pytest

from app.utils import db_postgres as db


@pytest.fixture
def connection(monkeypatch):
    native = SimpleNamespace(commits=0, rollbacks=0)
    native.commit = lambda: setattr(native, "commits", native.commits + 1)
    native.rollback = lambda: setattr(native, "rollbacks", native.rollbacks + 1)
    pool = SimpleNamespace(putconn=lambda *a, **k: None)
    monkeypatch.setattr(db, "_get_connection_pool", lambda: pool)
    monkeypatch.setattr(db, "_acquire_conn_with_wait", lambda p: native)
    return native


def test_nested_helper_commits_wait_for_owner(connection):
    with db.get_pg_transaction() as transaction:
        with db.get_pg_connection() as helper:
            assert helper is transaction
            helper.commit()
        with db.get_pg_transaction() as nested:
            assert nested is transaction
            nested.commit()
        assert connection.commits == 0
    assert connection.commits == 1
    assert connection.rollbacks == 0


def test_failure_rolls_back_and_clears_context(connection):
    with pytest.raises(ValueError):
        with db.get_pg_transaction():
            with db.get_pg_connection() as helper:
                helper.commit()
            raise ValueError("injected failure")
    assert connection.commits == 0
    assert connection.rollbacks > 0
    assert db._active_transaction.get() is None
    with db.get_pg_connection() as ordinary:
        ordinary.commit()
    assert connection.commits == 1


def test_swallowed_helper_failure_prevents_commit(connection):
    with pytest.raises(RuntimeError, match="marked for rollback"):
        with db.get_pg_transaction():
            try:
                with db.get_pg_connection():
                    raise ValueError("legacy helper catches this")
            except ValueError:
                pass
    assert connection.commits == 0
    assert connection.rollbacks > 0


def test_explicit_nested_rollback_prevents_commit(connection):
    with pytest.raises(RuntimeError, match="marked for rollback"):
        with db.get_pg_transaction():
            with db.get_pg_connection() as helper:
                helper.rollback()
    assert connection.commits == 0


def test_external_action_runs_only_after_commit_and_context_reset(connection):
    observations = []
    with db.get_pg_transaction():
        db.run_after_commit(lambda: observations.append((connection.commits, db._active_transaction.get())))
        assert observations == []
    assert observations == [(1, None)]


def test_rolled_back_fill_does_not_submit_followup_order(connection):
    orders = []
    with pytest.raises(RuntimeError):
        with db.get_pg_transaction():
            db.run_after_commit(orders.append, 'exit')
            raise RuntimeError('injected fill failure')
    assert orders == []
