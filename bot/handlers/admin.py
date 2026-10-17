"""Админка бота клуба: пользователи, контент, челленджи, оплата, рассылки.

Доступ только для администраторов (ADMIN_IDS в .env + таблица admins,
добавить через /admin <id>). Все тексты клуба редактируются здесь —
без пересборки кода.
"""
from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import config, storage
from ..services import challenges as ch
from ..services import chat_access, payments
from . import keyboards as kb
from .user import is_admin  # общая проверка прав

log = logging.getLogger(__name__)
router = Router(name="admin")

db = None            # инициализируется в main.py
bot: Bot | None = None


class AdminStates(StatesGroup):
    edit_content = State()       # ключ контента в data["key"]
    set_faq_q = State()          # ждём вопрос (data["index"] — менять/новый)
    set_faq_a = State()          # ждём ответ
    set_habit = State()          # месяц в data["month"]
    common_start = State()       # дата старта общего челленджа
    common_task = State()        # текст задания
    broadcast = State()          # текст рассылки
    add_admin = State()
    user_lookup = State()


CONTENT_KEYS = {
    "about_club": "ℹ️ Информация о клубе",
    "consent_text": "✅ Текст согласия (активация)",
    "rules": "📖 Правила участия",
    "challenge_intro": "🔥 Вступление в раздел челленджей",
    "point_a_prompt": "📍 Запрос точки А",
    "time_prompt": "⏰ Запрос времени напоминаний",
    "reminder_text": "🔔 Текст ежедневной напоминалки",
    "note_prompt": "📝 Запрос заметки к дню",
    "refusal_confirm": "⚠️ Подтверждение отказа",
    "payment_wait": "💳 Сообщение после выбора оплаты",
    "cabinet_header": "🗂 Шапка личного кабинета",
    "terms_url": "🔗 Ссылка: оферта",
    "privacy_url": "🔗 Ссылка: конфиденциальность",
    "pay_ru_url": "🔗 Ссылка: оплата картой РФ",
    "pay_intl_url": "🔗 Ссылка: иностранная карта",
    "plan_name": "🏷 Название тарифа",
    "plan_price": "💰 Цена тарифа (₽)",
}

# Ключи, где плейсхолдеры обязательны — подсказка админу
PLACEHOLDER_HINT = {
    "reminder_text": "{title} {day} {total} {series_line}",
    "point_a_prompt": "{days}",
    "challenge_intro": "{days} {days_word}",
    "refusal_confirm": "{title}",
    "consent_text": "{offer_url} {privacy_url}",
    "about_club": "{price} {days}",
}


async def _guard(message_or_cb) -> bool:
    uid = message_or_cb.from_user.id
    if await is_admin(uid):
        return True
    try:
        await message_or_cb.answer("⛔ У тебя нет доступа к админке.")
    except Exception:  # noqa: BLE001
        pass
    log.info("Попытка доступа в админку от %s", uid)
    return False


def admin_main_keyboard() -> "kb.InlineKeyboardMarkup":
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="👥 Пользователи", callback_data="adm:users")
    b.button(text="✏️ Контент и тексты", callback_data="adm:content")
    b.button(text="❓ FAQ", callback_data="adm:faq")
    b.button(text="🌱 Привычки месяца", callback_data="adm:habits")
    b.button(text="🔥 Общий челлендж", callback_data="adm:common")
    b.button(text="📣 Рассылка", callback_data="adm:broadcast")
    b.button(text="💳 Платежи / выдать доступ", callback_data="adm:payhelp")
    b.button(text="📊 Сводка клуба", callback_data="adm:summary")
    b.adjust("2", "2", "2", "1")
    return b.as_markup()


@router.message(Command("admin"))
async def cmd_admin(message: Message, command: CommandObject):
    if not await _guard(message):
        return
    if command and command.args:
        # /admin 123456 — добавить админа
        arg = command.args.strip()
        if arg.isdigit():
            await storage.add_admin(db, int(arg))
            await message.answer(f"✅ {arg} добавлен(а) в администраторы.")
            return
    await message.answer("🛠 <b>Админка клуба «Шесть месяцев»</b>",
                         reply_markup=admin_main_keyboard())


# ------------------------------------------------------------- сводка ----

