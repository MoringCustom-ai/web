"""Автоматическая выдача/отзыв доступа к закрытому чату клуба.

Бот должен быть админом superchat-а (CHAT_GROUP_ID). Активным участникам
подписки выдаётся invite-ссылка, при истечении подписки участник исключается.
Если CHAT_GROUP_ID не задан — функция молча пропускается (доступ выдаётся вручную).
"""
from __future__ import annotations

import logging

from .. import config

log = logging.getLogger(__name__)


async def grant_access(bot, user_id: int) -> str | None:
    """Возвращает invite-ссылку в чат, если чат настроен."""
    if not config.CHAT_GROUP_ID:
        return None
    try:
        link = await bot.create_chat_invite_link(
            chat_id=config.CHAT_GROUP_ID,
            name=f"member:{user_id}",
            creates_join_requests=False,
        )
        return link.invite_link
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось выдать доступ к чату для %s: %s", user_id, e)
        return None


async def revoke_access(bot, user_id: int) -> bool:
    """Исключает пользователя из чата (при окончании подписки)."""
    if not config.CHAT_GROUP_ID:
        return False
    revoked = False
    try:
        links = await bot.get_chat_invite_links(config.CHAT_GROUP_ID)
        for l in links:
            if l.name == f"member:{user_id}" and not l.is_revoked:
                await bot.revoke_chat_invite_link(
                    chat_id=config.CHAT_GROUP_ID, invite_link=l.invite_link
                )
                revoked = True
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось отозвать ссылки чата: %s", e)
    try:
        member = await bot.get_chat_member(config.CHAT_GROUP_ID, user_id)
        if member.status in ("member", "administrator") and member.user.id == user_id:
            await bot.ban_chat_member(config.CHAT_GROUP_ID, user_id)
            revoked = True
    except Exception:  # пользователя нет в чате — ок
        pass
    return revoked
