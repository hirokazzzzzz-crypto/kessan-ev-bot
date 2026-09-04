import json

import requests

from pretrade.fetch_cache import fetch_and_cache, load_cache


class _FakeClient:
    def get_topix(self, from_date, to_date):
        return [{"Date": from_date, "C": "2000"}, {"Date": to_date, "C": "2100"}]

    def get_statements(self, code=None, date=None):
        return [{"Code": code, "DiscDate": "2026-05-01"}]

    def get_daily_quotes(self, code, from_date, to_date):
        return [{"Date": from_date, "Code": code, "C": "1000"}]


class _TopixForbiddenClient(_FakeClient):
    def get_topix(self, from_date, to_date):
        response = requests.Response()
        response.status_code = 403
        raise requests.exceptions.HTTPError("403 Forbidden", response=response)


def test_fetch_and_cache_writes_expected_structure(tmp_path):
    out_path = tmp_path / "cache.json"
    path = fetch_and_cache(
        ["7203", "9984"], "2026-01-01", "2026-09-01", out_path, client=_FakeClient()
    )

    assert path == out_path
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert set(data["tickers"].keys()) == {"7203", "9984"}
    assert data["tickers"]["7203"]["statements"][0]["Code"] == "7203"
    assert len(data["topix"]) == 2


def test_load_cache_roundtrip(tmp_path):
    out_path = tmp_path / "cache.json"
    fetch_and_cache(["7203"], "2026-01-01", "2026-09-01", out_path, client=_FakeClient())

    loaded = load_cache(out_path)
    assert loaded["tickers"]["7203"]["quotes"][0]["Code"] == "7203"


def test_fetch_and_cache_falls_back_to_empty_topix_when_forbidden(tmp_path, capsys):
    out_path = tmp_path / "cache.json"
    path = fetch_and_cache(
        ["7203"], "2026-01-01", "2026-09-01", out_path, client=_TopixForbiddenClient()
    )

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["topix"] == []
    assert data["tickers"]["7203"]["statements"][0]["Code"] == "7203"

    captured = capsys.readouterr()
    assert "TOPIX" in captured.out


def test_load_cache_missing_file_raises(tmp_path):
    missing = tmp_path / "nope.json"
    try:
        load_cache(missing)
        assert False, "should have raised"
    except FileNotFoundError:
        pass
