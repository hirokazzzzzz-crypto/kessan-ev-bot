"""J-Quants API V2 の薄いラッパー。

認証はリフレッシュトークン(推奨)またはメールアドレス+パスワードで行う。
資格情報は環境変数から読む:
    JQUANTS_REFRESH_TOKEN            (優先)
    JQUANTS_MAILADDRESS / JQUANTS_PASSWORD  (未指定時にリフレッシュトークンを取得するため使用)

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
    def __init__(
        self,
        refresh_token: Optional[str] = None,
        mail_address: Optional[str] = None,
        password: Optional[str] = None,
        base_url: str = BASE_URL,
    ):
        self._refresh_token = refresh_token or os.environ.get("JQUANTS_REFRESH_TOKEN")
        self._mail_address = mail_address or os.environ.get("JQUANTS_MAILADDRESS")
        self._password = password or os.environ.get("JQUANTS_PASSWORD")
        self._base_url = base_url.rstrip("/")
        self._id_token: Optional[str] = None

    # -- 認証 -------------------------------------------------------
    def _fetch_refresh_token(self) -> str:
        if not (self._mail_address and self._password):
            raise JQuantsAuthError(
                "JQUANTS_REFRESH_TOKEN、または "
                "JQUANTS_MAILADDRESS/JQUANTS_PASSWORD を設定してください"
            )
        resp = requests.post(
            f"{self._base_url}/token/auth_user",
            json={"mailaddress": self._mail_address, "password": self._password},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["refreshToken"]

    def _ensure_id_token(self) -> str:
        if self._id_token:
            return self._id_token

        refresh_token = self._refresh_token or self._fetch_refresh_token()
        resp = requests.post(
            f"{self._base_url}/token/auth_refresh",
            params={"refreshtoken": refresh_token},
            timeout=30,
        )
        resp.raise_for_status()
        self._id_token = resp.json()["idToken"]
        return self._id_token

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        token = self._ensure_id_token()
        resp = requests.get(
            f"{self._base_url}{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=params or {},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    # -- データ取得 ---------------------------------------------------
    def get_statements(self, *, code: Optional[str] = None, date: Optional[str] = None) -> list:
        """財務情報(/fins/statements)。code または date のいずれかを指定する。"""
        if not code and not date:
            raise ValueError("code または date のいずれかを指定してください")
        params = {}
        if code:
            params["code"] = code
        if date:
            params["date"] = date
        return self._get("/fins/statements", params).get("statements", [])

    def get_daily_quotes(self, code: str, from_date: str, to_date: str) -> list:
        """株価四本値(/prices/daily_quotes)。"""
        params = {"code": code, "from": from_date, "to": to_date}
        return self._get("/prices/daily_quotes", params).get("daily_quotes", [])

    def get_topix(self, from_date: str, to_date: str) -> list:
        """TOPIX四本値(/indices/topix)。"""
        params = {"from": from_date, "to": to_date}
        return self._get("/indices/topix", params).get("topix", [])
