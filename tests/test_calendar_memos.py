from datetime import date

import pytest

from pretrade.db import get_connection
from pretrade.calendar_memos import add_memo, list_memos, due_memos


@pytest.fixture
def conn(tmp_path):
    return get_connection(tmp_path / "test.db")


def test_add_and_list_memo(conn):
    memo = add_memo(conn, event_month=3, event_day=28, note="配当権利落ちで下げやすい", tags=["権利落ち", "3月"])
    assert memo.id is not None
    assert memo.tag_list() == ["権利落ち", "3月"]

    memos = list_memos(conn)
    assert len(memos) == 1
    assert memos[0].note == "配当権利落ちで下げやすい"


def test_list_memos_filters_by_tag(conn):
    add_memo(conn, event_month=3, event_day=28, note="A", tags=["権利落ち"])
    add_memo(conn, event_month=9, event_day=30, note="B", tags=["四半期末"])

    filtered = list_memos(conn, tag="権利落ち")
    assert len(filtered) == 1
    assert filtered[0].note == "A"


def test_add_memo_rejects_invalid_month(conn):
    with pytest.raises(ValueError):
        add_memo(conn, event_month=13, event_day=1, note="x")


def test_due_memos_matches_same_period(conn):
    add_memo(conn, event_month=3, event_day=28, note="今週")
    add_memo(conn, event_month=9, event_day=28, note="半年後")

    due = due_memos(conn, today=date(2026, 3, 25), window_days=7)
    notes = {m.note for m in due}
    assert "今週" in notes
    assert "半年後" not in notes


def test_due_memos_wraps_around_year_boundary(conn):
    add_memo(conn, event_month=1, event_day=2, note="年始")

    due = due_memos(conn, today=date(2026, 12, 29), window_days=7)
    notes = {m.note for m in due}
    assert "年始" in notes
