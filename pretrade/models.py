"""トレード仮説(アルファ明確化ゲート)のデータモデルとリポジトリ関数。"""
from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional

from .rr import calculate_rr


@dataclass
class TradeThesis:
    id: Optional[int]
    ticker: str
    created_at: str
    alpha_thesis: str
    rationale_category: str
    entry_price: float
    target_price: float
    stop_price: float
    reward: float
    risk: float
    rr_ratio: float
    holding_period: str
    exit_condition: str
    status: str = "open"
    exit_price: Optional[float] = None
    exit_date: Optional[str] = None
    exit_reason: Optional[str] = None
    as_expected: Optional[str] = None
    reflection: Optional[str] = None
    pnl_pct: Optional[float] = None

    @classmethod
    def from_row(cls, row):
        return cls(**{k: row[k] for k in row.keys()})


def create_thesis(
    conn,
    *,
    ticker: str,
    alpha_thesis: str,
    rationale_category: str,
    entry_price: float,
    target_price: float,
    stop_price: float,
    holding_period: str,
    exit_condition: str,
) -> TradeThesis:
    """買う前チェック: アルファ仮説を登録し、RR比を自動計算して保存する。"""
    rr = calculate_rr(entry_price, target_price, stop_price)
    created_at = datetime.now().isoformat(timespec="seconds")

    cur = conn.execute(
        """
        INSERT INTO trade_theses (
            ticker, created_at, alpha_thesis, rationale_category,
            entry_price, target_price, stop_price,
            reward, risk, rr_ratio, holding_period, exit_condition, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
        """,
        (
            ticker, created_at, alpha_thesis, rationale_category,
            entry_price, target_price, stop_price,
            rr.reward, rr.risk, rr.ratio, holding_period, exit_condition,
        ),
    )
    conn.commit()
    return get_thesis(conn, cur.lastrowid)


def get_thesis(conn, thesis_id: int) -> Optional[TradeThesis]:
    row = conn.execute("SELECT * FROM trade_theses WHERE id = ?", (thesis_id,)).fetchone()
    return TradeThesis.from_row(row) if row else None


def list_open(conn):
    rows = conn.execute(
        "SELECT * FROM trade_theses WHERE status = 'open' ORDER BY created_at"
    ).fetchall()
    return [TradeThesis.from_row(r) for r in rows]


def list_closed(conn, year_month: Optional[str] = None):
    """決済済みトレードを一覧する。year_monthは'YYYY-MM'形式(exit_dateで絞り込み)。"""
    if year_month:
        rows = conn.execute(
            "SELECT * FROM trade_theses WHERE status = 'closed' AND exit_date LIKE ? ORDER BY exit_date",
            (f"{year_month}%",),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM trade_theses WHERE status = 'closed' ORDER BY exit_date"
        ).fetchall()
    return [TradeThesis.from_row(r) for r in rows]


def close_thesis(
    conn,
    thesis_id: int,
    *,
    exit_price: float,
    exit_reason: str,
    as_expected: str,
    reflection: str,
    exit_date: Optional[str] = None,
) -> TradeThesis:
    """売る前/決済チェック: 利確損切り区分・想定通りか・振り返りを記録する。"""
    thesis = get_thesis(conn, thesis_id)
    if thesis is None:
        raise ValueError(f"id={thesis_id} のトレード仮説が見つかりません")
    if thesis.status == "closed":
        raise ValueError(f"id={thesis_id} は既に決済済みです")

    exit_date = exit_date or date.today().isoformat()
    pnl_pct = (exit_price - thesis.entry_price) / thesis.entry_price * 100

    conn.execute(
        """
        UPDATE trade_theses
        SET status = 'closed', exit_price = ?, exit_date = ?, exit_reason = ?,
            as_expected = ?, reflection = ?, pnl_pct = ?
        WHERE id = ?
        """,
        (exit_price, exit_date, exit_reason, as_expected, reflection, pnl_pct, thesis_id),
    )
    conn.commit()
    return get_thesis(conn, thesis_id)
