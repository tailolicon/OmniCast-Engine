"""Publish messages to RabbitMQ exchanges.

Usage:
    publisher = VideoPublisher()
    await publisher.publish_task(video_task_message, routing_key="rendering")
"""

from __future__ import annotations

import orjson
import aio_pika
from aio_pika import DeliveryMode, Message

from omnicast.queue.connection import (
    get_channel,
    EXCHANGE_VIDEO,
    EXCHANGE_ALERT,
    EXCHANGE_DLQ,
)
from omnicast.models.schemas import VideoTaskMessage, AlertMessage
from omnicast.shared.errors import QueueError
import structlog

logger = structlog.get_logger()

# Priority mapping
PRIORITY_MAP = {
    "emergency": 9,
    "urgent": 7,
    "high": 5,
    "normal": 3,
    "low": 1,
}


class VideoPublisher:
    """Publish video production tasks."""

    async def publish_task(
        self, message: VideoTaskMessage, routing_key: str
    ) -> None:
        """Publish VideoTaskMessage to omnicast.video exchange.

        Args:
            message: VideoTaskMessage (Pydantic model)
            routing_key: one of RK_SCRIPTING, RK_RENDERING, etc.

        Raises:
            QueueError: if publish fails
        """
        try:
            channel = await get_channel()
            exchange = await channel.get_exchange(EXCHANGE_VIDEO)

            body = orjson.dumps(message.model_dump(mode="json"))

            msg = Message(
                body=body,
                delivery_mode=DeliveryMode.PERSISTENT,
                content_type="application/json",
                message_id=f"{message.video_id}_{message.status}",
                priority=PRIORITY_MAP.get(message.priority, 3),
            )

            await exchange.publish(msg, routing_key=routing_key)
            logger.info(
                "Published video task",
                video_id=message.video_id,
                routing_key=routing_key,
                priority=message.priority,
            )

        except QueueError:
            raise
        except Exception as exc:
            raise QueueError(
                f"Failed to publish video task: {exc}"
            ) from exc

    async def publish_to_dlq(
        self, message: VideoTaskMessage, error: str
    ) -> None:
        """Send failed task to DLQ with error details.

        - Add error to message details
        - Publish to EXCHANGE_DLQ with routing_key="video"
        """
        try:
            channel = await get_channel()
            exchange = await channel.get_exchange(EXCHANGE_DLQ)

            data = message.model_dump(mode="json")
            data["error"] = error
            body = orjson.dumps(data)

            msg = Message(
                body=body,
                delivery_mode=DeliveryMode.PERSISTENT,
                content_type="application/json",
                message_id=f"dlq_{message.video_id}_{message.status}",
            )

            await exchange.publish(msg, routing_key="video")
            logger.warning(
                "Published to DLQ",
                video_id=message.video_id,
                error=error,
            )

        except QueueError:
            raise
        except Exception as exc:
            raise QueueError(
                f"Failed to publish to DLQ: {exc}"
            ) from exc


class AlertPublisher:
    """Publish alerts to fanout exchange."""

    async def publish_alert(self, message: AlertMessage) -> None:
        """Publish AlertMessage to omnicast.alert exchange (fanout).

        - Serialize with orjson
        - DeliveryMode.PERSISTENT
        - No routing_key needed (fanout)

        Raises:
            QueueError: if publish fails
        """
        try:
            channel = await get_channel()
            exchange = await channel.get_exchange(EXCHANGE_ALERT)

            body = orjson.dumps(message.model_dump(mode="json"))

            msg = Message(
                body=body,
                delivery_mode=DeliveryMode.PERSISTENT,
                content_type="application/json",
                message_id=f"alert_{message.alert_type}_{message.source}",
            )

            await exchange.publish(msg, routing_key="")
            logger.info(
                "Published alert",
                alert_type=message.alert_type,
                severity=message.severity,
            )

        except QueueError:
            raise
        except Exception as exc:
            raise QueueError(
                f"Failed to publish alert: {exc}"
            ) from exc