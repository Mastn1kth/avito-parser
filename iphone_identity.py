"""Conservative title identities for comparable iPhone price samples.

Only explicitly named model and storage are usable. Unknown or ambiguous
titles return None rather than pooling different devices.
"""

import re


MODEL = re.compile(
    r"\b(?:iphone|айфон)\s*(?P<generation>1[0-7]|[4-9]|xs|xr|x|se)"
    r"(?P<suffix>\s*(?:pro\s*max|про\s*макс|pro|про|plus|плюс|mini|мини|s\s*plus|s|max|макс))?"
    r"(?=$|[\s,;/()\-]|\d{2,4}\s*(?:gb|гб|tb|тб))", re.I,
)
STORAGE = re.compile(r"(?<![\w/])([0-9]{1,4})\s*(gb|гб|tb|тб)\b", re.I)
ACCESSORY = re.compile(
    r"чехол|стекло|дисплей|экран|аккумулятор|батаре|корпус|шлейф|плат[аыу]|"
    r"кабел|зарядк|на\s+запчаст|муляж|реплик|копия|для\s+(?:iphone|айфон)", re.I,
)
SUFFIXES = {
    "про": "Pro", "pro": "Pro", "промакс": "Pro Max", "promax": "Pro Max",
    "plus": "Plus", "плюс": "Plus", "mini": "mini", "мини": "mini",
    "s": "s", "splus": "s Plus", "max": "Max", "макс": "Max", "": "",
}


def group_key(title: str) -> str | None:
    """Return canonical model/storage, never infer missing storage or SE year."""
    if ACCESSORY.search(title):
        return None
    models = list(MODEL.finditer(title))
    if len(models) != 1:
        return None
    match = models[0]
    if re.match(r"\s*(?:pro|про|max|макс|mini|мини|plus|плюс)", title[match.end():], re.I):
        return None
    generation = match["generation"].upper()
    suffix = SUFFIXES.get(re.sub(r"\s+", "", match["suffix"] or "").lower())
    if suffix is None or generation == "SE":
        return None  # SE generations require an explicit year-aware parser.
    allowed = {""}
    if generation == "XS":
        allowed.add("Max")
    if generation.isdigit():
        number = int(generation)
        if number in (4, 5, 6):
            allowed.add("s")
        if number in (6, 7, 8, 14, 15, 16):
            allowed.add("Plus")
        if number == 6:
            allowed.add("s Plus")
        if number in (12, 13):
            allowed.add("mini")
        if 11 <= number <= 17:
            allowed.update(("Pro", "Pro Max"))
    if suffix not in allowed:
        return None
    capacities = set()
    for storage in STORAGE.finditer(title):
        value = int(storage[1]) * (1024 if storage[2].lower() in ("tb", "тб") else 1)
        if value not in (8, 16, 32, 64, 128, 256, 512, 1024, 2048):
            return None
        capacities.add(value)
    if len(capacities) != 1:
        return None
    model = generation + (suffix if suffix == "s" else " " + suffix if suffix else "")
    return f"iPhone {model} · {capacities.pop()} ГБ"
