"""Хранилище данных (SQLite через aiosqlite).

Таблицы:
  users    — участники клуба, дата старта челленджа
  marks    — ежедневные отметки: ok / part / fail
"""
from __future__ import annotations

import aiosqlite
from datetime import date, datetime, timezone as dt_timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    full_name   TEXT,
    start_date  TEXT NOT NULL,          -- ISO-дата начала челленджа
    joined_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS marks (
    user_id  INTEGER NOT NULL,
    day      INTEGER NOT NULL,          -- 1..CHALLENGE_DAYS
    value    TEXT NOT NULL,             -- ok | part | fail
    marked_at TEXT NOT NULL,
    PRIMARY KEY (user_id, day),
    FOREIGN KEY (user_id) REFERENCES users (user_id)
);
"""

VALID_MARKS = {"ok", "part", "fail"}


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(config.DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.executescript(SCHEMA)
    return db


async def register_user(db, user_id: int, username: str | None, full_name: str) -> date:
    """Регистрирует пользователя (идемпотентно). Возвращает дату старта челленджа."""
    row = await db.execute_fetchall(
        "SELECT start_date FROM users WHERE user_id = ?", (user_id,)
    )
    if row:
        return date.fromisoformat(row[0]["start_date"])
    today = datetime.now(dt_timezone.utc).date()
    await db.execute(
        "INSERT INTO users (user_id, username, full_name, start_date, joined_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, username, full_name, today.isoformat(),
         datetime.now(dt_timezone.utc).isoformat()),
    )
    await db.commit()
    return today


async def set_mark(db, user_id: int, day: int, value: str) -> bool:
    """Ставит/обновляет отметку за день. False — если день вне челленджа."""
    if value not in VALID_MARKS:
        raise ValueError(f"Недопустимая отметка: {value}")
    if day < 1 or day > config.CHALLENGE_DAYS:
        return False
    await db.execute(
        "INSERT INTO marks (user_id, day, value, marked_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(user_id, day) DO UPDATE SET value = excluded.value, "
        "marked_at = excluded.marked_at",
        (user_id, day, value, datetime.now(dt_timezone.utc).isoformat()),
    )
    await db.commit()
    return True


async def get_marks(db, user_id: int) -> dict[int, str]:
    rows = await db.execute_fetchall(
        "SELECT day, value FROM marks WHERE user_id = ?", (user_id,)
    )
    return {r["day"]: r["value"] for r in rows}


async def get_start_date(db, user_id: int) -> date | None:
    rows = await db.execute_fetchall(
        "SELECT start_date FROM users WHERE user_id = ?", (user_id,)
    )
    if not rows:
        return None
    return date.fromisoformat(rows[0]["start_date"])


async def list_active_users(db) -> list[int]:
    rows = await db.execute_fetchall("SELECT user_id FROM users")
    return [r["user_id"] for r in rows]


# ---------- Аналитика (совпадает с логикой из дизайн-макета мини-приложения) ----------

def current_day(start: date) -> int:
    """Номер текущего дня челленджа: 1..CHALLENGE_DAYS (или больше, если истёк)."""
    return (datetime.now(dt_timezone.utc).date() - start).days + 1


def compute_stats(marks: dict[int, str], total_days: int) -> dict:
    cnt = {"ok": 0, "part": 0, "fail": 0}
    for v in marks.values():
        cnt[v] = cnt.get(v, 0) + 1
    marked = sum(cnt.values())
    pct = round(cnt["ok"] / marked * 100) if marked else 0

    # серии — как в прототипе: ok продлевает, part сохраняет, fail сбрасывает
    cur = best = 0
    for d in range(1, total_days + 1):
        m = marks.get(d)
        if m == "ok":
            cur += 1
        elif m == "part":
            pass
        else:
            cur = 0
        best = max(best, cur)

    return {
        "counts": cnt,
        "marked": marked,
        "pct": pct,
        "streak_cur": cur,
        "streak_best": best,
    }
