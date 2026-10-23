import pytest

import alert_queue
import telegram_notify


class Notifier:
    chat_id = 42

    def __init__(self, offline=False):
        self.offline = offline
        self.sent = []

    def send(self, text):
        if self.offline:
            raise telegram_notify.TelegramNetworkError("offline")
        self.sent.append(text)


def test_pending_alert_survives_restart_and_retries_once(tmp_path):
    path = tmp_path / "alerts.sqlite3"
    queue = alert_queue.AlertQueue(path)
    queue.enqueue("123", 42, "ПК 8 000 ₽")
    with pytest.raises(telegram_notify.TelegramNetworkError):
        queue.drain(Notifier(offline=True))
    assert queue.pending_count() == 1
    queue.close()
    queue = alert_queue.AlertQueue(path)
    notifier = Notifier()
    queue.drain(notifier)
    queue.enqueue("123", 42, "duplicate")
    queue.drain(notifier)
    assert notifier.sent == ["ПК 8 000 ₽"]
    assert queue.pending_count() == 0
    queue.close()


def test_recipient_change_does_not_leak_pending_alerts(tmp_path):
    queue = alert_queue.AlertQueue(tmp_path / "alerts.sqlite3")
    queue.enqueue("123", 7, "private alert")
    notifier = Notifier()
    queue.drain(notifier)
    assert notifier.sent == []
    assert queue.pending_count() == 1
    queue.close()
