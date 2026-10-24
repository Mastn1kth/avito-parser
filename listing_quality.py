"""Explain why a marketplace offer needs manual inspection."""

import re

import goods
import pc_prices


PARTS = re.compile(r"на\s+запчаст|на\s+разбор|без\s+(?:процессора|платы|аккумулятора|блока\s+питания)|не\s+включ|не\s+работает|заблок|icloud|айклауд", re.I)
BUYING = re.compile(r"^\s*(?:куплю|скупка|выкуп|ремонт|чехол|запчасти)\b", re.I)


def inspect(item: dict, fields: dict, kind: str) -> dict:
    """Return a new alert with evidence and cautions; never infer actual condition."""
    title = str(item.get("title") or "")
    description = str(item.get("description") or "")
    text = f"{title} {description}"
    result = {**fields, "notes": list(fields.get("notes") or [])}
    warnings = []
    if PARTS.search(text) or goods.DEFECT_PATTERN.search(text) or (kind == "pc" and pc_prices.incomplete(item)):
        warnings.append("заявлены неисправность, блокировка или некомплектность")
    if BUYING.search(title):
        warnings.append("похоже на объявление о покупке или услуге")
    if result.get("seller") != "частное лицо" or (result.get("closed_listings") or 0) >= goods.SHOP_CLOSED_LISTINGS:
        warnings.append("возможный магазин или перекупщик")
    if kind in ("pc", "laptop") and not result.get("market_value"):
        warnings.append("характеристик или сопоставимых объявлений недостаточно для оценки")
    if result.get("discount_percent") is not None and result["discount_percent"] > 50:
        warnings.append("цена более чем на 50% ниже медианы; проверьте комплектность и продавца")
    result["quality_warnings"] = warnings
    result["notes"].extend(w for w in warnings if w not in result["notes"])
    result["quality_ok"] = not any(w.startswith(("заявлены", "похоже", "возможный")) for w in warnings)
    if result.get("market_value") and not result.get("quality_warnings"):
        result["reasons"] = [f"сравнение с {result.get('reference_count', 0)} объявлениями похожей комплектации"]
    return result
