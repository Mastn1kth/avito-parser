"""Standalone watch for newly listed phones across Russia."""

from pathlib import Path

import broad_mode

NAME = "mode-phones"
DIRECTORY = Path(__file__).resolve().parent / "data" / "phone-mode"


def status_text(running: bool) -> str:
    return broad_mode.status_text(running, feeds=broad_mode.PHONE_FEEDS,
                                  directory=DIRECTORY, title="Все новые: телефоны")


if __name__ == "__main__":
    broad_mode.run(feeds=broad_mode.PHONE_FEEDS, directory=DIRECTORY, name=NAME)
