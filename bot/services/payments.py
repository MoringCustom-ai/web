"""Оплата: внешние платёжные ссылки (карта РФ / иностранная карта) и Telegram Stars.

Внешние ПС не могут без сервера приёмов сообщить боту об оплате, поэтому:
  • для внешних ссылок — кнопка «Проверить оплату» + ручное подтверждение админом
    (/paid <id>) либо автоматический webhook, если подключите свою ПС;
  • для тестовой эксплуатации — инвойсы Telegram Stars (бот получает
    pre_checkout_query / successful_payment автоматически).
"""
from __future__ import annotations

import uuid

from aiogram.types import LabeledPrice

from .. import config, storage

PAY_METHOD_LABEL = {
    "ru_card": "💳 Карта РФ",
    "intl_card": "💳 Иностранная карта",
    "stars": "⭐ Telegram Stars",
}


async def _pay_method_from_payload(payload: str) -> str:
    parts = payload.split(":")
    if len(parts) >= 3 and parts[1] in ("ru_card", "intl_card", "stars"):
        return parts[1]
    return "external"


async def create_external_payment(db, user_id: int, method: str) -> str:
    """Регистрирует pending-платёж для внешней платёжной системы. Возвращает payload."""
    payload = f"sub:{user_id}:{method}:{uuid.uuid4().hex[:8]}"
    price = await storage.get_content(db, "plan_price")
    await storage.create_payment(
        db, invoice_id=payload, user_id=user_id, provider="external",
        amount=int(float(price or 0)), currency="RUB", payload=payload,
    )
    return payload


async def create_stars_invoice(bot, db, user_id: int):
    """Создаёт инвойс Telegram Stars. Возвращает (invoice, payload)."""
    plan = await storage.get_content(db, "plan_name")
    payload = f"sub:{user_id}:stars:{uuid.uuid4().hex[:8]}"
    prices = [LabeledPrice(label=plan, amount=config.STARS_PRICE)]
    invoice = await bot.send_invoice(
        chat_id=user_id,
        title=plan,
        description=(await storage.get_content(db, "payment_comment")),
        payload=payload,
        provider_payload=payload,
        currency="XTR",
        prices=prices,
    )
    await storage.create_payment(
        db, invoice_id=payload, user_id=user_id, provider="stars",
        amount=config.STARS_PRICE, currency="XTR", payload=payload,
    )
    return invoice, payload


async def fulfill_payment(db, payload: str, *, extend: bool = False) -> dict | None:
    """Применяет оплаченный платёж: активирует/продлевает подписку.

    Возвращает dict(cached=bool, user_id, end_date) или None, если payload неизвестен.
    """
    payment = await storage.get_payment(db, payload)
    if payment is None:
        return None
    cached = payment["status"] == "paid"
    if cached:
        return {"cached": True, "user_id": payment["user_id"], "end_date": None}
    await storage.mark_payment_paid(db, payload)
    plan = await storage.get_content(db, "plan_name")
    method = await _pay_method_from_payload(payload)
    end = await storage.activate_subscription(
        db, payment["user_id"],
        method=method,
        payment_id=payload, plan=plan, extend_from="1" if extend else None,
    )
    return {"cached": False, "user_id": payment["user_id"], "end_date": end}
