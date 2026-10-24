"""One Telegram watch mode that searches laptop families separately."""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import alert_queue
import apartments
import avito_client
import goods
import laptop_prices
import listing_quality
import telegram_notify
import watch_lock

ROOT = Path(__file__).resolve().parent
DIRECTORY = ROOT / "data" / "laptop-mode"
NAME = "mode-laptops"
CATEGORY = "https://www.avito.ru/rossiya/noutbuki"
# Broad manufacturer/model families are split so one busy brand cannot hide others.
FAMILIES = (
    "MacBook Air", "MacBook Pro", "MacBook Neo", "ThinkPad", "IdeaPad",
    "VivoBook", "Zenbook", "Latitude", "Inspiron", "Pavilion",
    "EliteBook", "ProBook", "Aspire", "Nitro", "Predator", "Legion",
    "TUF", "ROG",
)
load = apartments.load_seen
save = apartments.save_json


def settings():
    raw = load(DIRECTORY / "settings.json")
    budget = raw.get("max_price", 0)
    discount = raw.get("min_discount_pct", 15)
    return {"max_price": budget if type(budget) is int and 0 <= budget <= 10_000_000 else 0,
            "min_discount_pct": discount if type(discount) is int and discount in (0, 15, 25) else 15}


def configure(*, max_price=None, min_discount_pct=None):
    current = settings()
    if max_price is not None:
        if type(max_price) is not int or not 0 <= max_price <= 10_000_000:
            raise ValueError("Бюджет должен быть от 0 до 10 000 000 ₽")
        current["max_price"] = max_price
    if min_discount_pct is not None:
        if type(min_discount_pct) is not int or min_discount_pct not in (0, 15, 25):
            raise ValueError("Допустимы скидки 0, 15, 25%")
        current["min_discount_pct"] = min_discount_pct
    save(DIRECTORY / "settings.json", current)
    return current


def _offer(item, family):
    offer = goods.offer_from_item(item)
    title = offer.listing.title.casefold()
    if family.casefold() not in title or offer.defect:
        return None
    return offer


def _fields(item, offer, references):
    fields = goods.alert_fields(offer)
    key = laptop_prices.model_key(offer.listing.title)
    reference = references.get(key) if key else None
    if reference and offer.listing.price:
        price, median = offer.listing.price, reference.median
        fields.update(market=goods.price_text(median), market_value=median,
                      vs_market=f"{price / median - 1:+.0%}",
                      price_assessment=goods.price_comparison(price / median - 1),
                      discount_percent=(1 - price / median) * 100,
                      reference_count=reference.count)
        fields["notes"].append(f"медиана: {reference.source}, {reference.count} объявлений")
    else:
        fields["notes"].append("цену оценить нельзя: нет точной комплектации или аналогов")
    return listing_quality.inspect(item, fields, "laptop")


def process_family(client, family, directory, config, queue, notifier, status):
    import avito

    path = directory / "families" / (family.casefold().replace(" ", "-") + ".json")
    state = load(path)
    base, seen = state.get("items", {}), state.get("seen", {})
    initial = not state.get("primed")
    offers = [goods.offer_from_item(item) for item in base.values()]
    references = laptop_prices.medians(offers)
    batch = {}
    params = {"q": family, "s": "104", "locationId": "660311"}
    url = CATEGORY + "?" + urlencode({"q": family})
    for number in (1, 2):
        page = client.page(catalog_url=url, params=params, number=number)
        for item in page.items:
            batch[str(item["id"])] = item
        if page.is_last:
            break
    now = time.time()
    deals = []
    for key, item in batch.items():
        offer = _offer(item, family)
        if offer and offer.seller == "частное лицо" and (offer.listing.closed_listings or 0) < goods.SHOP_CLOSED_LISTINGS:
            fields = _fields(item, offer, references)
            price = offer.listing.price
            within_budget = bool(price and (not config["max_price"] or price <= config["max_price"]))
            if within_budget and fields["quality_ok"]:
                if key not in seen and not initial and avito.is_fresh(avito.listed_since(item), 3):
                    if avito.discount_matches(fields, config["min_discount_pct"]) and notifier is not None:
                        queue.enqueue(key, notifier.chat_id, telegram_notify.goods_message("Все ноутбуки", fields))
                if fields["discount_percent"] is not None and 0 < fields["discount_percent"] <= 50:
                    deals.append(fields)
        seen[key], base[key] = now, item
    base = {key: value for key, value in base.items() if now - seen.get(key, 0) < 14 * 86400}
    save(path, {"items": base, "seen": seen, "primed": True})
    status.update(title=family, checked_at=now, items=len(base), groups=len(laptop_prices.medians(
        goods.offer_from_item(item) for item in base.values())), error=None,
        deals=sorted(deals, key=lambda d: d["discount_percent"], reverse=True)[:5])


