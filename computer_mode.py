"""Ready desktop PC watch: several bounded searches, one market per hardware group."""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import alert_queue
import apartments
import avito_client
import goods
import listing_quality
import pc_prices
import telegram_notify
import watch_lock

ROOT = Path(__file__).resolve().parent
DIRECTORY = ROOT / "data" / "computer-mode"
NAME = "mode-computers"
URL = "https://www.avito.ru/rossiya/nastolnye_kompyutery"
BASE_PARAMS = {"locationId": "660311", "s": "104"}
# Each query is a separate feed. These feeds overlap; one shared seen set avoids duplicates.
PARTITIONS = (
    ("intel-i3", "системный блок i3"),
    ("intel-i5", "системный блок i5"),
    ("intel-i7", "системный блок i7"),
    ("ryzen-3", "системный блок Ryzen 3"),
    ("ryzen-5", "системный блок Ryzen 5"),
    ("ryzen-7", "системный блок Ryzen 7"),
    ("gaming-gtx", "игровой компьютер GTX"),
    ("gaming-rtx", "игровой компьютер RTX"),
)
load = apartments.load_seen
save = apartments.save_json


def settings():
    raw = load(DIRECTORY / "settings.json")
    discount = raw.get("min_discount_pct", 0)
    budget = raw.get("max_price", 0)
    return {"min_discount_pct": discount if type(discount) is int and discount in (0, 15, 25) else 0,
            "max_price": budget if type(budget) is int and 0 <= budget <= 10_000_000 else 0}


def set_discount(value):
    if type(value) is not int or value not in (0, 15, 25):
        raise ValueError("Допустимы 0, 15, 25")
    save(DIRECTORY / "settings.json", {**settings(), "min_discount_pct": value})


def set_budget(value):
    if type(value) is not int or not 0 <= value <= 10_000_000:
        raise ValueError("Бюджет должен быть от 0 до 10 000 000 ₽")
    save(DIRECTORY / "settings.json", {**settings(), "max_price": value})


def offer(item):
    result = pc_prices.offer_from_item(item)
    key = pc_prices.group_key(item)
    # An unspecified graphics card can change the value dramatically.
    result.comparable = bool(key and "видеокарта не указана" not in key)
    return result


def eligible(candidate):
    return (not candidate.defect and candidate.seller == "частное лицо" and
            (candidate.listing.closed_listings or 0) < goods.SHOP_CLOSED_LISTINGS)


def analyze(items):
    offers = [offer(item) for item in items.values()]
    return goods.market_stats(goods.market_sample([candidate for candidate in offers
                                                  if eligible(candidate)]))


def process_partition(client, partition, directory, queue, notifier, status, config):
    import avito

    key, query = partition
    path = directory / "partitions" / f"{key}.json"
    state = load(path)
    global_path = directory / "seen.json"
    global_seen = load(global_path)
    base, seen = state.get("items", {}), state.get("seen", {})
    initial = not state.get("primed")
    stats = analyze(base)
    params = {**BASE_PARAMS, "q": query}  # No pmax: market reference must include full prices.
    url = URL + "?" + urlencode({"q": query})
    batch = {}
    for number in (1, 2):
        page = client.page(catalog_url=url, params=params, number=number)
        for item in page.items:
            batch[str(item["id"])] = item
        if page.is_last:
            break
    now = time.time()
    for item_id, item in batch.items():
        candidate = offer(item)
        if not initial and item_id not in seen and item_id not in global_seen and eligible(candidate):
            goods.annotate([candidate], stats)
            fields = goods.alert_fields(candidate)
            if not candidate.comparable:
                fields["market"] = None
                fields["vs_market"] = None
                fields["discount_percent"] = None
                fields["price_assessment"] = "цену оценить нельзя: не указаны процессор, ОЗУ или видеокарта"
                fields["notes"].append("уточните комплектацию у продавца")
            price = candidate.listing.price
            within_budget = not config["max_price"] or (price and price <= config["max_price"])
            fields = listing_quality.inspect(item, fields, "pc")
            if (within_budget and fields["quality_ok"] and avito.is_fresh(avito.listed_since(item), 3) and
                    avito.discount_matches(fields, config["min_discount_pct"])):
                if notifier is not None:
                    queue.enqueue(item_id, notifier.chat_id,
                                  telegram_notify.goods_message("Все компьютеры", fields, "🖥️"))
        seen[item_id] = now
        global_seen[item_id] = now
        base[item_id] = item
    base = {item_id: item for item_id, item in base.items()
            if now - seen.get(item_id, 0) < 14 * 86400}
    save(path, {"items": base, "seen": seen, "primed": True})
    save(global_path, global_seen)
    stats = analyze(base)
    deals = []
    for item in batch.values():
        candidate = offer(item)
        if not eligible(candidate) or not candidate.comparable:
            continue
        goods.annotate([candidate], stats)
        fields = listing_quality.inspect(item, goods.alert_fields(candidate), "pc")
        discount = fields.get("discount_percent")
        if fields["quality_ok"] and discount is not None and 0 < discount <= 50:
            deals.append(fields)
    status.update(title=query, checked_at=now, items=len(base), groups=len(stats), error=None,
                  deals=sorted(deals, key=lambda d: d["discount_percent"], reverse=True)[:5])


