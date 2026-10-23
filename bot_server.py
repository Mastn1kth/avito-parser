#!/usr/bin/env python3
"""Local Telegram control server for one configured chat."""

from __future__ import annotations

import logging
import json
import os
import re
import time
import secrets
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import avito
import bot_jobs
import bot_outbox
import presets
import search_wizard
import search_settings
import telegram_notify

ROOT = Path(__file__).resolve().parent
OFFSET_PATH = ROOT / "data" / "bot-offset.txt"
LOCK_PATH = ROOT / "data" / "bot-server.lock"
MENU_BUTTONS = {
    "➕ Добавить поиск": "/new",
    "🔎 Готовые поиски": "/presets",
    "📂 Мои поиски": "/searches",
    "✅ Выбрать для слежения": "/select",
    "➕ Добавить ссылку": "/add",
    "📡 Статус": "/status",
    "⏹ Остановить слежение": "/stop",
    "🏠 Главное меню": "/start",
}


def main_keyboard() -> dict:
    return {"keyboard": [
        [{"text": "➕ Добавить поиск"}],
        [{"text": "🔎 Готовые поиски"}, {"text": "📂 Мои поиски"}],
        [{"text": "✅ Выбрать для слежения"}, {"text": "➕ Добавить ссылку"}],
        [{"text": "📡 Статус"}, {"text": "⏹ Остановить слежение"}],
        [{"text": "🏠 Главное меню"}],
    ], "resize_keyboard": True, "is_persistent": True}


def buttons(rows: list[tuple[str, str]]) -> dict:
    return {"inline_keyboard": [[{"text": label, "callback_data": value}] for label, value in rows]}


def safe_url(url: str) -> str:
    """Percent-encode pasted Unicode without changing existing URL escapes."""
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme, parts.netloc, quote(parts.path, safe="/%"),
                       quote(parts.query, safe="=&%+/:?"), parts.fragment))


