"""決済後の振り返りレポート(仮説 vs 結果の突合・根拠別勝率の月次集計)。"""
from collections import defaultdict
from typing import Optional

from .models import list_closed


def _is_win(thesis) -> bool:
    return (thesis.pnl_pct or 0) > 0


def category_winrates(conn, year_month: Optional[str] = None):
    """根拠分類ごとの勝率・トレード数・平均RR比・平均損益率を集計する。"""
    theses = list_closed(conn, year_month)
    buckets = defaultdict(list)
    for t in theses:
        buckets[t.rationale_category].append(t)

    stats = {}
    for category, items in buckets.items():
        wins = sum(1 for t in items if _is_win(t))
        stats[category] = {
            "count": len(items),
            "wins": wins,
            "win_rate": wins / len(items) * 100 if items else 0.0,
            "avg_rr": sum(t.rr_ratio for t in items) / len(items),
            "avg_pnl_pct": sum(t.pnl_pct or 0 for t in items) / len(items),
        }
    return stats


def monthly_report_text(conn, year_month: str) -> str:
    """当初のアルファ仮説と実際の結果を並べて表示する月次レポートを文字列で返す。"""
    theses = list_closed(conn, year_month)
    lines = [f"===== {year_month} 月次振り返りレポート =====", ""]

    if not theses:
        lines.append("対象期間に決済済みのトレードはありません。")
        return "\n".join(lines)

    lines.append("--- 仮説 vs 結果 ---")
    for t in theses:
        result = "勝ち" if _is_win(t) else "負け"
        lines.append(
            f"[#{t.id}] {t.ticker} ({t.rationale_category}) 決済日:{t.exit_date}\n"
            f"  仮説   : {t.alpha_thesis}\n"
            f"  撤退条件: {t.exit_condition}\n"
            f"  結果   : {result} 損益率={t.pnl_pct:+.2f}% "
            f"区分={t.exit_reason} 想定={t.as_expected}\n"
            f"  振り返り: {t.reflection}\n"
        )

    lines.append("--- 根拠分類別 勝率集計 ---")
    stats = category_winrates(conn, year_month)
    for category, s in sorted(stats.items(), key=lambda kv: -kv[1]["win_rate"]):
        lines.append(
            f"  {category}: {s['wins']}/{s['count']}勝 "
            f"勝率={s['win_rate']:.1f}% 平均RR={s['avg_rr']:.2f} 平均損益率={s['avg_pnl_pct']:+.2f}%"
        )

    return "\n".join(lines)
