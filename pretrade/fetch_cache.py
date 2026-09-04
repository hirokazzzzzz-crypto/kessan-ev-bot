"""J-Quants APIから取得したデータをローカルJSONにキャッシュする(GitHub Actions定期バッチ想定)。

score/screen コマンドはこのキャッシュファイルを読み込んで動作する。
APIレート制限や再現性のため、都度APIを叩くのではなくキャッシュ経由にしている。
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

from .jquants_client import JQuantsClient

DEFAULT_CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "market_cache.json"


def _fetch_topix_or_empty(client: JQuantsClient, from_date: str, to_date: str) -> list:
    """TOPIXはJ-Quantsのプランによっては利用できない(APIが403/AccessDenied を返す)ため、
    取得に失敗しても致命的エラーにはせず、空リストにフォールバックする。
    TOPIXが空の場合、対TOPIX反応度を使う機能(2-0スクリーナー・2-4暴落検知)は
    自動的に対象外になる(screener.py/cash_control.py側で空データを安全に扱う)。
    """
    try:
        return client.get_topix(from_date, to_date)
    except requests.exceptions.HTTPError as e:
        print(
            f"[警告] TOPIXデータの取得に失敗しました(ご契約プランでは利用できない可能性があります): {e}\n"
            f"  -> TOPIXを使う機能(未認識の好進捗スクリーナー・暴落仕込みアラート)は動作しません。"
        )
        return []


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
        "topix": _fetch_topix_or_empty(client, from_date, to_date),
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
