"""Клавиатуры и построители сообщений бота клуба.

Все тексты берутся из БД (bot/content.py → таблица content) и редактируются
через админку; здесь только структура кнопок по ТЗ.
"""
from __future__ import annotations

from datetime import datetime, timezone as dt_timezone

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .. import config, storage
from ..services import challenges as ch


def plural(n: int, one: str, few: str, many: str) -> str:
    mod10, mod100 = n % 10, n % 100
    if mod10 == 1 and mod100 != 11:
        return one
    if 2 <= mod10 <= 4 and not 12 <= mod100 <= 14:
        return few
    return many


def _fmt_date(iso: str) -> str:
    months = ["января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=dt_timezone.utc)
    return f"{dt.day} {months[dt.month - 1]} {dt.year} года"


# ------------------------------------------------------------ keyboards ----

def consent_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="✅ Дать согласие", callback_data="consent:ok")
    return b.as_markup()


def info_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="❓ Вопросы о клубе", callback_data="faq")
    b.button(text="💳 Вступить в клуб", callback_data="pay:choose")
    b.adjust("1")
    return b.as_markup()


def faq_keyboard(items: list) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for i, (q, _a) in enumerate(items):
        text = q if len(q) <= 56 else q[:55] + "…"
        b.button(text=text, callback_data=f"faq:{i}")
    b.button(text="💳 Вступить в клуб", callback_data="pay:choose")
    b.adjust("1")
    return b.as_markup()


def faq_answer_keyboard(index: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="← К вопросам", callback_data="faq")
    b.button(text="💳 Вступить в клуб", callback_data="pay:choose")
    b.adjust("1")
    return b.as_markup()


def pay_keyboard(db_urls_ready: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💳 Карта РФ", callback_data="pay:ru_card")
    b.button(text="💳 Иностранная карта", callback_data="pay:intl_card")
    if config.PAYWALL_ENABLED:
        b.button(text="⭐ Оплатить прямо в Telegram (тест)", callback_data="pay:stars")
    b.button(text="← Назад", callback_data="nav:back_home")
    b.adjust("1")
    return b.as_markup()


def payment_wait_keyboard(payload: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="🔄 Проверить оплату", callback_data=f"pay:check:{payload}")
    b.button(text="В личный кабинет", callback_data="cabinet")
    b.adjust("1")
    return b.as_markup()


def cabinet_keyboard(sub_active: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="📅 Срок подписки", callback_data="cab:sub")
    b.button(text="💳 Автосписание", callback_data="cab:auto")
    b.button(text="📖 Правила участия", callback_data="cab:rules")
    b.button(text="🔥 Челленджи", callback_data="cab:challenges")
    if sub_active:
        b.button(text="💬 Перейти в чат", callback_data="cab:chat")
    if config.MINI_APP_URL:
        b.web_app(
            button=InlineKeyboardButton(
                text="📊 Мой путь (мини-приложение)",
                web_app={"url": config.MINI_APP_URL},
            )
        )
    b.button(text="ℹ️ Информация о клубе", callback_data="nav:about")
    b.adjust("1", "1", "1", "1", "1")
    return b.as_markup()


def auto_renew_keyboard(on: bool) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if on:
        b.button(text="Выключить автосписание", callback_data="auto:off")
    else:
        b.button(text="Включить автосписание", callback_data="auto:on")
    b.button(text="← В личный кабинет", callback_data="cabinet")
    b.adjust("1")
    return b.as_markup()


def back_cabinet_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="← В личный кабинет", callback_data="cabinet")
    return b.as_markup()


def chat_keyboard(link: str | None) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    url = link or config.CHAT_BUTTON_URL
    if url:
        b.button(text="💬 Открыть чат клуба", url=url)
    b.button(text="← В личный кабинет", callback_data="cabinet")
    b.adjust("1")
    return b.as_markup()