@router.callback_query(F.data == "adm:summary")
async def cb_summary(cb: CallbackQuery):
    if not await _guard(cb):
        return
    total = await storage.count_users(db)
    members = await storage.list_active_members(db)
    running = await storage.list_running_challenges(db)
    payments_rows = await db.execute_fetchall(
        "SELECT COUNT(*) c FROM payments WHERE status='paid'"
    )
    text = (
        "📊 <b>Сводка клуба</b>\n\n"
        f"Всего пользователей: <b>{total}</b>\n"
        f"Активных подписок: <b>{len(members)}</b>\n"
        f"Запущенных челленджей: <b>{len(running)}</b>\n"
        f"Оплаченных платежей: <b>{payments_rows[0]['c']}</b>"
    )
    await cb.message.answer(text, reply_markup=admin_main_keyboard())
    await cb.answer()


# ---------------------------------------------------------- пользователи ----

@router.callback_query(F.data == "adm:users")
async def cb_users(cb: CallbackQuery):
    if not await _guard(cb):
        return
    rows = await storage.list_users(db, limit=20)
    lines = ["👥 <b>Пользователи (последние 20)</b>", ""]
    for r in rows:
        sub = "✅ активна" if r["sub_status"] == "active" else ("⌛ истекла" if r["sub_status"] else "— нет")
        src = r["source"] or "—"
        lines.append(
            f"<code>{r['user_id']}</code> {r['full_name'] or ''} · подписка: {sub} · источник: {src}"
        )
    if len(rows) > 20:
        lines.append("\n<i>Показать конкретного: /user &lt;id&gt;</i>")
    await cb.message.answer("\n".join(lines), reply_markup=admin_main_keyboard())
    await cb.answer()


@router.message(Command("user"))
async def cmd_user(message: Message, command: CommandObject, state: FSMContext):
    if not await _guard(message):
        return
    if not (command and command.args):
        await state.set_state(AdminStates.user_lookup)
        await message.answer("Напиши Telegram ID пользователя одним сообщением:")
        return
    try:
        uid = int(command.args.strip())
    except ValueError:
        await state.set_state(AdminStates.user_lookup)
        await message.answer("Это не число. Напиши Telegram ID пользователя:")
        return
    await show_user_card(message, uid)


@router.message(AdminStates.user_lookup, F.text)
async def user_lookup_input(message: Message, state: FSMContext):
    if not await _guard(message):
        return
    await state.clear()
    try:
        uid = int(message.text.strip())
    except ValueError:
        await message.answer("Нужен числовой Telegram ID, например 123456789")
        return
    await show_user_card(message, uid)


async def show_user_card(message: Message, uid: int):
    u = await storage.get_user(db, uid)
    if not u:
        await message.answer("Пользователь не найден.")
        return
    sub = await storage.get_subscription(db, uid)
    rows = await storage.list_user_challenges(db, uid)
    parts = [
        f"👤 <b>{u['full_name']}</b> (<code>{uid}</code>)",
        f"username: @{u['username'] or '—'} · источник: {u['source'] or '—'}",
        f"Первый вход: {u['first_seen'][:16]} · согласие: "
        f"{(u['consent_at'] or '—')[:16]}",
    ]
    if sub:
        parts.append(
            f"\n💳 Подписка: {sub['plan']} · {sub['status']} · до {sub['end_date'][:10]} · "
            f"метод: {sub['pay_method']} · автосписание: {'вкл' if sub['auto_renew'] else 'выкл'}"
        )
    if rows:
        parts.append("\n🔥 Челленджи:")
        for c in rows:
            s = await storage.challenge_stats(db, c)
            stat = f" · {s['done']}/{s['elapsed']} ✅" if s else ""
            parts.append(f"• {ch.LABEL[c['type']]} [{c['status']}]{stat}")
    else:
        parts.append("\nЧелленджей пока нет.")
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="✅ Выдать подписку вручную", callback_data=f"admgive:{uid}")
    b.button(text="← Админка", callback_data="adm:menu")
    await message.answer("\n".join(parts), reply_markup=b.as_markup())


@router.callback_query(F.data == "adm:menu")
async def cb_adm_menu(cb: CallbackQuery):
    if not await _guard(cb):
        return
    await cb.message.answer("🛠 <b>Админка</b>", reply_markup=admin_main_keyboard())
    await cb.answer()


