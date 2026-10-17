"""Фоновые задачи бота (APScheduler):

  • напоминания о челленджах — каждую минуту, срабатывают в выбранное
    пользователем время (один раз в день, отметка не требуется);
  • «не выполнил» по умолчанию — вечером: неотмеченный день приравнивается
    к пропуску (по ТЗ игнор = не выполнено; у нас он так и считается в
    статистике, отдельная запись не создаётся);
  • автопродление подписки (автосписание) — шлёт ссылку на оплату за день
    до окончания;
  • истечение подписок + отзыв доступа к чату.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .. import config, storage
from ..services import chat_access, challenges as ch
from . import user as user_handlers

log = logging.getLogger(__name__)


def create_scheduler(bot) -> AsyncIOScheduler:
    sched = AsyncIOScheduler(timezone=config.TIMEZONE)

    async def reminders():
        await user_handlers.send_due_reminders(bot)

    async def billing_tick():
        """Истечения подписок, автосписания, завершения челленджей."""
        db = user_handlers.db
        # 1. завершившиеся челленджи
        for chal in await storage.list_running_challenges(db):
            if await ch.check_completions(db, chal):
                fresh = await storage.get_challenge(db, chal["id"])
                s = await storage.challenge_stats(db, fresh)
                title = await ch.display_title(db, fresh)
                text = (
                    f"🏁 <b>Челлендж завершён!</b>\n{title}\n\n"
                    f"<b>Ваш результат</b>\n{s['total']} дней\n"
                    f"{s['done']} выполнений · {s['skip']} пропусков\n"
                    f"Успешность: {s['pct']}%\nЛучшая серия: {s['streak_best']} дней\n\n"
                )
                if fresh["type"] == "habit_month":
                    text += "Следующий месяц привычки открыт 🔓"
                else:
                    text += "Новый этап доступен в разделе «Челленджи»."
                try:
                    await bot.send_message(fresh["user_id"], text,
                                           reply_markup=user_handlers.kb.back_cabinet_keyboard())
                except Exception:  # noqa: BLE001
                    pass
        # 2. истёкшие подписки → статус + отзыв доступа к чату
        expired = await storage.expire_overdue(db)
        for uid in expired:
            try:
                await bot.send_message(
                    uid,
                    "⌛ Подписка клуба закончилась. Доступ к чату отозван.\n"
                    "Будем рады видеть тебя снова — продли участие в клуб 💙",
                    reply_markup=user_handlers.kb.subscribe_keyboard(),
                )
            except Exception:  # noqa: BLE001
                pass
            await chat_access.revoke_access(bot, uid)
        # 3. автосписание: за сутки до конца — ссылка на оплату продления
        due = await storage.list_autorenew_due(db)
        for sub in due:
            paid_recent = await db.execute_fetchall(
                "SELECT 1 FROM payments WHERE user_id = ? AND status='pending' "
                "AND created_at > ?",
                (sub["user_id"],
                 (datetime.now(ZoneInfo("UTC")) - timedelta(days=2)).isoformat()),
            )
            if paid_recent:
                continue  # уже послали ссылку недавно
            price = await storage.get_content(db, "plan_price")
            ru_url = await storage.get_content(db, "pay_ru_url")
            payload = await user_handlers.payments_create("ru_card", sub["user_id"])
            try:
                await bot.send_message(
                    sub["user_id"],
                    "💳 <b>Автосписание</b>\n\nПодписка заканчивается "
                    f"{sub['end_date'][:10]}. Чтобы продлить на 30 дней ({price} ₽), "
                    f"заверши оплату: <a href=\"{ru_url}\">оплатить</a>\n"
                    f"<code>ID платежа: {payload}</code>",
                    reply_markup=user_handlers.kb.payment_wait_keyboard(payload),
                )
            except Exception as e:  # noqa: BLE001
                log.warning("Автопродление для %s: %s", sub["user_id"], e)

    sched.add_job(reminders, "interval", minutes=1, id="reminders",
                  max_instances=1, coalesce=True)
    sched.add_job(billing_tick, "interval", minutes=config.BILLING_TICK_MINUTES,
                  id="billing", max_instances=1, coalesce=True)
    return sched
