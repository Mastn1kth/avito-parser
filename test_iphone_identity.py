import pytest

from iphone_identity import group_key


@pytest.mark.parametrize("title", [
    "iPhone 11 Pro, 64 ГБ", "Apple IPHONE 11 PRO 64GB", "Айфон 11 про 64 гб",
])
def test_equivalent_titles(title):
    assert group_key(title) == "iPhone 11 Pro · 64 ГБ"


def test_suffixes_storage_and_units_are_distinct():
    assert group_key("iPhone 13 Pro Max 1 TB") == group_key("айфон 13 про макс 1024 ГБ")
    assert group_key("iPhone 13 Pro Max 1 TB") == "iPhone 13 Pro Max · 1024 ГБ"
    assert len({group_key(f"iPhone 11{suffix} {capacity}GB")
                for suffix in ("", " Pro", " Pro Max") for capacity in (64, 256)}) == 6
    assert group_key("iPhone 12 mini 128GB") == "iPhone 12 mini · 128 ГБ"
    assert group_key("iPhone 6s 64GB") == "iPhone 6s · 64 ГБ"


@pytest.mark.parametrize("title", [
    "iPhone 11 Pro", "iPhone 11 64/128GB", "iPhone 11 64GB 128GB",
    "Чехол iPhone 11 Pro 64GB", "Экран для iPhone 11 64GB",
    "iPhone 11 64GB на запчасти", "iPhone SE 64GB", "iPhone 11 mini 64GB",
    "iPhone 99 64GB", "iPhone 11 Pro Maximus 64GB", "iPhone 11 63GB",
    "iPhone 11 64GB и iPhone 12 64GB", "Samsung 128GB",
])
def test_unknown_ambiguous_and_accessory_titles_are_not_compared(title):
    assert group_key(title) is None
