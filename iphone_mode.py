"""One Telegram mode backed by the iPhone model filters returned by Avito."""
from __future__ import annotations

import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import alert_queue
import apartments
import avito_client
import goods
import iphone_identity
import link_resolver
import telegram_notify
import watch_lock

ROOT = Path(__file__).resolve().parent
DIRECTORY = ROOT / "data" / "iphone-mode"
NAME = "mode-iphones"
URL = "https://www.avito.ru/rossiya/telefony?q=iPhone"
PARAMS = {"categoryId": "84", "locationId": "660311", "q": "iPhone", "s": "104"}
load = apartments.load_seen
save = apartments.save_json


def discover(client):
    payload = client.page_payload(catalog_url=URL, params=dict(PARAMS), number=1)
    filters = link_resolver.filters_of(payload)
    brand = next(((key, value) for key, f in filters.items()
                  for value, title in f.values.items() if title == "Apple"), None)
    if brand is None:
        raise ValueError("Авито не вернул фильтр производителя Apple")
    def parameter(key):
        return key + "[0]" if filters[key].type in link_resolver.MULTI_VALUE_TYPES else key
    base = {**PARAMS, parameter(brand[0]): brand[1]}
    candidates = [(key, value, title) for key, f in filters.items()
                  for value, title in f.values.items() if title.startswith("iPhone")]
    if not candidates:
        payload = client.page_payload(catalog_url=URL, params=base, number=1)
        filters = link_resolver.filters_of(payload)
        candidates = [(key, value, title) for key, f in filters.items()
                      for value, title in f.values.items() if title.startswith("iPhone")]
    if not candidates:
        raise ValueError("Авито не вернул список моделей iPhone")
    models = []
    for key, value, title in candidates:
        if not value.isdigit() or not re.fullmatch(r"params\[\d+\]", key):
            continue
        models.append({"id": value, "title": title, "params": {**base, "q": title, parameter(key): value}})
    if not models:
        raise ValueError("Некорректный список моделей Авито")
    return sorted(models, key=lambda m: m["title"].casefold())


def normalized(text):
    text = text.casefold().replace("айфон", "iphone").replace("про", "pro").replace("макс", "max")
    return re.sub(r"[^a-z0-9]+", "", text)


def offer(item, model, models):
    """Match the longest catalog model name, preventing 11/11 Pro crossover."""
    result = goods.offer_from_item(item)
    title = result.listing.title
    accessory = re.search(r"^\s*(?:чехол|стекло|дисплей|экран|аккумулятор|корпус|кабель|зарядка|плата)\b|для\s+(?:iphone|айфон)|\b(?:куплю|скупка|реплика|муляж)\b", title, re.I)
    if result.defect or accessory:
        return None
    text = normalized(title)
    matches = [m["title"] for m in models if normalized(m["title"]) in text]
    if not matches or max(matches, key=lambda m: len(normalized(m))) != model["title"]:
        return None
    capacities = {int(m[1]) * (1024 if m[2].lower() in ("tb", "тб") else 1)
                  for m in iphone_identity.STORAGE.finditer(title)}
    result.model = model["title"]
    result.memory = f"{next(iter(capacities))} ГБ" if len(capacities) == 1 else ""
    result.comparable = len(capacities) == 1 and next(iter(capacities)) in (4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048)
    return result


def analyze(base, model, models):
    offers = [value for item in base.values() if (value := offer(item, model, models)) is not None]
    return goods.market_stats(goods.market_sample(offers))


def settings():
    value = load(DIRECTORY / "settings.json").get("min_discount_pct", 0)
    return value if type(value) is int and value in (0, 15, 25) else 0


def set_discount(value):
    if type(value) is not int or value not in (0, 15, 25):
        raise ValueError("Допустимы 0, 15, 25")
    save(DIRECTORY / "settings.json", {"min_discount_pct": value})


def process_model(client, model, models, directory, threshold, queue, notifier, status):
    import avito

    path = directory / "models" / f"{model['id']}.json"
    state = load(path)
    base, seen = state.get("items", {}), state.get("seen", {})
    initial = not state.get("primed")
    stats = analyze(base, model, models)
    batch = {}
    # Two newest pages per model: bounded requests and no budget bias.
    for number in (1, 2):
        model_url = "https://www.avito.ru/rossiya/telefony?" + urlencode({"q": model["title"]})
        page = client.page(catalog_url=model_url, params=model["params"], number=number)
        for item in page.items:
            batch[str(item["id"])] = item
        if page.is_last:
            break
    now = time.time()
    for key, item in batch.items():
        if key not in seen and not initial:
            candidate = offer(item, model, models)
            if candidate and candidate.seller == "частное лицо" and (candidate.listing.closed_listings or 0) < goods.SHOP_CLOSED_LISTINGS:
                goods.annotate([candidate], stats)
                fields = goods.alert_fields(candidate)
                if avito.is_fresh(avito.listed_since(item), 3) and avito.discount_matches(fields, threshold):
                    if notifier is not None:
                        queue.enqueue(key, notifier.chat_id, telegram_notify.goods_message("Все iPhone", fields))
        seen[key] = now
        base[key] = item
    # Retain a bounded recent reference window; seen IDs stay for deduplication.
    base = {key: value for key, value in base.items() if now - seen.get(key, 0) < 14 * 86400}
    save(path, {"items": base, "seen": seen, "primed": True})
    stats = analyze(base, model, models)
    deals = []
    for item in batch.values():
        candidate = offer(item, model, models)
        if candidate is None or candidate.seller != "частное лицо" or (candidate.listing.closed_listings or 0) >= goods.SHOP_CLOSED_LISTINGS:
            continue
        goods.annotate([candidate], stats)
        fields = goods.alert_fields(candidate)
        if fields["discount_percent"] is not None and 0 < fields["discount_percent"] <= 50:
            deals.append(fields)
    status.update(title=model["title"], checked_at=now, items=len(base), groups=len(stats),
                  error=None, deals=sorted(deals, key=lambda d: d["discount_percent"], reverse=True)[:5])


