"""A closed Telegram connection must be retried instead of killing the bot."""

import http.client

import pytest

import telegram_notify


def test_remote_disconnect_is_retried(monkeypatch):
    attempts = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return b'{"ok": true, "result": {"id": 1}}'

    def urlopen(_request, *, timeout):
        attempts.append(timeout)
        if len(attempts) == 1:
            raise http.client.RemoteDisconnected("Remote end closed connection without response")
        return Response()

    monkeypatch.setattr(telegram_notify.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(telegram_notify.time, "sleep", lambda _: None)

    assert telegram_notify.call("123:abcdef", "getMe") == {"id": 1}
    assert len(attempts) == 2


@pytest.mark.parametrize("broken_body", [b'{"ok":', b'\xff', b'[]'])
def test_malformed_response_is_retried(monkeypatch, broken_body):
    attempts = []

    class Response:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def read(self):
            return self.body

    def urlopen(_request, *, timeout):
        attempts.append(timeout)
        return Response(broken_body if len(attempts) == 1 else b'{"ok": true, "result": {"id": 1}}')

    monkeypatch.setattr(telegram_notify.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(telegram_notify.time, "sleep", lambda _: None)

    assert telegram_notify.call("123:abcdef", "getMe") == {"id": 1}
    assert len(attempts) == 2
