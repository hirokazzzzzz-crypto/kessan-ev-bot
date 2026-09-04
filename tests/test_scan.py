from pretrade.scan import build_score_inputs


def _statements():
    return [
        {
            "DisclosedDate": "2026-05-01",
            "DisclosedTime": "09:00:00",
            "Profit": "70",
            "OperatingProfit": "100",
            "ForecastProfit": "70",
            "ForecastOperatingProfit": "100",
        },
        {
            "DisclosedDate": "2026-08-01",
            "DisclosedTime": "09:00:00",
            "Profit": "150",
            "OperatingProfit": "180",
            "ForecastProfit": "70",
            "ForecastOperatingProfit": "100",
            "BookValuePerShare": "1200",
            "ForecastEarningsPerShare": "60",
        },
    ]


def _quotes():
    quotes = [{"Date": f"2026-06-{d:02d}", "Close": "1000", "Volume": "100"} for d in range(1, 21)]
    quotes.append({"Date": "2026-06-21", "Close": "1000", "Volume": "500"})
    return quotes


def test_build_score_inputs_detects_beat_and_volume_surge():
    inputs = build_score_inputs("7203", _statements(), _quotes())

    assert inputs.earnings_beat_or_revision_up is True
    assert inputs.volume_surge is True
    assert inputs.pbr == 1000 / 1200
    assert inputs.per == 1000 / 60


def test_build_score_inputs_uses_explicit_latest_price():
    inputs = build_score_inputs("7203", _statements(), _quotes(), latest_price=2400)
    assert inputs.pbr == 2400 / 1200