def challenges_menu_keyboard(rows: list, limits: dict) -> InlineKeyboardMarkup:
    """rows — челленджи пользователя; limits — что можно добавить."""
    b = InlineKeyboardBuilder()
    for c in rows:
        status_icon = {
            "running": "🟢", "pending_start": "⏳",
            "completed": "🏁", "declined": "⛔",
        }.get(c["status"], "•")
        label = ch.LABEL[c["type"]]
        if c["type"] == "habit_month":
            label += f" · месяц {c['month']}"
        name = (c["habit"] or "")[:20]
        text = f"{status_icon} {label}" + (f" «{name}»" if name and c["type"] != "common" else "")
        b.button(text=text[:64], callback_data=f"chal:{c['id']}")
    # доступные для добавления
    if limits.get("common"):
        b.button(text="➕ Общий челлендж", callback_data="chalnew:common")
    if limits.get("habit_month"):
        b.button(text=f"➕ Привычка месяца ({limits['habit_month']})",
                 callback_data="chalnew:habit_month")
    if limits.get("own_habit"):
        b.button(text="➕ Своя привычка", callback_data="chalnew:own_habit")
    b.button(text="← В личный кабинет", callback_data="cabinet")
    b.adjust("1")
    return b.as_markup()


def challenge_keyboard(chal_id: int, status: str) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if status == "pending_start":
        b.button(text="🚀 Начать челлендж", callback_data=f"chalstart:{chal_id}")
    if status == "running":
        b.button(text="✅ Выполнил", callback_data=f"mark:{chal_id}:1")
        b.button(text="❌ Не выполнил", callback_data=f"mark:{chal_id}:0")
        b.button(text="📈 Моя динамика", callback_data=f"stats:{chal_id}")
        b.button(text="⏰ Изменить время напоминаний", callback_data=f"time:{chal_id}")
        b.button(text="📍 Изменить точку А", callback_data=f"pointA:{chal_id}")
        b.button(text="✖️ Отказаться от челленджа", callback_data=f"decline:{chal_id}")
    if status in ("completed", "declined"):
        b.button(text="📈 Посмотреть результат", callback_data=f"stats:{chal_id}")
    b.button(text="← К челленджам", callback_data="cab:challenges")
    b.adjust("2", "2", "2", "1")
    return b.as_markup()


