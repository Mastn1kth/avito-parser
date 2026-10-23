import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

import market_reference as market


class Search:
    profile = "goods"
    catalog_url = "https://www.avito.ru/rossiya/telefony?q=iPhone&pmax=20000&pmin=1"

    def __init__(self, path):
        self.path = path
        self.request_params = {"q": "iPhone", "pmin": "1", "pmax": "20000", "s": "104", "locationId": "1"}

    def load(self, name):
        file = self.path / name
        return json.loads(file.read_text()) if file.exists() else {}

    def save(self, name, data):
        (self.path / name).write_text(json.dumps(data))


class Client:
    def __init__(self, last=False, fail=None):
        self.calls = []
        self.last = last
        self.fail = fail

    def page(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["number"] == self.fail:
            raise RuntimeError("network unavailable")
        return SimpleNamespace(items=[{"id": 1}, {"id": kwargs["number"] + 1}], is_last=self.last)


def test_unrestricted_sample_preserves_search_and_deduplicates(tmp_path):
    search, client = Search(tmp_path), Client()
    original = dict(search.request_params)
    assert set(market.refresh(client, search)) == {"1", "2", "3", "4"}
    assert len(client.calls) == 3
    assert search.request_params == original
    assert list(tmp_path.iterdir()) == [tmp_path / market.CACHE_FILE]
    for call in client.calls:
        assert call["params"] == {"q": "iPhone", "s": "104", "locationId": "1"}
        assert parse_qs(urlsplit(call["catalog_url"]).query) == {"q": ["iPhone"]}


def test_cache_expiry_and_changed_filters(tmp_path, monkeypatch):
    monkeypatch.setattr(market.time, "time", lambda: 100000)
    search, client = Search(tmp_path), Client(last=True)
    first = market.refresh(client, search)
    assert market.refresh(client, search) == first
    assert len(client.calls) == 1
    search.request_params["pmax"] = "10000"
    market.refresh(client, search)
    assert len(client.calls) == 1
    search.request_params["q"] = "Samsung"
    market.refresh(client, search)
    assert len(client.calls) == 2
    monkeypatch.setattr(market.time, "time", lambda: 100000 + market.TTL_SECONDS)
    market.refresh(client, search)
    assert len(client.calls) == 3


def test_failure_does_not_publish_partial_or_stale_sample(tmp_path, monkeypatch):
    search = Search(tmp_path)
    market.refresh(Client(last=True), search)
    before = search.load(market.CACHE_FILE)
    monkeypatch.setattr(market.time, "time", lambda: before["updated_at"] + market.TTL_SECONDS)
    with pytest.raises(RuntimeError):
        market.refresh(Client(fail=2), search)
    assert search.load(market.CACHE_FILE) == before


def test_unsupported_profile_skips_fetch(tmp_path):
    search, client = Search(tmp_path), Client()
    search.profile = "realty-owner"
    assert market.refresh(client, search) == {}
    assert not client.calls
