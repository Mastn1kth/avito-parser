"""The broad feed keeps every newly observed listing and batches delivery."""

import json
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import alert_queue
import avito_client
import broad_mode
import telegram_notify


def item(ident, title, price):
    return {"id": ident, "title": title, "priceDetailed": {"value": price},
            "sortTimeStamp": 1_800_000_000_000,
            "urlPath": f"/moskva/telefony/test_{ident}"}


def test_component_feeds_replace_printers_with_focused_queries():
    focused = broad_mode.FEEDS[4:]
    assert {feed.key for feed in focused} == {
        "components-gpu", "components-cpu", "components-ram",
        "components-motherboard", "components-storage", "components-psu",
    }
    assert all(feed.category_id == "101" and feed.params["q"] == feed.query
               and parse_qs(urlsplit(feed.url).query)["q"] == [feed.query]
               for feed in focused)
    assert not any("принтер" in f"{feed.title} {feed.query}".lower()
                   for feed in broad_mode.FEEDS)


def test_first_pass_primes_then_new_listings_are_batched_without_duplicates(tmp_path):
    phones, components = broad_mode.FEEDS[0], broad_mode.FEEDS[3]
    phone_batch = [item(i, "iPhone 13, 128 ГБ", price)
                   for i, price in enumerate((20000, 22000, 24000), 1)]
    component_batch = [item(20, "Видеокарта GTX 1660", 10000)]

    def page(*, catalog_url, params, number):
        batch = phone_batch if catalog_url == phones.url else component_batch
        return avito_client.Page(number, tuple(batch), len(batch), len(batch))

    client = SimpleNamespace(page=page)
    queue = alert_queue.AlertQueue(tmp_path / "pending.sqlite3")
    seen = broad_mode.SeenStore(tmp_path / "seen.sqlite3")
    try:
        broad_mode.process_feed(client, phones, tmp_path, seen, queue, 42, {})
        broad_mode.process_feed(client, components, tmp_path, seen, queue, 42, {})
        assert queue.pending_count() == 0

        phone_batch[:] = [item(10, "iPhone 13, 128 ГБ", 17000)]
        component_batch[:] = [item(10, "iPhone 13, 128 ГБ", 17000),
                             item(21, "Видеокарта RTX 3060", 12000)]
        broad_mode.process_feed(client, phones, tmp_path, seen, queue, 42, {})
        broad_mode.process_feed(client, components, tmp_path, seen, queue, 42, {})
        assert queue.pending_count() == 2

        messages = []
        notifier = SimpleNamespace(chat_id=42, send=messages.append)
        assert queue.drain_digest(notifier) == 2
        assert queue.pending_count() == 0
        assert len(messages) == 1
        assert "на 23% дешевле медианы" in messages[0]
        assert "цену оценить нельзя" in messages[0]
        assert messages[0].count("iPhone 13") == 1
    finally:
        queue.close()
        seen.close()


def test_digest_remains_pending_after_send_failure(tmp_path):
    queue = alert_queue.AlertQueue(tmp_path / "pending.sqlite3")
    queue.enqueue("1", 42, "<b>Объявление</b>")

    def fail(_message):
        raise RuntimeError("offline")

    try:
        notifier = SimpleNamespace(chat_id=42, send=fail)
        try:
            queue.drain_digest(notifier)
        except RuntimeError:
            pass
        else:
            assert False, "send should fail"
        assert queue.pending_count() == 1
    finally:
        queue.close()


def test_saved_backlog_is_sent_before_a_new_scan(tmp_path):
    queue = alert_queue.AlertQueue(tmp_path / "pending.sqlite3")
    queue.enqueue("1", 42, "Первое объявление")
    sent = []
    state = {"feeds": {}}
    try:
        broad_mode.deliver_pending(queue, SimpleNamespace(chat_id=42, send=sent.append),
                                   state, tmp_path)
        assert len(sent) == 1
        assert "Первое объявление" in sent[0]
        assert queue.pending_count() == 0
        assert json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))["pending"] == 0
    finally:
        queue.close()


def test_delivery_error_keeps_backlog_for_next_feed(tmp_path):
    queue = alert_queue.AlertQueue(tmp_path / "pending.sqlite3")
    queue.enqueue("1", 42, "Первое объявление")

    def fail(_message):
        raise telegram_notify.TelegramNetworkError("offline")

    state = {"feeds": {}}
    try:
        broad_mode.deliver_pending(queue, SimpleNamespace(chat_id=42, send=fail),
                                   state, tmp_path)
        assert state["pending"] == 1
        assert "offline" in state["delivery_error"]
        assert queue.pending_count() == 1
    finally:
        queue.close()