@router.callback_query(F.data.startswith("admgive:"))
async def cb_give_sub(cb: CallbackQuery):
    """Ручная выдача подписки (например, оплата прошла на стороне ПС)."""
    if not await _guard(cb):
        return
    uid = int(cb.data.split(":")[1])
    plan = await storage.get_content(db, "plan_name")
    end = await storage.activate_subscription(
        db, uid, method="manual", payment_id=f"manual:{cb.from_user.id}",
        plan=plan, extend_from="1",
    )
    link = await chat_access.grant_access(bot, uid)
    await cb.message.answer(
        f"✅ Подписка выдана пользователю <code>{uid}</code> до {end.date().isoformat()}."
        + (f"\n🔗 Ссылка на чат: {link}" if link else "")
    )
    await cb.answer()


# ---------------------------------------------------------------- платежи ----

@router.callback_query(F.data == "adm:payhelp")
async def cb_payhelp(cb: CallbackQuery):
    if not await _guard(cb):
        return
    pend = await db.execute_fetchall(
        "SELECT invoice_id, user_id, provider, amount, currency FROM payments "
        "WHERE status='pending' ORDER BY created_at DESC LIMIT 10"
    )
    lines = ["💳 <b>Неподтверждённые платежи</b>", ""]
    if not pend:
        lines.append("Нет pending-платежей.")
    for p in pend:
        lines.append(
            f"<code>{p['invoice_id']}</code> · user {p['user_id']} · "
            f"{p['amount']} {p['currency']} ({p['provider']})"
        )
    lines.append(
        "\nПодтвердить оплату из внешней ПС: <code>/paid &lt;ID платежа&gt;</code>\n"
        "Выдать доступ вручную: <code>/user &lt;telegram id&gt;</code>"
    )
    await cb.message.answer("\n".join(lines), reply_markup=admin_main_keyboard())
    await cb.answer()


@router.message(Command("paid"))
async def cmd_paid(message: Message, command: CommandObject):
    """Ручное подтверждение платежа из внешней платёжной системы."""
    if not await _guard(message):
        return
    payload = (command.args or "").strip()
    result = await payments.fulfill_payment(db, payload)
    if result is None:
        await message.answer("Платёж с таким ID не найден. Проверь /adm:payhelp → 💳 Платежи.")
        return
    if result["cached"]:
        await message.answer("Этот платёж уже был проведён ранее.")
        return
    uid = result["user_id"]
    link = await chat_access.grant_access(bot, uid)
    try:
        await bot.send_message(
            uid,
            "🎉 <b>Оплата подтверждена! Подписка активирована.</b>\n\n"
            "Добро пожаловать в клуб 💙"
            + (f'\n💬 Ссылка на закрытый чат: <a href="{link}">войти</a>' if link else ""),
            reply_markup=kb.cabinet_keyboard(True),
        )
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось уведомить %s об оплате: %s", uid, e)
    await message.answer(f"✅ Платёж {payload} проведён, подписка активирована для {uid}.")


# ---------------------------------------------------------------- контент ----

@router.callback_query(F.data == "adm:content")
async def cb_content_menu(cb: CallbackQuery):
    if not await _guard(cb):
        return
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    for key, label in CONTENT_KEYS.items():
        b.button(text=label, callback_data=f"admce:{key}")
    b.button(text="← Админка", callback_data="adm:menu")
    b.adjust("1")
    await cb.message.answer("✏️ <b>Что редактируем?</b> Текущие значения — в БД, меняются сразу для всех.",
                             reply_markup=b.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("admce:"))
async def cb_content_edit(cb: CallbackQuery, state: FSMContext):
    if not await _guard(cb):
        return
    key = cb.data.split(":")[1]
    value = await storage.get_content(db, key)
    hint = PLACEHOLDER_HINT.get(key)
    tip = f"\n\n<i>Доступные подстановки: {hint}</i>" if hint else ""
    await state.set_state(AdminStates.edit_content)
    await state.update_data(key=key)
    await cb.message.answer(
        f"🔑 <code>{key}</code>\n\n<b>Текущий текст:</b>\n{value}{tip}\n\n"
        "Отправь новым сообщением новый текст (или /cancel):",
    )
    await cb.answer()


@router.message(AdminStates.edit_content, F.text)
async def content_input(message: Message, state: FSMContext):
    if not await _guard(message):
        return
    data = await state.get_data()
    await storage.set_content(db, data["key"], message.text)
    await state.clear()
    await message.answer(f"✅ Сохранено: <code>{data['key']}</code>.")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено ✅")


# ------------------------------------------------------------------- FAQ ----

