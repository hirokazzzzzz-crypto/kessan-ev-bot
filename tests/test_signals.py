from pretrade import signals


def _stmt(disclosed_date, **overrides):
    base = {
        "DisclosedDate": disclosed_date,
        "DisclosedTime": "09:00:00",
        "TypeOfCurrentPeriod": "FY",
        "NetSales": "1000",
        "OperatingProfit": "100",
        "OrdinaryProfit": "100",
        "Profit": "70",
        "ForecastNetSales": "1000",
        "ForecastOperatingProfit": "100",
        "ForecastOrdinaryProfit": "100",
        "ForecastProfit": "70",
        "EarningsPerShare": "50",
        "ForecastEarningsPerShare": "55",
        "BookValuePerShare": "1200",
    }
    base.update(overrides)
    return base


def _quote(d, close, volume=1_000_000):
    return {"Date": d, "Close": str(close), "Volume": str(volume)}


def test_detect_earnings_beat_true_when_actual_exceeds_prior_forecast():
    stmts = [
        _stmt("2026-05-01", ForecastProfit="70"),
        _stmt("2026-08-01", Profit="120", ForecastProfit="70"),
    ]
    beat, reason = signals.detect_earnings_beat_or_upward_revision(stmts)
    assert beat is True
    assert "当期純利益" in reason


def test_detect_earnings_beat_false_when_no_prior_statement():
    beat, reason = signals.detect_earnings_beat_or_upward_revision([_stmt("2026-08-01")])
    assert beat is False


def test_detect_upward_revision_true_when_forecast_raised():
    stmts = [
        _stmt("2026-05-01", ForecastProfit="70"),
        _stmt("2026-07-01", Profit="70", ForecastProfit="90"),
    ]
    beat, reason = signals.detect_earnings_beat_or_upward_revision(stmts)
    assert beat is True
    assert "上方修正" in reason


def test_compute_pbr_and_per():
    stmt = _stmt("2026-08-01")
    pbr = signals.compute_pbr(stmt, price=1000)
    per = signals.compute_per(stmt, price=1000)
    assert pbr == 1000 / 1200
    assert per == 1000 / 55  # ForecastEarningsPerShare優先


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
