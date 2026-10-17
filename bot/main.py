"""Точка входа бота закрытого бизнес-клуба «Шесть месяцев».

Сборка приложения: Bot/Dispatcher, регистрация роутеров (user → admin),
инициализация общих объектов db/bot в хендлерах, запуск long-polling
и фоновых задач планировщика (напоминания, биллинг, доступ к чату).

Запуск:  python -m bot.main
Переменные окружения читаются из .env (см. bot/config.py): BOT_TOKEN, ADMIN_IDS и др.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from . import config, storage
from .handlers import admin as admin_handlers
from .handlers import user as user_handlers
from .scheduler import create_scheduler

log = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand(command="start", description="Начать / главное меню"),
    BotCommand(command="cabinet", description="Личный кабинет"),
    BotCommand(command="challenges", description="Мои челленджи"),
    BotCommand(command="subscribe", description="Вступить в клуб"),
    BotCommand(command="help", description="Помощь"),
]


async def main() -> None:
    if not config.BOT_TOKEN:
        raise SystemExit(
            "Не задан BOT_TOKEN. Создайте .env рядом с проектом:\n"
            "  BOT_TOKEN=123:abc...\n"
            "  ADMIN_IDS=111111\n"
            "(опционально: CHAT_GROUP_ID, MINI_APP_URL, PAYWALL_ENABLED и т.д.)"
        )

    # База данных — одно общее соединение на всё время жизни процесса
    db = await storage.get_db()

    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    # Инъекция общих объектов в модули хендлеров (объявлены как db/bot=None)
    user_handlers.db = db
    user_handlers.bot = bot
    admin_handlers.db = db
    admin_handlers.bot = bot

    dp = Dispatcher(storage=MemoryStorage())
    # Порядок важен: пользовательские хендлеры первыми, админские — после
    dp.include_router(user_handlers.router)
    dp.include_router(admin_handlers.router)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await bot.set_my_commands(BOT_COMMANDS)
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось настроить команды/вебхук: %s", e)

    sched = create_scheduler(bot)
    sched.start()
    log.info("Планировщик запущен (tz=%s). Бот готов.", config.TIMEZONE)

    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    )
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit) as e:
        if isinstance(e, SystemExit) and e.code not in (0, None):
            raise
        print("Бот остановлен.")
