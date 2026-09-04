import pytest

from pretrade.cash_control import (
    moving_average_deviation,
    unrealized_gain_pct,
    check_take_profit_candidates,
    check_stop_loss_breaches,
    check_crash_buy_opportunity,
)
from pretrade.scoring import ScoreResult, ScoreBreakdownItem


class _Thesis:
    def __init__(self, id, ticker, entry_price, stop_price):
        self.id = id
        self.ticker = ticker
        self.entry_price = entry_price
        self.stop_price = stop_price


def _quotes(closes):
    return [{"Date": f"2026-01-{i+1:02d}", "C": str(c)} for i, c in enumerate(closes)]


def test_moving_average_deviation():
    closes = [100] * 24 + [110]  # 25本、平均100.4、最新110
    quotes = _quotes(closes)
    dev = moving_average_deviation(quotes, window=25)
    assert dev == pytest.approx((110 - sum([100] * 24 + [110]) / 25) / (sum([100] * 24 + [110]) / 25) * 100)


def test_moving_average_deviation_insufficient_data_returns_none():
    quotes = _quotes([100, 101])
    assert moving_average_deviation(quotes, window=25) is None


def test_unrealized_gain_pct():
    assert unrealized_gain_pct(1000, 1200) == pytest.approx(20.0)
    assert unrealized_gain_pct(1000, 900) == pytest.approx(-10.0)


def test_check_take_profit_candidates_by_profit_threshold():
    theses = [_Thesis(1, "7203", entry_price=1000, stop_price=900)]
    latest_prices = {"7203": 1250}  # +25%
    alerts = check_take_profit_candidates(theses, latest_prices, {})
    assert len(alerts) == 1
    assert alerts[0].alert_type == "利確検討"
    assert "含み益" in alerts[0].message


def test_check_take_profit_candidates_by_ma_deviation():
    theses = [_Thesis(1, "7203", entry_price=1000, stop_price=900)]
    latest_prices = {"7203": 1050}  # +5%、利益基準未達
    ma_deviations = {"7203": 9.0}  # 乖離基準達
    alerts = check_take_profit_candidates(theses, latest_prices, ma_deviations)
    assert len(alerts) == 1
    assert "移動平均乖離" in alerts[0].message


def test_check_take_profit_candidates_no_alert_when_below_thresholds():
    theses = [_Thesis(1, "7203", entry_price=1000, stop_price=900)]
    latest_prices = {"7203": 1050}
    ma_deviations = {"7203": 2.0}
    assert check_take_profit_candidates(theses, latest_prices, ma_deviations) == []


def test_check_stop_loss_breaches():
    theses = [_Thesis(1, "7203", entry_price=1000, stop_price=950)]
    latest_prices = {"7203": 900}
    alerts = check_stop_loss_breaches(theses, latest_prices)
    assert len(alerts) == 1
    assert alerts[0].alert_type == "損切り"


def test_check_stop_loss_breaches_no_alert_when_above_stop():
    theses = [_Thesis(1, "7203", entry_price=1000, stop_price=950)]
    latest_prices = {"7203": 960}
    assert check_stop_loss_breaches(theses, latest_prices) == []


def _score_result(ticker, score):
    return ScoreResult(ticker=ticker, total_score=score, breakdown=[])


def test_check_crash_buy_opportunity_triggers_on_large_negative_deviation():
    closes = [100] * 24 + [85]  # 大きく下方乖離
    topix_quotes = _quotes(closes)
    scores = [_score_result("7203", 5), _score_result("9984", 3)]

    alert = check_crash_buy_opportunity(topix_quotes, scores, window=25, top_n=1)
    assert alert is not None
    assert alert.alert_type == "暴落仕込み"
    assert "7203" in alert.message


def test_check_crash_buy_opportunity_no_alert_when_deviation_small():
    closes = [100] * 25
    topix_quotes = _quotes(closes)
    assert check_crash_buy_opportunity(topix_quotes, []) is None
