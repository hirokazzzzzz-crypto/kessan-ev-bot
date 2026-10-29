import pytest

from pretrade import signals


def _stmt(disc_date, **overrides):
    base = {
        "DiscDate": disc_date,
        "DiscTime": "09:00:00",
        "CurPerType": "FY",
        "Sales": "1000",
        "OP": "100",
        "OdP": "100",
        "NP": "70",
        "FSales": "1000",
        "FOP": "100",
        "FOdP": "100",
        "FNP": "70",
        "EPS": "50",
        "FEPS": "55",
        "BPS": "1200",
    }
    base.update(overrides)
    return base


def _quote(d, close, volume=1_000_000):
    return {"Date": d, "C": str(close), "Vo": str(volume)}


def test_detect_earnings_beat_true_when_actual_exceeds_prior_forecast():
    stmts = [
        _stmt("2026-05-01", FNP="70"),
        _stmt("2026-08-01", NP="120", FNP="70"),
    ]
    beat, reason = signals.detect_earnings_beat_or_upward_revision(stmts)
    assert beat is True
    assert "当期純利益" in reason


def test_detect_earnings_beat_false_when_no_prior_statement():
    beat, reason = signals.detect_earnings_beat_or_upward_revision([_stmt("2026-08-01")])
    assert beat is False


def test_detect_upward_revision_true_when_forecast_raised():
    stmts = [
        _stmt("2026-05-01", FNP="70"),
        _stmt("2026-07-01", NP="70", FNP="90"),
    ]
    beat, reason = signals.detect_earnings_beat_or_upward_revision(stmts)
    assert beat is True
    assert "上方修正" in reason


def test_compute_pbr_and_per():
    stmt = _stmt("2026-08-01")
    pbr = signals.compute_pbr(stmt, price=1000)
    per = signals.compute_per(stmt, price=1000)
    assert pbr == 1000 / 1200
    assert per == 1000 / 55  # FEPS(予想EPS)優先


def test_is_pbr_under_1_and_is_per_cheap():
    assert signals.is_pbr_under_1(0.8) is True
    assert signals.is_pbr_under_1(1.2) is False
    assert signals.is_pbr_under_1(None) is False
    assert signals.is_per_cheap(10.0) is True
    assert signals.is_per_cheap(20.0) is False


def test_is_volume_surge_true_when_spike():
    quotes = [_quote(f"2026-01-{d:02d}", 1000, volume=100) for d in range(1, 21)]
    quotes.append(_quote("2026-01-21", 1000, volume=500))
    assert signals.is_volume_surge(quotes, window=20, multiple=2.0) is True


def test_is_volume_surge_false_when_insufficient_history():
    quotes = [_quote("2026-01-01", 1000, volume=100)]
    assert signals.is_volume_surge(quotes) is False


def test_detect_trend_reversal_golden_cross():
    closes = [100] * 25 + [90, 200]
    quotes = [_quote(f"2026-{(i//28)+1:02d}-{(i%28)+1:02d}", c) for i, c in enumerate(closes)]
    assert signals.detect_trend_reversal(quotes, short_window=5, long_window=25) is True


def test_detect_trend_reversal_false_when_flat():
    quotes = [_quote(f"2026-{(i//28)+1:02d}-{(i%28)+1:02d}", 100) for i in range(30)]
    assert signals.detect_trend_reversal(quotes, short_window=5, long_window=25) is False


# -- トレンドライン判定 ------------------------------------------------
# 実例(2026-10-16時点でユーザーがチャート上で確認): ソフトバンクG(9984)の過去2つの
# 安値が4,880.0 / 4,882.0でほぼ同水準に並んでおり、その日に安値4,836で一瞬下に
# 潜った後、+2.27%で4,962まで戻した。チャートは月単位の目盛りしか読めないため、
# 日付は目盛りから読み取れる範囲の近似値(横ばいの線なので日付の多少のズレは
# 結果にほぼ影響しない)。

