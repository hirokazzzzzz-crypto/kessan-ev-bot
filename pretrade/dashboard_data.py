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


def topix_candidates_table(candidates: list) -> list:
    rows = []
    for c in candidates:
        pos = c.price_position or {}
        pricing = c.priced_in
        rows.append(
            {
                "銘柄名": c.name,
                "コード": c.ticker,
                "先回り候補": "★" if c.is_precede_candidate else "",
                "採用候補度": round(c.candidate_score, 0),
                "パターン": c.pattern,
                "採用予想の根拠": c.forecast_basis,
                "JPX基準適合度(近似)": f"{c.jpx_fit.fit_score}/{c.jpx_fit.max_score}",
                "織り込み度": pricing.priced_in_level,
                "対TOPIX相対反応(%)": (
                    round(pricing.relative_reaction_pct, 1) if pricing.relative_reaction_pct is not None else None
                ),
                "52週高値から(%)": round(pos["pct_from_high"], 1) if pos.get("pct_from_high") is not None else None,
                "52週安値から(%)": round(pos["pct_from_low"], 1) if pos.get("pct_from_low") is not None else None,
                "注目すべき時期": c.watch_period,
            }
        )
    return rows


def topix_forecasts_table(forecasts: list) -> list:
    return [
        {
            "id": f.id,
            "銘柄": f.ticker,
            "証券会社": f.broker,
            "区分": "新規採用" if f.forecast_type == "new" else "除外",
            "言及日": f.mentioned_at,
            "メモ": f.source_note,
        }
        for f in forecasts
    ]


def topix_outcomes_table(outcomes: list) -> list:
    return [
        {
            "銘柄": o.ticker,
            "結果": o.outcome,
            "発表日": o.announcement_date,
            "発表日反応(%)": o.price_reaction_pct,
            "メモ": o.note,
        }
        for o in outcomes
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
