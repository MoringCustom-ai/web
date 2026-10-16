"""Настройки бота клуба «Шесть месяцев»."""
import os

try:  # загружаем .env, если он рядом (необязательно)
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# Длина челленджа (из дизайн-макета мини-приложения: TOTAL = 14)
CHALLENGE_DAYS = int(os.getenv("CHALLENGE_DAYS", "14"))

# База данных
DB_PATH = os.getenv("DB_PATH", "club.db")

# Настройки мини-приложения (Telegram WebApp / твоя ссылка на фронтенд)
MINI_APP_URL = os.getenv("MINI_APP_URL", "")  # например https://your-app.pages.dev
CHAT_BUTTON_URL = os.getenv("CHAT_BUTTON_URL", "")  # ссылка на закрытый чат клуба

# Cron для напоминаний (APScheduler), по умолчанию — ежедневная отметка в 20:00 МСК
REMINDER_HOUR = int(os.getenv("REMINDER_HOUR", "20"))
REMINDER_MINUTE = int(os.getenv("REMINDER_MINUTE", "0"))
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")