@router.callback_query(F.data == "adm:faq")
async def cb_faq_menu(cb: CallbackQuery, state: FSMContext):
    if not await _guard(cb):
        return
    items = await storage.get_json_content(db, "faq_json", [])
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    for i, (q, _a) in enumerate(items):
        b.button(text=f"{i + 1}. {q[:40]}", callback_data=f"admfaq:{i}")
    b.button(text="➕ Добавить вопрос", callback_data="admfaq:new")
    b.button(text="← Админка", callback_data="adm:menu")
    b.adjust("1")
    await cb.message.answer("❓ <b>FAQ клуба</b> — выбери вопрос для редактирования:",
                            reply_markup=b.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("admfaq:"))
async def cb_faq_edit(cb: CallbackQuery, state: FSMContext):
    if not await _guard(cb):
        return
    arg = cb.data.split(":")[1]
    items = await storage.get_json_content(db, "faq_json", [])
    if arg == "new":
        await state.set_state(AdminStates.set_faq_q)
        await state.update_data(index=len(items))
        await cb.message.answer("Напиши <b>вопрос</b>:")
    else:
        i = int(arg)
        await state.set_state(AdminStates.set_faq_q)
        await state.update_data(index=i)
        await cb.message.answer(
            f"Вопрос {i + 1}: «{items[i][0]}»\nОтвет: {items[i][1][:200]}\n\n"
            "Напиши новый <b>вопрос</b> (или /cancel):"
        )
    await cb.answer()


