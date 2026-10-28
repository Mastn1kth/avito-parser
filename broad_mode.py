"""One bounded feed for newly observed electronics across Russia."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import alert_queue
import apartments
import avito_client
import goods
import iphone_identity
import laptop_prices
import pc_prices
import telegram_notify
import watch_lock

ROOT = Path(__file__).resolve().parent
DIRECTORY = ROOT / "data" / "broad-mode"
NAME = "mode-broad"
INTERVAL_SECONDS = 180
PAGES_PER_FEED = 2
SAMPLE_LIMIT = 1000


@dataclass(frozen=True)
class Feed:
    key: str
    title: str
    category: str
    category_id: str | None = None
    query: str = ""

    @property
    def url(self) -> str:
        base = f"https://www.avito.ru/rossiya{self.category}"
        return base + ("?" + urlencode({"q": self.query}) if self.query else "")

    @property
    def params(self) -> dict[str, str]:
        result = {"locationId": "660311", "s": "104"}
        if self.category_id:
            result["categoryId"] = self.category_id
        if self.query:
            result["q"] = self.query
        return result


FEEDS = (
    Feed("phones", "Телефоны", "/telefony", "84"),
    Feed("laptops", "Ноутбуки", "/noutbuki", "98"),
    Feed("pcs", "Готовые ПК", "/nastolnye_kompyutery", "31"),
    Feed("components", "Комплектующие", "/tovary_dlya_kompyutera", "101"),
    Feed("components-gpu", "Видеокарты", "/tovary_dlya_kompyutera", "101", "видеокарта"),
    Feed("components-cpu", "Процессоры", "/tovary_dlya_kompyutera", "101", "процессор"),
    Feed("components-ram", "Оперативная память", "/tovary_dlya_kompyutera", "101", "оперативная память"),
    Feed("components-motherboard", "Материнские платы", "/tovary_dlya_kompyutera", "101", "материнская плата"),
    Feed("components-storage", "Накопители", "/tovary_dlya_kompyutera", "101", "SSD"),
    Feed("components-psu", "Блоки питания", "/tovary_dlya_kompyutera", "101", "блок питания"),
)


class SeenStore:
    """One ID registry prevents duplicate alerts from overlapping searches."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        with self.db:
            self.db.execute("CREATE TABLE IF NOT EXISTS seen (id TEXT PRIMARY KEY, first_seen REAL NOT NULL)")

    def contains(self, item_id: str) -> bool:
        return self.db.execute("SELECT 1 FROM seen WHERE id=?", (item_id,)).fetchone() is not None

    def add(self, item_id: str) -> None:
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO seen(id, first_seen) VALUES (?, ?)",
                            (item_id, time.time()))

    def close(self) -> None:
        self.db.close()


def _offer(item: dict, feed: Feed) -> goods.Offer:
    if feed.key == "pcs":
        offer = pc_prices.offer_from_item(item)
        offer.comparable = pc_prices.group_key(item) is not None
    else:
        offer = goods.offer_from_item(item)
        if feed.key == "phones":
            offer.comparable = iphone_identity.group_key(offer.listing.title) is not None
        elif feed.key.startswith("components"):
            offer.comparable = False
    return offer


def _references(base: dict[str, dict], feed: Feed):
    offers = [_offer(item, feed) for item in base.values()]
    if feed.key == "laptops":
        return laptop_prices.medians(offers)
    if feed.key in ("phones", "pcs"):
        return goods.market_stats(goods.market_sample(
            [offer for offer in offers if offer.comparable], private_only=False))
    return {}


def _fields(item: dict, feed: Feed, references: dict) -> dict:
    offer = _offer(item, feed)
    if not offer.defect and offer.comparable and feed.key in ("phones", "pcs"):
        goods.annotate([offer], references)
    fields = goods.alert_fields(offer)
    if feed.key == "laptops" and not offer.defect and offer.listing.price:
        key = laptop_prices.model_key(offer.listing.title)
        reference = references.get(key) if key else None
        if reference:
            price, median = offer.listing.price, reference.median
            fields.update(market=goods.price_text(median), market_value=median,
                          vs_market=f"{price / median - 1:+.0%}",
                          price_assessment=goods.price_comparison(price / median - 1),
                          discount_percent=(1 - price / median) * 100,
                          reference_count=reference.count)
    if offer.defect:
        fields["notes"].append("в описании есть признаки неисправности или некомплектности")
    return fields


