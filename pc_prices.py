"""Conservative groups for comparing prices of assembled desktop PCs."""

from __future__ import annotations

import re
from typing import Any

import goods


INTEL = re.compile(r"\b(?:intel\s+)?(?:core\s+)?i([3579])[-\s]?(\d{3,5})(KF|F|K|T)?\b", re.I)
RYZEN = re.compile(r"\b(?:amd\s+)?ryzen\s+([3579])\s*(\d{4})[a-z]?\b", re.I)
GPU = re.compile(r"\b(?:geforce\s+|radeon\s+)?(gtx|rtx|gt|rx)\s*[- ]?(\d{3,4})\s*(ti|super)?\b", re.I)
RAM = re.compile(
    r"\b(?:озу|ram|оперативн\w*\s+памят\w*)\s*[:\-]?\s*(\d{1,2})\s*(?:гб|gb)?\b|"
    r"\b(\d{1,2})\s*(?:гб|gb)\s*(?:озу|ram|ddr[2345])\b",
    re.I,
)
PLAIN_MEMORY = re.compile(r"\b(\d{1,2})\s*(?:гб|gb)\b", re.I)
INTEGRATED = re.compile(r"встроенн\w*\s+(?:видео|график)|интегрир\w*\s+график", re.I)
INCOMPLETE = re.compile(
    r"на\s+запчаст|под\s+восстановл|не\s+рабоч|не\s+включ|"
    r"без\s+(?:диска|ssd|hdd|накопителя|блока\s+питания|процессора|озу|видеокарты)|"
    r"(?:диск|ssd|hdd|накопитель|блок\s+питания)\s+не\s+входит",
    re.I,
)


def group_key(item: dict[str, Any]) -> str | None:
    """Group stated CPU/RAM and keep named, integrated and unknown GPUs apart."""
    title = str(item.get("title") or "")
    if re.search(r"ноутбук|моноблок|планшет", title, re.I):
        return None
    details = f"{title} {item.get('description') or ''}"
    intel = INTEL.search(details)
    ryzen = RYZEN.search(details)
    if intel and len(intel[2]) >= 4:
        model = intel[2]
        generation = int(model[:-3])
        cpu = f"Core i{intel[1]}, поколение {generation}"
        if intel[3]:
            cpu += f", серия {intel[3].upper()}"
    elif ryzen:
        cpu = f"Ryzen {ryzen[1]}, серия {ryzen[2][0]}000"
    else:
        return None
    memory = RAM.search(details)
    if memory:
        ram = int(memory[1] or memory[2])
    else:
        # An unlabelled "8 GB" in a title is usable only when there is one
        # candidate and it is not the video card's memory.
        candidates = [match for match in PLAIN_MEMORY.finditer(title)
                      if not GPU.search(title[max(0, match.start() - 18):match.start()])]
        if len(candidates) != 1:
            return None
        ram = int(candidates[0][1])
    if ram < 2 or ram > 64:
        return None
    graphics = GPU.search(details)
    if graphics:
        gpu = f"{graphics[1].upper()} {graphics[2]}{(' ' + graphics[3].upper()) if graphics[3] else ''}"
    elif INTEGRATED.search(details):
        gpu = "встроенная графика"
    else:
        gpu = "видеокарта не указана"
    has_monitor = (re.search(r"\bмонитор\w*\b", title, re.I)
                   and not re.search(r"без\s+монитор\w*", title, re.I))
    bundle = "с монитором" if has_monitor else "без указанного монитора"
    return f"{cpu} · {ram} ГБ ОЗУ · {gpu} · {bundle}"


def incomplete(item: dict[str, Any]) -> bool:
    return bool(INCOMPLETE.search(f"{item.get('title') or ''} {item.get('description') or ''}"))


def offer_from_item(item: dict[str, Any]) -> goods.Offer:
    offer = goods.offer_from_item(item)
    key = group_key(item)
    offer.defect = offer.defect or incomplete(item)
    offer.model = "Некомплектный/неисправный ПК" if offer.defect else (key or "Недостаточно характеристик")
    offer.memory = ""
    return offer
