"""J-Quants API V2の生データ(財務情報・株価四本値)から、銘柄選定基準(2-2)の
シグナルを導出する純粋関数群。ネットワークアクセスは行わない(テスト容易性のため)。

入力は J-Quants API V2 のレスポンス形式(/fins/summary, /equities/bars/daily の
`data` 配列の要素)をそのまま渡す想定。フィールド名はV2の略称キー
(例: OP=営業利益, OdP=経常利益, NP=当期純利益, FOP=営業利益_予想_期末)に準拠する。

トレンドライン判定(trendline_projection / check_trendline_touch)だけは、チャート上で
手動で見つけた2点(日付・価格)を入力にする純粋な幾何計算で、J-Quantsのデータ形式には依存しない。
"""
from dataclasses import dataclass
from datetime import date, datetime
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
        key=lambda s: (s.get("DiscDate") or "", s.get("DiscTime") or ""),
    )


def sort_quotes(quotes: list) -> list:
    return sorted(quotes, key=lambda q: q.get("Date") or "")


def _volume(quote: dict) -> Optional[float]:
    return to_float(quote.get("AdjVo")) or to_float(quote.get("Vo"))


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

    actual_profit = to_float(latest.get("NP"))
    prev_forecast_profit = to_float(previous.get("FNP"))
    if actual_profit is not None and prev_forecast_profit:
        if actual_profit > prev_forecast_profit:
            reasons.append(
                f"当期純利益が直前予想を上回る({actual_profit:.0f} > {prev_forecast_profit:.0f})"
            )

    actual_op = to_float(latest.get("OP"))
    prev_forecast_op = to_float(previous.get("FOP"))
    if actual_op is not None and prev_forecast_op:
        if actual_op > prev_forecast_op:
            reasons.append(
                f"営業利益が直前予想を上回る({actual_op:.0f} > {prev_forecast_op:.0f})"
            )

    latest_forecast_profit = to_float(latest.get("FNP"))
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
    bps = to_float(statement.get("BPS"))
    if not bps:
        return None
    return price / bps


def compute_per(statement: dict, price: float) -> Optional[float]:
    eps = to_float(statement.get("FEPS")) or to_float(statement.get("EPS"))
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
    """直近日の出来高(調整済み)が過去window日平均のmultiple倍以上なら急増と判定する。"""
    sorted_quotes = sort_quotes(quotes)
    volumes = [_volume(q) for q in sorted_quotes]
    if len(volumes) < window + 1:
        return False
    latest = volumes[-1]
    baseline = moving_average(volumes[:-1], window)
    if latest is None or not baseline:
        return False
    return latest >= baseline * multiple


# -- トレンド転換 (+1) ---------------------------------------------------

def close_series(quotes: list) -> list:
    sorted_quotes = sort_quotes(quotes)
    closes = []
    for q in sorted_quotes:
        close = to_float(q.get("AdjC"))
        if close is None:
            close = to_float(q.get("C"))
        closes.append(close)
    return closes


def detect_trend_reversal(quotes: list, short_window: int = 5, long_window: int = 25) -> bool:
    """短期移動平均が長期移動平均を直近日に上抜けた(ゴールデンクロス)かを判定する。"""
    closes = close_series(quotes)
    if len(closes) < long_window + 1:
        return False

    short_today = moving_average(closes, short_window)
    long_today = moving_average(closes, long_window)
    short_yesterday = moving_average(closes[:-1], short_window)
    long_yesterday = moving_average(closes[:-1], long_window)

    if None in (short_today, long_today, short_yesterday, long_yesterday):
        return False

    return short_yesterday <= long_yesterday and short_today > long_today


# -- トレンドライン判定(2点を結んで延長する支持線/抵抗線チェック) ---------
# チャート上で目視で見つけた2点(例: 過去2回の安値)を結んだ直線を、任意の日付まで
# 線形外挿する。「今の価格がこの延長線上に乗っているか」を判定するのに使う。

HORIZONTAL_SLOPE_THRESHOLD_PCT_PER_DAY = 0.05  # これ未満ならほぼ水平(横ばいの支持線)とみなす
DEFAULT_TOUCH_TOLERANCE_PCT = 2.0


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def trendline_projection(point1_date: str, point1_price: float, point2_date: str, point2_price: float,
                          target_date: str) -> float:
    """2点(point1_date, point1_price)-(point2_date, point2_price)を通る直線を、
    target_date まで線形外挿したときの価格を返す。日付は "YYYY-MM-DD" 形式。

    2点の日付が同じ場合は ValueError を送出する(傾きが定義できないため)。
    """
    d1 = _parse_date(point1_date)
    d2 = _parse_date(point2_date)
    dt = _parse_date(target_date)
    days_between = (d2 - d1).days
    if days_between == 0:
        raise ValueError("2点の日付が同じため、直線の傾きを計算できません")

    slope_per_day = (point2_price - point1_price) / days_between
    return point1_price + slope_per_day * (dt - d1).days


@dataclass
class TrendlineCheck:
    point1: tuple  # (date, price)
    point2: tuple  # (date, price)
    target_date: str
    projected_price: float
    actual_price: Optional[float]
    deviation_pct: Optional[float]  # (actual/projected - 1) * 100
    slope_pct_per_day: float  # 傾き(point1価格に対する1日あたりの変化率%)
    is_roughly_horizontal: bool  # 傾きが小さい(水平に近い支持線/抵抗線)
    is_touching: bool  # actual_price が許容誤差内で延長線に乗っているか


def check_trendline_touch(
    point1_date: str, point1_price: float,
    point2_date: str, point2_price: float,
    target_date: str,
    actual_price: Optional[float] = None,
    tolerance_pct: float = DEFAULT_TOUCH_TOLERANCE_PCT,
) -> TrendlineCheck:
    """2点を結んだ延長線上に actual_price が乗っているか(支持線/抵抗線タッチ)を判定する。

    actual_price が None の場合、is_touching は常に False(判定不能)になる
    -- "まだ検証できていない" という状態を明示的に表す。
    """
    projected = trendline_projection(point1_date, point1_price, point2_date, point2_price, target_date)

    days_between = (_parse_date(point2_date) - _parse_date(point1_date)).days
    slope_per_day = (point2_price - point1_price) / days_between
    slope_pct_per_day = (slope_per_day / point1_price * 100) if point1_price else 0.0
    is_horizontal = abs(slope_pct_per_day) < HORIZONTAL_SLOPE_THRESHOLD_PCT_PER_DAY

    deviation_pct = None
    is_touching = False
    if actual_price is not None and projected:
        deviation_pct = (actual_price / projected - 1) * 100
        is_touching = abs(deviation_pct) <= tolerance_pct

    return TrendlineCheck(
        point1=(point1_date, point1_price),
        point2=(point2_date, point2_price),
        target_date=target_date,
        projected_price=projected,
        actual_price=actual_price,
        deviation_pct=deviation_pct,
        slope_pct_per_day=slope_pct_per_day,
        is_roughly_horizontal=is_horizontal,
        is_touching=is_touching,
    )
