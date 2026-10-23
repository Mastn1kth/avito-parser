import json

import pytest

import avito
import bot_server
import search_settings
import telegram_notify
from test_bot_server import FakeJobs


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "phones.json"
    path.write_text(json.dumps({"profile": "goods", "params": {"q": "iPhone"},
                                "title": "Телефоны", "catalog_url": "https://www.avito.ru"}), encoding="utf-8")
    return path


def test_preserves_config_and_rejects_invalid_values(config):
    before = json.loads(config.read_text())
    search_settings.set_discount(config.parent, "phones", 15)
    assert json.loads(config.read_text(encoding="utf-8")) == dict(before, min_discount_pct=15)
    for name, value in [("../phones", 15), ("phones", 10), ("phones", True)]:
        with pytest.raises(ValueError):
            search_settings.set_discount(config.parent, name, value)
    assert not list(config.parent.glob("*.tmp"))


def test_replace_failure_keeps_original(config, monkeypatch):
    original = config.read_bytes()
    def fail(*args):
        raise OSError("disk unavailable")
    monkeypatch.setattr(search_settings.os, "replace", fail)
    with pytest.raises(OSError):
        search_settings.set_discount(config.parent, "phones", 25)
    assert config.read_bytes() == original
    assert not list(config.parent.glob("*.tmp"))


def test_unsupported_profile(config):
    config.write_text('{"profile": "realty-owner"}', encoding="utf-8")
    with pytest.raises(ValueError):
        search_settings.set_discount(config.parent, "phones", 0)


def test_callbacks_authorized_idle_only(config, monkeypatch):
    sent = []
    monkeypatch.setattr(avito, "SEARCHES_DIR", config.parent)
    monkeypatch.setattr(telegram_notify, "call", lambda *args: None)
    jobs = FakeJobs()
    jobs.busy = set()
    jobs.watch_names = []
    bot = bot_server.Bot("token", 42, jobs)
    monkeypatch.setattr(bot, "send", lambda text, markup=None: sent.append(text))
    def click(user=42):
        bot.handle({"callback_query": {"id": "x", "from": {"id": user},
                    "message": {"chat": {"id": 42}}, "data": "discount:25:phones"}})
    click(7)
    assert "min_discount_pct" not in search_settings.load(config.parent, "phones")
    jobs.busy = {"add"}
    click()
    assert "Дождитесь" in sent[-1]
    jobs.busy.clear()
    jobs.watch_names = ["phones"]
    monkeypatch.setattr(jobs, "watch_running", lambda: True)
    click()
    assert "/stop" in sent[-1]
    assert "min_discount_pct" not in search_settings.load(config.parent, "phones")
    jobs.watch_names = []
    click()
    assert search_settings.load(config.parent, "phones")["min_discount_pct"] == 25
    assert "25%" in sent[-1]
