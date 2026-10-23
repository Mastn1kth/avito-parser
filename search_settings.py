"""Validated, atomic edits of per-search notification preferences."""

import json
import os
import re
import tempfile
from pathlib import Path

SUPPORTED = {"goods", "pc-prices", "laptop-deals", "monitors"}
DISCOUNTS = (0, 15, 25)


def load(directory: Path, name: str) -> dict:
    if not re.fullmatch(r"[a-z0-9_-]+", name):
        raise ValueError("Неверное имя поиска.")
    config = json.loads((directory / f"{name}.json").read_text(encoding="utf-8"))
    if not isinstance(config, dict) or config.get("profile") not in SUPPORTED:
        raise ValueError("Для этого поиска настройка оценки цены не поддерживается.")
    return config


def set_discount(directory: Path, name: str, percent: int) -> None:
    if type(percent) is not int or percent not in DISCOUNTS:
        raise ValueError("Допустимые пороги: 0, 15 или 25 процентов.")
    config = load(directory, name)
    config["min_discount_pct"] = percent
    fd, temporary = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(config, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory / f"{name}.json")
    finally:
        Path(temporary).unlink(missing_ok=True)
