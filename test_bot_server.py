import json

import avito
import bot_server
import telegram_notify


class FakeJobs:
    watch_names = []
    busy = set()

    def __init__(self):
        self.started = []

    def run(self, key, args, done):
        self.started.append((key, args))
        return True

    def watch_running(self):
        return False

    def start_watch(self, names):
        self.started.append(("watch", names))
        return True

    def stop_watch(self):
        return False


def test_bot_rejects_other_chats_and_offers_presets(monkeypatch):
    sent = []
    monkeypatch.setattr(telegram_notify, "call", lambda token, method, payload=None: sent.append((method, payload)))
    jobs = FakeJobs()
    bot = bot_server.Bot("123:abc", 42, jobs)

    bot.handle({"message": {"chat": {"id": 7}, "text": "/presets"}})
    assert sent == []
    bot.handle({"message": {"chat": {"id": 42}, "text": "/presets"}})
    assert sent[-1][0] == "sendMessage"
    labels = [row[0]["text"] for row in sent[-1][1]["reply_markup"]["inline_keyboard"]]
    assert any("iPhone 11 Pro" in label for label in labels)
    assert any("компьютера" in label for label in labels)


def test_bot_watches_and_confirms_search_removal(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(telegram_notify, "call", lambda token, method, payload=None: sent.append((method, payload)))
    monkeypatch.setattr(avito, "SEARCHES_DIR", tmp_path)
    config = tmp_path / "phones.json"
    config.write_text(json.dumps({"title": "phones", "profile": "goods",
                                  "catalog_url": "https://www.avito.ru/rossiya/telefony",
                                  "params": {"categoryId": "84", "locationId": "660311"}}), encoding="utf-8")
    jobs = FakeJobs()
    bot = bot_server.Bot("123:abc", 42, jobs)

    bot.handle({"message": {"chat": {"id": 42}, "text": "/watch phones"}})
    assert jobs.started == [("watch", ["phones"])]
    bot.handle({"message": {"chat": {"id": 42}, "text": "/delete phones"}})
    assert config.exists()
    confirm = sent[-1][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    assert confirm.startswith("confirm:")
    bot.handle({"callback_query": {"id": "c1", "from": {"id": 42},
                                   "message": {"chat": {"id": 42}}, "data": confirm}})
    assert not config.exists()


def test_bot_selects_searches_and_rejects_stale_delete(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(telegram_notify, "call", lambda token, method, payload=None: sent.append((method, payload)))
    monkeypatch.setattr(avito, "SEARCHES_DIR", tmp_path)
    config = tmp_path / "phones.json"
    config.write_text(json.dumps({"title": "phones", "profile": "goods",
                                  "catalog_url": "https://www.avito.ru/rossiya/telefony",
                                  "params": {"categoryId": "84", "locationId": "660311"}}), encoding="utf-8")
    jobs = FakeJobs()
    bot = bot_server.Bot("123:abc", 42, jobs)
    for callback in ("toggle:phones", "watchselected"):
        bot.handle({"callback_query": {"id": callback, "from": {"id": 42},
                                       "message": {"chat": {"id": 42}}, "data": callback}})
    assert jobs.started == [("watch", ["phones"])]
    bot.handle({"callback_query": {"id": "stale", "from": {"id": 42},
                                   "message": {"chat": {"id": 42}}, "data": "confirm:phones"}})
    assert config.exists()


def test_bot_encodes_pasted_cyrillic_and_rejects_path_traversal(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(telegram_notify, "call", lambda token, method, payload=None: sent.append((method, payload)))
    monkeypatch.setattr(avito, "SEARCHES_DIR", tmp_path)
    jobs = FakeJobs()
    bot = bot_server.Bot("123:abc", 42, jobs)

    bot.execute("/add", "https://www.avito.ru/rossiya/telefony?q=айфон")
    assert "%D0%B0" in jobs.started[0][1][-1]
    bot.execute("/delete", "../outside")
    assert "Неверное имя" in sent[-1][1]["text"]


def test_main_keyboard_add_link_and_cancel(monkeypatch):
    sent = []
    monkeypatch.setattr(telegram_notify, "call", lambda token, method, payload=None: sent.append((method, payload)))
    jobs = FakeJobs()
    bot = bot_server.Bot("123:abc", 42, jobs)

    def say(text):
        bot.handle({"message": {"chat": {"id": 42}, "text": text}})

    say("/start")
    keyboard = sent[-1][1]["reply_markup"]["keyboard"]
    assert any(button["text"] == "➕ Добавить ссылку" for row in keyboard for button in row)
    say("➕ Добавить ссылку")
    assert bot.awaiting_link
    say("не ссылка")
    assert jobs.started == []
    say("🏠 Главное меню")
    assert not bot.awaiting_link
    say("➕ Добавить ссылку")
    say("https://www.avito.ru/rossiya/telefony?q=айфон")
    assert jobs.started[0][0] == "add"
    assert "%D0%B0" in jobs.started[0][1][-1]
