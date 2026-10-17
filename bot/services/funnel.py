"""Воронка и контент: активация, информация о клубе, FAQ, правила."""
from __future__ import annotations

from .. import storage


async def consent_message(db) -> str:
    price = await storage.get_content(db, "plan_price")
    return (await storage.get_content(db, "consent_text")).format(
        offer_url=await storage.get_content(db, "terms_url"),
        privacy_url=await storage.get_content(db, "privacy_url"),
        price=price,
    )


async def about_message(db) -> str:
    price = await storage.get_content(db, "plan_price")
    days = storage.config.CHALLENGE_DAYS
    text = await storage.get_content(db, "about_club")
    return text.format(price=price, days=days) if "{" in text else text


async def faq_list(db) -> list[tuple[str, str]]:
    items = await storage.get_json_content(db, "faq_json", [])
    return [(q, a) for q, a in items]


async def faq_answer(db, index: int) -> tuple[str, str] | None:
    items = await faq_list(db)
    if 0 <= index < len(items):
        q, a = items[index]
        price = await storage.get_content(db, "plan_price")
        return q, a.format(price=price) if "{" in a else a
    return None


async def rules_message(db) -> str:
    return await storage.get_content(db, "rules")
