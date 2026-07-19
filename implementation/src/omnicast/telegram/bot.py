"""Telegram bot client for sending messages.

Uses python-telegram-bot library (async).
Singleton pattern — init once, reuse.

Usage:
    bot = TelegramBot(token="BOT_TOKEN", chat_id="CHAT_ID")
    await bot.send_alert(alert_message)
    await bot.send_text("Pipeline paused by operator")
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog
from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError

if TYPE_CHECKING:
    from omnicast.models.schemas import AlertMessage

logger = structlog.get_logger()

# Telegram hard limit per message
_MAX_MSG_LEN = 4096


class TelegramBot:
    """Async Telegram bot client.

    Args:
        token: Bot API token from BotFather
        chat_id: Default chat ID for alerts (group or personal)
    """

    def __init__(self, token: str, chat_id: str) -> None:
        self.chat_id = chat_id
        self._bot = Bot(token=token)

    async def send_text(
        self,
        text: str,
        chat_id: str | None = None,
        parse_mode: str = ParseMode.MARKDOWN_V2,
        disable_notification: bool = False,
    ) -> int | None:
        """Send text message. Return message_id on success, None on failure.

        Truncates to 4096 chars; splits if longer.
        Never raises — best-effort delivery.
        """
        target = chat_id or self.chat_id
        try:
            if len(text) <= _MAX_MSG_LEN:
                msg = await self._bot.send_message(
                    chat_id=target,
                    text=text,
                    parse_mode=parse_mode,
                    disable_notification=disable_notification,
                )
                logger.info("Telegram sent", chat_id=target, length=len(text))
                return msg.message_id

            # Split into chunks
            last_id: int | None = None
            for i in range(0, len(text), _MAX_MSG_LEN):
                chunk = text[i : i + _MAX_MSG_LEN]
                msg = await self._bot.send_message(
                    chat_id=target,
                    text=chunk,
                    parse_mode=parse_mode,
                    disable_notification=disable_notification,
                )
                last_id = msg.message_id
            logger.info("Telegram sent (split)", chat_id=target, total_len=len(text))
            return last_id

        except TelegramError as exc:
            logger.error("Telegram send_text failed", error=str(exc))
            return None
        except Exception as exc:
            logger.error("Telegram send_text unexpected error", error=str(exc))
            return None

    async def send_document(
        self,
        file_path: str,
        caption: str = "",
        chat_id: str | None = None,
    ) -> int | None:
        """Send file as document. For daily digest CSV/PDF.

        Never raises — best-effort delivery.
        """
        target = chat_id or self.chat_id
        try:
            data = await asyncio.to_thread(lambda: open(file_path, "rb").read())  # noqa: WPS515
            msg = await self._bot.send_document(
                chat_id=target,
                document=data,
                caption=caption,
                filename=file_path.split("/")[-1].split("\\")[-1],
            )
            logger.info("Telegram document sent", chat_id=target, file=file_path)
            return msg.message_id
        except TelegramError as exc:
            logger.error("Telegram send_document failed", error=str(exc))
            return None
        except Exception as exc:
            logger.error("Telegram send_document unexpected error", error=str(exc))
            return None

    async def send_photo(
        self,
        photo_path: str,
        caption: str = "",
        chat_id: str | None = None,
    ) -> int | None:
        """Send image. For thumbnail previews or charts.

        Never raises — best-effort delivery.
        """
        target = chat_id or self.chat_id
        try:
            data = await asyncio.to_thread(lambda: open(photo_path, "rb").read())  # noqa: WPS515
            msg = await self._bot.send_photo(
                chat_id=target,
                photo=data,
                caption=caption,
            )
            logger.info("Telegram photo sent", chat_id=target)
            return msg.message_id
        except TelegramError as exc:
            logger.error("Telegram send_photo failed", error=str(exc))
            return None
        except Exception as exc:
            logger.error("Telegram send_photo unexpected error", error=str(exc))
            return None

    async def edit_message(
        self,
        message_id: int,
        text: str,
        chat_id: str | None = None,
    ) -> bool:
        """Edit existing message. Used to update alert status.

        Return True if edited, False on error.
        """
        target = chat_id or self.chat_id
        try:
            await self._bot.edit_message_text(
                chat_id=target,
                message_id=message_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN_V2,
            )
            return True
        except TelegramError as exc:
            logger.error("Telegram edit_message failed", error=str(exc))
            return False
        except Exception as exc:
            logger.error("Telegram edit_message unexpected error", error=str(exc))
            return False

    async def health_check(self) -> bool:
        """Verify bot connectivity via getMe() API."""
        try:
            await self._bot.get_me()
            return True
        except TelegramError as exc:
            logger.error("Telegram health_check failed", error=str(exc))
            return False
        except Exception as exc:
            logger.error("Telegram health_check unexpected error", error=str(exc))
            return False
