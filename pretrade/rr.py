"""リスクリワード比の自動計算。"""
from dataclasses import dataclass

RR_WARNING_THRESHOLD = 2.0


@dataclass
class RiskReward:
    reward: float
    risk: float
    ratio: float
    warning: bool  # True: RR比が閾値未満


def calculate_rr(entry_price: float, target_price: float, stop_price: float) -> RiskReward:
    """RR比を計算する。ロング前提(target > entry > stop)。"""
    reward = target_price - entry_price
    risk = entry_price - stop_price

    if risk <= 0:
        raise ValueError("損切り価格はエントリー価格より低く設定してください")
    if reward <= 0:
        raise ValueError("目標価格はエントリー価格より高く設定してください")

    ratio = reward / risk
    return RiskReward(reward=reward, risk=risk, ratio=ratio, warning=ratio < RR_WARNING_THRESHOLD)
