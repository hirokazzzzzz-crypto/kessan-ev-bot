"""SQLiteスキーマとコネクション管理。"""
import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "data" / "pretrade.db"

# 2-2の銘柄選定基準スコアリング項目と揃えた根拠分類。
RATIONALE_CATEGORIES = [
    "決算超過/上方修正",
    "PBR1倍割れ",
    "PER割安",
    "出来高急増",
    "トレンド転換",
    "その他",
]

EXIT_REASONS = ["利確", "損切り", "その他"]
AS_EXPECTED_CHOICES = ["想定通り", "一部想定通り", "想定外"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_theses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    created_at TEXT NOT NULL,
    alpha_thesis TEXT NOT NULL,
    rationale_category TEXT NOT NULL,
    entry_price REAL NOT NULL,
    target_price REAL NOT NULL,
    stop_price REAL NOT NULL,
    reward REAL NOT NULL,
    risk REAL NOT NULL,
    rr_ratio REAL NOT NULL,
    holding_period TEXT NOT NULL,
    exit_condition TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    exit_price REAL,
    exit_date TEXT,
    exit_reason TEXT,
    as_expected TEXT,
    reflection TEXT,
    pnl_pct REAL
);

CREATE TABLE IF NOT EXISTS calendar_memos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    event_month INTEGER NOT NULL,
    event_day INTEGER NOT NULL,
    tags TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL
);
"""


def get_connection(db_path=None):
    """SQLite接続を返す。テーブルが無ければ作成する。"""
    path = Path(db_path) if db_path else DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
