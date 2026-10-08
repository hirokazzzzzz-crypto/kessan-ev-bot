import pytest

from pretrade.topix_review import (
    BrokerForecast,
    JpxFitInputs,
    PATTERN_NEUTRAL,
    PATTERN_PRICED_IN,
    PATTERN_SURPRISE_UPSIDE,
    aggregate_forecasts,
    build_candidate,
    classify_outcome,
    classify_pattern,
    compute_pricing_in,
    compute_turnover_ratio,
    format_forecast_basis,
    precede_watchlist,
    price_position_in_52w_range,
    rank_candidates,
    score_jpx_fit,
    watch_period_label,
)


def _quotes(*rows):
    """rows: (date, close, volume) のタプル列。"""
    return [{"Date": d, "C": str(c), "Vo": str(v)} for d, c, v in rows]


# -- JPX基準適合度(近似) --------------------------------------------------

def test_score_jpx_fit_full_data_all_matched():
    inputs = JpxFitInputs(
        ticker="593A",
        market_cap=10_000_000_000,
        annual_trading_value=3_000_000_000,
        market_segment="グロース",
        market_cap_percentile=50.0,
    )
    result = score_jpx_fit(inputs)
    assert result.turnover_ratio == pytest.approx(0.3)
    assert result.fit_score == result.max_score == 5
    assert result.is_approximate is True


def test_score_jpx_fit_missing_data_notes_reflect_gaps():
    inputs = JpxFitInputs(ticker="7203")
    result = score_jpx_fit(inputs)
    assert result.fit_score == 0
    assert compute_turnover_ratio(inputs) is None
    assert any("時価総額" in n or "売買代金" in n for n in result.data_notes)


def test_score_jpx_fit_turnover_below_threshold_not_matched():
    inputs = JpxFitInputs(
        ticker="7203",
        market_cap=10_000_000_000,
        annual_trading_value=500_000_000,  # 回転率0.05 < 0.20
        market_segment="プライム",
        market_cap_percentile=10.0,
    )
    result = score_jpx_fit(inputs)
    # 回転率条件(+2)は落ちるが、市場区分(+1)と時価総額ランク(+2)は通る
    assert result.fit_score == 3


# -- 証券会社予想の集計 ----------------------------------------------------

def test_aggregate_forecasts_counts_distinct_brokers_and_first_date():
    forecasts = [
        BrokerForecast("593A", "大和証券", "2026-10", "new", "2026-09-02"),
        BrokerForecast("593A", "野村証券", "2026-10", "new", "2026-09-10"),
    ]
    summary = aggregate_forecasts(forecasts)
    assert summary.mention_count == 2
    assert summary.brokers == ["大和証券", "野村証券"]
    assert summary.first_mentioned_at == "2026-09-02"
    assert "大和証券" in format_forecast_basis(summary)


def test_aggregate_forecasts_empty_list():
    summary = aggregate_forecasts([])
    assert summary.mention_count == 0
    assert format_forecast_basis(summary) == "予想情報なし(未発見の可能性)"


# -- 織り込み度(実例: ティアフォー 593A、2026-10-07 TOPIX採用) --------------
# 大和証券が2026-09-02時点でグロース市場からの新規採用候補として言及。
# 発表日(10/7)終値は+1.81%、さらに引け後PTSで+7.92%まで上伸(ともに実際の報道値)。
# ここでは発表前までのデータだけを使い、「発表前時点でどこまで織り込まれていたか」を見る。

def test_compute_pricing_in_tieriv_case_already_priced_in_before_announcement():
    quotes = _quotes(
        ("2026-09-02", 1800, 5_000_000),
        ("2026-09-15", 2000, 6_000_000),
        ("2026-10-06", 2171, 7_000_000),
    )
    topix_quotes = _quotes(
        ("2026-09-02", 3100, 0),
        ("2026-09-15", 3150, 0),
        ("2026-10-06", 3200, 0),
    )
    result = compute_pricing_in("593A", quotes, topix_quotes, since_date="2026-09-02")
    assert result.since_date == "2026-09-02"
    assert result.price_reaction_pct == pytest.approx((2171 / 1800 - 1) * 100)
    assert result.topix_reaction_pct == pytest.approx((3200 / 3100 - 1) * 100)
    # 大和証券の言及(9/2)以降、発表前日(10/6)までで対TOPIX+17%超の先行上昇 -> すでに"high"
    # (実際、ティアフォーは発表当日もさらに+1.81%、引け後PTSで+7.92%まで伸びており、
    #  事前に織り込まれていてもなお反応した事例として興味深い)
    assert result.relative_reaction_pct > 15.0
    assert result.priced_in_level == "high"


