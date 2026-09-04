"""J-Quants APIの生データ(財務情報・株価四本値)から、銘柄選定基準(2-2)の
シグナルを導出する純粋関数群。ネットワークアクセスは行わない(テスト容易性のため)。

入力は J-Quants API のレスポンス形式(PascalCaseキーの辞書のリスト)をそのまま渡す想定。
"""
from typing import Optional


def to_float(value) -> Optional[float]:
    if value in (None, "", "-"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def sort_statements(statements: list) -> list:
    return sorted(
        statements,
        key=lambda s: (s.get("DisclosedDate") or "", s.get("DisclosedTime") or ""),
    )


def sort_quotes(quotes: list) -> list:
    return sorted(quotes, key=lambda q: q.get("Date") or "")


# -- 決算超過/上方修正 (+2) ------------------------------------------------

def detect_earnings_beat_or_upward_revision(statements: list) -> tuple:
    """直近の開示が、直前の開示時点の会社予想を上回っているか(決算超過)、
    または通期予想が直前開示より引き上げられているか(上方修正)を判定する。

    戻り値: (bool, 理由テキスト)
    """
    stmts = sort_statements(statements)
    if len(stmts) < 2:
        return False, "比較対象となる過去の開示が不足しています"

    latest, previous = stmts[-1], stmts[-2]
    reasons = []

    actual_profit = to_float(latest.get("Profit"))
    prev_forecast_profit = to_float(previous.get("ForecastProfit"))
    if actual_profit is not None and prev_forecast_profit:
        if actual_profit > prev_forecast_profit:
            reasons.append(
                f"当期純利益が直前予想を上回る({actual_profit:.0f} > {prev_forecast_profit:.0f})"
            )

    actual_op = to_float(latest.get("OperatingProfit"))
    prev_forecast_op = to_float(previous.get("ForecastOperatingProfit"))
    if actual_op is not None and prev_forecast_op:
        if actual_op > prev_forecast_op:
            reasons.append(
                f"営業利益が直前予想を上回る({actual_op:.0f} > {prev_forecast_op:.0f})"
            )

    latest_forecast_profit = to_float(latest.get("ForecastProfit"))
    if latest_forecast_profit is not None and prev_forecast_profit:
        if latest_forecast_profit > prev_forecast_profit:
            reasons.append(
                f"通期予想(当期純利益)が上方修正 "
                f"({prev_forecast_profit:.0f} -> {latest_forecast_profit:.0f})"
            )

    if reasons:
        return True, "; ".join(reasons)
    return False, "決算超過・上方修正は確認できませんでした"


# -- PBR1倍割れ / PER割安 (各+1) -------------------------------------------

def compute_pbr(statement: dict, price: float) -> Optional[float]:
    bps = to_float(statement.get("BookValuePerShare"))
    if not bps:
        return None
    return price / bps


def compute_per(statement: dict, price: float) -> Optional[float]:
    eps = to_float(statement.get("ForecastEarningsPerShare")) or to_float(
        statement.get("EarningsPerShare")
    )
    if not eps or eps <= 0:
        return None
    return price / eps


def is_pbr_under_1(pbr: Optional[float]) -> bool:
    return pbr is not None and pbr < 1.0


def is_per_cheap(per: Optional[float], threshold: float = 15.0) -> bool:
    return per is not None and per < threshold


# -- 出来高急増 (+1) ---------------------------------------------------

def moving_average(values: list, window: int) -> Optional[float]:
    valid = [v for v in values if v is not None]
    if len(valid) < window:
        return None
    return sum(valid[-window:]) / window


def is_volume_surge(quotes: list, window: int = 20, multiple: float = 2.0) -> bool:
    """直近日の出来高が過去window日平均のmultiple倍以上なら急増と判定する。"""
    sorted_quotes = sort_quotes(quotes)
    volumes = [to_float(q.get("Volume")) for q in sorted_quotes]
    if len(volumes) < window + 1:
        return False
    latest = volumes[-1]
    baseline = moving_average(volumes[:-1], window)
    if latest is None or not baseline:
        return False
    return latest >= baseline * multiple


# -- トレンド転換 (+1) ---------------------------------------------------

def _close_series(quotes: list) -> list:
    sorted_quotes = sort_quotes(quotes)
    closes = []
    for q in sorted_quotes:
        close = to_float(q.get("AdjustmentClose"))
        if close is None:
            close = to_float(q.get("Close"))
        closes.append(close)
    return closes


def detect_trend_reversal(quotes: list, short_window: int = 5, long_window: int = 25) -> bool:
    """短期移動平均が長期移動平均を直近日に上抜けた(ゴールデンクロス)かを判定する。"""
    closes = _close_series(quotes)
    if len(closes) < long_window + 1:
        return False

    short_today = moving_average(closes, short_window)
    long_today = moving_average(closes, long_window)
    short_yesterday = moving_average(closes[:-1], short_window)
    long_yesterday = moving_average(closes[:-1], long_window)

    if None in (short_today, long_today, short_yesterday, long_yesterday):
        return False

    return short_yesterday <= long_yesterday and short_today > long_today
