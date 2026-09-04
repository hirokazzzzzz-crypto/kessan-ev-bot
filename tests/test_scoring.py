from pretrade.scoring import ScoreInputs, score_stock, format_score_result


def _inputs(**overrides):
    base = dict(
        ticker="7203",
        earnings_beat_or_revision_up=False,
        earnings_reason="該当なし",
        pbr=None,
        per=None,
        volume_surge=False,
        trend_reversal=False,
        exclusion_reasons=[],
    )
    base.update(overrides)
    return ScoreInputs(**base)


def test_score_all_criteria_matched():
    result = score_stock(
        _inputs(
            earnings_beat_or_revision_up=True,
            pbr=0.8,
            per=10.0,
            volume_surge=True,
            trend_reversal=True,
        )
    )
    assert result.total_score == 2 + 1 + 1 + 1 + 1
    assert len(result.breakdown) == 6
    assert all(item.matched for item in result.breakdown[:5])


def test_score_none_matched():
    result = score_stock(_inputs())
    assert result.total_score == 0


def test_score_exclusion_applies_minus_three():
    result = score_stock(
        _inputs(
            earnings_beat_or_revision_up=True,
            exclusion_reasons=["債務超過の疑い"],
        )
    )
    # +2 (決算超過/上方修正) - 3 (除外条件) = -1
    assert result.total_score == -1
    exclusion_item = next(i for i in result.breakdown if i.criterion == "除外条件")
    assert exclusion_item.matched is True
    assert exclusion_item.points == -3


def test_pbr_exactly_1_does_not_match():
    result = score_stock(_inputs(pbr=1.0))
    pbr_item = next(i for i in result.breakdown if i.criterion == "PBR1倍割れ")
    assert pbr_item.matched is False


def test_format_score_result_includes_breakdown():
    result = score_stock(_inputs(earnings_beat_or_revision_up=True))
    text = format_score_result(result)
    assert "7203" in text
    assert "決算超過/上方修正" in text
