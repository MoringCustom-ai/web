"""Хендлеры пользовательской воронки клуба «Шесть месяцев».

Этапы: /start (источник) → активация (согласие) → информация о клубе → FAQ →
оплата → подписка → личный кабинет → челленджи (точка А → время → 30 дней →
статистика) → чат клуба.
"""
from __future__ import annotations

import logging
import re
import uuid

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           LabeledPrice, Message, PreCheckoutQuery,
                           SuccessfulPayment)

from .. import config, storage
from ..services import challenges as ch
from ..services import chat_access, funnel
from . import keyboards as kb

log = logging.getLogger(__name__)
router = Router(name="user")

# Общие объекты, инициализируются в main.py
db = None            # aiosqlite.Connection
bot: Bot | None = None


class ChalStates(StatesGroup):
    point_a = State()          # ждём текст точки А
    own_habit = State()        # ждём название своей привычки
    custom_time = State()      # ждём своё время ЧЧ:ММ
    day_note = State()         # ждём заметку к дню
    confirm_habit = State()    # подтверждение готовности (привычка месяца)


SOURCE_MAP = {
    "ig": "Instagram", "insta": "Instagram", "instagram": "Instagram",
    "tg": "Telegram", "telegram": "Telegram",
    "yt": "YouTube", "youtube": "YouTube",
    "vk": "VK", "ok": "OK",
}


def parse_source(payload: str | None) -> str | None:
    """/start ig_deep → 'Instagram' (UTM-подобная метка источника перехода)."""
    if not payload:
        return None
    tag = payload.split("_")[0].lower()
    return SOURCE_MAP.get(tag, payload[:64])


async def is_admin(user_id: int) -> bool:
    return user_id in await storage.list_admin_ids(db)


# ------------------------------------------------------------- воронка ----

async def _entry(message: Message, source: str | None):
    """Общий вход: регистрация + показ этапа воронки по состоянию пользователя."""
    u = db and await storage.get_user(db, message.from_user.id)
    await storage.ensure_user(
        db, message.from_user.id, message.from_user.username,
        message.from_user.full_name, source,
    )
    user = await storage.get_user(db, message.from_user.id)
    if not user["consent_at"]:
        text = await funnel.consent_message(db)
        await message.answer(text, reply_markup=kb.consent_keyboard())
        return
    await show_info(message)


@router.message(CommandStart())
async def cmd_start(message: Message, command=None):
    args = (command.args or "").strip() if command and hasattr(command, "args") else ""
    await _entry(message, parse_source(args))


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "Я бот клуба «Шесть месяцев» 🧠\n\n"
        "/start — вернуться в меню клуба\n"
        "/cabinet — личный кабинет\n"
        "/challenges — мои челленджи\n"
        "/subscribe — вступить в клуб\n\n"
        "Если что-то непонятно — напишите сюда, администратор увидит."
    )


@router.message(Command("cabinet"))
async def cmd_cabinet(message: Message):
    await show_cabinet_message(message)


@router.message(Command("challenges"))
async def cmd_challenges(message: Message):
    if not await storage.subscription_active(db, message.from_user.id):
        await message.answer("Раздел доступен участникам с активной подпиской.\n"
                             "Оформите участие: /subscribe")
        return
    text, markup = await kb.challenges_overview(db, message.from_user.id)
    await message.answer(text, reply_markup=markup)


@router.message(Command("subscribe"))
async def cmd_subscribe(message: Message):
    await show_pay_choose(message)


@router.callback_query(F.data == "consent:ok")
async def cb_consent(cb: CallbackQuery):
    await storage.ensure_user(db, cb.from_user.id, cb.from_user.username,
                              cb.from_user.full_name)
    await storage.activate_user(db, cb.from_user.id)
    info = await funnel.about_message(db)
    await cb.message.edit_text(info, reply_markup=kb.info_keyboard())
    await cb.answer("Согласие сохранено ✅")


