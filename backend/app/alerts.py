"""The one alert watcher (and Telegram bot) for this API process."""
from .config import settings
from .db import engine
from .live import runner
from .services.alerts.service import AlertService
from .services.alerts.telegram import TelegramClient

alerts = AlertService(
    engine,
    runner,
    settings.telegram_bot_token.strip() or None,
    client_factory=lambda token: TelegramClient(token, settings.telegram_api_url),
)
