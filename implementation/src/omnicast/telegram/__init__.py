"""Telegram bot and alert management.

Usage:
    from omnicast.telegram import TelegramBot, AlertManager, CommandRouter

    bot = TelegramBot(token=settings.telegram_bot_token, chat_id=settings.telegram_chat_id)
    manager = AlertManager(bot=bot)
    commands = CommandRouter(bot=bot)
"""

from omnicast.telegram.alert_manager import AlertManager
from omnicast.telegram.bot import TelegramBot
from omnicast.telegram.commands import CommandRouter
from omnicast.telegram.formatter import AlertFormatter

__all__ = [
    "TelegramBot",
    "AlertFormatter",
    "CommandRouter",
    "AlertManager",
]
