"""Behaviour of the ready laptop mode without live marketplace requests."""

import time
from types import SimpleNamespace

import pytest

import alert_queue
import avito_client
import laptop_mode as mode
from test_goods import phone


def item(ident, price, *, title="ThinkPad T480 i5-8250U 8/256 UHD 620"):
    value = phone(ident, price, title=title)
    value["sortTimeStamp"] = time.time() * 1000
    return value


def test_budget_and_discount_are_validated_and_persisted(monkeypatch, tmp_path):
    monkeypatch.setattr(mode, "DIRECTORY", tmp_path)
    assert mode.configure(max_price=20000, min_discount_pct=25) == {
        "max_price": 20000, "min_discount_pct": 25}
    assert mode.settings()["max_price"] == 20000
    with pytest.raises(ValueError):
        mode.configure(max_price=-1)
    with pytest.raises(ValueError):
        mode.configure(min_discount_pct=12)
    assert mode.settings()["min_discount_pct"] == 25


def test_first_pass_primes_and_only_matching_new_laptop_alerts(tmp_path):
    initial = [item(i, price) for i, price in enumerate((10000, 12000, 14000), 1)]
    batch = list(initial)
    client = SimpleNamespace(page=lambda **kw: avito_client.Page(1, tuple(batch), len(batch), 50))
    queue = alert_queue.AlertQueue(tmp_path / "alerts.sqlite3")
    notifier = SimpleNamespace(chat_id=42)
    status = {}
    config = {"max_price": 10000, "min_discount_pct": 25}
    mode.process_family(client, "ThinkPad", tmp_path, config, queue, notifier, status)
    assert queue.pending_count() == 0
    assert status["groups"] == 1
    batch[:] = [item(10, 9000), item(11, 8000, title="ThinkPad T480 i7-8650U 8/256 UHD 620"), *initial]
    mode.process_family(client, "ThinkPad", tmp_path, config, queue, notifier, status)
    assert queue.pending_count() == 1
    queue.close()


def test_failed_page_does_not_prime_family(tmp_path):
    queue = alert_queue.AlertQueue(tmp_path / "alerts.sqlite3")
    with pytest.raises(RuntimeError):
        mode.process_family(SimpleNamespace(page=lambda **kw: (_ for _ in ()).throw(RuntimeError("offline"))),
                            "ThinkPad", tmp_path, mode.settings(), queue, None, {})
    assert not (tmp_path / "families" / "thinkpad.json").exists()
    queue.close()
