"""Run long CLI actions without blocking Telegram polling."""

from __future__ import annotations

import json
import logging
import signal
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent


class Jobs:
    def __init__(self) -> None:
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.lock = threading.Lock()
        self.busy: set[str] = set()
        self.watch: subprocess.Popen | None = None
        self.watch_names: list[str] = []
        self.watch_log = None

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

    def start_watch(self, names: list[str]) -> bool:
        with self.lock:
            if self.watch_running():
                return False
            log_path = ROOT / "data" / "bot-watch.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            self.watch_log = log_path.open("a", encoding="utf-8")
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
            try:
                self.watch = subprocess.Popen(
                    [sys.executable, "avito.py", "--json", "watch", *names], cwd=ROOT,
                    stdout=self.watch_log, stderr=subprocess.STDOUT, creationflags=flags,
                )
            except OSError:
                self.watch_log.close()
                self.watch_log = None
                raise
            self.watch_names = names
            return True

    def stop_watch(self) -> bool:
        with self.lock:
            if not self.watch_running():
                self.watch_names = []
                if self.watch_log:
                    self.watch_log.close()
                    self.watch_log = None
                return False
            assert self.watch is not None
            if sys.platform == "win32":
                self.watch.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self.watch.send_signal(signal.SIGINT)
            try:
                self.watch.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.watch.terminate()
                self.watch.wait(timeout=10)
            self.watch_names = []
            if self.watch_log:
                self.watch_log.close()
                self.watch_log = None
            return True
