import pytest

from pretrade.db import get_connection
from pretrade.market_calls_db import add_call, all_calls_as_domain, list_calls, set_outcome


@pytest.fixture
def conn(tmp_path):
    return get_connection(tmp_path / "test.db")


def test_add_and_list_calls(conn):
    add_call(
        conn, ticker="4751", source="レオ", call_type="底値", called_at="2026-06-20",
        price_at_call=1500.0, note="優待権利落ち後にもう一段下げ→上昇を予想",
        url="https://x.com/example/status/123",
    )
    add_call(conn, ticker="9984", source="別の人", call_type="天井")

    all_calls = list_calls(conn)
    assert len(all_calls) == 2

    leo_calls = list_calls(conn, source="レオ")
    assert len(leo_calls) == 1
    assert leo_calls[0].ticker == "4751"
    assert leo_calls[0].outcome == "未確定"


def test_add_call_rejects_invalid_call_type(conn):
    with pytest.raises(ValueError):
        add_call(conn, ticker="4751", source="レオ", call_type="微妙")


def test_set_outcome_updates_and_returns_record(conn):
    created = add_call(conn, ticker="4751", source="レオ", call_type="底値")
    updated = set_outcome(conn, created.id, "的中")
    assert updated.outcome == "的中"

    reloaded = list_calls(conn, ticker="4751")[0]
    assert reloaded.outcome == "的中"


def test_set_outcome_rejects_invalid_outcome(conn):
    created = add_call(conn, ticker="4751", source="レオ", call_type="底値")
    with pytest.raises(ValueError):
        set_outcome(conn, created.id, "たぶん")


def test_set_outcome_unknown_id_raises(conn):
    with pytest.raises(ValueError):
        set_outcome(conn, 9999, "的中")


def test_all_calls_as_domain_roundtrips_to_market_call(conn):
    add_call(conn, ticker="4751", source="レオ", call_type="底値", price_at_call=1500.0)
    domain_calls = all_calls_as_domain(conn)
    assert len(domain_calls) == 1
    assert domain_calls[0].ticker == "4751"
    assert domain_calls[0].price_at_call == 1500.0
