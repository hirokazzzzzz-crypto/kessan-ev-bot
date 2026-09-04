from pretrade.slack_notify import send_slack_message


def test_send_slack_message_skips_when_not_configured(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    assert send_slack_message("hello") is False


def test_send_slack_message_posts_when_configured(monkeypatch):
    calls = []

    class _FakeResponse:
        def raise_for_status(self):
            pass

    def fake_post(url, json=None, timeout=None):
        calls.append((url, json))
        return _FakeResponse()

    monkeypatch.setattr("pretrade.slack_notify.requests.post", fake_post)

    result = send_slack_message("hello", webhook_url="https://hooks.example.com/x")
    assert result is True
    assert calls == [("https://hooks.example.com/x", {"text": "hello"})]
