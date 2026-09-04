import pytest

from pretrade.jquants_client import JQuantsClient, JQuantsAuthError


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_missing_credentials_raises_auth_error(monkeypatch):
    monkeypatch.delenv("JQUANTS_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("JQUANTS_MAILADDRESS", raising=False)
    monkeypatch.delenv("JQUANTS_PASSWORD", raising=False)

    client = JQuantsClient()
    with pytest.raises(JQuantsAuthError):
        client._ensure_id_token()


def test_get_statements_uses_refresh_token_and_returns_list(monkeypatch):
    client = JQuantsClient(refresh_token="dummy-refresh-token")

    calls = []

    def fake_post(url, params=None, json=None, timeout=None):
        calls.append((url, params, json))
        assert "auth_refresh" in url
        return _FakeResponse({"idToken": "dummy-id-token"})

    def fake_get(url, headers=None, params=None, timeout=None):
        assert headers["Authorization"] == "Bearer dummy-id-token"
        assert params["code"] == "7203"
        return _FakeResponse({"statements": [{"LocalCode": "7203"}]})

    monkeypatch.setattr("pretrade.jquants_client.requests.post", fake_post)
    monkeypatch.setattr("pretrade.jquants_client.requests.get", fake_get)

    result = client.get_statements(code="7203")
    assert result == [{"LocalCode": "7203"}]
    assert len(calls) == 1


def test_get_statements_requires_code_or_date():
    client = JQuantsClient(refresh_token="dummy")
    with pytest.raises(ValueError):
        client.get_statements()


def test_id_token_is_cached_across_calls(monkeypatch):
    client = JQuantsClient(refresh_token="dummy-refresh-token")
    post_calls = []

    def fake_post(url, params=None, json=None, timeout=None):
        post_calls.append(url)
        return _FakeResponse({"idToken": "dummy-id-token"})

    def fake_get(url, headers=None, params=None, timeout=None):
        return _FakeResponse({"daily_quotes": []})

    monkeypatch.setattr("pretrade.jquants_client.requests.post", fake_post)
    monkeypatch.setattr("pretrade.jquants_client.requests.get", fake_get)

    client.get_daily_quotes("7203", "2026-01-01", "2026-01-31")
    client.get_daily_quotes("7203", "2026-02-01", "2026-02-28")

    assert len(post_calls) == 1  # 2回目はキャッシュされたid tokenを使う
