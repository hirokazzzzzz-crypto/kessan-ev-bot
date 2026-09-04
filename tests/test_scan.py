from pretrade.scan import build_score_inputs


def _statements():
    return [
        {
            "DiscDate": "2026-05-01",
            "DiscTime": "09:00:00",
            "NP": "70",
            "OP": "100",
            "FNP": "70",
            "FOP": "100",
        },
        {
            "DiscDate": "2026-08-01",
            "DiscTime": "09:00:00",
            "NP": "150",
            "OP": "180",
            "FNP": "70",
            "FOP": "100",
            "BPS": "1200",
            "FEPS": "60",
        },
    ]


def _quotes():
    quotes = [{"Date": f"2026-06-{d:02d}", "C": "1000", "Vo": "100"} for d in range(1, 21)]
    quotes.append({"Date": "2026-06-21", "C": "1000", "Vo": "500"})
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
