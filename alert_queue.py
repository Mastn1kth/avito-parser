"""Durable per-search alerts; delivery is at least once across network failures."""

import sqlite3
import time
from pathlib import Path


class AlertQueue:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        with self.db:
            self.db.execute("CREATE TABLE IF NOT EXISTS alerts (id TEXT PRIMARY KEY, "
                            "chat_id INTEGER NOT NULL, text TEXT NOT NULL, created REAL NOT NULL, "
                            "delivered INTEGER NOT NULL DEFAULT 0)")

    def enqueue(self, item_id: str, chat_id: int, text: str):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO alerts(id, chat_id, text, created) VALUES (?, ?, ?, ?)",
                            (item_id, chat_id, text, time.time()))

    def drain(self, notifier, limit=20):
        # A changed Telegram recipient must not receive another recipient's backlog.
        rows = self.db.execute("SELECT id, text FROM alerts WHERE delivered=0 AND chat_id=? "
                               "ORDER BY created, id LIMIT ?", (notifier.chat_id, limit)).fetchall()
        for item_id, text in rows:
            notifier.send(text)
            with self.db:
                self.db.execute("UPDATE alerts SET delivered=1, text='' WHERE id=?", (item_id,))

    def pending_count(self):
        return self.db.execute("SELECT count(*) FROM alerts WHERE delivered=0").fetchone()[0]

    def close(self):
        self.db.close()
