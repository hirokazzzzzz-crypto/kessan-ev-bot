"""既存Slack Webhookを流用した通知送信。

環境変数 SLACK_WEBHOOK_URL が未設定の場合は送信をスキップする(CLI出力のみで運用可能)。
"""
import os
from typing import Optional

import requests


def send_slack_message(text: str, webhook_url: Optional[str] = None) -> bool:
    """Slack Incoming Webhookにメッセージを送る。送信したらTrue、未設定でスキップしたらFalseを返す。"""
    url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL")
    if not url:
        return False
    resp = requests.post(url, json={"text": text}, timeout=10)
    resp.raise_for_status()
    return True
