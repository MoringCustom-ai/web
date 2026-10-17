"""Хранилище данных клуба (SQLite через aiosqlite).

Таблицы:
  users         — участники: telegram id, username, имя, источник перехода,
                  дата первого входа, активация, согласие и его дата
  subscriptions — подписки: тариф, даты начала/окончания, статус, способ
                  оплаты, автосписание, id платежа
  payments      — платежи: invoice_id, status, amount, currency
  challenges    — челленджи пользователя: тип, статус, даты, точка А,
                  привычка, время напоминания, отказ
  marks         — ежедневные отметки: done 1/0, note, day (1..N)
  common_state  — состояние общего челленджа клуба (дата старта, задание)
  content       — редактируемый контент (тексты, FAQ, правила, тарифы)
  admins        — id администраторов
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone as dt_timezone

import aiosqlite

from . import config
from .content import get_defaults

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    full_name   TEXT,
    source      TEXT,
    first_seen  TEXT NOT NULL,
    activated_at TEXT,
    consent_at  TEXT
);

CREATE TABLE IF NOT EXISTS subscriptions (
    user_id        INTEGER PRIMARY KEY,
    plan           TEXT NOT NULL,
    paid_at        TEXT,
    start_date     TEXT NOT NULL,          -- ISO datetime начала подписки
    end_date       TEXT NOT NULL,          -- ISO datetime окончания
    status         TEXT NOT NULL,          -- active | expired
    pay_method     TEXT,                   -- ru_card | intl_card | stars
    auto_renew     INTEGER NOT NULL DEFAULT 1,
    payment_id     TEXT
);

CREATE TABLE IF NOT EXISTS payments (
    invoice_id TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    provider   TEXT NOT NULL,              -- external | stars
    amount     INTEGER NOT NULL,
    currency   TEXT NOT NULL,              -- XTR | RUB
    payload    TEXT,
    status     TEXT NOT NULL,              -- pending | paid | failed
    created_at TEXT NOT NULL,
    paid_at    TEXT
);

CREATE TABLE IF NOT EXISTS challenges (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id        INTEGER NOT NULL,
    type           TEXT NOT NULL,          -- common | habit_month | own_habit
    month          INTEGER NOT NULL DEFAULT 1,   -- номер месяца для habit_month
    status         TEXT NOT NULL,          -- pending_start | running | completed | declined
    start_date     TEXT,                   -- ISO-дата дня 1
    point_a        TEXT,
    habit          TEXT,
    remind_hour    INTEGER,
    remind_minute  INTEGER,
    reminded_on    TEXT,                   -- ISO-дата последней напоминалки
    declined_at    TEXT,
    completed_at   TEXT,
    UNIQUE (user_id, type, month)
);

CREATE TABLE IF NOT EXISTS marks (
    user_id  INTEGER NOT NULL,
    chal_id  INTEGER NOT NULL,
    day      INTEGER NOT NULL,             -- 1..CHALLENGE_DAYS
    done     INTEGER NOT NULL,             -- 1 выполнил / 0 не выполнил
    note     TEXT,
    marked_at TEXT NOT NULL,
    PRIMARY KEY (chal_id, day),
    FOREIGN KEY (chal_id) REFERENCES challenges (id)
);

CREATE TABLE IF NOT EXISTS common_state (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    start_date TEXT,                       -- ISO-дата старта общего челленджа
    task       TEXT
);

CREATE TABLE IF NOT EXISTS content (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admins (
    user_id INTEGER PRIMARY KEY
);
"""

CHAL_TYPES = {"common", "habit_month", "own_habit"}
CHAL_LABEL = {
    "common": "Общий челлендж",
    "habit_month": "Привычка месяца",
    "own_habit": "Своя привычка",
}


def now() -> datetime:
    return datetime.now(dt_timezone.utc)


