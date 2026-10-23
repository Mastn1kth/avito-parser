import argparse
import json

import pytest

import avito
import avito_client
import alert_queue
import telegram_notify
from test_watch_alerts import listing


@pytest.mark.parametrize("reference_fails", [False, True])
@pytest.mark.parametrize("delivery_fails", [False, True])
def test_watch_uses_unbounded_reference_without_alerting_reference_items(monkeypatch, tmp_path, reference_fails, delivery_fails):
    monkeypatch.setattr(avito, "SEARCHES_DIR", tmp_path / "searches")
    monkeypatch.setattr(avito, "DATA_DIR", tmp_path / "data")
    avito.SEARCHES_DIR.mkdir()
    (avito.SEARCHES_DIR / "phones.json").write_text(json.dumps({
        "profile": "goods", "catalog_url": "https://www.avito.ru/rossiya/telefony?pmax=9000",
        "params": {"q": "iPhone 15", "pmax": "9000"}, "min_discount_pct": 25,
        "new_only": False,
    }), encoding="utf-8")
    events = []
    sent = []

    class Notifier:
        chat_id = 42

        def send(self, text):
            if delivery_fails:
                raise telegram_notify.TelegramNetworkError("offline")
            sent.append(text)

    monkeypatch.setattr(telegram_notify.Notifier, "from_settings", lambda: Notifier())
    reference = []
    for ident, price in enumerate((10000, 12000, 14000), 100):
        item = listing(ident, 10)
        item["priceDetailed"]["value"] = price
        reference.append(item)
    candidate = listing(2, 1)
    candidate["priceDetailed"]["value"] = 9000

    class Client:
        sessions_opened = 1
        cycles = 0

        def __init__(self, **kwargs):
            pass

        def page(self, *, catalog_url, params, number):
            if "pmax" not in params:
                assert "pmax" not in catalog_url
                if reference_fails:
                    raise RuntimeError("reference unavailable")
                items = reference
            else:
                self.cycles += 1
                items = [] if self.cycles == 1 else [candidate]
            return avito_client.Page(number=number, items=tuple(items), total_count=len(items), items_on_page=50)

    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise KeyboardInterrupt

    monkeypatch.setattr(avito.avito_client, "CalmClient", Client)
    monkeypatch.setattr(avito.time, "sleep", sleep)
    monkeypatch.setattr(avito, "say", lambda event, **fields: events.append({"event": event, **fields}))
    avito.cmd_watch(argparse.Namespace(names=["phones"], interval=60, delay=0, no_telegram=False))
    alerts = [e for e in events if e["event"] == "ALERT"]
    if reference_fails:
        assert alerts == []
    else:
        assert len(alerts) == 1
        assert alerts[0]["id"] == 2
        assert alerts[0]["market_value"] == 12000
        assert alerts[0]["discount_percent"] == 25
    seen = json.loads((avito.DATA_DIR / "phones" / "seen.json").read_text(encoding="utf-8"))
    assert set(seen) == {"2"}
    queue = alert_queue.AlertQueue(avito.DATA_DIR / "phones" / "pending-alerts.sqlite3")
    assert queue.pending_count() == int(delivery_fails and not reference_fails)
    delivery_fails = False
    queue.drain(Notifier())
    assert len(sent) == (0 if reference_fails else 1)
    assert queue.pending_count() == 0
    queue.close()
