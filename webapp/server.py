"""HTTP API для Telegram Mini App («Мой путь» / «Клуб»).

Запуск:  python -m webapp.server
Мини-приложение запрашивает GET /api/me и GET /api/club с initData,
который проверяется по схеме Telegram (HMAC) — данные берутся из БД бота.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import urllib.parse
from datetime import datetime, timezone as dt_timezone

import aiosqlite
from aiohttp import web

# общие настройки/логика из пакета bot
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from bot import config, storage  # noqa: E402

BOT_SECRET_KEY = None  # вычисляется из токена при старте


def derive_secret(token: str) -> bytes:
    return hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()


def validate_init_data(init_data: str, token: str) -> dict | None:
    """Проверяет подпись Telegram WebApp initData. Возвращает payload user или None."""
    parsed = dict(urllib.parse.parse_qsl(init_data, keep_blank_values=True))
    hash_ = parsed.pop("hash", None)
    if not hash_:
        return None
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
    secret = derive_secret(token)
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, hash_):
        return None
    auth_date = int(parsed.get("auth_date", "0"))
    if auth_date and datetime.now(dt_timezone.utc).timestamp() - auth_date > 86400:
        return None  # устаревшая сессия
    try:
        payload = json.loads(parsed.get("user", "{}"))
    except json.JSONDecodeError:
        return None
    return payload


def build_my_payload(marks: dict[int, str], today: int) -> dict:
    """Формат, совпадающий с константами прототипа: MY = ['ok','none',...]"""
    my = []
    for d in range(1, config.CHALLENGE_DAYS + 1):
        if d > today:
            break
        my.append(marks.get(d, "none"))
    return {"total": config.CHALLENGE_DAYS, "today": min(today, config.CHALLENGE_DAYS), "my": my}


async def handle_me(request: web.Request) -> web.Response:
    init_data = request.headers.get("X-Init-Data") or request.query.get("initData", "")
    user = validate_init_data(init_data, config.BOT_TOKEN)
    if not user:
        return web.json_response({"error": "unauthorized"}, status=401)
    db = request.app["db"]
    uid = user["id"]
    start = await storage.get_start_date(db, uid)
    if not start:
        return web.json_response({"error": "not_started"}, status=404)
    marks = await storage.get_marks(db, uid)
    today = storage.current_day(start)
    return web.json_response(build_my_payload(marks, today))


async def handle_club(request: web.Request) -> web.Response:
    """Анонимная агрегированная статистика клуба по дням."""
    init_data = request.headers.get("X-Init-Data") or request.query.get("initData", "")
    if not validate_init_data(init_data, config.BOT_TOKEN):
        return web.json_response({"error": "unauthorized"}, status=401)
    db = request.app["db"]
    rows = await db.execute_fetchall(
        """
        SELECT m.day AS day,
               SUM(CASE WHEN m.value='ok'   THEN 1 ELSE 0 END) AS ok,
               SUM(CASE WHEN m.value='part' THEN 1 ELSE 0 END) AS part,
               SUM(CASE WHEN m.value='fail' THEN 1 ELSE 0 END) AS fail,
               COUNT(DISTINCT m.user_id) AS active
        FROM marks m JOIN users u ON u.user_id = m.user_id
        GROUP BY m.day ORDER BY m.day
        """
    )
    # формат для фронтенда: [день, выдержали, частично, сорвались, активных]
    club = [[r["day"], r["ok"], r["part"], r["fail"], r["active"]] for r in rows]
    total_users = await db.execute_fetchall("SELECT COUNT(*) c FROM users")
    return web.json_response({
        "club": club,
        "members": total_users[0]["c"] if total_users else 0,
    })


async def handle_index(request: web.Request) -> web.Response:
    """Раздаёт статику мини-приложения."""
    path = request.match_info.get("path", "index.html")
    full = os.path.join(os.path.dirname(__file__), path)
    if not os.path.isfile(full):
        return web.FileResponse(os.path.join(os.path.dirname(__file__), "index.html"))
    return web.FileResponse(full)


async def init_db(app: web.Application):
    app["db"] = await storage.get_db()
    yield
    await app["db"].close()


def main():
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN не задан (нужен для проверки initData)")
    app = web.Application()
    app.cleanup_ctx.append(init_db)
    app.router.add_get("/api/me", handle_me)
    app.router.add_get("/api/club", handle_club)
    app.router.add_get("/", lambda r: web.FileResponse(os.path.join(os.path.dirname(__file__), "index.html")))
    app.router.add_get("/{path:.*}", handle_index)
    port = int(os.getenv("WEBAPP_PORT", "3000"))
    print(f"Mini App сервер: http://0.0.0.0:{port}")
    web.run_app(app, port=port)


if __name__ == "__main__":
    main()
