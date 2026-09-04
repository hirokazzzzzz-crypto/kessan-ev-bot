import pytest

from pretrade.calendar_seasonality import (
    monthly_return_stats,
    weekly_return_stats,
    earnings_concentration_by_month,
    estimate_ex_rights_dates,
    quarter_end_rebalance_dates,
)


def _quote(d, close):
    return {"Date": d, "Close": str(close)}


def test_monthly_return_stats_computes_month_over_month_change():
    quotes = [
        _quote("2024-01-31", 1000),
        _quote("2024-02-29", 1100),  # +10%
        _quote("2025-01-31", 1000),
        _quote("2025-02-28", 900),  # -10%
    ]
    stats = monthly_return_stats(quotes)
    assert stats[2]["n"] == 2
    assert stats[2]["avg_return_pct"] == pytest.approx(0.0, abs=1e-6)
    assert stats[2]["win_rate_pct"] == pytest.approx(50.0)


def test_monthly_return_stats_skips_non_consecutive_months():
    quotes = [_quote("2024-01-31", 1000), _quote("2024-06-30", 2000)]
    stats = monthly_return_stats(quotes)
    assert stats == {}


def test_weekly_return_stats_basic():
    quotes = [
        _quote("2024-01-01", 1000),  # week 1
        _quote("2024-01-08", 1050),  # week 2, +5%
    ]
    stats = weekly_return_stats(quotes)
    assert 2 in stats
    assert stats[2]["avg_return_pct"] == pytest.approx(5.0)


def test_earnings_concentration_by_month():
    data = {
        "7203": {"statements": [{"DisclosedDate": "2026-05-10"}, {"DisclosedDate": "2026-05-12"}]},
        "9984": {"statements": [{"DisclosedDate": "2026-08-01"}]},
    }
    counts = earnings_concentration_by_month(data)
    assert counts[5] == 2
    assert counts[8] == 1


def test_estimate_ex_rights_dates_two_business_days_before_fy_end():
    data = {
        "7203": {
            "statements": [
                {"DisclosedDate": "2026-05-01", "CurrentFiscalYearEndDate": "2026-03-31"}
            ]
        }
    }
    result = estimate_ex_rights_dates(data)
    # 2026-03-31は火曜日 -> 2営業日前は2026-03-27(金)
    assert result["7203"] == "2026-03-27"


def test_quarter_end_rebalance_dates_avoids_weekend():
    dates = quarter_end_rebalance_dates(2026)
    assert len(dates) == 4
    # 2026-06-30は火曜日なのでそのまま、2026-12-31は木曜日なのでそのまま
    assert "2026-06-30" in dates
