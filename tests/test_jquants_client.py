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


def test_missing_api_key_raises_auth_error(monkeypatch):
    monkeypatch.delenv("JQUANTS_API_KEY", raising=False)

    client = JQuantsClient()
    with pytest.raises(JQuantsAuthError):
        client.get_statements(code="7203")


def test_get_statements_sends_api_key_header_and_returns_data(monkeypatch):
    client = JQuantsClient(api_key="dummy-api-key")
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append((url, headers, params))
        assert url == "https://api.jquants.com/v2/fins/summary"
        assert headers["x-api-key"] == "dummy-api-key"
        assert params["code"] == "7203"
        return _FakeResponse({"data": [{"Code": "7203"}]})

    monkeypatch.setattr("pretrade.jquants_client.requests.get", fake_get)

    result = client.get_statements(code="7203")
    assert result == [{"Code": "7203"}]
    assert len(calls) == 1


def test_get_statements_requires_code_or_date():
    client = JQuantsClient(api_key="dummy")
    with pytest.raises(ValueError):
        client.get_statements()


def test_get_daily_quotes_uses_correct_endpoint_and_params(monkeypatch):
    client = JQuantsClient(api_key="dummy")

    def fake_get(url, headers=None, params=None, timeout=None):
        assert url == "https://api.jquants.com/v2/equities/bars/daily"
        assert params == {"code": "7203", "from": "2026-01-01", "to": "2026-01-31"}
        return _FakeResponse({"data": [{"Date": "2026-01-05", "Code": "7203", "C": 1000}]})

    monkeypatch.setattr("pretrade.jquants_client.requests.get", fake_get)

    result = client.get_daily_quotes("7203", "2026-01-01", "2026-01-31")
    assert result == [{"Date": "2026-01-05", "Code": "7203", "C": 1000}]


def test_get_topix_uses_correct_endpoint_and_params(monkeypatch):
    client = JQuantsClient(api_key="dummy")

    def fake_get(url, headers=None, params=None, timeout=None):
        assert url == "https://api.jquants.com/v2/indices/bars/daily/topix"
        assert params == {"from": "2026-01-01", "to": "2026-01-31"}
        return _FakeResponse({"data": [{"Date": "2026-01-05", "C": 2000}]})

    monkeypatch.setattr("pretrade.jquants_client.requests.get", fake_get)

    result = client.get_topix("2026-01-01", "2026-01-31")
    assert result == [{"Date": "2026-01-05", "C": 2000}]


def test_pagination_key_follows_all_pages(monkeypatch):
    client = JQuantsClient(api_key="dummy")
    responses = [
        {"data": [{"Date": "2026-01-01"}], "pagination_key": "page2"},
        {"data": [{"Date": "2026-01-02"}]},
    ]
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append(params)
        return _FakeResponse(responses.pop(0))

    monkeypatch.setattr("pretrade.jquants_client.requests.get", fake_get)

    result = client.get_topix("2026-01-01", "2026-01-31")
    assert result == [{"Date": "2026-01-01"}, {"Date": "2026-01-02"}]
    assert calls[0].get("pagination_key") is None
    assert calls[1]["pagination_key"] == "page2"
