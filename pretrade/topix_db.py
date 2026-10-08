"""TOPIX採用予想・需給分析(Phase 5)のDB側。

証券会社等の採用予想ログ(topix_broker_forecasts)と、
発表後の結果記録(topix_outcomes)のCRUDを担う。スキーマ自体は db.py で定義する。
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .topix_review import BrokerForecast, OUTCOME_CHOICES


@dataclass
class StoredBrokerForecast:
    id: Optional[int]
    created_at: str
    ticker: str
    broker: str
    review_date: str
    forecast_type: str
    mentioned_at: str
    source_note: str

    @classmethod
    def from_row(cls, row):
        return cls(**{k: row[k] for k in row.keys()})

    def to_broker_forecast(self) -> BrokerForecast:
        return BrokerForecast(
            ticker=self.ticker,
            broker=self.broker,
            review_date=self.review_date,
            forecast_type=self.forecast_type,
            mentioned_at=self.mentioned_at,
            source_note=self.source_note,
        )


@dataclass
class StoredOutcome:
    id: Optional[int]
    created_at: str
    ticker: str
    review_date: str
    outcome: str
    announcement_date: Optional[str]
    price_reaction_pct: Optional[float]
    note: str

    @classmethod
    def from_row(cls, row):
        return cls(**{k: row[k] for k in row.keys()})


def add_forecast(
    conn,
    *,
    ticker: str,
    broker: str,
    review_date: str,
    forecast_type: str,
    mentioned_at: str,
    source_note: str = "",
) -> StoredBrokerForecast:
    if forecast_type not in ("new", "exclude"):
        raise ValueError('forecast_type は "new" または "exclude" で指定してください')

    created_at = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        """
        INSERT INTO topix_broker_forecasts
            (created_at, ticker, broker, review_date, forecast_type, mentioned_at, source_note)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (created_at, ticker, broker, review_date, forecast_type, mentioned_at, source_note),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM topix_broker_forecasts WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return StoredBrokerForecast.from_row(row)


def list_forecasts(conn, *, review_date: Optional[str] = None, ticker: Optional[str] = None) -> list:
    query = "SELECT * FROM topix_broker_forecasts WHERE 1=1"
    params = []
    if review_date:
        query += " AND review_date = ?"
        params.append(review_date)
    if ticker:
        query += " AND ticker = ?"
        params.append(ticker)
    query += " ORDER BY ticker, mentioned_at"
    rows = conn.execute(query, params).fetchall()
    return [StoredBrokerForecast.from_row(r) for r in rows]


def forecasts_by_ticker(conn, review_date: str) -> dict:
    """{ticker: [BrokerForecast, ...]} の形で、topix_review.py の関数にそのまま渡せる形にする。"""
    grouped: dict = {}
    for stored in list_forecasts(conn, review_date=review_date):
        grouped.setdefault(stored.ticker, []).append(stored.to_broker_forecast())
    return grouped


def add_outcome(
    conn,
    *,
    ticker: str,
    review_date: str,
    outcome: str,
    announcement_date: Optional[str] = None,
    price_reaction_pct: Optional[float] = None,
    note: str = "",
) -> StoredOutcome:
    if outcome not in OUTCOME_CHOICES:
        raise ValueError(f"outcome は次のいずれかで指定してください: {OUTCOME_CHOICES}")

    created_at = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        """
        INSERT INTO topix_outcomes
            (created_at, ticker, review_date, outcome, announcement_date, price_reaction_pct, note)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (created_at, ticker, review_date, outcome, announcement_date, price_reaction_pct, note),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM topix_outcomes WHERE id = ?", (cur.lastrowid,)).fetchone()
    return StoredOutcome.from_row(row)


def list_outcomes(conn, *, review_date: Optional[str] = None) -> list:
    query = "SELECT * FROM topix_outcomes WHERE 1=1"
    params = []
    if review_date:
        query += " AND review_date = ?"
        params.append(review_date)
    query += " ORDER BY ticker"
    rows = conn.execute(query, params).fetchall()
    return [StoredOutcome.from_row(r) for r in rows]


def accuracy_report(conn, *, review_date: Optional[str] = None) -> dict:
    """予想通り/予想外/見送りの件数集計(次回予想の精度確認用)。"""
    outcomes = list_outcomes(conn, review_date=review_date)
    counts = {choice: 0 for choice in OUTCOME_CHOICES}
    for o in outcomes:
        counts[o.outcome] = counts.get(o.outcome, 0) + 1
    return {"total": len(outcomes), "by_outcome": counts}
