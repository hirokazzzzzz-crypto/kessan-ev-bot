"""年間シーズナリティ・市場イベントカレンダー(2-1) 手動メモ側。

自由記述ログ+タグ付けを保存し、翌年以降の同時期に自動リマインドできるようにする。
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional


@dataclass
class CalendarMemo:
    id: Optional[int]
    created_at: str
    event_month: int
    event_day: int
    tags: str  # カンマ区切り
    note: str

    @classmethod
    def from_row(cls, row):
        return cls(**{k: row[k] for k in row.keys()})

    def tag_list(self) -> list:
        return [t.strip() for t in self.tags.split(",") if t.strip()]


def add_memo(conn, *, event_month: int, event_day: int, note: str, tags: Optional[list] = None) -> CalendarMemo:
    if not (1 <= event_month <= 12):
        raise ValueError("event_month は1〜12で指定してください")
    if not (1 <= event_day <= 31):
        raise ValueError("event_day は1〜31で指定してください")

    created_at = datetime.now().isoformat(timespec="seconds")
    tags_str = ",".join(tags) if tags else ""

    cur = conn.execute(
        """
        INSERT INTO calendar_memos (created_at, event_month, event_day, tags, note)
        VALUES (?, ?, ?, ?, ?)
        """,
        (created_at, event_month, event_day, tags_str, note),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM calendar_memos WHERE id = ?", (cur.lastrowid,)).fetchone()
    return CalendarMemo.from_row(row)


def list_memos(conn, tag: Optional[str] = None) -> list:
    rows = conn.execute(
        "SELECT * FROM calendar_memos ORDER BY event_month, event_day"
    ).fetchall()
    memos = [CalendarMemo.from_row(r) for r in rows]
    if tag:
        memos = [m for m in memos if tag in m.tag_list()]
    return memos


def _day_of_year_distance(month_a: int, day_a: int, month_b: int, day_b: int) -> int:
    """2つの(month, day)の、年をまたぐ場合も考慮した最短日数差(概算、非閏年基準)を返す。"""
    base_year = 2001  # 非閏年を基準にして2/29の扱いを避ける
    try:
        da = date(base_year, month_a, min(day_a, 28) if month_a == 2 else day_a)
    except ValueError:
        da = date(base_year, month_a, 28)
    try:
        db_ = date(base_year, month_b, min(day_b, 28) if month_b == 2 else day_b)
    except ValueError:
        db_ = date(base_year, month_b, 28)

    diff = abs((da - db_).days)
    return min(diff, 365 - diff)


def due_memos(conn, today: Optional[date] = None, window_days: int = 7) -> list:
    """今日から window_days 日以内(前後)に該当する(=翌年以降も含め同時期が近づいた)メモを返す。"""
    today = today or date.today()
    return [
        m
        for m in list_memos(conn)
        if _day_of_year_distance(m.event_month, m.event_day, today.month, today.day) <= window_days
    ]
