"""Логика челленджей: выбор, точка А, время напоминаний, отметки, статистика.

Правило ТЗ: одновременно можно вести максимум два челленджа —
Общий + (Привычка месяца ИЛИ Своя привычка).
"""
from __future__ import annotations

from datetime import date

from .. import config, storage

LABEL = storage.CHAL_LABEL


async def active_challenges(db, user_id: int) -> list:
    rows = await storage.list_user_challenges(db, user_id)
    return [r for r in rows if r["status"] == "running"]


def can_add_new(actives: list, new_type: str) -> bool:
    """Проверка комбинаций из ТЗ."""
    types = {c["type"] for c in actives}
    if len(types) >= 2:
        return False
    non_common = types - {"common"}
    if new_type != "common" and non_common:  # привычка месяца и своя — нельзя вместе
        return False
    return True


async def next_habit_month(db, user_id: int) -> int:
    """Следующий доступный месяц привычки: 1 или после завершённого предыдущего."""
    last_done = 0
    rows = await storage.list_user_challenges(db, user_id)
    for r in rows:
        if r["type"] == "habit_month" and r["status"] == "completed":
            last_done = max(last_done, r["month"])
    return last_done + 1


async def habit_for_month(db, month: int) -> str | None:
    habits = await storage.get_json_content(db, "habits_json", [])
    for h in habits:
        if int(h.get("month", 0)) == month:
            return h.get("habit")
    return None


async def challenge_title(chal) -> str:
    if chal["type"] == "habit_month":
        return f"Привычка месяца {chal['month']}: {chal['habit'] or ''}".strip()
    if chal["type"] == "own_habit":
        return chal["habit"] or "Своя привычка"
    task = ""
    return LABEL["common"]


async def display_title(db, chal) -> str:
    """Название челленджа для сообщений (подставляется в ветку напоминаний)."""
    if chal["type"] == "common":
        cs = await storage.get_common_state(db)
        task = (cs["task"] if cs else None) or await storage.get_content(db, "common_task")
        return f"Общий челлендж «{task}»"
    if chal["type"] == "habit_month":
        return f"Привычка месяца — «{chal['habit']}»"
    return f"Своя привычка — «{chal['habit']}»"


def day_number(chal) -> int:
    """Текущий день челленджа (1..N)."""
    return storage.current_day(chal["start_date"])


async def status_line(db, chal) -> str:
    """Короткая строка статуса челленджа для меню."""
    st = chal["status"]
    if st == "pending_start":
        return "ожидает старта (нужны точка А и время)"
    if st == "declined":
        return "отклонён"
    if st == "completed":
        s = await storage.challenge_stats(db, chal)
        return f"завершён · {s['pct']}% выполнения" if s else "завершён"
    if st == "running":
        d = day_number(chal)
        s = await storage.challenge_stats(db, chal)
        extra = f" · серия 🔥{s['streak_cur']}" if s else ""
        return f"день {min(d, config.CHALLENGE_DAYS)} из {config.CHALLENGE_DAYS}{extra}"
    return st


async def stats_text(db, chal) -> str:
    """«Моя динамика» по формату ТЗ."""
    s = await storage.challenge_stats(db, chal)
    title = await display_title(db, chal)
    if s is None:
        return (
            f"🔥 <b>{title}</b>\n\n"
            "Челлендж ещё не начат — статистика появится после старта."
        )
    return (
        f"🔥 <b>Ваша динамика</b>\n<b>{title}</b>\n\n"
        f"Дней прошло: <b>{s['elapsed']}</b> из {s['total']}\n"
        f"Выполнено: <b>{s['done']}</b>\n"
        f"Пропущено: <b>{s['skip']}</b>\n"
        f"Процент выполнения: <b>{s['pct']}%</b>\n"
        f"Текущая серия: <b>{s['streak_cur']} "
        f"{storage_plural(s['streak_cur'])}</b>\n"
        f"Лучшая серия: <b>{s['streak_best']} "
        f"{storage_plural(s['streak_best'])}</b>"
    )


def storage_plural(n: int) -> str:
    mod10, mod100 = n % 10, n % 100
    if mod10 == 1 and mod100 != 11:
        return "день"
    if 2 <= mod10 <= 4 and not 12 <= mod100 <= 14:
        return "дня"
    return "дней"


def plural_days(n: int) -> str:
    return storage_plural(n)


async def check_completions(db, chal) -> bool:
    """Если 30 дней истекли — завершает челлендж. True, если завершён."""
    if chal["status"] != "running" or not chal["start_date"]:
        return False
    start = storage.parse_dt(chal["start_date"]).date()
    today = storage.local_today()
    if (today - start).days >= config.CHALLENGE_DAYS:
        await storage.complete_challenge(db, chal["id"])
        return True
    return False
