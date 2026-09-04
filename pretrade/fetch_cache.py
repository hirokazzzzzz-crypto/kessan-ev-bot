"""J-Quants APIから取得したデータをローカルJSONにキャッシュする(GitHub Actions定期バッチ想定)。

score/screen コマンドはこのキャッシュファイルを読み込んで動作する。
APIレート制限や再現性のため、都度APIを叩くのではなくキャッシュ経由にしている。
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from .jquants_client import JQuantsClient

DEFAULT_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "market_cache.json"


def fetch_and_cache(
    codes: list,
    from_date: str,
    to_date: str,
    out_path=None,
    client: Optional[JQuantsClient] = None,
) -> Path:
    client = client or JQuantsClient()
    data = {
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "from_date": from_date,
        "to_date": to_date,
        "topix": client.get_topix(from_date, to_date),
        "tickers": {},
    }
    for code in codes:
        data["tickers"][code] = {
            "statements": client.get_statements(code=code),
            "quotes": client.get_daily_quotes(code, from_date, to_date),
        }

    path = Path(out_path) if out_path else DEFAULT_CACHE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_cache(path=None) -> dict:
    path = Path(path) if path else DEFAULT_CACHE_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"キャッシュファイルが見つかりません: {path}\n"
            f"先に `fetch-data` コマンドでデータを取得してください。"
        )
    return json.loads(path.read_text(encoding="utf-8"))
