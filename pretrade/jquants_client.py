"""J-Quants API V2 の薄いラッパー。

V2の認証はシンプルで、ダッシュボードで発行したAPIキーをそのまま
`x-api-key` ヘッダーに設定するだけでよい(V1のような
リフレッシュトークン→IDトークンの交換は不要)。
資格情報は環境変数 JQUANTS_API_KEY から読む。

このモジュールはネットワーク越しにJ-Quants APIを叩く薄い層のみを担う。
取得したデータの解釈(スコアリング・スクリーニング)は signals.py / scoring.py / screener.py で行う。
"""
import os
from typing import Optional

import requests

BASE_URL = "https://api.jquants.com/v2"


class JQuantsAuthError(RuntimeError):
    pass


class JQuantsClient:
    def __init__(self, api_key: Optional[str] = None, base_url: str = BASE_URL):
        self._api_key = api_key or os.environ.get("JQUANTS_API_KEY")
        self._base_url = base_url.rstrip("/")

    def _headers(self) -> dict:
        if not self._api_key:
            raise JQuantsAuthError("JQUANTS_API_KEY を設定してください")
        return {"x-api-key": self._api_key}

    def _get_all(self, path: str, params: dict) -> list:
        """pagination_key を辿って `data` の全ページ分を取得する。"""
        results = []
        query = dict(params)
        while True:
            resp = requests.get(
                f"{self._base_url}{path}",
                headers=self._headers(),
                params=query,
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json()
            results.extend(payload.get("data", []))

            pagination_key = payload.get("pagination_key")
            if not pagination_key:
                break
            query = dict(params, pagination_key=pagination_key)
        return results

    # -- データ取得 ---------------------------------------------------
    def get_statements(self, *, code: Optional[str] = None, date: Optional[str] = None) -> list:
        """財務情報サマリー(/fins/summary)。code または date のいずれかを指定する。"""
        if not code and not date:
            raise ValueError("code または date のいずれかを指定してください")
        params = {}
        if code:
            params["code"] = code
        if date:
            params["date"] = date
        return self._get_all("/fins/summary", params)

    def get_daily_quotes(self, code: str, from_date: str, to_date: str) -> list:
        """株価四本値(/equities/bars/daily)。"""
        params = {"code": code, "from": from_date, "to": to_date}
        return self._get_all("/equities/bars/daily", params)

    def get_topix(self, from_date: str, to_date: str) -> list:
        """TOPIX指数四本値(/indices/bars/daily/topix)。"""
        params = {"from": from_date, "to": to_date}
        return self._get_all("/indices/bars/daily/topix", params)