async def show_info(message: Message):
    info = await funnel.about_message(db)
    await message.answer(info, reply_markup=kb.info_keyboard())


@router.callback_query(F.data == "nav:about")
async def cb_about(cb: CallbackQuery):
    info = await funnel.about_message(db)
    await cb.message.answer(info, reply_markup=kb.info_keyboard())
    await cb.answer()


@router.callback_query(F.data == "nav:back_home")
async def cb_back_home(cb: CallbackQuery):
    await show_cabinet_cb(cb)
    await cb.answer()


# ------------------------------------------------------------------ FAQ ----

@router.callback_query(F.data == "faq")
async def cb_faq(cb: CallbackQuery):
    items = await funnel.faq_list(db)
    text = "❓ <b>Вопросы о клубе</b>\n\nВыбери вопрос — покажу ответ:"
    await cb.message.answer(text, reply_markup=kb.faq_keyboard(items))
    await cb.answer()


@router.callback_query(F.data.startswith("faq:"))
async def cb_faq_answer(cb: CallbackQuery):
    idx = int(cb.data.split(":")[1])
    res = await funnel.faq_answer(db, idx)
    if not res:
        await cb.answer("Вопрос не найден", show_alert=True)
        return
    q, a = res
    await cb.message.answer(f"❓ <b>{q}</b>\n\n{a}",
                            reply_markup=kb.faq_answer_keyboard(idx))
    await cb.answer()


# -------------------------------------------------------------- оплата ----

async def show_pay_choose(target: Message):
    price = await storage.get_content(db, "plan_price")
    plan = await storage.get_content(db, "plan_name")
    text = (
        f"💳 <b>Вступление в клуб</b>\n\n"
        f"Тариф: <b>{plan}</b> — {price} ₽\n\n"
        "Выберите способ оплаты:"
    )
    await target.answer(text, reply_markup=kb.pay_keyboard(True))


@router.callback_query(F.data == "pay:choose")
async def cb_pay_choose(cb: CallbackQuery):
    await show_pay_choose(cb.message)
    await cb.answer()


@router.callback_query(F.data.in_({"pay:ru_card", "pay:intl_card"}))
async def cb_pay_external(cb: CallbackQuery):
    method = cb.data.split(":")[1]
    key = "pay_ru_url" if method == "ru_card" else "pay_intl_url"
    url = await storage.get_content(db, key)
    payload = await payments_create(method, cb.from_user.id)
    wait = await storage.get_content(db, "payment_wait")
    from aiogram.utils.markdown import hlink
    await cb.message.answer(
        f"{wait}\n\n🔗 Ссылка для оплаты: {hlink('нажать здесь', url)}\n"
        f"<code>ID платежа: {payload}</code>",
        reply_markup=kb.payment_wait_keyboard(payload),
        disable_web_page_preview=True,
    )
    await cb.answer()


async def payments_create(method: str, user_id: int) -> str:
    from ..services import payments
    return await payments.create_external_payment(db, user_id, method)


