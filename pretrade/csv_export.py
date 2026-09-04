"""既存のポジション管理CSVと連携するためのCSV入出力。

出力するCSVは ticker 列をキーに既存のポジション管理CSV(銘柄コード列を持つ想定)と
突合できるフラットな形式にしている。
"""
import csv
from pathlib import Path

from .models import TradeThesis

FIELDNAMES = [
    "id", "ticker", "created_at", "alpha_thesis", "rationale_category",
    "entry_price", "target_price", "stop_price", "reward", "risk", "rr_ratio",
    "holding_period", "exit_condition", "status",
    "exit_price", "exit_date", "exit_reason", "as_expected", "reflection", "pnl_pct",
]


def export_csv(conn, csv_path) -> Path:
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = conn.execute("SELECT * FROM trade_theses ORDER BY id").fetchall()

    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in FIELDNAMES})
    return path
