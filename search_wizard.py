"""Telegram search creation with a live preview before saving."""

import secrets
from urllib.parse import urlencode

CATEGORIES = {
    "pc": ("Готовые ПК", "nastolnye_kompyutery", "pc-prices", "системный блок"),
    "laptop": ("Ноутбуки", "noutbuki", "laptop-deals", ""),
    "iphone": ("iPhone", "telefony", "goods", "iPhone"),
    "monitor": ("Мониторы", "tovary_dlya_kompyutera", "monitors", "монитор"),
}


class SearchWizard:
    def __init__(self, bot):
        self.bot = bot
        self.state = None

    def send(self, text, choices=()):
        rows = list(choices) + [("Отмена", "wizard:cancel")]
        self.bot.send(text, {"inline_keyboard": [[{"text": label, "callback_data": value}]
                                                  for label, value in rows]})

    def start(self):
        self.state = {"step": "category", "nonce": secrets.token_hex(6)}
        self.send("Выберите категорию или добавьте поиск по ссылке:",
                  [(v[0], "wizard:" + k) for k, v in CATEGORIES.items()] +
                  [("🔗 По ссылке", "wizard:link")])

    def callback(self, value):
        if value == "cancel":
            self.state = None
            self.bot.send("Создание поиска отменено.")
            return
        state = self.state
        if not state:
            self.bot.send("Этот шаг устарел. Нажмите «Добавить поиск».")
            return
        if value == "link" and state["step"] == "category":
            self.state = None
            self.bot.execute("/add")
            return
        if state["step"] == "category" and value in CATEGORIES:
            state.update(category=value, step="query")
            self.send("Что искать? Напишите модель или запрос. Отправьте «-», чтобы искать всю выбранную категорию.")
        elif value == "save:" + state["nonce"] and state["step"] == "ready":
            if "add" in self.bot.jobs.busy:
                self.send("Другое добавление ещё выполняется. Нажмите «Сохранить поиск» позже.",
                          [("Сохранить поиск", "wizard:save:" + state["nonce"])])
                return
            self.state = None
            self.bot.start_job("add", state["args"], "Добавление")

    def text(self, text):
        state = self.state
        if not state:
            return
        step = state["step"]
        if step == "query":
            if len(text) > 150:
                self.send("Запрос слишком длинный: максимум 150 символов.")
                return
            default = CATEGORIES[state["category"]][3]
            query = default if text == "-" else text
            if state["category"] == "iphone" and "iphone" not in query.casefold():
                query = "iPhone " + query
            if state["category"] == "monitor" and "монитор" not in query.casefold():
                query = "монитор " + query
            state.update(query=query, step="price")
            self.send("Максимальная цена в рублях? Например: 9000. Отправьте «-», если ограничения нет.")
        elif step == "price":
            value = text.replace(" ", "")
            if value != "-" and (not value.isascii() or not value.isdigit() or not 0 < int(value) <= 1000000000):
                self.send("Введите положительное число, например 9000, или «-».")
                return
            state.update(price=value, step="city")
            self.send("Напишите город или «Вся Россия».")
        elif step == "city":
            if len(text) > 100:
                self.send("Название региона слишком длинное.")
                return
            title, path, profile, _ = CATEGORIES[state["category"]]
            params = {"q": state["query"]} if state["query"] else {}
            if state["price"] != "-":
                params["pmax"] = state["price"]
            url = "https://www.avito.ru/rossiya/" + path
            if params:
                url += "?" + urlencode(params)
            args = ["add", url, "--name", "tg-" + state["nonce"], "--profile", profile]
            if text.casefold() not in ("вся россия", "россия", "-"):
                args += ["--city", text]
            state.update(args=args, step="checking")
            self.send("Проверяю поиск на Авито. Это может занять несколько минут.")

            def done(result):
                if self.state is not state:
                    return
                event = next((e for e in result["events"] if e.get("event") == "ADDED"), None)
                if not result["ok"] or not event:
                    state["step"] = "city"
                    self.send("Не удалось проверить поиск. Попробуйте другой город или повторите позже.")
                    return
                state["step"] = "ready"
                samples = "\n".join("• " + s for s in event.get("samples", [])[:5])
                summary = (f"{title}\nРегион: {event.get('city')}\n"
                           f"Запрос: {state['query'] or 'вся категория'}\n"
                           f"Цена до: {state['price'] if state['price'] != '-' else 'без ограничения'}\n"
                           f"Найдено: {event.get('total', 0)}\n{samples}")
                warnings = event.get("warnings", [])
                if warnings:
                    summary += "\n" + "\n".join(warnings)
                self.send(summary, [("Сохранить поиск", "wizard:save:" + state["nonce"])])

            if not self.bot.jobs.run("wizard-preview", args + ["--dry-run"], done):
                state["step"] = "city"
                self.send("Предыдущая проверка ещё выполняется. Повторите ввод региона позже.")
        else:
            self.send("Используйте кнопку текущего шага или отмените создание поиска.")