def _digest_line(feed: Feed, fields: dict) -> str:
    title = telegram_notify.esc(str(fields["title"])[:95])
    url = telegram_notify.esc(fields["url"])
    price = telegram_notify.esc(fields["price"])
    assessment = (telegram_notify.esc(fields["price_assessment"])
                  if fields.get("reference_count") else "цену оценить нельзя")
    caution = " · ⚠️ состояние проверить" if fields.get("defective") else ""
    return f"{telegram_notify.esc(feed.title)} · <a href=\"{url}\">{title}</a>\n{price} · {assessment}{caution}"


def process_feed(client, feed: Feed, directory: Path, seen: SeenStore,
                 queue: alert_queue.AlertQueue, chat_id: int, status: dict) -> None:
    path = directory / "feeds" / f"{feed.key}.json"
    state = apartments.load_seen(path)
    base = state.get("items", {})
    initial = not state.get("primed")
    references = _references(base, feed)
    batch: dict[str, dict] = {}
    for number in range(1, PAGES_PER_FEED + 1):
        page = client.page(catalog_url=feed.url, params=feed.params, number=number)
        for item in page.items:
            batch[str(item["id"])] = item
        if page.is_last:
            break
    found = 0
    for item_id, item in batch.items():
        if not seen.contains(item_id):
            if not initial:
                queue.enqueue(item_id, chat_id, _digest_line(feed, _fields(item, feed, references)))
                found += 1
            seen.add(item_id)
        base[item_id] = item
    recent = sorted(base.items(), key=lambda entry: entry[1].get("sortTimeStamp") or 0,
                    reverse=True)[:SAMPLE_LIMIT]
    apartments.save_json(path, {"items": dict(recent), "primed": True})
    status.update(checked_at=time.time(), observed=len(batch), new=found,
                  primed=True, error=None)


def status_text(running: bool) -> str:
    state = apartments.load_seen(DIRECTORY / "status.json")
    rows = ["📡 Все новые: электроника · вся Россия", "Работает" if running else "Остановлен"]
    for feed in FEEDS:
        info = state.get("feeds", {}).get(feed.key, {})
        checked = info.get("checked_at")
        when = datetime.fromtimestamp(checked).strftime("%d.%m %H:%M") if checked else "ещё не проверено"
        suffix = f" · ошибка: {info['error']}" if info.get("error") else ""
        rows.append(f"{feed.title}: {when}; новых за обход: {info.get('new', 0)}{suffix}")
    rows.append(f"Ожидают отправки: {state.get('pending', 0)}")
    if state.get("current"):
        rows.append(f"Сейчас проверяется: {state['current']}")
    if state.get("delivery_error"):
        rows.append(f"Ошибка отправки: {state['delivery_error']}")
    rows.append("Первый обход запоминает текущую выдачу. Проверяются две первые страницы каждого направления; охват Авито неполный.")
    return "\n".join(rows)


def run() -> None:
    import avito

    avito.use_utf8_output()
    avito.JSON_OUTPUT = True
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    notifier = telegram_notify.Notifier.from_settings()
    if notifier is None:
        raise SystemExit("Сначала подключите Telegram-бота.")
    queue = alert_queue.AlertQueue(DIRECTORY / "pending-alerts.sqlite3")
    seen = SeenStore(DIRECTORY / "seen.sqlite3")
    state = apartments.load_seen(DIRECTORY / "status.json")
    state.setdefault("feeds", {})
    client = avito_client.CalmClient(log=avito.say)
    try:
        with watch_lock.watch_locks(avito.DATA_DIR, [NAME]):
            avito.say("WATCH", searches=[NAME], interval_s=INTERVAL_SECONDS, telegram=True)
            while True:
                for feed in FEEDS:
                    state["current"] = feed.title
                    apartments.save_json(DIRECTORY / "status.json", state)
                    info = state["feeds"].setdefault(feed.key, {})
                    try:
                        process_feed(client, feed, DIRECTORY, seen, queue, notifier.chat_id, info)
                    except (RuntimeError, ValueError, OSError, *avito_client.TRANSPORT_ERRORS) as exc:
                        info["error"] = f"{type(exc).__name__}: {exc}"[:180]
                        avito.say("ERROR", search=feed.key, error=info["error"])
                    state["pending"] = queue.pending_count()
                    apartments.save_json(DIRECTORY / "status.json", state)
                try:
                    for _ in range(10):
                        if not queue.drain_digest(notifier):
                            break
                except telegram_notify.TelegramError as exc:
                    state["delivery_error"] = str(exc)[:180]
                else:
                    state["delivery_error"] = None
                state["pending"] = queue.pending_count()
                state["current"] = None
                state["round_completed_at"] = time.time()
                apartments.save_json(DIRECTORY / "status.json", state)
                time.sleep(INTERVAL_SECONDS)
    except KeyboardInterrupt:
        pass
    finally:
        queue.close()
        seen.close()


if __name__ == "__main__":
    run()
