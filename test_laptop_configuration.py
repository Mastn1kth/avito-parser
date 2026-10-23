import laptop_prices


def test_laptop_configuration_separates_cpu_memory_storage_and_gpu():
    title = "ThinkPad T480 i5-8250U 8/256 UHD 620"
    key = laptop_prices.model_key(title)
    assert key is not None
    for variant in (title.replace("8250", "8350"), title.replace("8/", "16/"),
                    title.replace("256", "512"), title.replace("UHD 620", "MX150")):
        assert laptop_prices.model_key(variant) != key
    assert laptop_prices.model_key("Lenovo THINKPAD T480 i5 8250u 8GB/256GB UHD620") == key


def test_missing_configuration_does_not_produce_comparison():
    for title in ("ThinkPad T480", "ThinkPad T480 i5-8250U", "ThinkPad T480 i5-8250U 8/256"):
        assert laptop_prices.model_key(title) is None
