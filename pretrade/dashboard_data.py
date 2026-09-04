"""ダッシュボード(Phase 4)向けの表示用データ整形。

Streamlit(表示側)に依存しない純粋関数として実装し、単体テストで検証できるようにしている。
"""
from .rr import RR_WARNING_THRESHOLD


def open_theses_table(theses: list) -> list:
    return [
        {
            "id": t.id,
            "銘柄": t.ticker,
            "根拠分類": t.rationale_category,
            "エントリー価格": t.entry_price,
            "目標価格": t.target_price,
            "損切り価格": t.stop_price,
            "RR比": round(t.rr_ratio, 2),
            "RR警告": t.rr_ratio < RR_WARNING_THRESHOLD,
            "保有期間": t.holding_period,
        }
        for t in theses
    ]


def score_breakdown_table(result) -> list:
    return [
        {
            "基準": item.criterion,
            "点数": item.points,
            "該当": "○" if item.matched else "×",
            "詳細": item.detail,
        }
        for item in result.breakdown
    ]


def screener_table(candidates: list) -> list:
    return [
        {
            "銘柄": c.ticker,
            "1Q進捗率(%)": round(c.progress_rate_pct, 1),
            "対TOPIX反応(%)": round(c.relative_reaction_pct, 1),
            "据え置き日数": c.stagnant_days,
            "ランクスコア": round(c.rank_score, 1),
        }
        for c in candidates
    ]


def monthly_stats_table(stats: dict) -> list:
    return [
        {
            "月": month,
            "平均騰落率(%)": round(s["avg_return_pct"], 2),
            "勝率(%)": round(s["win_rate_pct"], 1),
            "サンプル数": s["n"],
        }
        for month, s in sorted(stats.items())
    ]


def cash_alerts_table(alerts: list) -> list:
    return [
        {
            "種別": a.alert_type,
            "銘柄": a.ticker or "(市場全体)",
            "メッセージ": a.message,
        }
        for a in alerts
    ]


def memos_table(memos: list) -> list:
    return [
        {
            "id": m.id,
            "月/日": f"{m.event_month}/{m.event_day}",
            "タグ": m.tags,
            "メモ": m.note,
        }
        for m in memos
    ]
