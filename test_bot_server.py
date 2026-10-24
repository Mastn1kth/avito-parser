import json

import pytest

import avito
import bot_outbox
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
    assert any(button["text"] == "➕ Добавить поиск" for row in keyboard for button in row)
    say("➕ Добавить поиск")
    bot.handle({"callback_query": {"id": "link", "from": {"id": 42},
                                   "message": {"chat": {"id": 42}}, "data": "wizard:link"}})
    assert bot.awaiting_link
    say("не ссылка")
    assert jobs.started == []
    say("🏠 Главное меню")
    assert not bot.awaiting_link
    # Text from an older Telegram keyboard still works after the menu update.
    say("➕ Добавить ссылку")
    say("https://www.avito.ru/rossiya/telefony?q=айфон")
    assert jobs.started[0][0] == "add"
    assert "%D0%B0" in jobs.started[0][1][-1]


def test_compact_keyboard_keeps_search_and_watch_actions_reachable(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(telegram_notify, "call", lambda token, method, payload=None: sent.append((method, payload)))
    monkeypatch.setattr(avito, "SEARCHES_DIR", tmp_path)
    (tmp_path / "phones.json").write_text(json.dumps({
        "title": "phones", "profile": "goods",
        "catalog_url": "https://www.avito.ru/rossiya/telefony",
        "params": {"categoryId": "84", "locationId": "660311"},
    }), encoding="utf-8")
    bot = bot_server.Bot("123:abc", 42, FakeJobs())

    def click(action):
        bot.handle({"callback_query": {"id": action, "from": {"id": 42},
                                       "message": {"chat": {"id": 42}}, "data": action}})

    bot.execute("/start")
    labels = [button["text"] for row in sent[-1][1]["reply_markup"]["keyboard"] for button in row]
    assert labels == ["🚀 Готовые режимы", "📂 Мои поиски", "➕ Добавить поиск",
                      "📡 Наблюдение", "🏠 Главное меню"]

    bot.handle({"message": {"chat": {"id": 42}, "text": "📂 Мои поиски"}})
    actions = [row[0]["callback_data"] for row in sent[-1][1]["reply_markup"]["inline_keyboard"]]
    assert {"search:phones", "select", "presets"}.issubset(actions)
    click("presets")
    assert "Готовые поиски" in sent[-1][1]["text"]
    click("select")
    assert "Выберите поиски" in sent[-1][1]["text"]

    bot.handle({"message": {"chat": {"id": 42}, "text": "➕ Добавить поиск"}})
    actions = [row[0]["callback_data"] for row in sent[-1][1]["reply_markup"]["inline_keyboard"]]
    assert "wizard:link" in actions
    click("wizard:link")
    assert bot.awaiting_link and bot.wizard.state is None

    bot.handle({"message": {"chat": {"id": 42}, "text": "📡 Наблюдение"}})
    assert not bot.awaiting_link
    actions = [row[0]["callback_data"] for row in sent[-1][1]["reply_markup"]["inline_keyboard"]]
    assert {"select", "searches"}.issubset(actions)
    assert "stop" not in actions
    bot.jobs.watch_names = ["phones"]
    bot.jobs.watch_running = lambda: True
    bot.execute("/status")
    actions = [row[0]["callback_data"] for row in sent[-1][1]["reply_markup"]["inline_keyboard"]]
    assert "stop" in actions
    click("stop")
    assert "Наблюдение не запущено" in sent[-1][1]["text"]


def test_second_bot_server_cannot_take_lock(monkeypatch, tmp_path):
    monkeypatch.setattr(bot_server, "LOCK_PATH", tmp_path / "server.lock")
    first = bot_server.single_instance_lock()
    try:
        with pytest.raises(SystemExit, match="уже запущен"):
            bot_server.single_instance_lock()
    finally:
        first.close()
    second = bot_server.single_instance_lock()
    second.close()


def test_corrupt_search_does_not_crash_button_menu(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(telegram_notify, "call", lambda token, method, payload=None: sent.append((method, payload)))
    monkeypatch.setattr(avito, "SEARCHES_DIR", tmp_path)
    (tmp_path / "broken.json").write_text("{bad", encoding="utf-8")
    bot = bot_server.Bot("123:abc", 42, FakeJobs())

    bot.execute("/searches")
    assert "ошибка файла" in sent[-1][1]["reply_markup"]["inline_keyboard"][0][0]["text"]
    bot.search_actions("broken")
    assert "повреждён" in sent[-1][1]["text"]


def test_bot_queues_button_menu_when_telegram_is_offline(monkeypatch, tmp_path):
    def offline(token, method, payload=None):
        raise telegram_notify.TelegramNetworkError("offline")

    monkeypatch.setattr(telegram_notify, "call", offline)
    outbox = bot_outbox.Outbox(tmp_path / "outbox.json")
    bot = bot_server.Bot("123:abc", 42, FakeJobs(), outbox=outbox)
    bot.handle({"message": {"chat": {"id": 42}, "text": "/start"}})
    assert len(bot_outbox.Outbox(outbox.path).pending) == 1

    delivered = []
    monkeypatch.setattr(telegram_notify, "call", lambda token, method, payload=None: delivered.append(payload))
    outbox.drain("123:abc")
    assert delivered[0]["reply_markup"]["keyboard"]


def test_table_button_sends_generated_workbook(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(telegram_notify, "call", lambda token, method, payload=None: sent.append(method))
    monkeypatch.setattr(telegram_notify, "send_document",
                        lambda token, chat_id, path: sent.append((chat_id, path.name)))
    monkeypatch.setattr(avito, "SEARCHES_DIR", tmp_path)
    (tmp_path / "phones.json").write_text(json.dumps({
        "title": "phones", "profile": "goods", "catalog_url": "https://www.avito.ru/rossiya/telefony",
        "params": {"categoryId": "84", "locationId": "660311"},
    }), encoding="utf-8")
    workbook = tmp_path / "phones.xlsx"
    workbook.write_bytes(b"test")

    class CompletingJobs(FakeJobs):
        def run(self, key, args, done):
            done({"ok": True, "events": [{"event": "TABLE", "path": str(workbook)}], "error": ""})
            return True

    bot = bot_server.Bot("123:abc", 42, CompletingJobs())
    bot.execute("/table", "phones")
    assert (42, "phones.xlsx") in sent
