"""J-Quantsの生データ(statements/quotes)から scoring.ScoreInputs を組み立てるつなぎ役。"""
from typing import Optional

from . import signals
from .scoring import ScoreInputs


def build_score_inputs(
    ticker: str,
    statements: list,
    quotes: list,
    *,
    latest_price: Optional[float] = None,
    exclusion_reasons: Optional[list] = None,
) -> ScoreInputs:
    stmts = signals.sort_statements(statements)
    q_stock = signals.sort_quotes(quotes)

    beat_or_revision, reason = signals.detect_earnings_beat_or_upward_revision(stmts)

    price = latest_price
    if price is None and q_stock:
        last_quote = q_stock[-1]
        price = signals.to_float(last_quote.get("AdjC")) or signals.to_float(
            last_quote.get("C")
        )

    pbr = per = None
    if stmts and price:
        latest_stmt = stmts[-1]
        pbr = signals.compute_pbr(latest_stmt, price)
        per = signals.compute_per(latest_stmt, price)

    return ScoreInputs(
        ticker=ticker,
        earnings_beat_or_revision_up=beat_or_revision,
        earnings_reason=reason,
        pbr=pbr,
        per=per,
        volume_surge=signals.is_volume_surge(q_stock),
        trend_reversal=signals.detect_trend_reversal(q_stock),
        exclusion_reasons=exclusion_reasons or [],
    )
