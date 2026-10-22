"""Persist Telegram control replies until the API accepts them."""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from pathlib import Path

import telegram_notify


class Outbox:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.Lock()
        self.sending = threading.Lock()
        try:
            self.pending = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self.pending = []
        if not isinstance(self.pending, list) or any(
            not isinstance(entry, dict) or not all(key in entry for key in ("id", "kind", "payload"))
            for entry in self.pending
        ):
            raise ValueError(f"неверный формат очереди Telegram: {path}")

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.pending, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, self.path)

    def enqueue(self, kind: str, payload: dict) -> None:
        with self.lock:
            self.pending.append({"id": uuid.uuid4().hex, "kind": kind, "payload": payload})
            try:
                self._save()
            except OSError:
                self.pending.pop()
                raise

    def drain(self, token: str) -> None:
        if not self.sending.acquire(blocking=False):
            return
        try:
            while True:
                with self.lock:
                    if not self.pending:
                        return
                    entry = self.pending[0]
                try:
                    if entry["kind"] == "message":
                        telegram_notify.call(token, "sendMessage", entry["payload"])
                    elif entry["kind"] == "document":
                        telegram_notify.send_document(
                            token, int(entry["payload"]["chat_id"]), Path(entry["payload"]["path"])
                        )
                    else:
                        raise ValueError(f"неверный тип сообщения в очереди: {entry['kind']}")
                except FileNotFoundError:
                    logging.error("Telegram document no longer exists: %s", entry["payload"].get("path"))
                    with self.lock:
                        self.pending[0] = {
                            "id": entry["id"], "kind": "message",
                            "payload": {"chat_id": entry["payload"]["chat_id"],
                                        "text": "Таблица не найдена на компьютере. Запустите сбор и запросите её снова."},
                        }
                        self._save()
                    continue
                except (telegram_notify.TelegramError, OSError) as exc:
                    logging.warning("Telegram reply queued for retry: %s", exc)
                    return
                with self.lock:
                    if self.pending and self.pending[0]["id"] == entry["id"]:
                        self.pending.pop(0)
                        self._save()
        finally:
            self.sending.release()
