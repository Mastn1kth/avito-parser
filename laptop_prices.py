"""Conservative laptop model matching for price comparisons."""

from __future__ import annotations

import re
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from goods import Offer

PRIVATE_SAMPLE = 3
ALL_SELLER_SAMPLE = 5
MAX_AGE_DAYS = 14
APPLE = re.compile(r"\bmacbook\s+(air|pro)\s+(1[3456])\b.*?\b(m[1-9](?:\s+(?:pro|max|ultra))?)\b", re.I)
NEO = re.compile(r"\bmacbook\s+neo\s+13\b", re.I)
MEMORY = re.compile(r"\b(\d{1,2})\s*(?:gb|гб)?\s*[/\\]\s*(\d{3,4})\s*(?:gb|гб)?\b", re.I)
SERIES = re.compile(
    r"\b(thinkpad|ideapad|vivobook|zenbook|latitude|inspiron|pavilion|elitebook|"
    r"probook|aspire|nitro|predator|legion|tuf|rog)\s+([a-z]?\d{3,4}[a-z0-9-]*)\b", re.I
)
CPU = re.compile(r"\b(?:core\s+)?(i[3579])[- ]?(\d{4,5}[a-z]{0,2})\b|\b(ryzen\s+[3579])\s+(\d{4}[a-z]{0,2})\b", re.I)
GRAPHICS = re.compile(r"\b(?:geforce\s+)?((?:rtx|gtx|mx)\s*\d{3,4}(?:\s*ti)?)\b|\b(uhd\s*\d{3}|iris\s+xe|встроенная\s+графика)\b", re.I)


def model_key(title: str) -> str | None:
    """Return a comparable model, or None when a title is too vague."""
    text = title.lower()
    neo = NEO.search(text)
    if neo:
        memory = MEMORY.search(text)
        return f"macbook neo 13 {memory[1]}/{memory[2]}" if memory else None
    apple = APPLE.search(text)
    if apple:
        memory = MEMORY.search(text)
        if memory:
            return f"macbook {apple[1]} {apple[2]} {apple[3].replace(' ', '')} {memory[1]}/{memory[2]}"
        return None
    series = SERIES.search(text)
    if series:
        cpu, memory, graphics = CPU.search(text), MEMORY.search(text), GRAPHICS.search(text)
        if not cpu or not memory or not graphics:
            return None
        processor = "".join(part.replace(" ", "") for part in cpu.groups() if part)
        gpu = re.sub(r"\s+", "", graphics[1] or graphics[2])
        return f"{series[1]} {series[2]} {processor} {memory[1]}/{memory[2]} {gpu}"
    return None


@dataclass(frozen=True)
class Reference:
    median: int
    count: int
    source: str


def _median(prices: list[int], minimum: int) -> Reference | None:
    if len(prices) < minimum:
        return None
    raw = statistics.median(prices)
    plausible = [price for price in prices if 0.5 * raw <= price <= 1.8 * raw]
    if len(plausible) < minimum:
        return None
    return Reference(round(statistics.median(plausible)), len(plausible), "")


def medians(offers: Iterable[Offer], *, now: float | None = None) -> dict[str, Reference]:
    private: dict[str, list[int]] = defaultdict(list)
    all_sellers: dict[str, list[int]] = defaultdict(list)
    now = time.time() if now is None else now
    for offer in offers:
        key = model_key(offer.listing.title)
        stamp = offer.listing.timestamp_ms
        if stamp and now - float(stamp) / 1000 > MAX_AGE_DAYS * 86400:
            continue
        if not key or not offer.listing.price or offer.defect:
            continue
        all_sellers[key].append(offer.listing.price)
        if offer.seller == "частное лицо" and (offer.listing.closed_listings or 0) < 100:
            private[key].append(offer.listing.price)
    result = {}
    for key, prices in all_sellers.items():
        reference = _median(private[key], PRIVATE_SAMPLE)
        if reference:
            result[key] = Reference(reference.median, reference.count, "частные продавцы")
            continue
        reference = _median(prices, ALL_SELLER_SAMPLE)
        if reference:
            result[key] = Reference(reference.median, reference.count, "все продавцы")
    return result
