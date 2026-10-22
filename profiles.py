"""Search profiles: how listings of one kind are judged, tabulated and alerted.

* ``realty-owner`` — flats: owner/agent verdict, draft message for the owner;
  alerts only for owners' listings.
* ``goods`` — things like phones: model + storage groups, market price;
  alerts for every new listing with its price against the market.
"""

from __future__ import annotations

import re

from pathlib import Path
from typing import Any

import apartments
import goods
import laptop_prices


# --- realty-owner -----------------------------------------------------------

def price_text(value: int | None) -> str:
    return f"{value:,} ₽".replace(",", " ") if value else "цена не указана"


def short_address(listing: apartments.Listing) -> str:
    return listing.address.removeprefix("Санкт-Петербург, ").strip()


def draft_message(listing: apartments.Listing) -> str:
    """A first message the realtor can copy into Avito chat and edit.

    It asks about this particular flat and offers something useful; it does
    not presume the owner has a problem and does not invent a buyer.
    """
    place = short_address(listing) or "вашей квартиры"
    flat = f"2-комнатной квартиры по адресу {place}" if listing.address else "2-комнатной квартиры"
    if listing.pays_agent:
        return (
            f"Здравствуйте! Увидела ваше объявление о продаже {flat}. "
            "Вы писали, что готовы работать с агентом, который приведёт покупателя. "
            "Я риэлтор, работаю с вторичкой в этом районе. Квартира ещё продаётся? "
            "Удобно созвониться, чтобы я задала пару вопросов по квартире?"
        )
    if listing.asks_no_agents:
        return (
            f"Здравствуйте! Увидела ваше объявление о продаже {flat}. "
            "Понимаю, что вы продаёте сами, и навязываться не буду. "
            "Если захотите сверить цену с недавними сделками рядом или появится "
            "вопрос по документам — напишите, подскажу бесплатно."
        )
    return (
        f"Здравствуйте! Увидела ваше объявление о продаже {flat} "
        f"за {price_text(listing.price)}. Я риэлтор, работаю с вторичкой в этом районе. "
        "Квартира ещё продаётся? Если интересно, расскажу, за сколько сейчас "
        "реально уходят похожие квартиры рядом, — без обязательств."
    )


def alert_fields(listing: apartments.Listing) -> dict[str, Any]:
    notes = []
    if listing.pays_agent:
        notes.append("готов платить агенту за покупателя")
    if listing.asks_no_agents:
        notes.append("просит агентов не беспокоить")
    if listing.has_own_agent:
        notes.append("у собственника уже есть свой агент")
    if not listing.calls_allowed:
        notes.append("звонки отключены, только чат")
    return {
        "id": listing.id,
        "title": listing.title,
        "price": price_text(listing.price),
        "price_per_m2": price_text(listing.price_per_meter),
        "address": short_address(listing),
        "metro": listing.metro,
        "published": listing.published,
        "verdict": listing.verdict,
        "reasons": listing.reasons,
        "notes": notes,
        "url": listing.url,
        "draft": draft_message(listing),
    }


class RealtyOwnerProfile:
    name = "realty-owner"

    def __init__(self, base: dict[str, Any], home_city: str = "", alert_sellers: str = "private") -> None:
        self.base = base

    def alert(self, item: dict[str, Any]) -> dict[str, Any] | None:
        listing = apartments.classify(apartments.listing_from_item(item))
        if listing.verdict == apartments.VERDICT_AGENT:
            return None
        return alert_fields(listing)

    def write_table(self, path: Path, seen_before: dict[str, str]) -> dict[str, int]:
        listings = [
            apartments.classify(apartments.listing_from_item(item))
            for item in self.base.values()
        ]
        for listing in listings:
            listing.is_new = str(listing.id) not in seen_before
        apartments.write_workbook(path, listings)
        return {
            verdict: sum(listing.verdict == verdict for listing in listings)
            for verdict in (apartments.VERDICT_OWNER, apartments.VERDICT_CHECK, apartments.VERDICT_AGENT)
        }


