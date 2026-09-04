"""現金比率コントロール(2-4)。

- 移動平均乖離+8〜10%超 または 含み益+20%超 -> 「利確検討リスト」
- 損切り価格割れの含み損銘柄を検知 -> 損切りを後押し
- 市場(TOPIX)の-10%超の下方乖離 -> 「待機資金+スコア上位銘柄」を提示し、暴落時の仕込みを後押し

入力は J-Quants API のレスポンス形式(PascalCaseキーの辞書のリスト)や、
Phase 1/2で得たトレード仮説・スコア結果のオブジェクトをそのまま渡す想定。
ネットワークアクセスは行わない(テスト容易性のため)。
"""
from dataclasses import dataclass
from typing import Optional

from . import signals

DEFAULT_PROFIT_THRESHOLD_PCT = 20.0
DEFAULT_MA_DEVIATION_THRESHOLD_PCT = 8.0
DEFAULT_CRASH_DEVIATION_THRESHOLD_PCT = -10.0
DEFAULT_MA_WINDOW = 25


@dataclass
class CashControlAlert:
    alert_type: str  # "利確検討" | "損切り" | "暴落仕込み"
    ticker: Optional[str]
    message: str


def moving_average_deviation(quotes: list, window: int = DEFAULT_MA_WINDOW) -> Optional[float]:
    """直近終値の、window日移動平均からの乖離率(%)を返す。"""
    closes = signals.close_series(quotes)
    if not closes or closes[-1] is None:
        return None
    ma = signals.moving_average(closes, window)
    if not ma:
        return None
    latest = closes[-1]
    return (latest - ma) / ma * 100


def unrealized_gain_pct(entry_price: float, latest_price: float) -> float:
    return (latest_price / entry_price - 1) * 100


def check_take_profit_candidates(
    open_theses: list,
    latest_prices: dict,
    ma_deviations: dict,
    *,
    profit_threshold: float = DEFAULT_PROFIT_THRESHOLD_PCT,
    ma_deviation_threshold: float = DEFAULT_MA_DEVIATION_THRESHOLD_PCT,
) -> list:
    alerts = []
    for thesis in open_theses:
        price = latest_prices.get(thesis.ticker)
        if price is None:
            continue
        gain_pct = unrealized_gain_pct(thesis.entry_price, price)
        deviation = ma_deviations.get(thesis.ticker)

        reasons = []
        if gain_pct >= profit_threshold:
            reasons.append(f"含み益{gain_pct:+.1f}%")
        if deviation is not None and deviation >= ma_deviation_threshold:
            reasons.append(f"移動平均乖離{deviation:+.1f}%")

        if reasons:
            alerts.append(
                CashControlAlert(
                    alert_type="利確検討",
                    ticker=thesis.ticker,
                    message=f"#{thesis.id} {thesis.ticker}: " + "・".join(reasons) + " -> 利確を検討してください",
                )
            )
    return alerts


def check_stop_loss_breaches(open_theses: list, latest_prices: dict) -> list:
    alerts = []
    for thesis in open_theses:
        price = latest_prices.get(thesis.ticker)
        if price is None:
            continue
        if price < thesis.stop_price:
            loss_pct = unrealized_gain_pct(thesis.entry_price, price)
            alerts.append(
                CashControlAlert(
                    alert_type="損切り",
                    ticker=thesis.ticker,
                    message=(
                        f"#{thesis.id} {thesis.ticker}: 現在値{price}が損切り価格{thesis.stop_price}を"
                        f"割れています(含み損{loss_pct:+.1f}%) -> 損切りを検討してください"
                    ),
                )
            )
    return alerts


def check_crash_buy_opportunity(
    topix_quotes: list,
    score_results: list,
    *,
    window: int = DEFAULT_MA_WINDOW,
    deviation_threshold: float = DEFAULT_CRASH_DEVIATION_THRESHOLD_PCT,
    top_n: int = 5,
) -> Optional[CashControlAlert]:
    """TOPIXが移動平均から大きく下方乖離した際に、待機資金投入とスコア上位銘柄を提示する。"""
    deviation = moving_average_deviation(topix_quotes, window)
    if deviation is None or deviation > deviation_threshold:
        return None

    top = sorted(score_results, key=lambda r: r.total_score, reverse=True)[:top_n]
    tickers_str = ", ".join(f"{r.ticker}(score={r.total_score})" for r in top) or "該当銘柄なし"

    return CashControlAlert(
        alert_type="暴落仕込み",
        ticker=None,
        message=(
            f"TOPIXが{window}日移動平均から{deviation:+.1f}%下方乖離しています。"
            f"待機資金の投入を検討してください。スコア上位銘柄: {tickers_str}"
        ),
    )
