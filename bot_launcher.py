"""Open the local menu and keep Telegram control running in the background."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import avito
import telegram_notify

ROOT = Path(__file__).resolve().parent
TASK_NAME = "AvitoParserBot"
_child: subprocess.Popen | None = None


def _has_windows_task() -> bool:
    return os.name == "nt" and subprocess.run(
        ["schtasks", "/Query", "/TN", TASK_NAME],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    ).returncode == 0


def start_bot(*, restart: bool = False) -> bool:
    """Start the configured server; reuse the Windows task when available."""
    global _child
    try:
        settings = telegram_notify.load_settings()
    except telegram_notify.TelegramError as exc:
        print(f"Telegram: ошибка настроек: {exc}")
        return False
    if not settings.get("token") or not settings.get("chat_id"):
        print("Telegram ещё не подключён. Откройте пункт Telegram в меню.")
        return False

    if _has_windows_task():
        if restart:
            subprocess.run(["schtasks", "/End", "/TN", TASK_NAME],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        result = subprocess.run(["schtasks", "/Run", "/TN", TASK_NAME],
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False)
        if result.returncode:
            print("Не удалось запустить задание Telegram-бота. Проверьте планировщик Windows.")
            return False
    else:
        if restart and _child is not None and _child.poll() is None:
            _child.terminate()
            try:
                _child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                print("Прежний сервер ещё завершает работу. Проверьте журнал data/bot-server.log.")
                return False
        options = {"creationflags": subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP} \
            if os.name == "nt" else {"start_new_session": True}
        try:
            _child = subprocess.Popen(
                [sys.executable, str(ROOT / "bot_server.py")], cwd=ROOT,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, **options,
            )
        except OSError as exc:
            print(f"Не удалось запустить Telegram-бота: {exc}")
            return False
    print("Telegram-бот запускается. Старое меню доступно ниже.")
    return True


def main() -> None:
    avito.use_utf8_output()
    start_bot()
    import menu

    menu.main()


if __name__ == "__main__":
    main()