def decline_confirm_keyboard(chal_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Да, отказаться", callback_data=f"declineyes:{chal_id}")
    b.button(text="Продолжить челлендж", callback_data=f"chal:{chal_id}")
    b.adjust("1")
    return b.as_markup()


def point_a_keyboard(chal_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="⏭ Пропустить", callback_data=f"pointA:skip:{chal_id}")
    return b.as_markup()


TIME_PRESETS = ["09:00", "12:00", "18:00", "21:00"]


def time_keyboard(chal_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for t in TIME_PRESETS:
        b.button(text=t, callback_data=f"time:set:{chal_id}:{t}")
    b.button(text="Выбрать своё время", callback_data=f"time:custom:{chal_id}")
    b.adjust("2", "2", "1")
    return b.as_markup()


def note_keyboard(chal_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="Пропустить", callback_data=f"note:skip:{chal_id}")
    return b.as_markup()


def subscribe_keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.button(text="💳 Вступить в клуб", callback_data="pay:choose")
    b.button(text="🗂 Личный кабинет", callback_data="cabinet")
    b.adjust("1")
    return b.as_markup()


# ------------------------------------------------------------ messages ----

async def subscription_text(db, user_id: int) -> str:
    sub = await storage.get_subscription(db, user_id)
    if not sub:
        return (
            "📅 <b>Срок подписки</b>\n\n"
            "У вас пока нет активной подписки.\n"
            "Нажмите «💳 Вступить в клуб», чтобы оформить участие."
        )
    from datetime import datetime, timezone as tz
    end = datetime.fromisoformat(sub["end_date"])
    if end.tzinfo is None:
        end = end.replace(tzinfo=tz.utc)
    now = datetime.now(tz.utc)
    if sub["status"] == "active" and end > now:
        left = await storage.days_left(sub)
        return (
            "📅 <b>Срок подписки</b>\n\n"
            f"Ваша подписка активна до <b>{_fmt_date(sub['end_date'])}</b>.\n"
            f"Осталось {left} {plural(left, 'день', 'дня', 'дней')}.\n\n"
            f"Тариф: {sub['plan']}\n"
            f"Начало: {_fmt_date(sub['start_date'])}\n"
            f"Способ оплаты: {sub['pay_method'] or '—'}\n"
            f"Автосписание: {'включено' if sub['auto_renew'] else 'выключено'}"
        )
    return (
        "📅 <b>Срок подписки</b>\n\n"
        f"Подписка истекла {_fmt_date(sub['end_date'])}.\n"
        "Для продления нажмите «💳 Вступить в клуб»."
    )


async def auto_renew_text(db, user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    sub = await storage.get_subscription(db, user_id)
    if not sub:
        return (
            "💳 <b>Автосписание</b>\n\nАвтосписание доступно участникам с активной подпиской.",
            back_cabinet_keyboard(),
        )
    on = bool(sub["auto_renew"])
    state = "включено ✅" if on else "выключено ❌"
    return (
        f"💳 <b>Автосписание</b>\n\nАвтосписание {state}.\n\n"
        "<i>При включённом автосписании бот автоматически продлевает подписку "
        "и отправляет ссылку на оплату за день до окончания.</i>",
        auto_renew_keyboard(on),
    )


async def challenges_overview(db, user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    days = config.CHALLENGE_DAYS
    intro = (await storage.get_content(db, "challenge_intro")).format(
        days=days, days_word=plural(days, "день", "дня", "дней")
    )
    rows = await storage.list_user_challenges(db, user_id)
    actives = [r for r in rows if r["status"] == "running"]
    lines = []
    if rows:
        lines.append("\n<b>Ваши челленджи:</b>")
        for c in rows:
            lines.append(f"• {ch.LABEL[c['type']]} — {await ch.status_line(db, c)}")
    limits = {}
    if not any(c["type"] == "common" and c["status"] in ("running", "pending_start") for c in rows):
        cs = await storage.get_common_state(db)
        if cs and cs["start_date"]:
            limits["common"] = True
    hm_done = max([c["month"] for c in rows
                   if c["type"] == "habit_month" and c["status"] == "completed"] or [0])
    next_m = hm_done + 1
    if next_m <= 6 and ch.can_add_new(actives, "habit_month"):
        has_pending_hm = any(c["type"] == "habit_month"
                             and c["status"] in ("running", "pending_start") for c in rows)
        habit = await ch.habit_for_month(db, next_m)
        if habit and not has_pending_hm:
            limits["habit_month"] = habit
    if ch.can_add_new(actives, "own_habit"):
        own_exists = any(c["type"] == "own_habit"
                         and c["status"] in ("running", "pending_start") for c in rows)
        if not own_exists:
            limits["own_habit"] = True
    if not rows and not limits:
        cs = await storage.get_common_state(db)
        if not cs or not cs["start_date"]:
            lines.append("\n<i>Общий челлендж ещё не назначен администратором — "
                         "это нормально, следите за анонсами.</i>")
    return intro + "\n".join(lines), challenges_menu_keyboard(rows, limits)


async def challenge_view(db, chal) -> tuple[str, InlineKeyboardMarkup]:
    title = await ch.display_title(db, chal)
    parts = [f"🔥 <b>{title}</b>", "", f"Статус: {await ch.status_line(db, chal)}"]
    if chal["start_date"]:
        parts.append(f"Старт: {chal['start_date']} · день {min(ch.day_number(chal), config.CHALLENGE_DAYS)}")
    parts.append(
        f"Точка А: {chal['point_a'] or 'не зафиксирована'}"
    )
    if chal["remind_hour"] is not None:
        parts.append(
            f"Напоминание: {chal['remind_hour']:02d}:{(chal['remind_minute'] or 0):02d}"
        )
    s = await storage.challenge_stats(db, chal)
    if s:
        parts.append(
            f"Выполнено {s['done']} · пропущено {s['skip']} · {s['pct']}% · серия 🔥{s['streak_cur']}"
        )
    return "\n".join(parts), ch_challenge_kb(chal)


def ch_challenge_kb(chal) -> InlineKeyboardMarkup:
    return challenge_keyboard(chal["id"], chal["status"])
