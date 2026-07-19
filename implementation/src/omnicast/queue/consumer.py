"""Consume messages from RabbitMQ queues.

Usage:
    consumer = VideoConsumer(queue_name="video.rendering")
    await consumer.start(callback=handle_render_task)
    # ... runs until cancelled ...
    await consumer.stop()
"""

from __future__ import annotations

from collections.abc import Callable, Awaitable

import orjson
import aio_pika
from aio_pika.abc import AbstractIncomingMessage

from omnicast.queue.connection import get_channel
from omnicast.models.schemas import VideoTaskMessage, AlertMessage
from omnicast.shared.errors import QueueError
import structlog

logger = structlog.get_logger()


class VideoConsumer:
    """Consume video tasks from a specific queue."""

    def __init__(self, queue_name: str):
        self.queue_name = queue_name
        self._consumer_tag: str | None = None
        self._callback: Callable[[VideoTaskMessage], Awaitable[None]] | None = None

    async def start(
        self,
        callback: Callable[[VideoTaskMessage], Awaitable[None]],
    ) -> None:
        """Start consuming messages.

        Args:
            callback: async function that processes VideoTaskMessage.
                     If callback raises → message is NACK'd (redelivered).
                     If callback returns normally → message is ACK'd.
        """
        self._callback = callback
        channel = await get_channel()
        queue = await channel.get_queue(self.queue_name)

        self._consumer_tag = await queue.consume(self._on_message)
        logger.info(
            "VideoConsumer started",
            queue_name=self.queue_name,
            consumer_tag=self._consumer_tag,
        )

    async def _on_message(self, message: AbstractIncomingMessage) -> None:
        """Process incoming message. Auto-ack on success, nack on exception."""
        async with message.process():
            try:
                body = orjson.loads(message.body)
            except orjson.JSONDecodeError:
                logger.error(
                    "Invalid JSON in message body, sending to DLQ",
                    queue_name=self.queue_name,
                    message_id=message.message_id,
                )
                # nack without requeue → goes to DLQ
                await message.nack(requeue=False)
                return

            try:
                task = VideoTaskMessage.model_validate(body)
            except Exception as exc:
                logger.error(
                    "Failed to parse VideoTaskMessage",
                    error=str(exc),
                    message_id=message.message_id,
                )
                await message.nack(requeue=False)
                return

            if self._callback is None:
                logger.error("No callback set for consumer")
                return

            await self._callback(task)

    async def stop(self) -> None:
        """Cancel consumer. Graceful: wait for current message to finish."""
        if self._consumer_tag is not None:
            channel = await get_channel()
            queue = await channel.get_queue(self.queue_name)
            await queue.cancel(self._consumer_tag)
            logger.info(
                "VideoConsumer stopped",
                queue_name=self.queue_name,
            )


class AlertConsumer:
    """Consume alerts from alert queue."""

    def __init__(self, queue_name: str):
        self.queue_name = queue_name
        self._consumer_tag: str | None = None
        self._callback: Callable[[AlertMessage], Awaitable[None]] | None = None

    async def start(
        self,
        callback: Callable[[AlertMessage], Awaitable[None]],
    ) -> None:
        """Start consuming messages. Same pattern as VideoConsumer but deserializes AlertMessage."""
        self._callback = callback
        channel = await get_channel()
        queue = await channel.get_queue(self.queue_name)

        self._consumer_tag = await queue.consume(self._on_message)
        logger.info(
            "AlertConsumer started",
            queue_name=self.queue_name,
            consumer_tag=self._consumer_tag,
        )

    async def _on_message(self, message: AbstractIncomingMessage) -> None:
        """Process incoming alert message."""
        async with message.process():
            try:
                body = orjson.loads(message.body)
            except orjson.JSONDecodeError:
                logger.error(
                    "Invalid JSON in alert message body",
                    queue_name=self.queue_name,
                    message_id=message.message_id,
                )
                await message.nack(requeue=False)
                return

            try:
                alert = AlertMessage.model_validate(body)
            except Exception as exc:
                logger.error(
                    "Failed to parse AlertMessage",
                    error=str(exc),
                    message_id=message.message_id,
                )
                await message.nack(requeue=False)
                return

            if self._callback is None:
                logger.error("No callback set for AlertConsumer")
                return

            await self._callback(alert)

    async def stop(self) -> None:
        """Cancel consumer."""
        if self._consumer_tag is not None:
            channel = await get_channel()
            queue = await channel.get_queue(self.queue_name)
            await queue.cancel(self._consumer_tag)
            logger.info(
                "AlertConsumer stopped",
                queue_name=self.queue_name,
            )


class DLQConsumer:
    """Consume from Dead Letter Queue for manual review/retry.

    DLQ messages have extra headers:
      x-death: [{count, reason, queue, time, exchange, routing-keys}]

    Parse x-death to get: original queue, failure count, first failure time.
    """

    def __init__(self, queue_name: str):
        self.queue_name = queue_name
        self._consumer_tag: str | None = None
        self._callback: Callable[[dict], Awaitable[None]] | None = None

    async def start(
        self,
        callback: Callable[[dict], Awaitable[None]],
    ) -> None:
        """Consume DLQ messages. Callback receives raw dict with x-death metadata."""
        self._callback = callback
        channel = await get_channel()
        queue = await channel.get_queue(self.queue_name)

        self._consumer_tag = await queue.consume(self._on_message)
        logger.info(
            "DLQConsumer started",
            queue_name=self.queue_name,
            consumer_tag=self._consumer_tag,
        )

    async def _on_message(self, message: AbstractIncomingMessage) -> None:
        """Process DLQ message with x-death headers."""
        async with message.process():
            try:
                body = orjson.loads(message.body)
            except orjson.JSONDecodeError:
                logger.error(
                    "Invalid JSON in DLQ message body",
                    queue_name=self.queue_name,
                )
                return

            # Parse x-death headers
            x_death_info = {}
            if message.headers and "x-death" in message.headers:
                x_death_list = message.headers["x-death"]
                if x_death_list and len(x_death_list) > 0:
                    first_death = x_death_list[0]
                    x_death_info = {
                        "original_queue": first_death.get("queue", "unknown"),
                        "failure_count": first_death.get("count", 0),
                        "first_failure_time": str(first_death.get("time", "unknown")),
                        "reason": first_death.get("reason", "unknown"),
                    }

            data = {
                "body": body,
                "message_id": message.message_id,
                "x_death": x_death_info,
            }

            if self._callback is None:
                logger.error("No callback set for DLQConsumer")
                return

            await self._callback(data)

    async def stop(self) -> None:
        """Cancel consumer."""
        if self._consumer_tag is not None:
            channel = await get_channel()
            queue = await channel.get_queue(self.queue_name)
            await queue.cancel(self._consumer_tag)
            logger.info(
                "DLQConsumer stopped",
                queue_name=self.queue_name,
            )