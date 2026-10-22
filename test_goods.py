from openpyxl import load_workbook

import avito_client
import avito
import goods
import profiles


def phone(item_id, price, *, title="iPhone 15, 128 ГБ, SIM + eSIM", city="sankt-peterburg",
          description="Продаю свой телефон.", seller=None, closed="5 завершённых объявлений", badges=()):
    item = {
        "id": item_id,
        "type": "item",
        "title": title,
        "urlPath": f"/{city}/telefony/iphone_15_{item_id}",
        "description": description,
        "priceDetailed": {"value": price},
        "closedItemsText": closed,
        "contacts": {"phone": True},
        "iva": {
            "BadgeBarStep": [{"payload": {"badges": [{"title": b} for b in badges]}}],
            "SecondLineStep": [{"payload": {"value": seller}}] if seller else [],
        },
    }
    return item


def test_title_gives_model_memory_and_city():
    offer = goods.offer_from_item(phone(1, 35_000, city="moskva", badges=("Только доставка", "Цена ниже рыночной")))

    assert offer.group == "iPhone 15, 128 ГБ"
    assert offer.city == "moskva"
    assert offer.delivery_only is True
    assert offer.avito_price_badge == "Цена ниже рыночной"
    assert offer.seller == "частное лицо"


def test_all_russia_search_accepts_private_sellers_from_any_city():
    search = avito.Search(name="pcs", title="PCs", profile="goods",
                          catalog_url="https://www.avito.ru/rossiya/nastolnye_kompyutery", params={})
    item = phone(1, 9000, city="kazan", title="Системный блок")

    assert search.home_city == ""
    assert profiles.GoodsProfile({}, search.home_city).alert(item) is not None


def test_laptop_deals_use_private_sample_median_and_reject_extremes():
    base = {str(i): phone(i, 10_000, title=f"Ноутбук модель {i}") for i in range(20)}
    profile = profiles.LaptopDealsProfile(base)

    cheap = profile.alert(phone(21, 8_000, title="Ноутбук рабочий"))
    assert cheap is not None and cheap["vs_market"] == "-20%"
    assert profile.alert(phone(22, 4_000, title="Ноутбук рабочий")) is None
    assert profile.alert(phone(23, 9_000, title="Ноутбук рабочий")) is None
    assert profile.alert(phone(24, 8_000, title="Ноутбук не работает")) is None
    assert profiles.LaptopDealsProfile({}).alert(phone(25, 8_000)) is None


def test_monitor_alert_ignores_accessories_and_unrelated_titles():
    profile = profiles.MonitorProfile({})

    assert profile.alert(phone(1, 6_000, title="Монитор 24 дюйма")) is not None
    assert profile.alert(phone(2, 500, title="Кабель для монитора")) is None
    assert profile.alert(phone(3, 500, title="Витая пара")) is None


def test_market_median_ignores_defects_and_extremes():
    offers = [goods.offer_from_item(phone(i, price)) for i, price in enumerate((34_000, 35_000, 36_000, 37_000))]
    offers.append(goods.offer_from_item(phone(10, 9_000)))  # extreme
    offers.append(goods.offer_from_item(phone(11, 15_000, description="Заблокирован по iCloud")))

    stats = goods.market_stats(offers)["iPhone 15, 128 ГБ"]

    assert stats.count == 5
    assert stats.used == 4
    assert stats.median == 35_500


def test_annotations_mark_cheap_defect_shop_and_other_city():
    offers = [goods.offer_from_item(phone(i, 36_000)) for i in range(4)]
    cheap = goods.offer_from_item(phone(20, 29_000))
    locked = goods.offer_from_item(phone(21, 15_000, description="Битый экран, на запчасти"))
    shop = goods.offer_from_item(phone(22, 36_000, closed="777 завершённых объявлений"))
    remote = goods.offer_from_item(phone(23, 36_000, city="moskva"))
    everything = offers + [cheap, locked, shop, remote]
    stats = goods.market_stats(everything)

    goods.annotate(everything, stats, "sankt-peterburg")

    assert "дешевле рынка" in cheap.notes
    assert locked.defect and "заблокирован/неисправен (по описанию)" in locked.notes
    assert any("похоже на магазин" in note for note in shop.notes)
    assert "другой город: moskva" in remote.notes


def test_not_broken_is_not_a_defect():
    assert not goods.offer_from_item(phone(1, 35_000, description="Не битый, не вскрывался")).defect


def test_goods_profile_alerts_only_for_home_city(tmp_path):
    base = {str(i): phone(i, 36_000) for i in range(4)}
    profile = profiles.GoodsProfile(base, "sankt-peterburg")

    assert profile.alert(phone(50, 30_000, city="moskva")) is None
    alert = profile.alert(phone(51, 30_000))
    assert alert["price"] == "30 000 ₽"
    assert alert["vs_market"] == "-17%"
    assert alert["price_assessment"] == "на 17% дешевле медианы"

    path = tmp_path / "phones.xlsx"
    profile.write_table(path, seen_before={})
    assert load_workbook(path).sheetnames == ["Рынок", "Объявления"]
    assert load_workbook(path)["Объявления"]["F1"].value == "Оценка цены"


def test_short_page_is_last():
    full = avito_client.Page(number=1, items=({"id": 1},), total_count=1065, items_on_page=50)
    short = avito_client.Page(number=22, items=({"id": 1},), total_count=1065, items_on_page=15)
    empty = avito_client.Page(number=23, items=(), total_count=1065, items_on_page=0)

    assert not full.is_last
    assert short.is_last
    assert empty.is_last


def test_items_url_keeps_search_params_and_page():
    url = avito_client.items_url({"categoryId": "84", "q": "iphone 15"}, 3)

    assert "categoryId=84" in url and "q=iphone+15" in url and "p=3" in url


def test_goods_alerts_only_private_people_by_default():
    base = {str(i): phone(i, 36_000) for i in range(4)}
    private = profiles.GoodsProfile(base, "sankt-peterburg")
    everyone = profiles.GoodsProfile(base, "sankt-peterburg", alert_sellers="all")

    company = phone(60, 36_000, seller="Компания")
    shop = phone(61, 36_000, closed="8884 завершённых объявления")
    person = phone(62, 36_000)

    assert private.alert(company) is None
    assert private.alert(shop) is None
    assert private.alert(person) is not None
    assert everyone.alert(company) is not None


def test_pow_challenge_comes_from_cookie_for_html_pages():
    class Html439:
        status_code = 439
        def json(self):
            raise ValueError("not json")

    class Session:
        cookies = {"pow_challenge": "abc"}

    source = avito_client.pow_source(Html439(), Session())
    assert source.json() == {"pow_challenge": "abc"}
