import pytest

from pretrade.db import get_connection
from pretrade.models import create_thesis, close_thesis, list_open, list_closed, get_thesis


@pytest.fixture
def conn(tmp_path):
    return get_connection(tmp_path / "test.db")


def _make_thesis(conn, **overrides):
    defaults = dict(
        ticker="7203",
        alpha_thesis="1Q進捗率が高く上方修正が期待できる",
        rationale_category="決算超過/上方修正",
        entry_price=1000.0,
        target_price=1200.0,
        stop_price=950.0,
        holding_period="3週間",
        exit_condition="決算発表後に上方修正がなければ撤退",
    )
    defaults.update(overrides)
    return create_thesis(conn, **defaults)


def test_create_thesis_computes_rr(conn):
    thesis = _make_thesis(conn)
    assert thesis.id is not None
    assert thesis.status == "open"
    assert thesis.rr_ratio == pytest.approx(4.0)


def test_create_thesis_rejects_invalid_prices(conn):
    with pytest.raises(ValueError):
        _make_thesis(conn, stop_price=1000.0)


def test_list_open_and_close(conn):
    t1 = _make_thesis(conn, ticker="7203")
    t2 = _make_thesis(conn, ticker="9984")

    assert {t.id for t in list_open(conn)} == {t1.id, t2.id}

    closed = close_thesis(
        conn,
        t1.id,
        exit_price=1150.0,
        exit_reason="利確",
        as_expected="想定通り",
        reflection="決算後に上方修正が出て想定通り上昇",
        exit_date="2026-08-15",
    )
    assert closed.status == "closed"
    assert closed.pnl_pct == pytest.approx(15.0)

    open_ids = {t.id for t in list_open(conn)}
    assert open_ids == {t2.id}

    closed_list = list_closed(conn, "2026-08")
    assert len(closed_list) == 1
    assert closed_list[0].id == t1.id


def test_close_thesis_twice_raises(conn):
    t1 = _make_thesis(conn)
    close_thesis(
        conn, t1.id, exit_price=1150.0, exit_reason="利確",
        as_expected="想定通り", reflection="ok",
    )
    with pytest.raises(ValueError):
        close_thesis(
            conn, t1.id, exit_price=1160.0, exit_reason="利確",
            as_expected="想定通り", reflection="again",
        )


def test_close_unknown_id_raises(conn):
    with pytest.raises(ValueError):
        close_thesis(
            conn, 999, exit_price=1000.0, exit_reason="利確",
            as_expected="想定通り", reflection="x",
        )


def test_get_thesis_missing_returns_none(conn):
    assert get_thesis(conn, 999) is None
