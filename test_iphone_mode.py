import time
from types import SimpleNamespace

import pytest

import alert_queue
import avito_client
import bot_server
import iphone_mode as mode
import telegram_notify
from test_bot_server import FakeJobs
from test_goods import phone


MODELS = [{"id": "1", "title": "iPhone 11 Pro", "params": {"model": "1"}},
          {"id": "2", "title": "iPhone 11 Pro Max", "params": {"model": "2"}},
          {"id": "3", "title": "iPhone SE (2020)", "params": {"model": "3"}}]


def item(ident, price, title="iPhone 11 Pro, 64 ГБ"):
    value = phone(ident, price, title=title)
    value["sortTimeStamp"] = time.time() * 1000
    return value


def test_catalog_all_models_uses_structured_model_and_apple_filters(monkeypatch):
    from link_resolver import Filter
    monkeypatch.setattr(mode.link_resolver, "filters_of", lambda _: {
        "params[1]": Filter("params[1]", "brand", "sectionedMultiselect", {"4": "Apple", "5": "Samsung"}),
        "params[2]": Filter("params[2]", "model", "sectionedMultiselect", {"10": "iPhone SE (2020)", "11": "iPhone Air"}),
    })
    found = mode.discover(SimpleNamespace(page_payload=lambda **kw: {}))
    assert len(found) == 2
    assert {m["params"]["params[2][0]"] for m in found} == {"10", "11"}
    assert all(m["params"]["params[1][0]"] == "4" for m in found)
    assert all(m["params"]["q"] == m["title"] for m in found)
    assert all("pmax" not in m["params"] for m in found)


def test_model_and_memory_and_generation_separation():
    assert mode.offer(item(1, 10000, "iPhone 11 Pro Max 64GB"), MODELS[0], MODELS) is None
    first = mode.offer(item(2, 10000), MODELS[0], MODELS)
    second = mode.offer(item(3, 12000, "iPhone 11 Pro 256GB"), MODELS[0], MODELS)
    assert first.group != second.group
    assert mode.offer(item(4, 1000, "Чехол для iPhone 11 Pro"), MODELS[0], MODELS) is None
    assert mode.offer(item(5, 10000, "iPhone SE (2020) 64GB"), MODELS[2], MODELS).comparable
    assert not mode.offer(item(6, 10000, "iPhone 11 Pro"), MODELS[0], MODELS).comparable


def test_first_pass_seeds_then_new_discount_alert_is_durable(tmp_path):
    initial = [item(i, price) for i, price in enumerate((10000, 12000, 14000), 1)]
    batch = list(initial)
    client = SimpleNamespace(page=lambda **kw: avito_client.Page(1, tuple(batch), len(batch), 50))
    queue = alert_queue.AlertQueue(tmp_path / "queue.sqlite3")
    notifier = SimpleNamespace(chat_id=42)
    status = {}
    mode.process_model(client, MODELS[0], MODELS, tmp_path, 25, queue, notifier, status)
    assert queue.pending_count() == 0
    assert status["groups"] == 1
    batch[:] = [item(10, 9000), *initial]
    mode.process_model(client, MODELS[0], MODELS, tmp_path, 25, queue, notifier, status)
    assert queue.pending_count() == 1
    mode.process_model(client, MODELS[0], MODELS, tmp_path, 25, queue, notifier, status)
    assert queue.pending_count() == 1
    sent = []
    queue.drain(SimpleNamespace(chat_id=42, send=sent.append))
    assert "25%" in sent[0] and "12 000" in sent[0]
    queue.close()


def test_failed_page_does_not_prime_model_or_lose_candidates(tmp_path):
    def failed(**kwargs):
        raise RuntimeError("offline")
    queue = alert_queue.AlertQueue(tmp_path / "queue.sqlite3")
    with pytest.raises(RuntimeError):
        mode.process_model(SimpleNamespace(page=failed), MODELS[0], MODELS, tmp_path, 0, queue, None, {})
    assert not (tmp_path / "models" / "1.json").exists()
    queue.close()


def test_telegram_mode_authorization_and_start(monkeypatch, tmp_path):
    monkeypatch.setattr(mode, "DIRECTORY", tmp_path)
    sent = []
    monkeypatch.setattr(telegram_notify, "call", lambda *args: sent.append(args))
    jobs = FakeJobs()
    bot = bot_server.Bot("test", 42, jobs)
    def click(action, sender=42):
        bot.handle({"callback_query": {"id": "x", "from": {"id": sender},
            "message": {"chat": {"id": 42}}, "data": "iphones:" + action}})
    click("start", 7)
    assert jobs.started == []
    click("discount:25")
    assert mode.settings() == 25
    click("start")
    assert jobs.started == [("watch", [mode.NAME])]


def test_status_and_deals_exclude_old_results(monkeypatch, tmp_path):
    monkeypatch.setattr(mode, "DIRECTORY", tmp_path)
    mode.save(tmp_path / "status.json", {"total": 2, "models": {
        "1": {"title": "iPhone", "checked_at": 1, "deals": [{"id": 1}]},
        "2": {"title": "iPhone 11", "error": "offline"}}})
    assert "1/2" in mode.status_text(False)
    assert "iPhone 11" in mode.status_text(False)
    assert "Пока нет" in mode.deals_text()
    assert "ошибка запроса" in mode.coverage_text()


def test_mode_start_does_not_interrupt_existing_watch(monkeypatch, tmp_path):
    monkeypatch.setattr(mode, "DIRECTORY", tmp_path)
    monkeypatch.setattr(telegram_notify, "call", lambda *args: None)
    jobs = FakeJobs()
    jobs.watch_running = lambda: True
    jobs.watch_names = ["my-existing-search"]
    bot = bot_server.Bot("test", 42, jobs)
    bot.iphone_mode_action("start")
    bot.iphone_mode_action("stop")
    assert jobs.started == []
    assert jobs.watch_names == ["my-existing-search"]
