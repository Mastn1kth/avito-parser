import bot_outbox
import telegram_notify


def test_reply_survives_network_failure_and_process_restart(monkeypatch, tmp_path):
    path = tmp_path / "outbox.json"
    sent = []

    def unavailable(token, method, payload):
        raise telegram_notify.TelegramNetworkError("offline")

    monkeypatch.setattr(telegram_notify, "call", unavailable)
    first = bot_outbox.Outbox(path)
    first.enqueue("message", {"chat_id": 42, "text": "Готово"})
    first.drain("123:abc")
    assert len(first.pending) == 1

    monkeypatch.setattr(telegram_notify, "call", lambda token, method, payload: sent.append(payload["text"]))
    restarted = bot_outbox.Outbox(path)
    restarted.drain("123:abc")
    assert sent == ["Готово"]
    assert bot_outbox.Outbox(path).pending == []


def test_missing_document_does_not_block_later_replies(monkeypatch, tmp_path):
    sent = []
    monkeypatch.setattr(telegram_notify, "call", lambda token, method, payload: sent.append(payload["text"]))
    monkeypatch.setattr(telegram_notify, "send_document", lambda token, chat_id, path: path.read_bytes())
    outbox = bot_outbox.Outbox(tmp_path / "outbox.json")
    outbox.enqueue("document", {"chat_id": 42, "path": str(tmp_path / "missing.xlsx")})
    outbox.enqueue("message", {"chat_id": 42, "text": "Следующее сообщение"})

    outbox.drain("123:abc")
    assert sent == ["Таблица не найдена на компьютере. Запустите сбор и запросите её снова.",
                    "Следующее сообщение"]
    assert outbox.pending == []
