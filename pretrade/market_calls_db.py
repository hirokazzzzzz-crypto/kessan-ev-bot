"""market_calls.py のDB側。底値/天井の発言ログのCRUDを担う。"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from .market_calls import MarketCall, OUTCOME_PENDING, validate_call_type, validate_outcome


@dataclass
class StoredMarketCall:
    id: Optional[int]
    created_at: str
    ticker: str
    source: str
    call_type: str
    called_at: Optional[str]
    price_at_call: Optional[float]
    note: str
    url: str
    outcome: str

    @classmethod
    def from_row(cls, row):
        return cls(**{k: row[k] for k in row.keys()})

    def to_market_call(self) -> MarketCall:
        return MarketCall(
            ticker=self.ticker, source=self.source, call_type=self.call_type,
            called_at=self.called_at, price_at_call=self.price_at_call,
            note=self.note, url=self.url, outcome=self.outcome,
        )


def add_call(
    conn,
    *,
    ticker: str,
    source: str,
    call_type: str,
    called_at: Optional[str] = None,
    price_at_call: Optional[float] = None,
    note: str = "",
    url: str = "",
) -> StoredMarketCall:
    validate_call_type(call_type)
    created_at = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        """
        INSERT INTO market_calls
            (created_at, ticker, source, call_type, called_at, price_at_call, note, url, outcome)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (created_at, ticker, source, call_type, called_at, price_at_call, note, url, OUTCOME_PENDING),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM market_calls WHERE id = ?", (cur.lastrowid,)).fetchone()
    return StoredMarketCall.from_row(row)


def list_calls(conn, *, ticker: Optional[str] = None, source: Optional[str] = None) -> list:
    query = "SELECT * FROM market_calls WHERE 1=1"
    params = []
    if ticker:
        query += " AND ticker = ?"
        params.append(ticker)
    if source:
        query += " AND source = ?"
        params.append(source)
    query += " ORDER BY COALESCE(called_at, created_at) DESC"
    rows = conn.execute(query, params).fetchall()
    return [StoredMarketCall.from_row(r) for r in rows]


def set_outcome(conn, call_id: int, outcome: str) -> StoredMarketCall:
    validate_outcome(outcome)
    conn.execute("UPDATE market_calls SET outcome = ? WHERE id = ?", (outcome, call_id))
    conn.commit()
    row = conn.execute("SELECT * FROM market_calls WHERE id = ?", (call_id,)).fetchone()
    if row is None:
        raise ValueError(f"id={call_id} のレコードが見つかりません")
    return StoredMarketCall.from_row(row)


def all_calls_as_domain(conn) -> list:
    """market_calls.summarize_accuracy_by_source() にそのまま渡せる形で全件返す。"""
    return [stored.to_market_call() for stored in list_calls(conn)]
