"""Хендлеры бота клуба «Шесть месяцев»."""
from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from .. import config, storage
from .keyboards import (
    ABOUT_TEXT,
    CHALLENGE_DONE_TEXT,
    MARK_LABEL,
    REMIND_TEXT,
    STARTED_TEXT,
    WELCOME_TEXT,
    main_keyboard,
    mark_keyboard,
    plural,
    start_keyboard,
    stats_message,
)

router = Router()

# Общие объекты, инициализируются в main.py
db = None          # aiosqlite.Connection
bot: Bot | None = None


def _has_miniprogram() -> bool:
    return bool(config.MINI_APP_URL)


async def _user_today(user_id: int) -> tuple[object, int]:
    """Возвращает (start_date, номер текущего дня)."""
    start = await storage.get_start_date(db, user_id)
    if start is None:
        return None, 0
    return start, storage.current_day(start)


@router.message(CommandStart())
async def cmd_start(message: Message):
    await storage.register_user(
        db, message.from_user.id,
        message.from_user.username,
        message.from_user.full_name,
    )
    start, day = await _user_today(message.from_user.id)
    if day > 1:  # уже участвует
        marks = await storage.get_marks(db, message.from_user.id)
        stats = storage.compute_stats(marks, config.CHALLENGE_DAYS)
        await message.answer(
            stats_message(start, day, stats, config.CHALLENGE_DAYS),
            reply_markup=main_keyboard(_has_miniprogram()),
        )
        return
    await message.answer(
        WELCOME_TEXT.format(days=config.CHALLENGE_DAYS),
        reply_markup=start_keyboard(),
    )


@router.callback_query(F.data == "start_challenge")
async def cb_start_challenge(cb: CallbackQuery):
    await storage.register_user(
        db, cb.from_user.id, cb.from_user.username, cb.from_user.full_name
    )
    await cb.message.edit_text(
        STARTED_TEXT.format(
            days=config.CHALLENGE_DAYS,
            remind_time=f"{config.REMINDER_HOUR:02d}:{config.REMINDER_MINUTE:02d}",
        ),
        reply_markup=main_keyboard(_has_miniprogram()),
    )
    await cb.answer()


@router.callback_query(F.data == "about")
async def cb_about(cb: CallbackQuery):
    await cb.message.answer(ABOUT_TEXT, reply_markup=main_keyboard(_has_miniprogram()))
    await cb.answer()


@router.callback_query(F.data == "mark:today")
async def cb_mark_today(cb: CallbackQuery):
    start, day = await _user_today(cb.from_user.id)
    if start is None:
        await cb.answer("Сначала нажми /start 🙂", show_alert=True)
        return
    if day > config.CHALLENGE_DAYS:
        await cb.answer("Челлендж уже завершён 🎉", show_alert=True)
        return
    marks = await storage.get_marks(db, cb.from_user.id)
    current = marks.get(day)
    hint = f" (сейчас: {MARK_LABEL[current]})" if current else ""
    await cb.message.answer(
        f"Как прошёл <b>день {day}</b>{hint}?",
        reply_markup=mark_keyboard(day),
    )
    await cb.answer()


@router.callback_query(F.data.startswith("set:"))
async def cb_set_mark(cb: CallbackQuery):
    _, day_s, value = cb.data.split(":")
    day = int(day_s)
    ok = await storage.set_mark(db, cb.from_user.id, day, value)
    if not ok:
        await cb.answer("Этот день недоступен для отметки", show_alert=True)
        return
    await cb.answer(f"Отметка «{MARK_LABEL[value]}» сохранена!")

    marks = await storage.get_marks(db, cb.from_user.id)
    stats = storage.compute_stats(marks, config.CHALLENGE_DAYS)

    emoji = {"ok": "💪", "part": "🙂", "fail": "🫂"}[value]
    support = {
        "ok": f"Серия 🔥 {stats['streak_cur']} — так держать!",
        "part": "Частично — тоже прогресс. Завтра новый заход 💙",
        "fail": "Сорвался — не страшно. Клуб рядом, завтра всё получится 🫂",
    }[value]

    text = f"{emoji} День {day}: {MARK_LABEL[value].lower()}.\n{support}"

    if day >= config.CHALLENGE_DAYS:
        text += "\n\n" + CHALLENGE_DONE_TEXT.format(
            days=config.CHALLENGE_DAYS,
            ok=stats["counts"]["ok"],
            part=stats["counts"]["part"],
            fail=stats["counts"]["fail"],
            pct=stats["pct"],
            best=stats["streak_best"],
        )
    await cb.message.answer(text)

    if day >= config.CHALLENGE_DAYS:
        await cb.message.answer(
            stats_message(None, day, stats, config.CHALLENGE_DAYS),
            reply_markup=main_keyboard(_has_miniprogram()),
        )


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    start, day = await _user_today(message.from_user.id)
    if start is None:
        await message.answer("Ты ещё не начал челлендж. Нажми /start 👆")
        return
    marks = await storage.get_marks(db, message.from_user.id)
    stats = storage.compute_stats(marks, config.CHALLENGE_DAYS)
    await message.answer(
        stats_message(start, day, stats, config.CHALLENGE_DAYS),
        reply_markup=main_keyboard(_has_miniprogram()),
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "Команды:\n"
        "/start — главная меню\n"
        "/stats — моя статистика\n"
        "/mark — быстро отметить сегодня\n"
        "/help — эта справка"
    )


@router.message(Command("mark"))
async def cmd_mark(message: Message):
    start, day = await _user_today(message.from_user.id)
    if start is None or day > config.CHALLENGE_DAYS:
        await message.answer("Сначала начни челлендж: /start")
        return
    await message.answer(
        f"Как прошёл <b>день {day}</b>?",
        reply_markup=mark_keyboard(day),
    )


async def send_reminder(bot_obj: Bot, user_id: int):
    """Вызывается планировщиком каждый вечер."""
    global bot
    bot = bot_obj
    start, day = await _user_today(user_id)
    if start is None or day > config.CHALLENGE_DAYS:
        return
    marks = await storage.get_marks(db, user_id)
    if day in marks:
        return  # уже отметил(а)
    stats = storage.compute_stats(marks, config.CHALLENGE_DAYS)
    try:
        await bot_obj.send_message(
            user_id,
            REMIND_TEXT.format(
                day=day, streak=stats["streak_cur"], best=stats["streak_best"], name="друг",
            ),
            reply_markup=mark_keyboard(day),
        )
    except Exception:
        pass  # пользователь заблокировал бота
