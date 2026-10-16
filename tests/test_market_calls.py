import pytest

from pretrade.market_calls import (
    MarketCall,
    OUTCOME_HIT,
    OUTCOME_MISS,
    OUTCOME_PENDING,
    summarize_accuracy_by_source,
    validate_call_type,
    validate_outcome,
)


def test_validate_call_type_rejects_unknown():
    with pytest.raises(ValueError):
        validate_call_type("なんか")


def test_validate_outcome_rejects_unknown():
    with pytest.raises(ValueError):
        validate_outcome("たぶん")


# 実例(ユーザー談): サイバーエージェントの底値を、Xの「レオ」氏が株主優待の権利落ち後に
# もう一段下げてから上昇する、と予想。実際その通りになった。
def test_summarize_accuracy_by_source_ranks_hit_rate_descending():
    calls = [
        MarketCall("4751", "レオ", "底値", note="優待権利落ち後にもう一段下げ→上昇を予想", outcome=OUTCOME_HIT),
        MarketCall("7203", "レオ", "底値", outcome=OUTCOME_HIT),
        MarketCall("9984", "別の人", "底値", outcome=OUTCOME_MISS),
        MarketCall("6857", "別の人", "底値", outcome=OUTCOME_PENDING),
    ]
    summary = summarize_accuracy_by_source(calls)

    assert summary[0].source == "レオ"
    assert summary[0].hit_rate_pct == pytest.approx(100.0)
    assert summary[0].total == 2

    second = next(s for s in summary if s.source == "別の人")
    assert second.hits == 0
    assert second.misses == 1
    assert second.pending == 1
    assert second.hit_rate_pct == pytest.approx(0.0)


def test_summarize_accuracy_by_source_pending_only_has_none_hit_rate_and_sorts_last():
    calls = [
        MarketCall("4751", "勝率高い人", "底値", outcome=OUTCOME_HIT),
        MarketCall("7203", "未検証の人", "底値", outcome=OUTCOME_PENDING),
    ]
    summary = summarize_accuracy_by_source(calls)
    assert summary[0].source == "勝率高い人"
    assert summary[-1].source == "未検証の人"
    assert summary[-1].hit_rate_pct is None