def test_compute_pricing_in_unknown_without_since_date():
    result = compute_pricing_in("7203", [], [], since_date=None)
    assert result.priced_in_level == "unknown"
    assert result.relative_reaction_pct is None


def test_compute_pricing_in_high_when_large_relative_runup():
    quotes = _quotes(("2026-08-01", 1000, 1_000_000), ("2026-10-01", 1400, 1_000_000))
    topix_quotes = _quotes(("2026-08-01", 3000, 0), ("2026-10-01", 3030, 0))
    result = compute_pricing_in("1234", quotes, topix_quotes, since_date="2026-08-01")
    assert result.priced_in_level == "high"


# -- 52週レンジ位置 --------------------------------------------------------

def test_price_position_in_52w_range():
    quotes = _quotes(("2026-01-01", 1000, 0), ("2026-06-01", 500, 0), ("2026-09-01", 800, 0))
    pos = price_position_in_52w_range(quotes)
    assert pos["high"] == 1000
    assert pos["low"] == 500
    assert pos["latest"] == 800
    assert pos["pct_from_low"] == pytest.approx(60.0)
    assert pos["pct_from_high"] == pytest.approx(-20.0)


def test_price_position_in_52w_range_empty():
    assert price_position_in_52w_range([]) is None


# -- パターン判定 ----------------------------------------------------------

def test_classify_pattern_priced_in_when_forecasted_and_high_runup():
    from pretrade.topix_review import ForecastSummary, PricingInResult, JpxFitResult

    fit = JpxFitResult("X", 4, 5, 0.3, [])
    forecast = ForecastSummary("X", 2, ["大和証券"], "2026-09-01", "2026-09-01", "new")
    pricing = PricingInResult("X", "2026-09-01", 20.0, 2.0, 18.0, True, "high")
    assert classify_pattern(fit, forecast, pricing) == PATTERN_PRICED_IN


def test_classify_pattern_surprise_upside_when_no_forecast_but_fits_criteria():
    from pretrade.topix_review import ForecastSummary, PricingInResult, JpxFitResult

    fit = JpxFitResult("Y", 4, 5, 0.3, [])
    forecast = ForecastSummary("Y", 0, [], None, None, None)
    pricing = PricingInResult("Y", None, None, None, None, False, "unknown")
    assert classify_pattern(fit, forecast, pricing) == PATTERN_SURPRISE_UPSIDE


def test_classify_pattern_neutral_when_fit_too_low():
    from pretrade.topix_review import ForecastSummary, PricingInResult, JpxFitResult

    fit = JpxFitResult("Z", 1, 5, None, [])
    forecast = ForecastSummary("Z", 0, [], None, None, None)
    pricing = PricingInResult("Z", None, None, None, None, False, "unknown")
    assert classify_pattern(fit, forecast, pricing) == PATTERN_NEUTRAL


# -- watch_period_label ----------------------------------------------------

def test_watch_period_label_far_future():
    from datetime import date
    label = watch_period_label("2026-12-31", today=date(2026, 9, 1))
    assert "早期発掘" in label


def test_watch_period_label_past_basis_date():
    from datetime import date
    label = watch_period_label("2026-08-31", today=date(2026, 10, 8))
    assert "発表待ち" in label


# -- build_candidate / rank_candidates / precede_watchlist 統合 ------------

def test_build_candidate_and_precede_watchlist_identifies_underpriced_fit():
    quotes = _quotes(("2026-09-01", 1000, 1_000_000), ("2026-10-01", 1020, 1_000_000))
    topix_quotes = _quotes(("2026-09-01", 3000, 0), ("2026-10-01", 3030, 0))
    jpx_inputs = JpxFitInputs(
        ticker="999A", market_cap=5_000_000_000, annual_trading_value=1_500_000_000,
        market_segment="グロース", market_cap_percentile=40.0,
    )
    forecasts = [BrokerForecast("999A", "大和証券", "2026-10", "new", "2026-09-01")]

    candidate = build_candidate(
        "999A", "テスト銘柄", jpx_inputs, forecasts, quotes, topix_quotes,
        review_date_basis="2026-08-31",
    )

    assert candidate.jpx_fit.fit_score >= 3
    assert candidate.priced_in.priced_in_level == "low"
    assert candidate.pattern == PATTERN_SURPRISE_UPSIDE
    assert candidate.is_precede_candidate is True

    ranked = rank_candidates([candidate])
    assert ranked[0].ticker == "999A"
    watchlist = precede_watchlist([candidate])
    assert len(watchlist) == 1


def test_classify_outcome():
    assert classify_outcome(was_forecasted=True, was_included=True) == "予想通り採用"
    assert classify_outcome(was_forecasted=False, was_included=True) == "予想外採用"
    assert classify_outcome(was_forecasted=True, was_included=False) == "採用見送り"
