import pytest

from pretrade.screener import (
    analyze_ticker,
    find_unrecognized_progress,
    has_large_one_time_gain,
)


def _q1_statement(disclosed_date="2026-05-01", operating_profit=35, forecast_operating_profit=100,
                   profit=25, ordinary_profit=30):
    return {
        "DisclosedDate": disclosed_date,
        "DisclosedTime": "09:00:00",
        "TypeOfCurrentPeriod": "1Q",
        "OperatingProfit": str(operating_profit),
        "ForecastOperatingProfit": str(forecast_operating_profit),
        "Profit": str(profit),
        "OrdinaryProfit": str(ordinary_profit),
    }


def _quotes(pre_date, pre_close, latest_date, latest_close):
    return [
        {"Date": pre_date, "Close": str(pre_close)},
        {"Date": latest_date, "Close": str(latest_close)},
    ]


def test_analyze_ticker_unrecognized_progress_candidate():
    statements = [_q1_statement()]
    quotes = _quotes("2026-04-30", 1000, "2026-08-01", 1050)
    topix_quotes = _quotes("2026-04-30", 2000, "2026-08-01", 2100)

    candidate = analyze_ticker(
        "7203", statements, quotes, topix_quotes, as_of="2026-08-01"
    )

    assert candidate is not None
    assert candidate.progress_rate_pct == pytest.approx(35.0)
    assert candidate.price_reaction_pct == pytest.approx(5.0)
    assert candidate.topix_reaction_pct == pytest.approx(5.0)
    assert candidate.relative_reaction_pct == pytest.approx(0.0)
    assert candidate.forecast_unchanged is True
    assert candidate.stagnant_days == 92
    assert candidate.excluded is False


def test_analyze_ticker_returns_none_without_1q_statement():
    candidate = analyze_ticker("7203", [], [], [])
    assert candidate is None


def test_has_large_one_time_gain_true_when_profit_exceeds_ordinary():
    stmt = _q1_statement(profit=50, ordinary_profit=30)
    assert has_large_one_time_gain(stmt) is True


def test_has_large_one_time_gain_false_when_normal():
    stmt = _q1_statement(profit=20, ordinary_profit=30)
    assert has_large_one_time_gain(stmt) is False


def test_find_unrecognized_progress_filters_and_ranks():
    topix_quotes = _quotes("2026-04-30", 2000, "2026-08-01", 2100)

    data_by_ticker = {
        # 進捗率良好・株価未反応 -> 採用
        "7203": {
            "statements": [_q1_statement(operating_profit=40, forecast_operating_profit=100)],
            "quotes": _quotes("2026-04-30", 1000, "2026-08-01", 1030),
        },
        # 進捗率が閾値未満 -> 除外
        "9984": {
            "statements": [_q1_statement(operating_profit=10, forecast_operating_profit=100)],
            "quotes": _quotes("2026-04-30", 1000, "2026-08-01", 1010),
        },
        # 一過性利益(特別利益等) -> 除外
        "6758": {
            "statements": [
                _q1_statement(
                    operating_profit=40, forecast_operating_profit=100,
                    profit=80, ordinary_profit=30,
                )
            ],
            "quotes": _quotes("2026-04-30", 1000, "2026-08-01", 1010),
        },
        # 既に株価が大きく反応済み -> 除外
        "8306": {
            "statements": [_q1_statement(operating_profit=40, forecast_operating_profit=100)],
            "quotes": _quotes("2026-04-30", 1000, "2026-08-01", 1300),
        },
    }

    candidates = find_unrecognized_progress(
        data_by_ticker, topix_quotes, as_of="2026-08-01"
    )

    tickers = [c.ticker for c in candidates]
    assert tickers == ["7203"]
