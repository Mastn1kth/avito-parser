import listing_quality


def test_marks_parts_buying_reseller_and_missing_comparables():
    result = listing_quality.inspect(
        {"title": "Куплю системный блок", "description": "на запчасти"},
        {"seller": "Компания", "closed_listings": 140, "notes": [], "market_value": None}, "pc")
    assert not result["quality_ok"]
    assert len(result["quality_warnings"]) == 4
    assert "недостаточно" in result["notes"][-1]


def test_discount_and_evidence_are_explained_without_changing_input():
    fields = {"seller": "частное лицо", "closed_listings": 1,
              "market_value": 10000, "discount_percent": 60, "reference_count": 7, "notes": []}
    result = listing_quality.inspect({"title": "ПК рабочий"}, fields, "pc")
    assert any("50%" in note for note in result["notes"])
    assert result["quality_ok"]
    assert fields["notes"] == []
    ordinary = listing_quality.inspect({"title": "ПК рабочий"},
        {**fields, "discount_percent": 20}, "pc")
    assert "7 объявлениями" in ordinary["reasons"][0]
