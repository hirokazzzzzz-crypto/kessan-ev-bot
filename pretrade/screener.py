"""「未認識の好進捗」スクリーナー(2-0)。

1Q進捗率が良いのに、TOPIX比で株価が反応しておらず、通期予想も据え置きの銘柄を
発掘してランキングする。一過性利益(特別利益等)が主因とみられる銘柄は除外する。

入力は J-Quants API V2 のレスポンス形式(/fins/summary, /equities/bars/daily の
`data` 配列の要素)をそのまま渡す想定。ネットワークアクセスは行わない(テスト容易性のため)。
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from .signals import to_float, sort_statements, sort_quotes

DEFAULT_PROGRESS_THRESHOLD = 30.0  # 1Q進捗率(%) の下限目安
DEFAULT_REACTION_THRESHOLD = 5.0  # TOPIX比の株価反応(%) の上限目安(これ未満なら「未反応」)
STAGNANT_DAYS_CAP = 90
STAGNANT_BONUS_SCALE = 9.0  # stagnant_days / STAGNANT_BONUS_SCALE をランクスコアに加点


@dataclass
class ScreenerCandidate:
    ticker: str
    progress_rate_pct: float
    price_reaction_pct: float
    topix_reaction_pct: float
    relative_reaction_pct: float
    forecast_unchanged: bool
    stagnant_days: int
    has_one_time_gain: bool
    excluded: bool
    exclusion_reason: Optional[str]
    rank_score: float


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _price_before(quotes_sorted: list, cutoff_date: str) -> Optional[float]:
    """cutoff_date より前の最後の終値を返す(開示直前の株価)。"""
    candidate = None
    for q in quotes_sorted:
        if (q.get("Date") or "") >= cutoff_date:
            break
        close = to_float(q.get("AdjC")) or to_float(q.get("C"))
        if close is not None:
            candidate = close
    return candidate


def _latest_price(quotes_sorted: list) -> Optional[float]:
    for q in reversed(quotes_sorted):
        close = to_float(q.get("AdjC")) or to_float(q.get("C"))
        if close is not None:
            return close
    return None


def has_large_one_time_gain(statement: dict) -> bool:
    """当期純利益が経常利益を上回る場合、特別利益等の一過性要因を疑う簡易ヒューリスティック。"""
    profit = to_float(statement.get("NP"))
    ordinary = to_float(statement.get("OdP"))
    if profit is None or ordinary is None or ordinary <= 0:
        return False
    return profit > ordinary


def _latest_1q_statement(statements_sorted: list) -> Optional[dict]:
    for stmt in reversed(statements_sorted):
        if stmt.get("CurPerType") == "1Q":
            return stmt
    return None


def analyze_ticker(
    ticker: str,
    statements: list,
    quotes: list,
    topix_quotes: list,
    *,
    progress_metric: str = "OP",
    as_of: Optional[str] = None,
) -> Optional[ScreenerCandidate]:
    """1銘柄分のデータから ScreenerCandidate を計算する。データ不足時は None を返す。

    progress_metric は財務情報サマリー(/fins/summary)の実績値キー
    (例: "OP"=営業利益, "NP"=当期純利益)。対応する予想値キーは "F" を前置した
    ("FOP", "FNP" 等)ものを参照する。
    """
    stmts = sort_statements(statements)
    q_stock = sort_quotes(quotes)
    q_topix = sort_quotes(topix_quotes)

    q1_stmt = _latest_1q_statement(stmts)
    if q1_stmt is None:
        return None

    actual = to_float(q1_stmt.get(progress_metric))
    forecast = to_float(q1_stmt.get(f"F{progress_metric}"))
    if not actual or not forecast:
        return None
    progress_rate_pct = actual / forecast * 100

    disclosed_date = q1_stmt.get("DiscDate")
    if not disclosed_date:
        return None

    pre_price = _price_before(q_stock, disclosed_date)
    latest_price = _latest_price(q_stock)
    pre_topix = _price_before(q_topix, disclosed_date)
    latest_topix = _latest_price(q_topix)
    if not pre_price or not latest_price or not pre_topix or not latest_topix:
        return None

    price_reaction_pct = (latest_price / pre_price - 1) * 100
    topix_reaction_pct = (latest_topix / pre_topix - 1) * 100
    relative_reaction_pct = price_reaction_pct - topix_reaction_pct

    latest_stmt = stmts[-1]
    latest_forecast = to_float(latest_stmt.get(f"F{progress_metric}"))
    if latest_stmt is q1_stmt:
        forecast_unchanged = True
        end_date_str = as_of or date.today().isoformat()
    else:
        forecast_unchanged = latest_forecast is not None and latest_forecast == forecast
        end_date_str = latest_stmt.get("DiscDate") or (as_of or date.today().isoformat())

    stagnant_days = (_parse_date(end_date_str) - _parse_date(disclosed_date)).days
    stagnant_days = max(stagnant_days, 0)

    one_time_gain = has_large_one_time_gain(q1_stmt)
    excluded = one_time_gain
    exclusion_reason = "一過性利益(特別利益等)の可能性があり除外" if one_time_gain else None

    stagnant_bonus = min(stagnant_days, STAGNANT_DAYS_CAP) / STAGNANT_BONUS_SCALE
    rank_score = progress_rate_pct - relative_reaction_pct + stagnant_bonus

    return ScreenerCandidate(
        ticker=ticker,
        progress_rate_pct=progress_rate_pct,
        price_reaction_pct=price_reaction_pct,
        topix_reaction_pct=topix_reaction_pct,
        relative_reaction_pct=relative_reaction_pct,
        forecast_unchanged=forecast_unchanged,
        stagnant_days=stagnant_days,
        has_one_time_gain=one_time_gain,
        excluded=excluded,
        exclusion_reason=exclusion_reason,
        rank_score=rank_score,
    )


def find_unrecognized_progress(
    data_by_ticker: dict,
    topix_quotes: list,
    *,
    progress_threshold: float = DEFAULT_PROGRESS_THRESHOLD,
    reaction_threshold: float = DEFAULT_REACTION_THRESHOLD,
    progress_metric: str = "OP",
    as_of: Optional[str] = None,
) -> list:
    """未認識の好進捗銘柄をランキングする。

    data_by_ticker: {ticker: {"statements": [...], "quotes": [...]}} の形式。
    戻り値は rank_score 降順の ScreenerCandidate のリスト(除外銘柄・条件未達は含まない)。
    """
    candidates = []
    for ticker, data in data_by_ticker.items():
        candidate = analyze_ticker(
            ticker,
            data.get("statements", []),
            data.get("quotes", []),
            topix_quotes,
            progress_metric=progress_metric,
            as_of=as_of,
        )
        if candidate is None or candidate.excluded:
            continue
        if candidate.progress_rate_pct < progress_threshold:
            continue
        if candidate.relative_reaction_pct > reaction_threshold:
            continue
        if not candidate.forecast_unchanged:
            continue
        candidates.append(candidate)

    return sorted(candidates, key=lambda c: c.rank_score, reverse=True)
