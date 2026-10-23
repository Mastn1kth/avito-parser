from urllib.parse import parse_qs, urlsplit

import pytest

import bot_server
import telegram_notify
from test_bot_server import FakeJobs


class PreviewJobs(FakeJobs):
    def run(self, key, args, done):
        self.started.append((key, args))
        self.done = done
        return True


@pytest.fixture
def setup(monkeypatch):
    sent = []
    monkeypatch.setattr(telegram_notify, "call", lambda *args: sent.append(args))
    jobs = PreviewJobs()
    bot = bot_server.Bot("123:abc", 42, jobs)
    return bot, jobs, sent


def message(bot, text, chat=42):
    bot.handle({"message": {"chat": {"id": chat}, "text": text}})


def click(bot, value, sender=42):
    bot.handle({"callback_query": {"id": "button", "from": {"id": sender},
        "message": {"chat": {"id": 42}}, "data": "wizard:" + value}})


def preview(bot, category="iphone", query="11 Pro", city="Вся Россия"):
    message(bot, "➕ Добавить поиск")
    click(bot, category)
    message(bot, query)
    message(bot, "9 000")
    message(bot, city)


def success(jobs):
    jobs.done({"ok": True, "events": [{"event": "ADDED", "city": "Россия",
        "total": 123, "samples": ["Пример объявления"], "warnings": []}]})


@pytest.mark.parametrize("category,query,expected,profile", [
    ("iphone", "11 Pro", "iPhone 11 Pro", "goods"),
    ("pc", "-", "системный блок", "pc-prices"),
    ("laptop", "ThinkPad T480", "ThinkPad T480", "laptop-deals"),
    ("monitor", "Samsung", "монитор Samsung", "monitors"),
])
def test_preview_then_explicit_save(setup, category, query, expected, profile):
    bot, jobs, sent = setup
    preview(bot, category, query)
    args = jobs.started[0][1]
    assert "--dry-run" in args
    assert "--city" not in args
    assert args[args.index("--profile") + 1] == profile
    assert parse_qs(urlsplit(args[1]).query) == {"q": [expected], "pmax": ["9000"]}
    nonce = bot.wizard.state["nonce"]
    click(bot, "save:" + nonce)
    assert len(jobs.started) == 1
    success(jobs)
    assert "Пример объявления" in sent[-1][2]["text"]
    click(bot, "save:" + nonce)
    assert len(jobs.started) == 2
    assert "--dry-run" not in jobs.started[-1][1]
    click(bot, "save:" + nonce)
    assert len(jobs.started) == 2


def test_invalid_price_region_and_failed_preview(setup):
    bot, jobs, _ = setup
    message(bot, "/new")
    click(bot, "laptop")
    message(bot, "-")
    for price in ("0", "-10", "abc", "1000000001", "９０００"):
        message(bot, price)
        assert bot.wizard.state["step"] == "price"
    message(bot, "-")
    message(bot, "Казань")
    args = jobs.started[0][1]
    assert args[-3:] == ["--city", "Казань", "--dry-run"]
    assert "pmax" not in args[1]
    jobs.done({"ok": False, "events": []})
    assert bot.wizard.state["step"] == "city"


@pytest.mark.parametrize("cancel", ["cancel", "/start", "/add"])
def test_cancel_discards_late_preview(setup, cancel):
    bot, jobs, sent = setup
    preview(bot)
    if cancel.startswith("/"):
        message(bot, cancel)
    else:
        click(bot, cancel)
    count = len(sent)
    success(jobs)
    assert len(sent) == count
    assert bot.wizard.state is None


def test_other_users_and_stale_confirmation_cannot_save(setup):
    bot, jobs, _ = setup
    message(bot, "/new", chat=7)
    assert bot.wizard.state is None
    message(bot, "/new")
    click(bot, "iphone", sender=7)
    assert bot.wizard.state["step"] == "category"
    preview(bot)
    success(jobs)
    click(bot, "save:old-nonce")
    assert len(jobs.started) == 1
