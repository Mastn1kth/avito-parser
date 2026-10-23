"""Budget-independent reference samples, kept separate from watched listings."""
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TTL_SECONDS = 6 * 60 * 60
MAX_PAGES = 3
CACHE_FILE = "market-reference.json"
SUPPORTED_PROFILES = {"goods", "pc-prices", "laptop-deals", "monitors"}


def refresh(client, search) -> dict[str, dict]:
    """Return a fresh sample; failed refreshes propagate without replacing cache.

    Prices remain asking prices, and three newest pages are a limited sample,
    not a complete market census. Budget changes alone do not invalidate it.
    """
    if search.profile not in SUPPORTED_PROFILES:
        return {}
    params = {k: v for k, v in search.request_params.items() if k not in {"pmin", "pmax"}}
    parts = urlsplit(search.catalog_url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if k not in {"pmin", "pmax"}]
    catalog_url = urlunsplit(parts._replace(query=urlencode(query)))
    cached = search.load(CACHE_FILE)
    now = time.time()
    age = now - cached.get("updated_at", 0) if isinstance(cached.get("updated_at", 0), (int, float)) else TTL_SECONDS
    if (0 <= age < TTL_SECONDS and cached.get("params") == params
            and cached.get("catalog_url") == catalog_url
            and cached.get("profile") == search.profile
            and isinstance(cached.get("items"), dict)):
        return cached["items"]
    items = {}
    for number in range(1, MAX_PAGES + 1):
        page = client.page(catalog_url=catalog_url, params=dict(params), number=number)
        for item in page.items:
            if item.get("id") is not None:
                items.setdefault(str(item["id"]), item)
        if page.is_last:
            break
    search.save(CACHE_FILE, {"updated_at": time.time(), "params": params,
                            "catalog_url": catalog_url, "profile": search.profile,
                            "items": items})
    return items
