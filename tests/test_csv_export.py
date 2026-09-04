import csv

import pytest

from pretrade.db import get_connection
from pretrade.models import create_thesis
from pretrade.csv_export import export_csv, FIELDNAMES


@pytest.fixture
def conn(tmp_path):
    return get_connection(tmp_path / "test.db")


def test_export_csv_writes_rows(conn, tmp_path):
    create_thesis(
        conn,
        ticker="7203",
        alpha_thesis="仮説",
        rationale_category="出来高急増",
        entry_price=1000.0,
        target_price=1200.0,
        stop_price=950.0,
        holding_period="2週間",
        exit_condition="撤退条件",
    )

    out_path = export_csv(conn, tmp_path / "export.csv")
    with out_path.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1
    assert rows[0]["ticker"] == "7203"
    assert set(rows[0].keys()) == set(FIELDNAMES)
