"""Ready Avito search links offered by the interactive menu and Telegram bot."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Preset:
    name: str
    title: str
    url: str
    profile: str = "goods"


PRESETS = (
    Preset("iphone-11-pro-russia", "iPhone 11 Pro · вся Россия",
           "https://www.avito.ru/rossiya/telefony?q=iPhone%2011%20Pro"),
    Preset("iphone-russia", "Все iPhone · вся Россия",
           "https://www.avito.ru/rossiya/telefony?q=iPhone"),
    Preset("computer-goods-russia", "Товары для компьютера · вся Россия",
           "https://www.avito.ru/rossiya/tovary_dlya_kompyutera"),
    Preset("pc-ready-9000-russia", "Системные блоки до 9 000 ₽ · вся Россия",
           "https://www.avito.ru/rossiya/nastolnye_kompyutery?q=%D1%81%D0%B8%D1%81%D1%82%D0%B5%D0%BC%D0%BD%D1%8B%D0%B9%20%D0%B1%D0%BB%D0%BE%D0%BA&pmax=9000", "pc-prices"),
    Preset("laptops-russia", "Ноутбуки · вся Россия",
           "https://www.avito.ru/rossiya/noutbuki", "laptop-deals"),
    Preset("monitors-russia", "Мониторы · вся Россия",
           "https://www.avito.ru/rossiya/tovary_dlya_kompyutera?q=%D0%BC%D0%BE%D0%BD%D0%B8%D1%82%D0%BE%D1%80", "monitors"),
)


def get(name: str) -> Preset | None:
    return next((preset for preset in PRESETS if preset.name == name), None)