def single_instance_lock():
    """Keep an OS lock for the lifetime of this process; stale files are safe."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = LOCK_PATH.open("a+b")
    try:
        handle.seek(0)
        if not handle.read(1):
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise SystemExit("Telegram-сервер уже запущен. Используйте открытое окно сервера.") from None
    return handle


class Bot:
    def __init__(self, token: str, chat_id: int, jobs: bot_jobs.Jobs | None = None,
                 outbox: bot_outbox.Outbox | None = None) -> None:
        self.token = token
        self.chat_id = chat_id
        self.jobs = jobs or bot_jobs.Jobs()
        self.outbox = outbox
        self.selected: set[str] = set()
        self.pending_deletes: dict[str, str] = {}
        self.awaiting_link = False
        self.wizard = search_wizard.SearchWizard(self)

    def send(self, message: str, markup: dict | None = None) -> None:
        payload = {"chat_id": self.chat_id, "text": message[:3900]}
        if markup:
            payload["reply_markup"] = markup
        if self.outbox:
            self.outbox.enqueue("message", payload)
            self.outbox.drain(self.token)
        else:
            telegram_notify.call(self.token, "sendMessage", payload)

    def searches(self) -> None:
        items = sorted(avito.SEARCHES_DIR.glob("*.json"))
        if not items:
            self.send("Поисков пока нет. Откройте /presets или отправьте /add <ссылка Авито>.")
            return
        rows = [(self.search_title(path) or f"⚠️ {path.stem} (ошибка файла)",
                 f"search:{path.stem}") for path in items]
        rows.append(("🏠 Главное меню", "menu"))
        self.send("Мои поиски. Выберите один или запустите /watch имя1 имя2:", buttons(rows))

    def show_presets(self) -> None:
        self.send("Готовые поиски по всей России:",
                  buttons([(p.title, f"preset:{p.name}") for p in presets.PRESETS] +
                          [("🏠 Главное меню", "menu")]))

    def select_searches(self) -> None:
        names = [path.stem for path in sorted(avito.SEARCHES_DIR.glob("*.json"))]
        self.selected.intersection_update(names)
        if not names:
            self.send("Поисков пока нет. Откройте /presets.")
            return
        rows = [(f"{'✅' if name in self.selected else '▫️'} "
                 f"{self.search_title(avito.SEARCHES_DIR / f'{name}.json') or '⚠️ ' + name + ' (ошибка файла)'}",
                 f"toggle:{name}") for name in names]
        rows.append((f"▶ Следить за выбранными ({len(self.selected)})", "watchselected"))
        rows.append(("🏠 Главное меню", "menu"))
        self.send("Выберите поиски для наблюдения:", buttons(rows))

    def search_actions(self, name: str) -> None:
        if not re.fullmatch(r"[a-z0-9_-]+", name) or not (avito.SEARCHES_DIR / f"{name}.json").exists():
            self.send("Этот поиск уже удалён.")
            return
        title = self.search_title(avito.SEARCHES_DIR / f"{name}.json")
        if title is None:
            self.send(f"Поиск «{name}» повреждён. Можно удалить его конфигурацию; "
                      "собранные данные останутся на ПК.", buttons([
                          ("🗑 Удалить", f"delete:{name}"), ("📂 Мои поиски", "searches")
                      ]))
            return
        self.send(f"{title}\nИмя: {name}", buttons([
            ("▶ Следить", f"watch:{name}"), ("⟳ Собрать", f"scan:{name}"),
            ("📊 Таблица Excel", f"table:{name}"), ("🗑 Удалить", f"delete:{name}"),
            ("⚙️ Уведомления", f"alerts:{name}"),
            ("📂 Мои поиски", "searches"),
        ]))

    def notification_settings(self, name: str, percent: int | None = None) -> None:
        try:
            if percent is not None:
                if name in self.jobs.watch_names and self.jobs.watch_running():
                    self.send("Сначала остановите наблюдение через /stop, измените настройки и запустите его снова.")
                    return
                if self.jobs.busy:
                    self.send("Дождитесь завершения долгих операций, затем измените уведомления.")
                    return
                search_settings.set_discount(avito.SEARCHES_DIR, name, percent)
            config = search_settings.load(avito.SEARCHES_DIR, name)
        except (OSError, ValueError) as exc:
            self.send(f"Не удалось открыть настройки: {exc}")
            return
        current = config.get("min_discount_pct")
        label = ("по правилам категории" if current is None else
                 "все подходящие объявления" if current == 0 else f"дешевле медианы на {current}%")
        self.send(f"Уведомления: {config.get('title') or name}\nСейчас: {label}.\n"
                  "При пороге 15% или 25% объявления без надёжной оценки цены не присылаются.\n"
                  "Выбор «Все» сохраняет фильтры категории и состояния товара.", buttons([
                      ("Все подходящие", f"discount:0:{name}"),
                      ("Дешевле медианы на 15%", f"discount:15:{name}"),
                      ("Дешевле медианы на 25%", f"discount:25:{name}"),
                      ("Назад к поиску", f"search:{name}"),
                  ]))

    @staticmethod
    def search_title(path: Path) -> str | None:
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(config, dict) or not all(key in config for key in ("profile", "catalog_url", "params")):
                raise ValueError("missing search fields")
            return str(config.get("title") or path.stem)
        except (OSError, ValueError, TypeError):
            return None

    def start_job(self, key: str, args: list[str], kind: str) -> None:
        def finished(result: dict) -> None:
            try:
                events = result["events"]
                if not result["ok"]:
                    error = next((e.get("error") for e in reversed(events) if e.get("error")), None)
                    self.send(f"{kind}: ошибка — {error or result['error'] or 'команда завершилась с ошибкой'}")
                    return
                if kind == "Таблица":
                    table = next((e for e in reversed(events) if e.get("event") == "TABLE"), None)
                    if table:
                        if self.outbox:
                            self.outbox.enqueue("document", {"chat_id": self.chat_id, "path": table["path"]})
                            self.outbox.drain(self.token)
                        else:
                            telegram_notify.send_document(self.token, self.chat_id, Path(table["path"]))
                            self.send("Таблица отправлена.")
                    else:
                        self.send("Таблица не была создана.")
                elif kind == "Сбор":
                    pages = [e for e in events if e.get("event") == "PAGE"]
                    errors = [e for e in events if e.get("event") == "ERROR"]
                    self.send(f"Сбор завершён: страниц {len(pages)}." +
                              (f" Последняя ошибка: {errors[-1]['error']}" if errors else ""))
                else:
                    added = next((e for e in events if e.get("event") == "ADDED"), None)
                    self.send(f"Поиск добавлен: {added['name']} — {added['title']}" if added else "Поиск добавлен.")
            except (telegram_notify.TelegramError, OSError) as exc:
                logging.error("Job result delivery failed: %s", exc)

        if not self.jobs.run(key, args, finished):
            self.send("Эта операция уже выполняется.")
        else:
            self.send(f"{kind}: запущено. Результат пришлю сюда.")

    def execute(self, command: str, argument: str = "") -> None:
        if command in ("/start", "/help", "/add", "/new"):
            self.wizard.state = None
            self.awaiting_link = False
        if command in ("/start", "/help"):
            self.awaiting_link = False
            self.send("Управление поисками Авито. Выберите действие кнопкой внизу. "
                      "Свою ссылку можно прислать после кнопки «Добавить ссылку». "
                      "Команды /watch, /scan, /table и /delete тоже работают.", main_keyboard())
        elif command == "/new":
            self.wizard.start()
        elif command == "/presets":
            self.show_presets()
        elif command in ("/searches", "/list"):
            self.searches()
        elif command == "/select":
            self.select_searches()
        elif command == "/status":
            running = ", ".join(self.jobs.watch_names) if self.jobs.watch_running() else "не запущено"
            self.send(f"Наблюдение: {running}. Долгие операции: {', '.join(sorted(self.jobs.busy)) or 'нет'}.")
        elif command == "/test":
            self.send("✅ Telegram-бот отвечает.")
        elif command == "/stop":
            self.send("Наблюдение остановлено." if self.jobs.stop_watch() else "Наблюдение не запущено этим сервером.")
        elif command == "/add" and not argument:
            self.awaiting_link = True
            self.send("Пришлите ссылку на результаты поиска Авито одним сообщением. "
                      "Чтобы отменить, нажмите «Главное меню».")
        elif command == "/add" and argument:
            self.awaiting_link = False
            self.start_job("add", ["add", safe_url(argument)], "Добавление")
        elif command in ("/scan", "/table", "/delete") and argument:
            name = argument.strip()
            if not re.fullmatch(r"[a-z0-9_-]+", name):
                self.send("Неверное имя поиска. Выберите его через /searches.")
            elif not (avito.SEARCHES_DIR / f"{name}.json").exists():
                self.send("Такого поиска нет. Откройте /searches.")
            elif command == "/delete":
                nonce = secrets.token_urlsafe(8)
                self.pending_deletes[nonce] = name
                self.send(f"Удалить поиск «{name}»? Собранные данные останутся на ПК.",
                          buttons([("Да, удалить", f"confirm:{nonce}"), ("Отмена", f"cancel:{nonce}")]))
            elif name in self.jobs.watch_names and self.jobs.watch_running():
                self.send("Сначала остановите наблюдение через /stop, затем запустите эту операцию.")
            elif any(key.endswith(f":{name}") for key in self.jobs.busy):
                self.send("Дождитесь завершения другой операции с этим поиском.")
            else:
                self.start_job(f"{command}:{name}", [command[1:], name],
                               "Таблица" if command == "/table" else "Сбор")
        elif command == "/watch" and argument:
            names = argument.split()
            if any(not re.fullmatch(r"[a-z0-9_-]+", name) or
                   not (avito.SEARCHES_DIR / f"{name}.json").exists() for name in names):
                self.send("Один из поисков не найден. Откройте /searches.")
            elif any(any(key.endswith(f":{name}") for key in self.jobs.busy) for name in names):
                self.send("Сначала дождитесь завершения сбора этого поиска.")
            elif self.jobs.start_watch(names):
                self.send("Наблюдение запущено: " + ", ".join(names) +
                          ". Текущая выдача будет запомнена, уведомления — о новых объявлениях.")
            else:
                self.send(getattr(self.jobs, "last_watch_error", "") or "Наблюдение не запустилось.")
        else:
            self.send("Команда не распознана. Откройте /help.")

    def handle(self, update: dict) -> None:
        callback = update.get("callback_query")
        message = update.get("message") or {}
        source = callback.get("message") or {} if callback else message
        if int((source.get("chat") or {}).get("id", 0)) != self.chat_id:
            return
        if callback:
            if int((callback.get("from") or {}).get("id", 0)) != self.chat_id:
                return
            try:
                telegram_notify.call(self.token, "answerCallbackQuery", {"callback_query_id": callback["id"]})
            except telegram_notify.TelegramError:
                logging.warning("Could not acknowledge Telegram button; continuing action")
            action, _, name = str(callback.get("data") or "").partition(":")
            if action == "wizard":
                self.wizard.callback(name)
            elif action == "preset":
                preset = presets.get(name)
                if preset is None:
                    self.send("Шаблон не найден.")
                elif (avito.SEARCHES_DIR / f"{name}.json").exists():
                    self.send("Этот поиск уже есть в «Мои поиски».")
                else:
                    self.start_job("add", ["add", "--name", name, "--profile", preset.profile, preset.url], "Добавление")
            elif action == "alerts":
                self.notification_settings(name)
            elif action == "discount":
                percent, _, target = name.partition(":")
                if percent in ("0", "15", "25"):
                    self.notification_settings(target, int(percent))
                else:
                    self.send("Неверный порог уведомлений.")
            elif action == "search":
                self.search_actions(name)
            elif action == "searches":
                self.searches()
            elif action == "menu":
                self.execute("/start")
            elif action == "toggle" and re.fullmatch(r"[a-z0-9_-]+", name):
                if (avito.SEARCHES_DIR / f"{name}.json").exists():
                    self.selected.symmetric_difference_update({name})
                self.select_searches()
            elif action == "watchselected":
                if self.selected:
                    self.execute("/watch", " ".join(sorted(self.selected)))
                else:
                    self.send("Сначала выберите хотя бы один поиск через /select.")
            elif action in ("watch", "scan", "table", "delete"):
                self.execute("/" + action, name)
            elif action == "confirm":
                target = self.pending_deletes.pop(name, None)
                if target and (avito.SEARCHES_DIR / f"{target}.json").exists():
                    if target in self.jobs.watch_names and self.jobs.watch_running():
                        self.send("Сначала остановите наблюдение через /stop.")
                    elif any(key.endswith(f":{target}") for key in self.jobs.busy):
                        self.send("Дождитесь завершения операции с этим поиском.")
                    else:
                        (avito.SEARCHES_DIR / f"{target}.json").unlink()
                        self.selected.discard(target)
                        self.send(f"Поиск «{target}» удалён. Ранее собранные данные сохранены на ПК.")
                else:
                    self.send("Подтверждение устарело. Откройте /searches.")
            elif action == "cancel":
                self.pending_deletes.pop(name, None)
                self.send("Удаление отменено.")
            return
        text = str(message.get("text") or "").strip()
        if not text:
            return
        if text in MENU_BUTTONS:
            self.execute(MENU_BUTTONS[text])
            return
        if self.wizard.state and not text.startswith("/"):
            self.wizard.text(text)
            return
        if self.awaiting_link and not text.startswith("/"):
            if text.startswith(("https://", "http://")):
                self.execute("/add", text)
            else:
                self.send("Нужна ссылка, начинающаяся с https://www.avito.ru/. "
                          "Или нажмите «Главное меню» для отмены.")
            return
        command, _, argument = text.partition(" ")
        self.execute(command.split("@", 1)[0].lower(), argument.strip())


def main() -> None:
    lock = single_instance_lock()
    settings = telegram_notify.load_settings()
    if not settings.get("token") or not settings.get("chat_id"):
        raise SystemExit("Сначала выполните: python -m uv run python avito.py telegram setup")
    (ROOT / "data").mkdir(exist_ok=True)
    logging.basicConfig(filename=ROOT / "data" / "bot-server.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    bot = Bot(settings["token"], int(settings["chat_id"]),
              outbox=bot_outbox.Outbox(ROOT / "data" / "bot-outbox.json"))
    if (ROOT / "data" / "bot-watch-targets.json").exists() and not bot.jobs.resume_watch():
        logging.error("Could not resume watch: %s", bot.jobs.last_watch_error)
    offset = int(OFFSET_PATH.read_text(encoding="ascii")) if OFFSET_PATH.exists() else 0
    print("Telegram-сервер запущен. Остановить: Ctrl+C", flush=True)
    try:
        while True:
            try:
                bot.outbox.drain(bot.token)
                updates = telegram_notify.call(bot.token, "getUpdates", {"offset": offset, "timeout": 10})
                for update in updates or []:
                    try:
                        bot.handle(update)
                    except (telegram_notify.TelegramError, OSError, ValueError) as exc:
                        logging.error("Update failed: %s", exc)
                    offset = int(update["update_id"]) + 1
                    OFFSET_PATH.write_text(str(offset), encoding="ascii")
                stopped = bot.jobs.take_stopped_watch()
                if stopped:
                    bot.send(stopped)
            except telegram_notify.TelegramError as exc:
                logging.error("Polling failed: %s", exc)
                time.sleep(5)
    except KeyboardInterrupt:
        print("Telegram-сервер остановлен.", flush=True)
    finally:
        try:
            bot.jobs.stop_watch(preserve_selection=True)
        finally:
            lock.close()


if __name__ == "__main__":
    main()
