import pytest

import avito
import goods
import profiles
from test_goods import phone


@pytest.mark.parametrize("price,threshold,expected", [
    (8500, 15, True), (8501, 15, False), (7500, 25, True),
    (7501, 25, False), (12000, 0, True),
])
def test_exact_discount_boundary(price, threshold, expected):
    assert avito.discount_matches({"price_value": price, "market_value": 10000}, threshold) is expected


def test_unknown_or_defective_cannot_pass_discount():
    assert not avito.discount_matches({}, 15)
    assert not avito.discount_matches({"price_value": 100, "market_value": 1000, "defective": True}, 15)


def test_phone_identity_is_used_in_actual_profile():
    base = {str(i): phone(i, price, title="iPhone 11 Pro, 64 ГБ")
            for i, price in enumerate((10000, 12000, 14000))}
    profile = profiles.GoodsProfile(base)
    fields = profile.alert(phone(10, 9000, title="айфон 11 про 64gb"))
    assert fields["market_value"] == 12000
    assert fields["reference_count"] == 3
    assert avito.discount_matches(fields, 25)
    assert profile.alert(phone(11, 9000, title="iPhone 11 Pro Max 64GB"))["market_value"] is None
    assert not goods.offer_from_item(phone(12, 9000, title="iPhone 11 Pro")).comparable


def test_laptop_all_mode_removes_default_discount_gate():
    base = {str(i): phone(i, 10000, title="ThinkPad T480") for i in range(5)}
    profile = profiles.LaptopDealsProfile(base)
    item = phone(10, 9500, title="ThinkPad T480")
    assert profile.alert(item) is None
    profile.min_discount_pct = 0
    assert profile.alert(item)["market_value"] == 10000
