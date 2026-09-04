"""銘柄選定基準の可視化(2-2)。シグナルからスコアと内訳を計算する。

決算超過/上方修正 +2、PBR1倍割れ +1、PER割安 +1、出来高急増 +1、
トレンド転換 +1、除外条件 -3(該当時は理由に関わらず一律)。
"""
from dataclasses import dataclass, field
from typing import Optional


POINTS_EARNINGS_BEAT_OR_REVISION_UP = 2
POINTS_PBR_UNDER_1 = 1
POINTS_PER_CHEAP = 1
POINTS_VOLUME_SURGE = 1
POINTS_TREND_REVERSAL = 1
POINTS_EXCLUSION = -3


@dataclass
class ScoreInputs:
    ticker: str
    earnings_beat_or_revision_up: bool
    earnings_reason: str
    pbr: Optional[float]
    per: Optional[float]
    volume_surge: bool
    trend_reversal: bool
    exclusion_reasons: list = field(default_factory=list)


@dataclass
class ScoreBreakdownItem:
    criterion: str
    points: int
    matched: bool
    detail: str


@dataclass
class ScoreResult:
    ticker: str
    total_score: int
    breakdown: list


def score_stock(inputs: ScoreInputs) -> ScoreResult:
    breakdown = []

    breakdown.append(
        ScoreBreakdownItem(
            criterion="決算超過/上方修正",
            points=POINTS_EARNINGS_BEAT_OR_REVISION_UP if inputs.earnings_beat_or_revision_up else 0,
            matched=inputs.earnings_beat_or_revision_up,
            detail=inputs.earnings_reason,
        )
    )

    pbr_matched = inputs.pbr is not None and inputs.pbr < 1.0
    breakdown.append(
        ScoreBreakdownItem(
            criterion="PBR1倍割れ",
            points=POINTS_PBR_UNDER_1 if pbr_matched else 0,
            matched=pbr_matched,
            detail=f"PBR={inputs.pbr:.2f}" if inputs.pbr is not None else "PBRデータなし",
        )
    )

    per_matched = inputs.per is not None and inputs.per < 15.0
    breakdown.append(
        ScoreBreakdownItem(
            criterion="PER割安",
            points=POINTS_PER_CHEAP if per_matched else 0,
            matched=per_matched,
            detail=f"PER={inputs.per:.2f}" if inputs.per is not None else "PERデータなし",
        )
    )

    breakdown.append(
        ScoreBreakdownItem(
            criterion="出来高急増",
            points=POINTS_VOLUME_SURGE if inputs.volume_surge else 0,
            matched=inputs.volume_surge,
            detail="直近出来高が過去平均の2倍以上" if inputs.volume_surge else "急増なし",
        )
    )

    breakdown.append(
        ScoreBreakdownItem(
            criterion="トレンド転換",
            points=POINTS_TREND_REVERSAL if inputs.trend_reversal else 0,
            matched=inputs.trend_reversal,
            detail="短期線が長期線を上抜け" if inputs.trend_reversal else "転換シグナルなし",
        )
    )

    excluded = bool(inputs.exclusion_reasons)
    breakdown.append(
        ScoreBreakdownItem(
            criterion="除外条件",
            points=POINTS_EXCLUSION if excluded else 0,
            matched=excluded,
            detail="; ".join(inputs.exclusion_reasons) if excluded else "該当なし",
        )
    )

    total_score = sum(item.points for item in breakdown)
    return ScoreResult(ticker=inputs.ticker, total_score=total_score, breakdown=breakdown)


def format_score_result(result: ScoreResult) -> str:
    lines = [f"銘柄 {result.ticker} スコア合計: {result.total_score}"]
    for item in result.breakdown:
        mark = "○" if item.matched else "×"
        lines.append(f"  [{mark}] {item.criterion} ({item.points:+d}点): {item.detail}")
    return "\n".join(lines)