# --- goods --------------------------------------------------------------------

class GoodsProfile:
    name = "goods"

    def __init__(self, base: dict[str, Any], home_city: str = "", alert_sellers: str = "private") -> None:
        self.base = base
        self.home_city = home_city
        self.alert_sellers = alert_sellers
        self.refresh_market()

    def refresh_market(self) -> None:
        offers = [goods.offer_from_item(item) for item in self.base.values()]
        self.stats = goods.market_stats(goods.market_sample(
            offers, private_only=self.alert_sellers == "private"
        ))

    def alert(self, item: dict[str, Any]) -> dict[str, Any] | None:
        offer = goods.offer_from_item(item)
        # Listings from other cities come with delivery and flood the feed;
        # they stay in the table but do not alert.
        if self.home_city and offer.city and offer.city != self.home_city:
            return None
        # By default only private people: companies and "private" sellers
        # with a shop-sized history stay in the table but do not alert.
        if self.alert_sellers == "private" and (
            offer.seller != "частное лицо"
            or (offer.listing.closed_listings or 0) >= goods.SHOP_CLOSED_LISTINGS
        ):
            return None
        goods.annotate([offer], self.stats, self.home_city)
        return goods.alert_fields(offer)

    def write_table(self, path: Path, seen_before: dict[str, str]) -> dict[str, int]:
        offers = [goods.offer_from_item(item) for item in self.base.values()]
        stats = goods.market_stats(goods.market_sample(
            offers, private_only=self.alert_sellers == "private"
        ))
        goods.annotate(offers, stats, self.home_city)
        for offer in offers:
            offer.listing.is_new = str(offer.listing.id) not in seen_before
        goods.write_workbook(path, offers, stats)
        return {"объявлений": len(offers), "групп с рыночной ценой": len(stats)}


class LaptopDealsProfile(GoodsProfile):
    """Alert only when enough comparable private listings exist."""

    name = "laptop-deals"

    def refresh_market(self) -> None:
        offers = [goods.offer_from_item(item) for item in self.base.values()]
        self.laptop_medians = laptop_prices.medians(offers)

    def alert(self, item: dict[str, Any]) -> dict[str, Any] | None:
        offer = goods.offer_from_item(item)
        if self.home_city and offer.city and offer.city != self.home_city:
            return None
        if self.alert_sellers == "private" and (
            offer.seller != "частное лицо" or
            (offer.listing.closed_listings or 0) >= goods.SHOP_CLOSED_LISTINGS
        ):
            return None
        key = laptop_prices.model_key(offer.listing.title)
        price = offer.listing.price
        reference = self.laptop_medians.get(key) if key else None
        if offer.defect or not price or reference is None:
            return None
        median = reference.median
        if not 0.5 * median <= price <= 0.85 * median:
            return None
        fields = goods.alert_fields(offer)
        fields["market"] = goods.price_text(median)
        fields["vs_market"] = f"{price / median - 1:+.0%}"
        fields["price_assessment"] = goods.price_comparison(price / median - 1)
        fields["notes"].append(
            f"медиана: {reference.source}, {reference.count} объявлений; "
            "состояние и характеристики проверьте вручную"
        )
        return fields


class MonitorProfile(GoodsProfile):
    """Keep computer accessories out of monitor alerts."""

    name = "monitors"
    ACCESSORY = re.compile(r"кабель|кронштейн|подставк|матриц|шлейф|плат[ауы]|блок питания", re.I)

    def alert(self, item: dict[str, Any]) -> dict[str, Any] | None:
        title = str(item.get("title") or "")
        if not re.search(r"монитор", title, re.I) or self.ACCESSORY.search(title):
            return None
        return super().alert(item)


PROFILES = {profile.name: profile for profile in (RealtyOwnerProfile, GoodsProfile, LaptopDealsProfile, MonitorProfile)}