def status_text(running):
    state = load(DIRECTORY / "status.json")
    partitions = state.get("partitions", {})
    checked = sum(bool(p.get("checked_at")) for p in partitions.values())
    errors = [p.get("title", key) for key, p in partitions.items() if p.get("error")]
    config = settings()
    lines = ["🖥 Все компьютеры · вся Россия", "Работает" if running else "Остановлен",
             f"Направлений проверено: {checked}/{len(PARTITIONS)}; с ошибками: {len(errors)}",
             f"Текущее направление: {state.get('current') or '—'}",
             f"Обход: {state.get('position', 0)}/{len(PARTITIONS)}",
             f"Бюджет: {goods.price_text(config['max_price']) if config['max_price'] else 'без лимита'}",
             f"Скидка: {config['min_discount_pct']}%", f"Ожидают отправки: {state.get('pending', 0)}"]
    if errors:
        lines.append("Ошибки: " + ", ".join(errors))
    recent = max((p.get("checked_at", 0) for p in partitions.values()), default=0)
    if recent:
        lines.append("Последняя успешная проверка: " + datetime.fromtimestamp(recent).strftime("%d.%m %H:%M"))
    if state.get("delivery_error"):
        lines.append("Telegram: сообщение ждёт повторной отправки")
    lines.append("Первый обход собирает базу; полный охват Авито не гарантируется.")
    return "\n".join(lines)


def deals_text():
    state = load(DIRECTORY / "status.json")
    unique = {str(deal["id"]): deal for part in state.get("partitions", {}).values()
              if not part.get("error") and time.time() - part.get("checked_at", 0) < 86400
              for deal in part.get("deals", [])}
    best = sorted(unique.values(), key=lambda d: d["discount_percent"], reverse=True)[:10]
    if not best:
        return "Пока нет ПК с рассчитанной скидкой. Дождитесь обхода направлений."
    return "Последние предложения; наличие и комплектацию проверьте по ссылке:\n\n" + "\n\n".join(
        f"{d['title']} — {d['price']}\n{d['price_assessment']}; медиана: {d['market']}; "
        f"аналогов: {d['reference_count']}\n{d['url']}" for d in best)


def run():
    import avito

    avito.use_utf8_output()
    avito.JSON_OUTPUT = True
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    state = load(DIRECTORY / "status.json") or {"partitions": {}}
    notifier = telegram_notify.Notifier.from_settings()
    client = avito_client.CalmClient(delay=30, log=avito.say)
    with watch_lock.watch_locks(ROOT / "data" / "searches", [NAME]):
        queue = alert_queue.AlertQueue(DIRECTORY / "alerts.sqlite3")
        try:
            avito.say("WATCH", searches=[NAME], interval_s=180, telegram=notifier is not None)
            while True:
                for position, partition in enumerate(PARTITIONS, 1):
                    key, query = partition
                    state.update(current=query, position=position)
                    save(DIRECTORY / "status.json", state)
                    result = state["partitions"].setdefault(key, {})
                    try:
                        process_partition(client, partition, DIRECTORY, queue, notifier, result, settings())
                    except (RuntimeError, ValueError, *avito_client.TRANSPORT_ERRORS) as exc:
                        result.update(title=query, error=str(exc)[:250])
                    if notifier is not None:
                        try:
                            queue.drain(notifier)
                        except telegram_notify.TelegramError as exc:
                            state["delivery_error"] = str(exc)[:250]
                        else:
                            state["delivery_error"] = None
                    state["pending"] = queue.pending_count()
                    save(DIRECTORY / "status.json", state)
                state["round_completed_at"] = time.time()
                time.sleep(180)
        except KeyboardInterrupt:
            pass
        finally:
            queue.close()


if __name__ == "__main__":
    run()