def local_today(tz_name: str | None = None) -> date:
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(tz_name or config.TIMEZONE)).date()


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(config.DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA foreign_keys = ON")
    await db.executescript(SCHEMA)
    await seed_content(db)
    await db.commit()
    return db


# ---------------------------------------------------------------- content ----

async def seed_content(db):
    """Загружает тексты по умолчанию в таблицу content (не перезаписывает)."""
    for key, value in get_defaults().items():
        await db.execute(
            "INSERT OR IGNORE INTO content (key, value) VALUES (?, ?)", (key, value)
        )


async def get_content(db, key: str, default: str = "") -> str:
    rows = await db.execute_fetchall("SELECT value FROM content WHERE key = ?", (key,))
    if rows:
        return rows[0]["value"]
    return get_defaults().get(key, default)


async def set_content(db, key: str, value: str):
    await db.execute(
        "INSERT INTO content (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    await db.commit()


async def get_json_content(db, key: str, default):
    raw = await get_content(db, key)
    try:
        return json.loads(raw) if raw else default
    except json.JSONDecodeError:
        return default


async def set_json_content(db, key: str, value):
    await set_content(db, key, json.dumps(value, ensure_ascii=False))


# ----------------------------------------------------------------- users ----

async def ensure_user(db, user_id: int, username: str | None, full_name: str,
                      source: str | None = None):
    """Регистрирует пользователя при первом входе; обновляет данные профиля."""
    rows = await db.execute_fetchall(
        "SELECT user_id, source FROM users WHERE user_id = ?", (user_id,)
    )
    if not rows:
        await db.execute(
            "INSERT INTO users (user_id, username, full_name, source, first_seen) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, username, full_name, source, now().isoformat()),
        )
    else:
        new_source = source or (rows[0]["source"] if rows[0]["source"] else None)
        await db.execute(
            "UPDATE users SET username = ?, full_name = ?, source = ? WHERE user_id = ?",
            (username, full_name, new_source, user_id),
        )
    await db.commit()


async def activate_user(db, user_id: int):
    """Сохраняет факт согласия и дату активации (идемпотентно)."""
    ts = now().isoformat()
    await db.execute(
        "UPDATE users SET consent_at = COALESCE(consent_at, ?), "
        "activated_at = COALESCE(activated_at, ?) WHERE user_id = ?",
        (ts, ts, user_id),
    )
    await db.commit()


async def get_user(db, user_id: int) -> aiosqlite.Row | None:
    rows = await db.execute_fetchall("SELECT * FROM users WHERE user_id = ?", (user_id,))
    return rows[0] if rows else None


async def list_users(db, limit: int = 50, offset: int = 0) -> list[aiosqlite.Row]:
    return await db.execute_fetchall(
        """
        SELECT u.*, s.plan, s.end_date, s.status AS sub_status, s.auto_renew
        FROM users u LEFT JOIN subscriptions s ON s.user_id = u.user_id
        ORDER BY u.first_seen DESC LIMIT ? OFFSET ?
        """,
        (limit, offset),
    )


async def count_users(db) -> int:
    rows = await db.execute_fetchall("SELECT COUNT(*) c FROM users")
    return rows[0]["c"]


# ------------------------------------------------------------------- ads ----

async def add_admin(db, user_id: int):
    await db.execute("INSERT OR IGNORE INTO admins (user_id) VALUES (?)", (user_id,))
    await db.commit()


async def remove_admin(db, user_id: int):
    await db.execute("DELETE FROM admins WHERE user_id = ?", (user_id,))
    await db.commit()


async def list_admin_ids(db) -> set[int]:
    rows = await db.execute_fetchall("SELECT user_id FROM admins")
    return {r["user_id"] for r in rows} | config.ADMIN_IDS


# ---------------------------------------------------------- subscription ----

async def get_subscription(db, user_id: int) -> aiosqlite.Row | None:
    rows = await db.execute_fetchall(
        "SELECT * FROM subscriptions WHERE user_id = ?", (user_id,)
    )
    return rows[0] if rows else None


async def subscription_active(db, user_id: int) -> bool:
    sub = await get_subscription(db, user_id)
    if not sub:
        return False
    return sub["status"] == "active" and datetime.fromisoformat(sub["end_date"]) > now()


async def days_left(sub: aiosqlite.Row) -> int:
    delta = datetime.fromisoformat(sub["end_date"]) - now()
    return max(delta.days + (1 if delta.seconds else 0), 0)


async def activate_subscription(db, user_id: int, *, method: str, payment_id: str,
                                plan: str,
                                extend_from: str | None = None) -> datetime:
    """Создаёт или продлевает подписку. Возвращает datetime окончания."""
    sub = await get_subscription(db, user_id)
    base = now()
    if sub and sub["status"] == "active" and extend_from:
        base = max(base, datetime.fromisoformat(sub["end_date"]))
    end = base + timedelta(days=config.SUBSCRIPTION_DAYS)
    if sub:
        await db.execute(
            "UPDATE subscriptions SET plan=?, paid_at=?, start_date=?, end_date=?, "
            "status='active', pay_method=?, payment_id=? WHERE user_id=?",
            (plan, now().isoformat(), base.isoformat(), end.isoformat(),
             method, payment_id, user_id),
        )
    else:
        await db.execute(
            "INSERT INTO subscriptions (user_id, plan, paid_at, start_date, end_date, "
            "status, pay_method, auto_renew, payment_id) "
            "VALUES (?, ?, ?, ?, ?, 'active', ?, 1, ?)",
            (user_id, plan, now().isoformat(), base.isoformat(), end.isoformat(),
             method, payment_id),
        )
    await db.commit()
    return end


async def set_auto_renew(db, user_id: int, on: bool):
    await db.execute(
        "UPDATE subscriptions SET auto_renew = ? WHERE user_id = ?",
        (1 if on else 0, user_id),
    )
    await db.commit()


async def expire_overdue(db) -> list[int]:
    """Помечает истёкшие подписки; возвращает id пользователей."""
    rows = await db.execute_fetchall(
        "SELECT user_id FROM subscriptions WHERE status='active' AND end_date <= ?",
        (now().isoformat(),),
    )
    ids = [r["user_id"] for r in rows]
    if ids:
        await db.execute(
            f"UPDATE subscriptions SET status='expired' WHERE user_id IN "
            f"({','.join('?' * len(ids))})", ids,
        )
        await db.commit()
    return ids


async def list_autorenew_due(db) -> list[aiosqlite.Row]:
    """Активные подписки с автосписанием, истекающие в ближайшие сутки."""
    horizon = (now() + timedelta(days=1)).isoformat()
    return await db.execute_fetchall(
        "SELECT * FROM subscriptions WHERE status='active' AND auto_renew=1 "
        "AND end_date <= ?",
        (horizon,),
    )


# ---------------------------------------------------------------- payment ----

async def create_payment(db, invoice_id: str, user_id: int, provider: str,
                         amount: int, currency: str, payload: str):
    await db.execute(
        "INSERT OR REPLACE INTO payments (invoice_id, user_id, provider, amount, "
        "currency, payload, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
        (invoice_id, user_id, provider, amount, currency, payload, now().isoformat()),
    )
    await db.commit()


async def get_payment(db, invoice_id: str) -> aiosqlite.Row | None:
    rows = await db.execute_fetchall(
        "SELECT * FROM payments WHERE invoice_id = ?", (invoice_id,)
    )
    return rows[0] if rows else None


async def mark_payment_paid(db, invoice_id: str) -> aiosqlite.Row | None:
    await db.execute(
        "UPDATE payments SET status='paid', paid_at=? WHERE invoice_id=? AND status!='paid'",
        (now().isoformat(), invoice_id),
    )
    await db.commit()
    return await get_payment(db, invoice_id)


# -------------------------------------------------------------- challenge ----

async def get_common_state(db) -> aiosqlite.Row | None:
    rows = await db.execute_fetchall("SELECT * FROM common_state WHERE id = 1")
    return rows[0] if rows else None


async def set_common_state(db, start_date: str | None, task: str | None):
    cur = await get_common_state(db)
    if cur is None:
        await db.execute(
            "INSERT INTO common_state (id, start_date, task) VALUES (1, ?, ?)",
            (start_date, task),
        )
    else:
        await db.execute(
            "UPDATE common_state SET start_date = COALESCE(?, start_date), "
            "task = COALESCE(?, task) WHERE id = 1",
            (start_date, task),
        )
    await db.commit()


async def get_challenge(db, chal_id: int) -> aiosqlite.Row | None:
    rows = await db.execute_fetchall(
        "SELECT * FROM challenges WHERE id = ?", (chal_id,)
    )
    return rows[0] if rows else None


async def find_challenge(db, user_id: int, ctype: str, month: int = 1) -> aiosqlite.Row | None:
    rows = await db.execute_fetchall(
        "SELECT * FROM challenges WHERE user_id = ? AND type = ? AND month = ?",
        (user_id, ctype, month),
    )
    return rows[0] if rows else None


async def list_user_challenges(db, user_id: int) -> list[aiosqlite.Row]:
    return await db.execute_fetchall(
        "SELECT * FROM challenges WHERE user_id = ? ORDER BY id", (user_id,)
    )


async def create_challenge(db, user_id: int, ctype: str, *, month: int = 1,
                           status: str = "pending_start", habit: str | None = None,
                           start_date: str | None = None) -> int:
    cur = await db.execute(
        "INSERT INTO challenges (user_id, type, month, status, habit, start_date) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, ctype, month, status, habit, start_date),
    )
    await db.commit()
    return cur.lastrowid


async def update_challenge(db, chal_id: int, **fields):
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    await db.execute(
        f"UPDATE challenges SET {sets} WHERE id = ?", (*fields.values(), chal_id)
    )
    await db.commit()


async def set_point_a(db, chal_id: int, text: str):
    await update_challenge(db, chal_id, point_a=text)


async def set_remind_time(db, chal_id: int, hour: int, minute: int):
    await update_challenge(db, chal_id, remind_hour=hour, remind_minute=minute)


async def start_challenge(db, chal_id: int, start_iso: str | None = None):
    await update_challenge(
        db, chal_id, status="running",
        start_date=start_iso or local_today().isoformat(),
    )


async def decline_challenge(db, chal_id: int):
    await update_challenge(db, chal_id, status="declined", declined_at=now().isoformat())


async def complete_challenge(db, chal_id: int):
    await update_challenge(db, chal_id, status="completed", completed_at=now().isoformat())


async def set_mark(db, chal_id: int, day: int, done: bool, note: str | None = None):
    await db.execute(
        "INSERT INTO marks (user_id, chal_id, day, done, note, marked_at) "
        "VALUES ((SELECT user_id FROM challenges WHERE id = ?), ?, ?, ?, ?, ?) "
        "ON CONFLICT(chal_id, day) DO UPDATE SET done = excluded.done, "
        "note = COALESCE(excluded.note, marks.note), marked_at = excluded.marked_at",
        (chal_id, chal_id, day, 1 if done else 0, note, now().isoformat()),
    )
    await db.commit()


async def get_marks(db, chal_id: int) -> dict[int, tuple[int, str | None]]:
    rows = await db.execute_fetchall(
        "SELECT day, done, note FROM marks WHERE chal_id = ?", (chal_id,)
    )
    return {r["day"]: (r["done"], r["note"]) for r in rows}


async def list_running_challenges(db) -> list[aiosqlite.Row]:
    return await db.execute_fetchall(
        "SELECT * FROM challenges WHERE status = 'running'"
    )


async def list_pending_common(db, common_start_iso: str) -> list[aiosqlite.Row]:
    """Пользователи с подпиской, которым можно создать общий челлендж к старту."""
    return await db.execute_fetchall(
        """
        SELECT u.user_id FROM users u
        JOIN subscriptions s ON s.user_id = u.user_id
        WHERE s.status = 'active' AND s.end_date > ?
          AND NOT EXISTS (
            SELECT 1 FROM challenges c
            WHERE c.user_id = u.user_id AND c.type = 'common'
          )
        """,
        (now().isoformat(),),
    )


# ------------------------------------------------------------- analytics ----

def current_day(start_iso: str) -> int:
    """Номер текущего дня челленджа: 1..N (день 1 = дата старта)."""
    return (local_today() - date.fromisoformat(start_iso)).days + 1


def compute_stats(marks: dict[int, tuple[int, str | None]], elapsed_days: int,
                  total_days: int) -> dict:
    """Статистика по ТЗ: выполнено/пропущено/процент/серии.

    Неотмеченный прошедший день = пропуск. Серия — подряд идущие
    выполненные дни (текущая считается по последним elapsed дням).
    """
    elapsed = max(min(elapsed_days, total_days), 0)
    done_cnt = skip_cnt = 0
    for d in range(1, elapsed + 1):
        m = marks.get(d)
        if m and m[0]:
            done_cnt += 1
        else:
            skip_cnt += 1
    pct = round(done_cnt / elapsed * 100) if elapsed else 0

    cur = best = run = 0
    for d in range(1, elapsed + 1):
        m = marks.get(d)
        if m and m[0]:
            run += 1
        else:
            run = 0
        best = max(best, run)
    # текущая серия — на конец прошедшего периода
    cur = run
    # если сегодня ещё не отмечен, серия не обнуляется до конца дня
    return {
        "elapsed": elapsed,
        "total": total_days,
        "done": done_cnt,
        "skip": skip_cnt,
        "pct": pct,
        "streak_cur": cur,
        "streak_best": best,
    }


async def challenge_stats(db, chal: aiosqlite.Row) -> dict | None:
    """Полная статистика запущенного/завершённого челленджа."""
    if chal["status"] not in ("running", "completed") or not chal["start_date"]:
        return None
    marks = await get_marks(db, chal["id"])
    if chal["status"] == "completed":
        elapsed = config.CHALLENGE_DAYS
    else:
        elapsed = current_day(chal["start_date"])
    return compute_stats(marks, elapsed, config.CHALLENGE_DAYS)


async def list_active_members(db) -> list[int]:
    rows = await db.execute_fetchall(
        "SELECT user_id FROM subscriptions WHERE status='active' AND end_date > ?",
        (now().isoformat(),),
    )
    return [r["user_id"] for r in rows]