@router.callback_query(F.data == "pay:stars")
async def cb_pay_stars(cb: CallbackQuery):
    from ..services import payments
    plan = await storage.get_content(db, "plan_name")
    payload = f"sub:{cb.from_user.id}:stars:{uuid.uuid4().hex[:8]}"
    try:
        await cb.message.answer_invoice(
            title=plan,
            description=await storage.get_content(db, "payment_comment"),
            payload=payload,
            provider_payload=payload,
            currency="XTR",
            prices=[LabeledPrice(label=plan, amount=config.STARS_PRICE)],
        )
        await storage.create_payment(
            db, invoice_id=payload, user_id=cb.from_user.id, provider="stars",
            amount=config.STARS_PRICE, currency="XTR", payload=payload,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("Не удалось отправить инвойс Stars: %s", e)
        await cb.answer("Оплата Stars недоступна для этого аккаунта", show_alert=True)
        return
    await cb.answer()


@router.pre_checkout_query()
async def pre_checkout(pc: PreCheckoutQuery):
    await pc.answer(ok=True)


@router.message(F.successful_payment)
async def successful_payment(message: Message):
    from ..services import payments
    sp: SuccessfulPayment = message.successful_payment
    result = await payments.fulfill_payment(db, sp.invoice_payload)
    if result is None:
        log.warning("Оплата с неизвестным payload: %s", sp.invoice_payload)
        return
    await after_payment(message.from_user.id, message, cached=result["cached"])


@router.callback_query(F.data.startswith("pay:check:"))
async def cb_check_payment(cb: CallbackQuery):
    """Проверка оплаты во внешней ПС без webhook: статус подтверждает админ
    (/paid <ID>) или используется тестовая оплата Stars."""
    payload = cb.data.split(":", 2)[2]
    payment = await storage.get_payment(db, payload)
    if payment is None:
        await cb.answer("Платёж не найден", show_alert=True)
        return
    if payment["status"] == "paid":
        await cb.answer("Оплата уже проведена ✅")
        await show_cabinet_cb(cb)
        return
    # платёж ещё pending — сверяем звёзды через Telegram (если это stars-инвойс)
    from ..services import payments as pay_svc
    if payment["provider"] == "stars":
        result = await pay_svc.fulfill_payment(db, payload)
        if result and not result["cached"]:
            await after_payment(cb.from_user.id, cb.message)
            await cb.answer("Оплата подтверждена ✅")
            return
    await cb.answer(
        "Оплата ещё не подтверждена.\nКак только платёж пройдёт — открою кабинет.",
        show_alert=True,
    )


async def after_payment(user_id: int, message: Message, cached: bool = False):
    """После успешной оплаты: кнопка Личный кабинет + доступ к чату."""
    link = await chat_access.grant_access(bot, user_id)
    text = ("🎉 <b>Оплата получена! Подписка активирована.</b>\n\n"
            "Добро пожаловать в клуб «Шесть месяцев» 💙")
    if link:
        text += f'\n\n💬 Твоя ссылка на закрытый чат: <a href="{link}">войти</a>'
    await message.answer(text, reply_markup=kb.cabinet_keyboard(True))


# ------------------------------------------------------- личный кабинет ----

async def show_cabinet_message(message: Message):
    header = await storage.get_content(db, "cabinet_header")
    active = await storage.subscription_active(db, message.from_user.id)
    if not active:
        sub = await storage.get_subscription(db, message.from_user.id)
        if sub:
            header += "\n\n⚠️ <b>Подписка истекла.</b> Продлите участие — " \
                      "кнопка «Вступить в клуб» ниже."
    await message.answer(header, reply_markup=kb.cabinet_keyboard(active))


async def show_cabinet_cb(cb: CallbackQuery):
    header = await storage.get_content(db, "cabinet_header")
    active = await storage.subscription_active(db, cb.from_user.id)
    if not active:
        header += "\n\n⚠️ <b>Подписка истекла или не оформлена.</b>"
    await cb.message.answer(header, reply_markup=kb.cabinet_keyboard(active))


@router.callback_query(F.data == "cabinet")
async def cb_cabinet(cb: CallbackQuery):
    await show_cabinet_cb(cb)
    if not await storage.subscription_active(db, cb.from_user.id):
        await cb.message.answer(
            "🔒 Разделы клуба доступны участникам с активной подпиской.\n"
            "Оформи участие — кнопкой ниже.",
            reply_markup=kb.subscribe_keyboard(),
        )
    await cb.answer()


@router.callback_query(F.data == "cab:sub")
async def cb_cab_sub(cb: CallbackQuery):
    text = await kb.subscription_text(db, cb.from_user.id)
    await cb.message.answer(text, reply_markup=kb.back_cabinet_keyboard())
    await cb.answer()


@router.callback_query(F.data == "cab:auto")
async def cb_cab_auto(cb: CallbackQuery):
    text, markup = await kb.auto_renew_text(db, cb.from_user.id)
    await cb.message.answer(text, reply_markup=markup)
    await cb.answer()


@router.callback_query(F.data.in_({"auto:on", "auto:off"}))
async def cb_auto_toggle(cb: CallbackQuery):
    on = cb.data == "auto:on"
    await storage.set_auto_renew(db, cb.from_user.id, on)
    text, markup = await kb.auto_renew_text(db, cb.from_user.id)
    await cb.message.answer(text, reply_markup=markup)
    await cb.answer(f"Автосписание {'включено' if on else 'выключено'}")


@router.callback_query(F.data == "cab:rules")
async def cb_cab_rules(cb: CallbackQuery):
    rules = await funnel.rules_message(db)
    await cb.message.answer(rules, reply_markup=kb.back_cabinet_keyboard())
    await cb.answer()


@router.callback_query(F.data == "cab:chat")
async def cb_cab_chat(cb: CallbackQuery):
    if not await storage.subscription_active(db, cb.from_user.id):
        await cb.answer("Подписка не активна — доступ к чату закрыт.", show_alert=True)
        return
    link = await chat_access.grant_access(bot, cb.from_user.id)
    if not link and not config.CHAT_BUTTON_URL:
        await cb.answer("Ссылка на чат ещё не настроена администратором.", show_alert=True)
        return
    await cb.message.answer(
        "💬 <b>Чат клуба «Шесть месяцев»</b>\n\n"
        "Закрытое пространство участников. Берегите друг друга 🤝",
        reply_markup=kb.chat_keyboard(link),
    )
    await cb.answer()


# ------------------------------------------------------------ челленджи ----

@router.callback_query(F.data == "cab:challenges")
async def cb_challenges(cb: CallbackQuery):
    if not await storage.subscription_active(db, cb.from_user.id):
        await cb.message.answer(
            "🔒 Челленджи доступны участникам с активной подпиской.",
            reply_markup=kb.subscribe_keyboard(),
        )
        await cb.answer()
        return
    text, markup = await kb.challenges_overview(db, cb.from_user.id)
    await cb.message.answer(text, reply_markup=markup)
    await cb.answer()


@router.callback_query(F.data.startswith("chalnew:"))
async def cb_chal_new(cb: CallbackQuery, state: FSMContext):
    ctype = cb.data.split(":")[1]
    if not await storage.subscription_active(db, cb.from_user.id):
        await cb.answer("Нужна активная подписка", show_alert=True)
        return
    actives = await ch.active_challenges(db, cb.from_user.id)
    if not ch.can_add_new(actives, ctype):
        await cb.answer(
            "Нельзя взять этот челлендж: одновременно доступно максимум два — "
            "Общий + (Привычка месяца ИЛИ Своя привычка).",
            show_alert=True,
        )
        return

    if ctype == "common":
        cs = await storage.get_common_state(db)
        if not cs or not cs["start_date"]:
            await cb.answer("Общий челлендж ещё не назначен администратором.",
                            show_alert=True)
            return
        chal_id = await storage.create_challenge(
            db, cb.from_user.id, "common", status="pending_start",
            start_date=cs["start_date"],
        )
    elif ctype == "habit_month":
        rows = await storage.list_user_challenges(db, cb.from_user.id)
        hm_done = max([c["month"] for c in rows
                       if c["type"] == "habit_month" and c["status"] == "completed"] or [0])
        month = hm_done + 1
        habit = await ch.habit_for_month(db, month)
        if not habit:
            await cb.answer("Привычка на следующий месяц ещё не подготовлена.",
                            show_alert=True)
            return
        chal_id = await storage.create_challenge(
            db, cb.from_user.id, "habit_month", month=month,
            status="pending_start", habit=habit,
        )
        text = (
            f"🌱 <b>Привычка месяца {month}</b>: «{habit}»\n\n"
            f"Это 30-дневный цикл: ежедневные напоминания, отметки и статистика.\n"
            "Подтверди, что готов(а) начать:"
        )
        from aiogram.utils.keyboard import InlineKeyboardBuilder
        b = InlineKeyboardBuilder()
        b.button(text="✅ Да, готов(а)", callback_data=f"hmconfirm:{chal_id}")
        b.button(text="Отмена", callback_data="cab:challenges")
        await cb.message.answer(text, reply_markup=b.as_markup())
        await cb.answer()
        return
    else:  # own_habit
        await state.set_state(ChalStates.own_habit)
        await cb.message.answer(
            "✍️ Введите привычку, которую хотите сформировать:\n"
            "<i>Например: Пить 2 л воды</i>",
        )
        await cb.answer()
        return
    await ask_point_a(cb.message, chal_id, state)
    await cb.answer()


@router.callback_query(F.data.startswith("hmconfirm:"))
async def cb_hm_confirm(cb: CallbackQuery, state: FSMContext):
    chal_id = int(cb.data.split(":")[1])
    chal = await storage.get_challenge(db, chal_id)
    if not chal or chal["user_id"] != cb.from_user.id:
        await cb.answer("Челлендж не найден", show_alert=True)
        return
    await ask_point_a(cb.message, chal_id, state)
    await cb.answer()


@router.message(ChalStates.own_habit, F.text)
async def own_habit_input(message: Message, state: FSMContext):
    habit = message.text.strip()[:120]
    if not habit:
        return
    await state.clear()
    chal_id = await storage.create_challenge(
        db, message.from_user.id, "own_habit", status="pending_start", habit=habit,
    )
    await message.answer(f"✅ Привычка «{habit}» сохранена.")
    await ask_point_a(message, chal_id, state)


async def ask_point_a(message: Message, chal_id: int, state: FSMContext):
    days = config.CHALLENGE_DAYS
    text = (await storage.get_content(db, "point_a_prompt")).format(days=days)
    await state.update_data(chal_id=chal_id)
    await state.set_state(ChalStates.point_a)
    await message.answer(text, reply_markup=kb.point_a_keyboard(chal_id))


@router.callback_query(F.data.startswith("pointA:skip:"))
async def cb_point_a_skip(cb: CallbackQuery, state: FSMContext):
    chal_id = int(cb.data.split(":")[2])
    await state.clear()
    await ask_time(cb.message, chal_id, state)
    await cb.answer("Пропущено")


@router.callback_query(F.data.startswith("pointA:") & ~F.data.startswith("pointA:skip:"))
async def cb_point_a_edit(cb: CallbackQuery, state: FSMContext):
    """Изменение точки А у запущенного челленджа."""
    chal_id = int(cb.data.split(":")[1])
    await state.update_data(chal_id=chal_id, edit_only=True)
    await state.set_state(ChalStates.point_a)
    await cb.message.answer(
        "📍 Напиши новый текст точки А одним сообщением:"
    )
    await cb.answer()


@router.message(ChalStates.point_a, F.text)
async def point_a_input(message: Message, state: FSMContext):
    data = await state.get_data()
    chal_id = data["chal_id"]
    text = message.text.strip()[:500]
    await storage.set_point_a(db, chal_id, text)
    was_edit = data.get("edit_only")
    await state.clear()
    chal = await storage.get_challenge(db, chal_id)
    if was_edit:
        await message.answer("✅ Точка А обновлена.",
                             reply_markup=kb.back_cabinet_keyboard())
        return
    await message.answer(f"✅ Точка А зафиксирована: «{text[:80]}»")
    await ask_time(message, chal_id, state)


async def ask_time(message: Message, chal_id: int, state: FSMContext):
    text = await storage.get_content(db, "time_prompt")
    await state.update_data(chal_id=chal_id)
    await message.answer(text, reply_markup=kb.time_keyboard(chal_id))


@router.callback_query(F.data.startswith("time:set:"))
async def cb_time_set(cb: CallbackQuery, state: FSMContext):
    _, _, chal_id_s, t = cb.data.split(":")
    chal_id = int(chal_id_s)
    hh, mm = map(int, t.split(":"))
    await storage.set_remind_time(db, chal_id, hh, mm)
    await state.clear()
    await finalize_setup(cb.message, chal_id)
    await cb.answer(f"Напоминание в {t}")


@router.callback_query(F.data.startswith("time:custom:"))
async def cb_time_custom(cb: CallbackQuery, state: FSMContext):
    chal_id = int(cb.data.split(":")[2])
    await state.update_data(chal_id=chal_id)
    await state.set_state(ChalStates.custom_time)
    await cb.message.answer("Напиши время в формате <b>ЧЧ:ММ</b> (например 07:30):")
    await cb.answer()


@router.callback_query(F.data.startswith("time:") & ~F.data.startswith("time:set:")
                       & ~F.data.startswith("time:custom:"))
async def cb_time_change_running(cb: CallbackQuery, state: FSMContext):
    """Кнопка «Изменить время» у активного челленджа."""
    chal_id = int(cb.data.split(":")[1])
    await state.update_data(chal_id=chal_id, edit_only=True)
    await ask_time(cb.message, chal_id, state)
    await cb.answer()


@router.message(ChalStates.custom_time, F.text)
async def custom_time_input(message: Message, state: FSMContext):
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", message.text.strip())
    if not m:
        await message.answer("Не понял время ⌛ Напиши в формате ЧЧ:ММ, например 07:30.")
        return
    data = await state.get_data()
    chal_id = data["chal_id"]
    await storage.set_remind_time(db, chal_id, int(m.group(1)), int(m.group(2)))
    edit_only = data.get("edit_only")
    await state.clear()
    if edit_only:
        await message.answer(f"⏰ Время напоминаний обновлено: {m.group(0)}",
                             reply_markup=kb.back_cabinet_keyboard())
        return
    await finalize_setup(message, chal_id)


async def finalize_setup(message: Message, chal_id: int):
    """Старт челленджа после настройки (для common — ждём дату старта от админа)."""
    chal = await storage.get_challenge(db, chal_id)
    if chal is None:
        return
    if chal["type"] == "common":
        cs = await storage.get_common_state(db)
        if cs and cs["start_date"]:
            await storage.start_challenge(db, chal_id, cs["start_date"])
            d = storage.current_day(cs["start_date"])
            if d >= 1:
                await message.answer(
                    "🚀 Общий челлендж подключён! Идём вместе со всем клубом — "
                    f"сегодня <b>день {min(d, config.CHALLENGE_DAYS)}</b>."
                )
            else:
                await message.answer(
                    "⏳ Ты записан в общий челлендж! Старт "
                    f"<b>{cs['start_date']}</b> — тогда же придёт первая напоминалка."
                )
            return
        await message.answer(
            "✅ Всё сохранено. Общий челлендж стартует, когда его запустит "
            "администратор — ты получишь сообщение автоматически.",
            reply_markup=kb.back_cabinet_keyboard(),
        )
        return
    await storage.start_challenge(db, chal_id)
    title = await ch.display_title(db, chal)
    await message.answer(
        f"🚀 <b>Челлендж запущен!</b>\n{title}\n\n"
        f"Сегодня <b>день 1 из {config.CHALLENGE_DAYS}</b>. Каждый день в "
        "выбранное время я буду спрашивать о выполнении. Отмечайся кнопками "
        "✅/❌ — можно с заметкой.\n\n"
        "Удачи! 💙",
        reply_markup=kb.back_cabinet_keyboard(),
    )


@router.callback_query(F.data.startswith("chal:"))
async def cb_chal_view(cb: CallbackQuery):
    chal_id = int(cb.data.split(":")[1])
    chal = await storage.get_challenge(db, chal_id)
    if not chal or chal["user_id"] != cb.from_user.id:
        await cb.answer("Челлендж не найден", show_alert=True)
        return
    if await ch.check_completions(db, chal):
        chal = await storage.get_challenge(db, chal_id)
    text, markup = await kb.challenge_view(db, chal)
    await cb.message.answer(text, reply_markup=markup)
    await cb.answer()


@router.callback_query(F.data.startswith("chalstart:"))
async def cb_chal_start(cb: CallbackQuery):
    chal_id = int(cb.data.split(":")[1])
    chal = await storage.get_challenge(db, chal_id)
    if not chal or chal["user_id"] != cb.from_user.id:
        await cb.answer("Челлендж не найден", show_alert=True)
        return
    if chal["status"] != "pending_start":
        await cb.answer("Челлендж уже в другом статусе", show_alert=True)
        return
    if chal["type"] == "common":
        await cb.answer("Общий челлендж стартует по расписанию администратора",
                        show_alert=True)
        return
    if chal["remind_hour"] is None:
        await cb.answer("Сначала настрой время напоминаний — вернись в раздел «Челленджи»",
                        show_alert=True)
        return
    await storage.start_challenge(db, chal_id)
    chal = await storage.get_challenge(db, chal_id)
    text, markup = await kb.challenge_view(db, chal)
    await cb.message.answer("🚀 Челлендж начат!\n\n" + text, reply_markup=markup)
    await cb.answer()


# --------------------------------------------------------- отметка дня ----

async def _mark_today(bot_obj: Bot, user_id: int, chal, done: bool,
                      note: str | None = None) -> str:
    day = ch.day_number(chal)
    if day > config.CHALLENGE_DAYS:
        day = config.CHALLENGE_DAYS
    await storage.set_mark(db, chal["id"], day, done, note)
    s = await storage.challenge_stats(db, chal)
    title = await ch.display_title(db, chal)
    if done:
        res = (f"✅ Отметка сохранена! <b>{title}</b> — день {day} выполнен.\n"
               f"Текущая серия: 🔥 {s['streak_cur']}")
    else:
        res = (f"❌ День {day} отмечен как пропущен. Ничего страшного — "
               "завтра новый день 💙")
    return res


@router.callback_query(F.data.startswith("mark:"))
async def cb_mark(cb: CallbackQuery, state: FSMContext):
    _, chal_id_s, val = cb.data.split(":")
    chal = await storage.get_challenge(db, int(chal_id_s))
    if not chal or chal["user_id"] != cb.from_user.id:
        await cb.answer("Челлендж не найден", show_alert=True)
        return
    if chal["status"] != "running":
        await cb.answer("Челлендж сейчас не активен", show_alert=True)
        return
    if await ch.check_completions(db, chal):
        await cb.answer("Челлендж завершён — посмотри результат 🏁", show_alert=True)
        return
    done = val == "1"
    res = await _mark_today(bot, cb.from_user.id, chal, done)
    await cb.message.answer(res)
    # необязательная заметка к дню
    await state.update_data(chal_id=chal["id"])
    await state.set_state(ChalStates.day_note)
    note_text = await storage.get_content(db, "note_prompt")
    await cb.message.answer(note_text, reply_markup=kb.note_keyboard(chal["id"]))
    await cb.answer()


@router.callback_query(F.data.startswith("note:skip:"))
async def cb_note_skip(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer("Ок!")


@router.message(ChalStates.day_note, F.text)
async def note_input(message: Message, state: FSMContext):
    data = await state.get_data()
    chal_id = data["chal_id"]
    await state.clear()
    chal = await storage.get_challenge(db, chal_id)
    if not chal or chal["status"] != "running":
        await message.answer("Челлендж не активен — заметку добавить нельзя.")
        return
    day = min(ch.day_number(chal), config.CHALLENGE_DAYS)
    marks = await storage.get_marks(db, chal_id)
    today_mark = marks.get(day)
    if today_mark is None:
        await message.answer("Сначала отметь сегодняшний день ✅/❌, потом добавляй заметку 🙂")
        return
    await storage.set_mark(db, chal_id, day, bool(today_mark[0]),
                           message.text.strip()[:500])
    await message.answer(f"📝 Заметка сохранена к дню {day}.")


@router.callback_query(F.data.startswith("stats:"))
async def cb_stats(cb: CallbackQuery):
    chal_id = int(cb.data.split(":")[1])
    chal = await storage.get_challenge(db, chal_id)
    if not chal or chal["user_id"] != cb.from_user.id:
        await cb.answer("Челлендж не найден", show_alert=True)
        return
    if await ch.check_completions(db, chal):
        chal = await storage.get_challenge(db, chal_id)
    text = await ch.stats_text(db, chal)
    if chal["status"] == "completed":
        text += "\n\n🏁 <b>Месяц завершён!</b> Следующий этап открыт в разделе «Челленджи»."
    await cb.message.answer(text, reply_markup=kb.back_cabinet_keyboard())
    await cb.answer()


@router.callback_query(F.data.startswith("decline:"))
async def cb_decline(cb: CallbackQuery):
    chal_id = int(cb.data.split(":")[1])
    chal = await storage.get_challenge(db, chal_id)
    if not chal or chal["user_id"] != cb.from_user.id:
        await cb.answer("Челлендж не найден", show_alert=True)
        return
    title = await ch.display_title(db, chal)
    text = (await storage.get_content(db, "refusal_confirm")).format(title=title)
    await cb.message.answer(text, reply_markup=kb.decline_confirm_keyboard(chal_id))
    await cb.answer()


@router.callback_query(F.data.startswith("declineyes:"))
async def cb_decline_yes(cb: CallbackQuery):
    chal_id = int(cb.data.split(":")[1])
    chal = await storage.get_challenge(db, chal_id)
    if not chal or chal["user_id"] != cb.from_user.id:
        await cb.answer("Челлендж не найден", show_alert=True)
        return
    await storage.decline_challenge(db, chal_id)
    await cb.message.answer(
        "⛔ Челлендж отключён: напоминания прекращены, история отметок сохранена.\n"
        "Можно снова активировать доступный челлендж в любой момент.",
        reply_markup=kb.back_cabinet_keyboard(),
    )
    await cb.answer()


# ------------------------------------------------------ напоминания ----

async def send_due_reminders(bot_obj: Bot):
    """Вызывается планировщиком каждую минуту: шлёт напоминания тем,
    у кого наступило выбранное время (по таймзоне TIMEZONE)."""
    global bot
    bot = bot_obj
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now_local = datetime.now(ZoneInfo(config.TIMEZONE))
    today_iso = now_local.date().isoformat()
    rows = await storage.list_running_challenges(db)
    for chal in rows:
        if chal["remind_hour"] is None:
            continue
        if chal["reminded_on"] == today_iso:
            continue
        if now_local.hour < chal["remind_hour"] or (
            now_local.hour == chal["remind_hour"]
            and now_local.minute < (chal["remind_minute"] or 0)
        ):
            continue
        day = ch.day_number(chal)
        if day > config.CHALLENGE_DAYS:
            continue  # завершение обработает billing tick
        marks = await storage.get_marks(db, chal["id"])
        if day in marks:
            await storage.update_challenge(db, chal["id"], reminded_on=today_iso)
            continue
        s = await storage.challenge_stats(db, chal)
        title = await ch.display_title(db, chal)
        series_line = (f"<i>Текущая серия: 🔥 {s['streak_cur']} · "
                       f"лучшая: {s['streak_best']}</i>" if s else "")
        tpl = await storage.get_content(db, "reminder_text")
        text = tpl.format(title=title, day=day, total=config.CHALLENGE_DAYS,
                          series_line=series_line)
        markup = kb.challenge_keyboard(chal["id"], "running")
        try:
            await bot_obj.send_message(chal["user_id"], text, reply_markup=markup)
            await storage.update_challenge(db, chal["id"], reminded_on=today_iso)
        except Exception as e:  # noqa: BLE001
            log.warning("Напоминалка %s не доставлена (%s): %s", chal["user_id"], chal["id"], e)
