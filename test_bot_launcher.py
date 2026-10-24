import subprocess

import bot_launcher
import menu


def test_launcher_opens_menu_when_telegram_not_configured(monkeypatch):
    calls = []
    monkeypatch.setattr(bot_launcher, "start_bot", lambda: calls.append("server"))
    monkeypatch.setattr(menu, "main", lambda: calls.append("menu"))
    bot_launcher.main()
    assert calls == ["server", "menu"]


def test_existing_windows_task_is_reused(monkeypatch):
    commands = []
    monkeypatch.setattr(bot_launcher.telegram_notify, "load_settings",
                        lambda: {"token": "configured", "chat_id": 1})
    monkeypatch.setattr(bot_launcher, "_has_windows_task", lambda: True)

    def run(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(bot_launcher.subprocess, "run", run)
    assert bot_launcher.start_bot()
    assert commands == [["schtasks", "/Run", "/TN", "AvitoParserBot"]]


def test_reconfigure_restarts_existing_task(monkeypatch):
    commands = []
    monkeypatch.setattr(bot_launcher.telegram_notify, "load_settings",
                        lambda: {"token": "configured", "chat_id": 1})
    monkeypatch.setattr(bot_launcher, "_has_windows_task", lambda: True)

    def run(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(bot_launcher.subprocess, "run", run)
    assert bot_launcher.start_bot(restart=True)
    assert commands == [
        ["schtasks", "/End", "/TN", "AvitoParserBot"],
        ["schtasks", "/Run", "/TN", "AvitoParserBot"],
    ]


def test_menu_restarts_bot_after_successful_setup(monkeypatch):
    monkeypatch.setattr(menu, "choose", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(menu.telegram_notify.Notifier, "from_settings", lambda: None)
    monkeypatch.setattr(menu, "run", lambda *_args, **_kwargs: True)
    calls = []
    monkeypatch.setattr(bot_launcher, "start_bot", lambda **kwargs: calls.append(kwargs))
    menu.telegram_menu()
    assert calls == [{"restart": True}]
