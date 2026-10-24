import bot_server
import computer_mode
import laptop_mode
import telegram_notify
from test_bot_server import FakeJobs


def test_ready_modes_button_budget_discount_and_start(monkeypatch, tmp_path):
    monkeypatch.setattr(computer_mode, "DIRECTORY", tmp_path / "pc")
    monkeypatch.setattr(laptop_mode, "DIRECTORY", tmp_path / "laptop")
    sent = []
    monkeypatch.setattr(telegram_notify, "call", lambda token, method, payload=None: sent.append((method, payload)))
    jobs = FakeJobs()
    bot = bot_server.Bot("token", 42, jobs)

    def message(text, chat=42):
        bot.handle({"message": {"chat": {"id": chat}, "text": text}})

    def click(action, sender=42):
        bot.handle({"callback_query": {"id": "callback", "from": {"id": sender},
                                   "message": {"chat": {"id": 42}}, "data": action}})

    message("🚀 Готовые режимы")
    options = [row[0]["callback_data"] for row in sent[-1][1]["reply_markup"]["inline_keyboard"]]
    assert {"ready:pc:status", "ready:laptop:status"}.issubset(options)
    click("ready:pc:budget")
    message("9000", chat=7)
    assert computer_mode.settings()["max_price"] == 0
    message("9000")
    assert computer_mode.settings()["max_price"] == 9000
    click("ready:pc:discount:25")
    assert computer_mode.settings()["min_discount_pct"] == 25
    click("ready:laptop:budget")
    message("12000")
    assert laptop_mode.settings()["max_price"] == 12000
    click("ready:laptop:discount:15")
    assert laptop_mode.settings()["min_discount_pct"] == 15
    click("ready:pc:start", sender=7)
    assert jobs.started == []
    click("ready:pc:start")
    assert jobs.started == [("watch", [computer_mode.NAME])]


def test_ready_mode_start_preserves_existing_watch(monkeypatch, tmp_path):
    monkeypatch.setattr(computer_mode, "DIRECTORY", tmp_path)
    monkeypatch.setattr(telegram_notify, "call", lambda *args: None)
    jobs = FakeJobs()
    jobs.watch_running = lambda: True
    jobs.watch_names = ["phones"]
    bot = bot_server.Bot("token", 42, jobs)
    bot.ready_mode_action("pc:start")
    bot.ready_mode_action("pc:stop")
    assert jobs.started == []
    assert jobs.watch_names == ["phones"]
