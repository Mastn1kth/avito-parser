"""Run long CLI actions without blocking Telegram polling."""

from __future__ import annotations

import json
import logging
import re
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent
WATCH_TARGETS = ROOT / "data" / "bot-watch-targets.json"


class Jobs:
    def __init__(self) -> None:
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.lock = threading.Lock()
        self.busy: set[str] = set()
        self.watch: subprocess.Popen | None = None
        self.watch_names: list[str] = []
        self.watch_log = None
        self.last_watch_error = ""

    def run(self, key: str, args: list[str], done: Callable[[dict], None]) -> bool:
        with self.lock:
            if key in self.busy:
                return False
            self.busy.add(key)

        def work() -> None:
            try:
                result = subprocess.run(
                    [sys.executable, "avito.py", "--json", *args], cwd=ROOT,
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800,
                )
                events = []
                for line in result.stdout.splitlines():
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
                outcome = {"ok": result.returncode == 0, "events": events,
                           "error": (result.stderr or "").strip()[-500:]}
            except (OSError, subprocess.TimeoutExpired) as exc:
                outcome = {"ok": False, "events": [], "error": str(exc)}
            finally:
                with self.lock:
                    self.busy.discard(key)
            try:
                done(outcome)
            except Exception:
                logging.exception("Job callback failed")

        self.pool.submit(work)
        return True

    def watch_running(self) -> bool:
        return self.watch is not None and self.watch.poll() is None

    def take_stopped_watch(self) -> str | None:
        """Return one notice when the watched process exits by itself."""
        with self.lock:
            if self.watch is None or self.watch.poll() is None:
                return None
            notice = (f"Наблюдение остановилось: {', '.join(self.watch_names)} "
                      f"(код {self.watch.returncode}). Подробности: data/bot-watch.log")
            self.watch = None
            self.watch_names = []
            if self.watch_log:
                self.watch_log.close()
                self.watch_log = None
            return notice

    def start_watch(self, names: list[str]) -> bool:
        with self.lock:
            self.last_watch_error = ""
            if self.watch_running():
                self.last_watch_error = "Наблюдение уже работает. Остановите его перед новым выбором."
                return False
            log_path = ROOT / "data" / "bot-watch.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            start_offset = log_path.stat().st_size if log_path.exists() else 0
            self.watch_log = log_path.open("a", encoding="utf-8")
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
            try:
                command = ([sys.executable, "iphone_mode.py"] if names == ["mode-iphones"] else
                           [sys.executable, "avito.py", "--json", "watch", *names])
                self.watch = subprocess.Popen(
                    command, cwd=ROOT,
                    stdout=self.watch_log, stderr=subprocess.STDOUT, creationflags=flags,
                )
            except OSError:
                self.watch_log.close()
                self.watch_log = None
                raise
            self.watch_names = names
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with log_path.open("r", encoding="utf-8", errors="replace") as reader:
                reader.seek(start_offset)
                lines = reader.readlines()
            for line in lines:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("event") == "WATCH":
                    WATCH_TARGETS.write_text(json.dumps(names), encoding="utf-8")
                    return True
                if event.get("event") == "FATAL":
                    self.last_watch_error = str(event.get("error") or "ошибка запуска")
                    self.stop_watch()
                    return False
            if not self.watch_running():
                self.last_watch_error = f"Наблюдение завершилось при запуске (код {self.watch.returncode})."
                self.stop_watch()
                return False
            time.sleep(0.1)
        self.last_watch_error = "Парсер не подтвердил запуск за 10 секунд. Проверьте журнал data/bot-watch.log."
        self.stop_watch()
        return False

    def stop_watch(self, *, preserve_selection: bool = False) -> bool:
        if not preserve_selection:
            WATCH_TARGETS.unlink(missing_ok=True)
        with self.lock:
            if not self.watch_running():
                self.watch_names = []
                if self.watch_log:
                    self.watch_log.close()
                    self.watch_log = None
                return False
            assert self.watch is not None
            try:
                if sys.platform == "win32":
                    self.watch.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    self.watch.send_signal(signal.SIGINT)
                self.watch.wait(timeout=10)
            except (OSError, subprocess.TimeoutExpired):
                if self.watch.poll() is None:
                    self.watch.terminate()
                    self.watch.wait(timeout=10)
            finally:
                self.watch_names = []
                self.watch = None
                if self.watch_log:
                    self.watch_log.close()
                    self.watch_log = None
            return True

    def resume_watch(self) -> bool:
        try:
            names = json.loads(WATCH_TARGETS.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        if not isinstance(names, list) or not names or not all(
            isinstance(name, str) and re.fullmatch(r"[a-z0-9_-]+", name)
            and (name == "mode-iphones" or (ROOT / "searches" / f"{name}.json").exists())
            for name in names
        ):
            return False
        if "mode-iphones" in names and names != ["mode-iphones"]:
            return False
        return self.start_watch(names)