def status_text(running):
    state = load(DIRECTORY / "status.json")
    models = state.get("models", {})
    checked = sum(bool(m.get("checked_at")) for m in models.values())
    errors = sum(bool(m.get("error")) for m in models.values())
    lines = ["📱 Все iPhone · вся Россия", "Работает" if running else "Остановлен",
             f"Моделей проверено: {checked}/{state.get('total', 0)}; с ошибками: {errors}",
             f"Текущая модель: {state.get('current') or '—'}",
             f"Позиция текущего обхода: {state.get('position', 0)}/{state.get('total', 0)}",
             f"Ожидают отправки: {state.get('pending', 0)}",
             f"Фильтр: {'все новые подходящие' if settings() == 0 else 'дешевле медианы на ' + str(settings()) + '%'}"]
    if state.get("error"):
        lines.append("Ошибка режима: " + state["error"])
    if state.get("delivery_error"):
        lines.append("Telegram: сообщение сохранено для повторной отправки")
    failed = [m.get("title", "модель") for m in models.values() if m.get("error")]
    if failed:
        lines.append("Не проверены из-за ошибок: " + ", ".join(failed[:10]))
    recent = max((m.get("checked_at", 0) for m in models.values()), default=0)
    if recent:
        lines.append("Последняя успешная проверка: " + datetime.fromtimestamp(recent).strftime("%d.%m %H:%M"))
    lines.append("Первый обход собирает базу. Полный охват всех объявлений Авито не гарантируется.")
    return "\n".join(lines)


def deals_text():
    state = load(DIRECTORY / "status.json")
    deals = {str(d["id"]): d for m in state.get("models", {}).values()
             if time.time() - m.get("checked_at", 0) < 86400 and not m.get("error")
             for d in m.get("deals", [])}
    best = sorted(deals.values(), key=lambda d: d["discount_percent"], reverse=True)[:10]
    if not best:
        return "Пока нет предложений с подтверждённой выборкой аналогов. Дождитесь обхода моделей."
    return "Последние найденные предложения; наличие проверьте по ссылке:\n\n" + "\n\n".join(
        f"{d['title']} — {d['price']}\n{d['price_assessment']}; аналогов: {d['reference_count']}\n{d['url']}" for d in best)


def coverage_text():
    state = load(DIRECTORY / "status.json")
    rows = []
    for model in state.get("models", {}).values():
        stamp = model.get("checked_at")
        result = ("ошибка запроса" if model.get("error") else
                  datetime.fromtimestamp(stamp).strftime("%d.%m %H:%M") + f", групп: {model.get('groups', 0)}"
                  if stamp else "ожидает обхода")
        rows.append(f"{model.get('title', 'Модель')}: {result}")
    return "Проверка моделей:\n" + ("\n".join(rows) or "Список ещё загружается. Запустите режим.")


def run():
    import avito

    avito.use_utf8_output()
    avito.JSON_OUTPUT = True
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    state = load(DIRECTORY / "status.json") or {"models": {}, "total": 0}
    state.update(current="получение списка моделей", position=0)
    notifier = telegram_notify.Notifier.from_settings()
    client = avito_client.CalmClient(delay=30, log=avito.say)
    with watch_lock.watch_locks(ROOT / "data" / "searches", [NAME]):
        queue = alert_queue.AlertQueue(DIRECTORY / "alerts.sqlite3")
        try:
            save(DIRECTORY / "status.json", state)
            avito.say("WATCH", searches=[NAME], interval_s=180, telegram=notifier is not None)
            models, refreshed = [], 0
            while True:
                if not models or time.time() - refreshed > 86400:
                    try:
                        models = discover(client)
                        refreshed = time.time()
                        state["error"] = None
                        state["total"] = len(models)
                        state["models"] = {m["id"]: {**state["models"].get(m["id"], {}), "title": m["title"]} for m in models}
                        save(DIRECTORY / "catalog.json", {"updated_at": refreshed, "models": models})
                    except (RuntimeError, ValueError, *avito_client.TRANSPORT_ERRORS) as exc:
                        state["error"] = str(exc)[:250]
                        save(DIRECTORY / "status.json", state)
                        time.sleep(180)
                        continue
                for position, model in enumerate(models, 1):
                    state["current"] = model["title"]
                    state["position"] = position
                    save(DIRECTORY / "status.json", state)
                    result = state["models"].setdefault(model["id"], {})
                    try:
                        process_model(client, model, models, DIRECTORY, settings(), queue, notifier, result)
                    except (RuntimeError, ValueError, *avito_client.TRANSPORT_ERRORS) as exc:
                        result.update(title=model["title"], error=str(exc)[:250])
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
