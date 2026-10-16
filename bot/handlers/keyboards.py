"""Тексты и клавиатуры бота клуба «Шесть месяцев».

Стиль сообщений — дружелюбный, без давления; опирается на концепцию
мини-приложения (My path / Club): день из 14, серии, отметки ok/part/fail.
"""
from __future__ import annotations

from datetime import date

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import config

MARK_LABEL = {
    "ok": "Выдержал ✅",
    "part": "Частично 🟡",
    "fail": "Сорвался ❌",
}

WELCOME_TEXT = (
    "👋 Добро пожаловать в клуб <b>«Шесть месяцев»</b>!\n\n"
    "Здесь мы проходим <b>дофаминовый детокс: {days} дней</b>. Каждый вечер "
    "бот будет просить тебя отметить день:\n\n"
    "✅ <b>Выдержал</b> — прошёл день по правилам\n"
    "🟡 <b>Частично</b> — были срывы, но ты удержался\n"
    "❌ <b>Сорвался</b> — честно признать тоже победа\n\n"
    "Никакого осуждения — только честность и поддержка клуба 💙\n\n"
    "Нажми <b>«Начать челлендж»</b>, чтобы запустить свой день 1."
)

STARTED_TEXT = (
    "🚀 Старт дан! Твой челлендж начался — сегодня <b>день 1 из {days}</b>.\n\n"
    "Каждый день в {remind_time} я буду напоминать поставить отметку. "
    "Отметиться можно и раньше кнопкой <b>«Отметить день»</b>."
)

REMIND_TEXT = (
    "🌙 Вечер {day}-го дня, {name}!\n\n"
    "Как прошёл день дофаминового детока?\n"
    "<i>Текущая серия: 🔥 {streak} · Лучшая: {best}</i>"
)

NO_REMIND_TEXT = (
    "⏰ Напоминалка на день {day}: ещё можно отметиться!\n"
    "Честная отметка важнее идеальной картинки 😉"
)

CHALLENGE_DONE_TEXT = (
    "🎉 <b>Челлендж пройден!</b> {days} дней позади.\n\n"
    "Твои итоги:\n"
    "✅ Выдержал: {ok}\n"
    "🟡 Частично: {part}\n"
    "❌ Сорвался: {fail}\n"
    "📈 Дней «выдержал»: {pct}%\n"
    "🔥 Лучшая серия: {best}\n\n"
    "Гордимся тобой! Клуб продолжает путь дальше 💙"
)


def main_keyboard(has_miniprogram: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Отметить день", callback_data="mark:today")
    if has_miniprogram:
        b.web_app(
            button=InlineKeyboardButton(text="📊 Мой путь", web_app={"url": config.MINI_APP_URL})
        )
    if config.CHAT_BUTTON_URL:
        b.button(text="💬 Чат клуба", url=config.CHAT_BUTTON_URL)
    b.button(text="ℹ️ О клубе", callback_data="about")
    b.adjust("1")
    return b.as_markup()


def start_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🚀 Начать челлендж", callback_data="start_challenge")
    return b.as_markup()


def mark_keyboard(day: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for key, label in MARK_LABEL.items():
        b.button(text=label, callback_data=f"set:{day}:{key}")
    b.adjust("1")
    return b.as_markup()


def plural(n: int, one: str, few: str, many: str) -> str:
    """Простое склонение числительных: 1 день / 2 дня / 5 дней."""
    mod10, mod100 = n % 10, n % 100
    if mod10 == 1 and mod100 != 11:
        return one
    if 2 <= mod10 <= 4 and not 12 <= mod100 <= 14:
        return few
    return many


def stats_message(start: date, today: int, stats: dict, days: int) -> str:
    left = max(days - today, 0)
    c = stats["counts"]
    lines = [
        f"📊 <b>День {min(today, days)} из {days}</b>",
        f"Осталось {left} {plural(left, 'день', 'дня', 'дней')} до конца челленджа"
        if left else "Челлендж завершён 🏁",
        "",
        f"🔥 Текущая серия: <b>{stats['streak_cur']}</b>",
        f"🏆 Лучшая серия: <b>{stats['streak_best']}</b>",
        f"📈 Дней «выдержал»: <b>{stats['pct']}%</b>",
        "",
        f"✅ {c['ok']} · 🟡 {c['part']} · ❌ {c['fail']}",
    ]
    return "\n".join(lines)


ABOUT_TEXT = (
    "🧠 <b>Клуб «Шесть месяцев»</b>\n\n"
    "Мы вернем себе внимание и дофамин вместе. Формат MVP:\n"
    f"• Челлендж «дофаминовый детокс» на <b>{config.CHALLENGE_DAYS} дней</b>\n"
    "• Ежедневная честная отметка вечером\n"
    "• Серии, статистика и сравнение с клубом\n"
    "• Поддержка в закрытом чате — без токсичности и осуждения\n\n"
    "Полное «шесть месяцев» путешествие разбито на этапы; этот бот — старт первого из них."
)