@router.message(AdminStates.set_faq_q, F.text)
async def faq_q_input(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.set_state(AdminStates.set_faq_a)
    await state.update_data(q=message.text.strip())
    await message.answer("Теперь напиши <b>ответ</b> (можно {price}):")


@router.message(AdminStates.set_faq_a, F.text)
async def faq_a_input(message: Message, state: FSMContext):
    data = await state.get_data()
    items = await storage.get_json_content(db, "faq_json", [])
    idx = data["index"]
    new_q, new_a = data["q"], message.text.strip()
    if idx < len(items):
        items[idx] = [new_q, new_a]
    else:
        items.append([new_q, new_a])
    await storage.set_json_content(db, "faq_json", items)
    await state.clear()
    await message.answer(f"✅ FAQ обновлён. Вопрос: «{new_q[:60]}»")


# ------------------------------------------------------- привычки месяца ----

@router.callback_query(F.data == "adm:habits")
async def cb_habits(cb: CallbackQuery):
    if not await _guard(cb):
        return
    habits = await storage.get_json_content(db, "habits_json", [])
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    for h in habits:
        b.button(text=f"М{h['month']}: {h['habit'][:30]}", callback_data=f"admhab:{h['month']}")
    for m in range(len(habits) + 1, 7):
        b.button(text=f"➕ Месяц {m}", callback_data=f"admhab:{m}")
    b.button(text="← Админка", callback_data="adm:menu")
    b.adjust("1")
    await cb.message.answer("🌱 <b>Привычки по месяцам</b> (6 месяцев клуба):",
                            reply_markup=b.as_markup())
    await cb.answer()


@router.callback_query(F.data.startswith("admhab:"))
async def cb_habit_edit(cb: CallbackQuery, state: FSMContext):
    if not await _guard(cb):
        return
    month = int(cb.data.split(":")[1])
    habits = await storage.get_json_content(db, "habits_json", [])
    cur = next((h["habit"] for h in habits if h["month"] == month), None)
    await state.set_state(AdminStates.set_habit)
    await state.update_data(month=month)
    await cb.message.answer(
        f"Месяц {month}: {cur or '— не задана —'}\n\nНапиши новую привычку:"
    )
    await cb.answer()


@router.message(AdminStates.set_habit, F.text)
async def habit_input(message: Message, state: FSMContext):
    data = await state.get_data()
    month = data["month"]
    habits = await storage.get_json_content(db, "habits_json", [])
    habits = [h for h in habits if h["month"] != month]
    habits.append({"month": month, "habit": message.text.strip()})
    habits.sort(key=lambda h: h["month"])
    await storage.set_json_content(db, "habits_json", habits)
    await state.clear()
    await message.answer(f"✅ Привычка месяца {month} сохранена.")


# ------------------------------------------------------ общий челлендж ----

@router.callback_query(F.data == "adm:common")
async def cb_common(cb: CallbackQuery):
    if not await _guard(cb):
        return
    cs = await storage.get_common_state(db)
    start = cs["start_date"] if cs and cs["start_date"] else "не назначен"
    task = (cs["task"] if cs and cs["task"] else
            await storage.get_content(db, "common_task"))
    participants = await db.execute_fetchall(
        "SELECT COUNT(*) c FROM challenges WHERE type='common' AND status IN ('running','pending_start')"
    )
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    b = InlineKeyboardBuilder()
    b.button(text="📅 Дата старта", callback_data="admcom:start")
    b.button(text="📝 Текст задания", callback_data="admcom:task")
    b.button(text="🚀 Старт сейчас + рассылка всем", callback_data="admcom:launch")
    b.button(text="← Админка", callback_data="adm:menu")
    b.adjust("1")
    await cb.message.answer(
        f"🔥 <b>Общий челлендж</b>\n\nСтарт: <b>{start}</b>\nЗадание: {task}\n"
        f"Участников: {participants[0]['c']}",
        reply_markup=b.as_markup(),
    )
    await cb.answer()


@router.callback_query(F.data == "admcom:start")
async def cb_common_start_ask(cb: CallbackQuery, state: FSMContext):
    if not await _guard(cb):
        return
    await state.set_state(AdminStates.common_start)
    await cb.message.answer("Введи дату старта в формате <b>ГГГГ-ММ-ДД</b> (например 2026-11-01):")
    await cb.answer()


@router.message(AdminStates.common_start, F.text)
async def common_start_input(message: Message, state: FSMContext):
    import datetime as dt
    try:
        d = dt.date.fromisoformat(message.text.strip())
    except ValueError:
        await message.answer("Не понял дату. Формат: ГГГГ-ММ-ДД")
        return
    await storage.set_common_state(db, d.isoformat(), None)
    await state.clear()
    await message.answer(f"✅ Старт общего челленджа назначен на {d.isoformat()}.")


@router.callback_query(F.data == "admcom:task")
async def cb_common_task_ask(cb: CallbackQuery, state: FSMContext):
    if not await _guard(cb):
        return
    await state.set_state(AdminStates.common_task)
    await cb.message.answer("Введи новый текст задания общим сообщением:")
    await cb.answer()


@router.message(AdminStates.common_task, F.text)
async def common_task_input(message: Message, state: FSMContext):
    await storage.set_common_state(db, None, message.text.strip())
    await storage.set_content(db, "common_task", message.text.strip())
    await state.clear()
    await message.answer("✅ Задание сохранено.")


@router.callback_query(F.data == "admcom:launch")
async def cb_common_launch(cb: CallbackQuery):
    """Мгновенный старт + автоматическая рассылка всем участникам с подпиской."""
    if not await _guard(cb):
        return
    today = storage.local_today().isoformat()
    await storage.set_common_state(db, today, None)
    sent = 0
    rows = await storage.list_pending_common(db, today)
    for r in rows:
        uid = r["user_id"]
        chal_id = await storage.create_challenge(db, uid, "common",
                                                 status="pending_start", start_date=today)
        await storage.start_challenge(db, chal_id, today)
        try:
            await bot.send_message(
                uid,
                "🚀 <b>Общий челлендж стартует сегодня!</b>\n\n"
                "Все участники идут вместе. Если хочешь заранее настроить "
                "точку А и время напоминаний — открой «🔥 Челленджи» в личном кабинете.",
                reply_markup=kb.cabinet_keyboard(True),
            )
            sent += 1
        except Exception:  # noqa: BLE001
            pass
    await cb.message.answer(
        f"🚀 Общий челлендж запущен на {today}. Уведомлено участников: {sent}."
    )
    await cb.answer()


# ------------------------------------------------------------- рассылка ----

@router.callback_query(F.data == "adm:broadcast")
async def cb_broadcast_ask(cb: CallbackQuery, state: FSMContext):
    if not await _guard(cb):
        return
    await state.set_state(AdminStates.broadcast)
    await cb.message.answer(
        "📣 Напиши текст рассылки — он уйдёт всем пользователям бота "
        "(HTML-разметка поддерживается). /cancel — отмена."
    )
    await cb.answer()


@router.message(AdminStates.broadcast, F.text)
async def broadcast_input(message: Message, state: FSMContext):
    if not await _guard(message):
        return
    await state.clear()
    text = message.text
    users = await storage.list_users(db, limit=100000)
    ok = fail = 0
    for u in users:
        try:
            await bot.send_message(u["user_id"], text)
            ok += 1
        except Exception:  # noqa: BLE001
            fail += 1
    await message.answer(f"📣 Рассылка готова: доставлено {ok}, ошибок {fail}.")
