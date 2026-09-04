from pretrade.cash_control import CashControlAlert
from pretrade.calendar_memos import CalendarMemo
from pretrade.dashboard_data import (
    cash_alerts_table,
    memos_table,
    monthly_stats_table,
    open_theses_table,
    score_breakdown_table,
    screener_table,
)
from pretrade.models import TradeThesis
from pretrade.screener import ScreenerCandidate
from pretrade.scoring import ScoreBreakdownItem, ScoreResult


def _thesis(rr_ratio):
    return TradeThesis(
        id=1,
        ticker="7203",
        created_at="2026-08-01T00:00:00",
        alpha_thesis="test",
        rationale_category="その他",
        entry_price=1000,
        target_price=1200,
        stop_price=950,
        reward=200,
        risk=50,
        rr_ratio=rr_ratio,
        holding_period="2週間",
        exit_condition="test",
    )


def test_open_theses_table_flags_rr_warning():
    rows = open_theses_table([_thesis(1.5), _thesis(4.0)])
    assert rows[0]["RR警告"] is True
    assert rows[1]["RR警告"] is False
    assert rows[0]["銘柄"] == "7203"


def test_score_breakdown_table():
    result = ScoreResult(
        ticker="7203",
        total_score=3,
        breakdown=[
            ScoreBreakdownItem(criterion="決算超過/上方修正", points=2, matched=True, detail="ok"),
            ScoreBreakdownItem(criterion="PBR1倍割れ", points=0, matched=False, detail="no data"),
        ],
    )
    rows = score_breakdown_table(result)
    assert rows[0]["該当"] == "○"
    assert rows[1]["該当"] == "×"


def test_screener_table():
    candidate = ScreenerCandidate(
        ticker="7203",
        progress_rate_pct=40.123,
        price_reaction_pct=1.0,
        topix_reaction_pct=2.0,
        relative_reaction_pct=-1.0,
        forecast_unchanged=True,
        stagnant_days=92,
        has_one_time_gain=False,
        excluded=False,
        exclusion_reason=None,
        rank_score=45.678,
    )
    rows = screener_table([candidate])
    assert rows[0]["1Q進捗率(%)"] == 40.1
    assert rows[0]["据え置き日数"] == 92


def test_monthly_stats_table_sorted_by_month():
    stats = {12: {"avg_return_pct": 1.0, "win_rate_pct": 50.0, "n": 2}, 1: {"avg_return_pct": -1.0, "win_rate_pct": 40.0, "n": 3}}
    rows = monthly_stats_table(stats)
    assert [r["月"] for r in rows] == [1, 12]


def test_cash_alerts_table_defaults_market_wide_ticker():
    alert = CashControlAlert(alert_type="暴落仕込み", ticker=None, message="msg")
    rows = cash_alerts_table([alert])
    assert rows[0]["銘柄"] == "(市場全体)"


def test_memos_table():
    memo = CalendarMemo(id=1, created_at="2026-01-01T00:00:00", event_month=3, event_day=28, tags="権利落ち", note="note")
    rows = memos_table([memo])
    assert rows[0]["月/日"] == "3/28"
