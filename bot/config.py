"""Настройки бота закрытого бизнес-клуба «Шесть месяцев»."""
import os

try:  # загружаем .env, если он рядом (необязательно)
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# ID пользователей-администраторов через запятую (можно также добавить через админку /admin)
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}

# Длина челленджа в днях (по ТЗ — 30)
CHALLENGE_DAYS = int(os.getenv("CHALLENGE_DAYS", "30"))

# Длительность подписки в днях
SUBSCRIPTION_DAYS = int(os.getenv("SUBSCRIPTION_DAYS", "30"))

# База данных
DB_PATH = os.getenv("DB_PATH", "club.db")

# Ссылки (используются как значения по умолчанию для контента в БД)
MINI_APP_URL = os.getenv("MINI_APP_URL", "")        # Telegram Mini App (статистика)
CHAT_BUTTON_URL = os.getenv("CHAT_BUTTON_URL", "")  # ссылка-приглашение в закрытый чат

# SuperChat закрытого чата клуба: bot должен быть его админом —
# тогда бот автоматически выдаёт и отзывает доступ по статусу подписки
CHAT_GROUP_ID = int(os.getenv("CHAT_GROUP_ID", "0") or 0)

# Инвойды Telegram Stars (тестовый режим оплаты прямо в боте).
# Реальные платёжные ссылки (карта РФ / иностранная карта) редактируются в админке.
PAYWALL_ENABLED = os.getenv("PAYWALL_ENABLED", "1") == "1"
STARS_PRICE = int(os.getenv("STARS_PRICE", "100"))  # цена инвойса в XTR

# Напоминания: пользователь выбирает время сам; это — значение по умолчанию
REMINDER_HOUR = int(os.getenv("REMINDER_HOUR", "20"))
REMINDER_MINUTE = int(os.getenv("REMINDER_MINUTE", "0"))
TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")

# Период проверки автосписаний / истечения подписок (минуты)
BILLING_TICK_MINUTES = int(os.getenv("BILLING_TICK_MINUTES", "15"))