def status_text(running):
    state, config = load(DIRECTORY / "status.json"), settings()
    families = state.get("families", {})
    checked = sum(bool(value.get("checked_at")) for value in families.values())
    errors = [value.get("title", "модель") for value in families.values() if value.get("error")]
    lines = ["💻 Все ноутбуки · вся Россия", "Работает" if running else "Остановлен",
             f"Семейств проверено: {checked}/{len(FAMILIES)}; с ошибками: {len(errors)}",
             f"Сейчас: {state.get('current') or '—'} ({state.get('position', 0)}/{len(FAMILIES)})",
             f"Бюджет: {goods.price_text(config['max_price']) if config['max_price'] else 'без ограничения'}",
             f"Уведомления: {'все новые подходящие' if not config['min_discount_pct'] else 'дешевле медианы на ' + str(config['min_discount_pct']) + '%'}",
             f"Ожидают отправки: {state.get('pending', 0)}"]
    if errors:
        lines.append("Ошибки: " + ", ".join(errors[:8]))
    if state.get("error"):
        lines.append("Ошибка: " + str(state["error"]))
    recent = max((value.get("checked_at", 0) for value in families.values()), default=0)
    if recent:
        lines.append("Последняя проверка: " + datetime.fromtimestamp(recent).strftime("%d.%m %H:%M"))
    lines.append("Первый обход собирает базу. Полный охват Авито не гарантируется.")
    return "\n".join(lines)


def deals_text():
    state = load(DIRECTORY / "status.json")
    deals = {str(d["id"]): d for family in state.get("families", {}).values()
             if time.time() - family.get("checked_at", 0) < 86400 and not family.get("error")
             for d in family.get("deals", [])}
    best = sorted(deals.values(), key=lambda d: d["discount_percent"], reverse=True)[:10]
    if not best:
        return "Пока нет ноутбуков с достаточной выборкой аналогов. Дождитесь обхода."
    return "Последние предложения; наличие проверьте по ссылке:\n\n" + "\n\n".join(
        f"{d['title']} — {d['price']}\n{d['price_assessment']}; аналогов: {d['reference_count']}\n{d['url']}" for d in best)


def run():
    import avito

    avito.use_utf8_output()
    avito.JSON_OUTPUT = True
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    state = load(DIRECTORY / "status.json") or {"families": {}}
    notifier = telegram_notify.Notifier.from_settings()
    client = avito_client.CalmClient(delay=30, log=avito.say)
    with watch_lock.watch_locks(ROOT / "data" / "searches", [NAME]):
        queue = alert_queue.AlertQueue(DIRECTORY / "alerts.sqlite3")
        try:
            avito.say("WATCH", searches=[NAME], interval_s=180, telegram=notifier is not None)
            while True:
                for position, family in enumerate(FAMILIES, 1):
                    state.update(current=family, position=position)
                    save(DIRECTORY / "status.json", state)
                    result = state["families"].setdefault(family, {})
                    try:
                        process_family(client, family, DIRECTORY, settings(), queue, notifier, result)
                    except (RuntimeError, ValueError, *avito_client.TRANSPORT_ERRORS) as exc:
                        result.update(title=family, error=str(exc)[:250])
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
