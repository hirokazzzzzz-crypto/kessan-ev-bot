"""年間シーズナリティ・市場イベントカレンダー(2-1) データ分析側。

過去N年の月次/週次騰落率、決算集中期、四半期末リバランス時期、権利落ち日の目安を集計する。
入力は J-Quants API のレスポンス形式(PascalCaseキーの辞書のリスト)をそのまま渡す想定。
ネットワークアクセスは行わない(テスト容易性のため)。
"""
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

from .signals import sort_quotes, sort_statements, to_float


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _month_end_closes(quotes: list) -> dict:
    """(year, month) -> 月末終値 の辞書を作る。"""
    sorted_quotes = sort_quotes(quotes)
    result = {}
    for q in sorted_quotes:
        date_str = q.get("Date")
        close = to_float(q.get("AdjustmentClose")) or to_float(q.get("Close"))
        if not date_str or close is None:
            continue
        d = _parse_date(date_str)
        result[(d.year, d.month)] = close  # 月内で後の日付が上書きし、結果的に月末値が残る
    return result


def monthly_return_stats(quotes: list) -> dict:
    """月ごと(1〜12月)の騰落率統計を返す。

    戻り値: {month: {"avg_return_pct": float, "win_rate_pct": float, "n": int}}
    前月末終値 -> 当月末終値 の変化率を、収集できた全年分についてカレンダー月ごとに集計する。
    """
    month_end = _month_end_closes(quotes)
    keys_sorted = sorted(month_end.keys())

    returns_by_month = defaultdict(list)
    for i in range(1, len(keys_sorted)):
        prev_key, cur_key = keys_sorted[i - 1], keys_sorted[i]
        prev_year, prev_month = prev_key
        cur_year, cur_month = cur_key
        # 連続する月のペアのみ対象(欠損月をまたぐ場合は除外)
        expected_next = (prev_year + 1, 1) if prev_month == 12 else (prev_year, prev_month + 1)
        if cur_key != expected_next:
            continue
        prev_close, cur_close = month_end[prev_key], month_end[cur_key]
        if prev_close:
            returns_by_month[cur_month].append((cur_close / prev_close - 1) * 100)

    stats = {}
    for month, returns in returns_by_month.items():
        wins = sum(1 for r in returns if r > 0)
        stats[month] = {
            "avg_return_pct": sum(returns) / len(returns),
            "win_rate_pct": wins / len(returns) * 100,
            "n": len(returns),
        }
    return stats


def weekly_return_stats(quotes: list) -> dict:
    """ISO週番号(1〜53)ごとの騰落率統計を返す。"""
    sorted_quotes = sort_quotes(quotes)
    week_end_close = {}
    for q in sorted_quotes:
        date_str = q.get("Date")
        close = to_float(q.get("AdjustmentClose")) or to_float(q.get("Close"))
        if not date_str or close is None:
            continue
        d = _parse_date(date_str)
        iso_year, iso_week, _ = d.isocalendar()
        week_end_close[(iso_year, iso_week)] = close

    keys_sorted = sorted(week_end_close.keys())
    returns_by_week = defaultdict(list)
    for i in range(1, len(keys_sorted)):
        prev_key, cur_key = keys_sorted[i - 1], keys_sorted[i]
        prev_close, cur_close = week_end_close[prev_key], week_end_close[cur_key]
        if prev_close:
            returns_by_week[cur_key[1]].append((cur_close / prev_close - 1) * 100)

    stats = {}
    for week, returns in returns_by_week.items():
        wins = sum(1 for r in returns if r > 0)
        stats[week] = {
            "avg_return_pct": sum(returns) / len(returns),
            "win_rate_pct": wins / len(returns) * 100,
            "n": len(returns),
        }
    return stats


def earnings_concentration_by_month(statements_by_ticker: dict) -> dict:
    """決算集中期の目安として、開示月(1〜12)ごとの開示件数を集計する。"""
    counts = defaultdict(int)
    for ticker_data in statements_by_ticker.values():
        for stmt in ticker_data.get("statements", []):
            date_str = stmt.get("DisclosedDate")
            if not date_str:
                continue
            counts[_parse_date(date_str).month] += 1
    return dict(counts)


def estimate_ex_rights_dates(statements_by_ticker: dict) -> dict:
    """権利落ち日の目安を銘柄ごとに返す(近似値)。

    J-Quants財務情報の CurrentFiscalYearEndDate(期末日=多くの場合の権利確定日)を基準に、
    権利落ち日 = 権利確定日の2営業日前、として簡易計算する。実際の権利確定日・配当設定は
    銘柄ごとに異なる場合があるため、あくまで目安として扱うこと。

    戻り値: {ticker: 権利落ち日(ISO文字列)}
    """
    result = {}
    for ticker, ticker_data in statements_by_ticker.items():
        stmts = sort_statements(ticker_data.get("statements", []))
        if not stmts:
            continue
        latest = stmts[-1]
        fy_end = latest.get("CurrentFiscalYearEndDate")
        if not fy_end:
            continue
        record_date = _parse_date(fy_end)
        ex_rights_date = _subtract_business_days(record_date, 2)
        result[ticker] = ex_rights_date.isoformat()
    return result


def _subtract_business_days(d: date, n: int) -> date:
    current = d
    remaining = n
    while remaining > 0:
        current -= timedelta(days=1)
        if current.weekday() < 5:  # 0=月曜 ... 4=金曜
            remaining -= 1
    return current


def quarter_end_rebalance_dates(year: int) -> list:
    """四半期末リバランス時期の目安(3/6/9/12月末、土日の場合は直前平日)を返す。"""
    dates = []
    for month in (3, 6, 9, 12):
        if month == 12:
            last_day = date(year, 12, 31)
        else:
            last_day = date(year, month + 1, 1) - timedelta(days=1)
        while last_day.weekday() >= 5:
            last_day -= timedelta(days=1)
        dates.append(last_day.isoformat())
    return dates
