import pytest

from pretrade.db import get_connection
from pretrade.models import create_thesis, close_thesis
from pretrade.report import category_winrates, monthly_report_text


@pytest.fixture
def conn(tmp_path):
    return get_connection(tmp_path / "test.db")


def _trade(conn, ticker, category, entry, target, stop, exit_price, exit_date, as_expected="想定通り"):
    t = create_thesis(
        conn,
        ticker=ticker,
        alpha_thesis=f"{ticker}のアルファ仮説",
        rationale_category=category,
        entry_price=entry,
        target_price=target,
        stop_price=stop,
        holding_period="2週間",
        exit_condition="撤退条件テキスト",
    )
    return close_thesis(
        conn, t.id, exit_price=exit_price,
        exit_reason="利確" if exit_price > entry else "損切り",
        as_expected=as_expected, reflection="振り返りテキスト",
        exit_date=exit_date,
    )


def test_category_winrates(conn):
    _trade(conn, "7203", "決算超過/上方修正", 1000, 1200, 950, 1150, "2026-08-01")
    _trade(conn, "9984", "決算超過/上方修正", 1000, 1200, 950, 900, "2026-08-05", as_expected="想定外")
    _trade(conn, "6758", "出来高急増", 500, 600, 480, 590, "2026-08-10")

    stats = category_winrates(conn, "2026-08")
    assert stats["決算超過/上方修正"]["count"] == 2
    assert stats["決算超過/上方修正"]["wins"] == 1
    assert stats["決算超過/上方修正"]["win_rate"] == pytest.approx(50.0)
    assert stats["出来高急増"]["win_rate"] == pytest.approx(100.0)


def test_monthly_report_text_includes_thesis_and_result(conn):
    _trade(conn, "7203", "決算超過/上方修正", 1000, 1200, 950, 1150, "2026-08-01")

    text = monthly_report_text(conn, "2026-08")
    assert "7203" in text
    assert "7203のアルファ仮説" in text
    assert "根拠分類別" in text


def test_monthly_report_text_empty_month(conn):
    text = monthly_report_text(conn, "2099-01")
    assert "決済済みのトレードはありません" in text
