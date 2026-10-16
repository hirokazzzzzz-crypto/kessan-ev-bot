"""底値/天井判断の材料収集。

「SNS等の情報をもとに今が仕込み時か判断する」ことそのものは自動化しない
(ユーザー自身の要望どおり、判断は後回しでよい)。まずは誰が・いつ・何を
根拠に「そろそろ底/天井では」と言っていたかを記録し、結果が出た後に
振り返って発言元ごとの的中率を追えるようにする、という割り切った設計にしている。

ネットワークアクセスは行わない(既存モジュールと同じ方針)。SNS投稿の自動収集手段は
無いため、見つけた都度 market_calls_db.py 経由で手動ログする想定。
"""
from dataclasses import dataclass
from typing import Optional

CALL_TYPES = ["底値", "天井", "その他"]
OUTCOME_HIT = "的中"
OUTCOME_MISS = "外れ"
OUTCOME_PENDING = "未確定"
OUTCOME_CHOICES = [OUTCOME_HIT, OUTCOME_MISS, OUTCOME_PENDING]


@dataclass
class MarketCall:
    ticker: str
    source: str  # 例: "X:@leo_xxx" や「レオ」
    call_type: str  # CALL_TYPES のいずれか
    called_at: Optional[str] = None  # 発言日(YYYY-MM-DD)。分からなければ None
    price_at_call: Optional[float] = None
    note: str = ""
    url: str = ""
    outcome: str = OUTCOME_PENDING


def validate_call_type(call_type: str) -> None:
    if call_type not in CALL_TYPES:
        raise ValueError(f"call_type は次のいずれかで指定してください: {CALL_TYPES}")


def validate_outcome(outcome: str) -> None:
    if outcome not in OUTCOME_CHOICES:
        raise ValueError(f"outcome は次のいずれかで指定してください: {OUTCOME_CHOICES}")


@dataclass
class SourceAccuracy:
    source: str
    total: int
    hits: int
    misses: int
    pending: int

    @property
    def hit_rate_pct(self) -> Optional[float]:
        """判定済み(的中+外れ)のうち的中した割合。未確定しかない場合は None。"""
        resolved = self.hits + self.misses
        if resolved == 0:
            return None
        return self.hits / resolved * 100


def summarize_accuracy_by_source(calls: list) -> list:
    """MarketCall のリストを発言元(source)ごとに集計し、的中率の高い順に返す。

    「レオさんは今回も当たった」のような、発言元の信頼度を積み上げて見るための集計。
    """
    grouped: dict = {}
    for call in calls:
        acc = grouped.setdefault(call.source, {"total": 0, "hits": 0, "misses": 0, "pending": 0})
        acc["total"] += 1
        if call.outcome == OUTCOME_HIT:
            acc["hits"] += 1
        elif call.outcome == OUTCOME_MISS:
            acc["misses"] += 1
        else:
            acc["pending"] += 1

    results = [
        SourceAccuracy(source=source, total=v["total"], hits=v["hits"], misses=v["misses"], pending=v["pending"])
        for source, v in grouped.items()
    ]

    def _sort_key(r: SourceAccuracy):
        rate = r.hit_rate_pct
        # 的中率が高い順。未確定のみ(rate=None)は最後に回す。
        return (rate is None, -(rate or 0), -r.total)

    return sorted(results, key=_sort_key)