def test_check_trendline_touch_softbank_horizontal_support_example():
    result = signals.check_trendline_touch(
        "2026-08-10", 4880.0,
        "2026-09-15", 4882.0,
        target_date="2026-10-16",
        actual_price=4836.0,  # 当日安値
    )
    assert result.is_roughly_horizontal is True
    assert result.is_touching is True
    assert result.deviation_pct == pytest.approx(-0.98, abs=0.2)


def test_trendline_projection_simple_ascending_line():
    # 日付の近似誤差に強い「水平線」と違い、傾きのある線は日付の精度が結果を大きく
    # 左右するため、ここでは分かりやすいクリーンな数値で検証する。
    projected = signals.trendline_projection(
        "2026-01-01", 100.0, "2026-01-11", 200.0, target_date="2026-01-21"
    )
    # 10日で+100なら、1日あたり+10。20日後は+200。
    assert projected == pytest.approx(300.0)


def test_check_trendline_touch_not_touching_when_price_far_above_line():
    result = signals.check_trendline_touch(
        "2026-01-01", 100.0, "2026-01-11", 200.0,
        target_date="2026-01-21", actual_price=500.0,
    )
    assert result.is_roughly_horizontal is False
    assert result.is_touching is False
    assert result.deviation_pct == pytest.approx((500 / 300 - 1) * 100)


def test_check_trendline_touch_unknown_when_no_actual_price():
    result = signals.check_trendline_touch("2026-01-01", 100.0, "2026-01-11", 200.0, target_date="2026-01-21")
    assert result.actual_price is None
    assert result.deviation_pct is None
    assert result.is_touching is False


def test_trendline_projection_rejects_same_date_points():
    with pytest.raises(ValueError):
        signals.trendline_projection("2026-01-01", 100.0, "2026-01-01", 200.0, target_date="2026-01-21")


# -- ベンチマークとの連動性(相関・ベータ) ---------------------------------

def _price_series(closes):
    """closes: 終値のリスト。日付は2026-01-01から1日ずつ進める簡易版。"""
    from datetime import date, timedelta
    base = date(2026, 1, 1)
    return [
        {"Date": (base + timedelta(days=i)).isoformat(), "C": str(c)}
        for i, c in enumerate(closes)
    ]


def test_compute_correlation_perfectly_correlated():
    ticker = _price_series([100, 110, 99, 115, 110])
    # 同じ方向に動く(倍率は違ってもよい)系列を作る
    benchmark = _price_series([1000, 1050, 945, 1060, 1010])
    corr = signals.compute_correlation(ticker, benchmark)
    assert corr == pytest.approx(1.0, abs=0.05)


def test_compute_correlation_inversely_correlated():
    ticker = _price_series([100, 110, 99, 115, 110])
    benchmark = _price_series([1000, 950, 1050, 930, 970])
    corr = signals.compute_correlation(ticker, benchmark)
    assert corr < -0.8


def test_compute_correlation_none_when_insufficient_overlap():
    ticker = _price_series([100, 110])
    benchmark = _price_series([1000])
    assert signals.compute_correlation(ticker, benchmark) is None


def test_compute_beta_double_sensitivity():
    # ベンチマークの騰落率のちょうど2倍動く銘柄
    benchmark = _price_series([1000, 1010, 1000, 1030, 1000])
    bench_returns = [1010 / 1000 - 1, 1000 / 1010 - 1, 1030 / 1000 - 1, 1000 / 1030 - 1]
    ticker_closes = [500]
    for r in bench_returns:
        ticker_closes.append(ticker_closes[-1] * (1 + 2 * r))
    ticker = _price_series(ticker_closes)

    beta = signals.compute_beta(ticker, benchmark)
    assert beta == pytest.approx(2.0, abs=0.01)


def test_compute_beta_none_when_benchmark_flat():
    ticker = _price_series([100, 105, 103, 108])
    benchmark = _price_series([1000, 1000, 1000, 1000])
    assert signals.compute_beta(ticker, benchmark) is None
