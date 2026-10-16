"""Точка входа: запуск бота клуба «Шесть месяцев» + ежедневные напоминания."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from . import config, storage
from .handlers import user


async def nightly_reminders(bot_obj: Bot):
    """Рассылает напоминалку всем, кто ещё не отметил сегодняшний день."""
    users = await storage.list_active_users(user.db)
    for uid in users:
        try:
            await user.send_reminder(bot_obj, uid)
        except Exception as e:  # noqa: BLE001
            logging.warning("Не удалось отправить напоминание %s: %s", uid, e)


async def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    if not config.BOT_TOKEN:
        raise SystemExit(
            "BOT_TOKEN не задан. Экспортируй токен от @BotFather: export BOT_TOKEN=..."
        )

    user.db = await storage.get_db()

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await bot.set_my_commands([
        BotCommand(command="start", description="Начать / главное меню"),
        BotCommand(command="mark", description="Отметить день"),
        BotCommand(command="stats", description="Моя статистика"),
        BotCommand(command="help", description="Справка"),
    ])

    dp = Dispatcher()
    dp.include_router(user.router)

    # Ежедневное напоминание
    scheduler = AsyncIOScheduler(timezone=config.TIMEZONE)
    scheduler.add_job(
        nightly_reminders,
        CronTrigger(hour=config.REMINDER_HOUR, minute=config.REMINDER_MINUTE),
        args=[bot],
    )
    scheduler.start()

    # Webhook вместо long polling (для продакшена на хостинге):
    #   WEBHOOK_URL=https://your-domain.com  WEBHOOK_PORT=8443
    import os
    webhook_url = os.getenv("WEBHOOK_URL")

    if webhook_url:
        from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
        from aiohttp import web

        await bot.set_webhook(f"{webhook_url}/webhook", secret_token=os.getenv("WEBHOOK_SECRET"))
        app = web.Application()
        SimpleRequestHandler(dispatcher=dp, bot=bot,
                             secret_token=os.getenv("WEBHOOK_SECRET")).register(app, path="/webhook")
        setup_application(app, dp, bot=bot)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=int(os.getenv("WEBHOOK_PORT", "8081")))
        await site.start()
        logging.info("Webhook запущен на порту %s", os.getenv("WEBHOOK_PORT", "8081"))
        while True:
            await asyncio.sleep(3600)
    else:
        logging.info("Бот запущен (long polling)…")
        await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
