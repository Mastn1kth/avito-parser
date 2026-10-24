import time
from types import SimpleNamespace

import alert_queue
import avito_client
import computer_mode as mode


def item(ident, price, title="Системный блок i5-10400 16 ГБ ОЗУ GTX 1660"):
    return {"id": ident, "title": title, "priceDetailed": {"value": price},
            "price": price, "sortTimeStamp": time.time() * 1000,
            "urlPath": "/moskva/nastolnye_kompyutery/test_" + str(ident)}


def test_partition_seeds_and_prices_only_matching_hardware(tmp_path, monkeypatch):
    import avito

    monkeypatch.setattr(avito, "is_fresh", lambda *args: True)
    sent = []
    monkeypatch.setattr(mode.telegram_notify, "goods_message", lambda title, fields, icon: sent.append(fields) or "message")
    batch = [item(i, price) for i, price in enumerate((10000, 12000, 14000), 1)]
    client = SimpleNamespace(page=lambda **kw: avito_client.Page(1, tuple(batch), len(batch), 50))
    queue = alert_queue.AlertQueue(tmp_path / "alerts.sqlite3")
    notifier = SimpleNamespace(chat_id=42)
    config = {"min_discount_pct": 15, "max_price": 10000}
    status = {}
    partition = ("intel-i5", "системный блок i5")
    mode.process_partition(client, partition, tmp_path, queue, notifier, status, config)
    assert queue.pending_count() == 0
    assert status["groups"] == 1
    batch[:] = [item(10, 9000), *batch]
    mode.process_partition(client, partition, tmp_path, queue, notifier, status, config)
    assert queue.pending_count() == 1
    assert sent[0]["market_value"] == 12000
    assert sent[0]["reference_count"] == 3
    assert sent[0]["discount_percent"] == 25
    assert status["deals"]
    monkeypatch.setattr(mode, "DIRECTORY", tmp_path)
    mode.save(tmp_path / "status.json", {"partitions": {"intel-i5": status}})
    assert "медиана: 11 000 ₽" in mode.deals_text()
    # GPU unspecified is never assigned a confident market price.
    assert not mode.offer(item(11, 5000, "ПК i5-10400 16 ГБ ОЗУ")).comparable
    queue.close()


def test_deals_ignore_stale_partition(tmp_path, monkeypatch):
    monkeypatch.setattr(mode, "DIRECTORY", tmp_path)
    mode.save(tmp_path / "status.json", {"partitions": {"old": {
        "checked_at": 1, "deals": [{"id": 1, "discount_percent": 30}]}}})
    assert "Пока нет" in mode.deals_text()


def test_failed_fetch_does_not_prime_partition(tmp_path):
    def fail(**kwargs):
        raise RuntimeError("offline")
    queue = alert_queue.AlertQueue(tmp_path / "alerts.sqlite3")
    try:
        try:
            mode.process_partition(SimpleNamespace(page=fail), mode.PARTITIONS[0], tmp_path,
                                   queue, None, {}, {"min_discount_pct": 0, "max_price": 0})
        except RuntimeError:
            pass
        else:
            assert False, "fetch should fail"
        assert not (tmp_path / "partitions" / "intel-i3.json").exists()
    finally:
        queue.close()
