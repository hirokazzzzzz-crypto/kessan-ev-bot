import pytest

from pretrade.db import get_connection
from pretrade.topix_db import (
    accuracy_report,
    add_forecast,
    add_outcome,
    forecasts_by_ticker,
    list_forecasts,
    list_outcomes,
)


@pytest.fixture
def conn(tmp_path):
    return get_connection(tmp_path / "test.db")


def test_add_and_list_forecasts(conn):
    add_forecast(
        conn, ticker="593A", broker="大和証券", review_date="2026-10",
        forecast_type="new", mentioned_at="2026-09-02", source_note="グロース新規候補として言及",
    )
    add_forecast(
        conn, ticker="593A", broker="野村証券", review_date="2026-10",
        forecast_type="new", mentioned_at="2026-09-10",
    )
    add_forecast(
        conn, ticker="999A", broker="大和証券", review_date="2026-10",
        forecast_type="exclude", mentioned_at="2026-09-02",
    )

    all_for_593a = list_forecasts(conn, ticker="593A")
    assert len(all_for_593a) == 2
    assert all_for_593a[0].broker == "大和証券"

    all_for_review = list_forecasts(conn, review_date="2026-10")
    assert len(all_for_review) == 3


def test_add_forecast_rejects_invalid_type(conn):
    with pytest.raises(ValueError):
        add_forecast(
            conn, ticker="593A", broker="大和証券", review_date="2026-10",
            forecast_type="maybe", mentioned_at="2026-09-02",
        )


def test_forecasts_by_ticker_groups_for_topix_review(conn):
    add_forecast(
        conn, ticker="593A", broker="大和証券", review_date="2026-10",
        forecast_type="new", mentioned_at="2026-09-02",
    )
    add_forecast(
        conn, ticker="485A", broker="野村証券", review_date="2026-10",
        forecast_type="new", mentioned_at="2026-09-05",
    )

    grouped = forecasts_by_ticker(conn, "2026-10")
    assert set(grouped.keys()) == {"593A", "485A"}
    assert grouped["593A"][0].ticker == "593A"
    assert grouped["593A"][0].broker == "大和証券"


def test_add_and_list_outcomes(conn):
    add_outcome(
        conn, ticker="593A", review_date="2026-10", outcome="予想通り採用",
        announcement_date="2026-10-07", price_reaction_pct=1.81,
        note="大和証券が9/2に候補として言及。発表日+1.81%、PTSでさらに+7.92%。",
    )
    add_outcome(conn, ticker="999A", review_date="2026-10", outcome="採用見送り")

    outcomes = list_outcomes(conn, review_date="2026-10")
    assert len(outcomes) == 2

    report = accuracy_report(conn, review_date="2026-10")
    assert report["total"] == 2
    assert report["by_outcome"]["予想通り採用"] == 1
    assert report["by_outcome"]["採用見送り"] == 1
    assert report["by_outcome"]["予想外採用"] == 0


def test_add_outcome_rejects_invalid_outcome(conn):
    with pytest.raises(ValueError):
        add_outcome(conn, ticker="593A", review_date="2026-10", outcome="微妙")
