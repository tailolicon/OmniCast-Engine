"""RabbitMQ connection management.

Usage:
    await init_rabbitmq("amqp://user:pass@localhost/")
    # ... use publisher/consumer ...
    await close_rabbitmq()
"""

from __future__ import annotations

import aio_pika
from aio_pika import connect_robust, ExchangeType
from aio_pika.abc import AbstractRobustConnection, AbstractChannel
import structlog

from omnicast.shared.errors import QueueError

logger = structlog.get_logger()

# === Constants ===

# Exchanges
EXCHANGE_VIDEO = "omnicast.video"
EXCHANGE_ALERT = "omnicast.alert"
EXCHANGE_DLQ = "omnicast.dlq"

# Queues
QUEUE_SCRIPTING = "video.scripting"
QUEUE_RENDERING = "video.rendering"
QUEUE_UPLOADING = "video.uploading"
QUEUE_QUALITY_CHECK = "video.quality_check"
QUEUE_ALERT_TELEGRAM = "alert.telegram"
QUEUE_ALERT_DASHBOARD = "alert.dashboard"
QUEUE_DLQ_VIDEO = "dlq.video"
QUEUE_DLQ_ALERT = "dlq.alert"

# Routing keys
RK_SCRIPTING = "scripting"
RK_RENDERING = "rendering"
RK_UPLOADING = "uploading"
RK_QUALITY_CHECK = "quality_check"

# Global state
_connection: AbstractRobustConnection | None = None
_channel: AbstractChannel | None = None


# Queue arguments for production queues
QUEUE_ARGS = {
    "x-queue-type": "quorum",
    "x-delivery-limit": 5,
    "x-dead-letter-exchange": EXCHANGE_DLQ,
    "x-message-ttl": 86400000,  # 24h TTL
}


async def init_rabbitmq(url: str) -> None:
    """Initialize connection + channel + declare topology.

    Steps:
    1. connect_robust(url) → auto-reconnect on failure
    2. channel = await connection.channel()
    3. Set prefetch_count=10 (don't overload consumer)
    4. Declare exchanges: video (topic), alert (fanout), dlq (direct)
    5. Declare queues with arguments above
    6. Bind queues to exchanges
    7. Log: "RabbitMQ initialized: {exchange_count} exchanges, {queue_count} queues"

    Raises:
        QueueError: if connection fails
    """
    global _connection, _channel

    try:
        _connection = await connect_robust(url)
        _channel = await _connection.channel()
        await _channel.set_qos(prefetch_count=10)

        # Declare exchanges
        await _channel.declare_exchange(
            EXCHANGE_VIDEO, ExchangeType.TOPIC, durable=True
        )
        await _channel.declare_exchange(
            EXCHANGE_ALERT, ExchangeType.FANOUT, durable=True
        )
        await _channel.declare_exchange(
            EXCHANGE_DLQ, ExchangeType.DIRECT, durable=True
        )

        # Declare DLQ queues
        await _channel.declare_queue(
            QUEUE_DLQ_VIDEO,
            durable=True,
            arguments={"x-queue-type": "quorum"},
        )
        await _channel.declare_queue(
            QUEUE_DLQ_ALERT,
            durable=True,
            arguments={"x-queue-type": "quorum"},
        )

        # Bind DLQ queues
        await _channel.get_queue(QUEUE_DLQ_VIDEO).bind(
            EXCHANGE_DLQ, routing_key="video"
        )
        await _channel.get_queue(QUEUE_DLQ_ALERT).bind(
            EXCHANGE_DLQ, routing_key="alert"
        )

        # Declare video queues with DLQ args
        video_queues = [
            (QUEUE_SCRIPTING, RK_SCRIPTING),
            (QUEUE_RENDERING, RK_RENDERING),
            (QUEUE_UPLOADING, RK_UPLOADING),
            (QUEUE_QUALITY_CHECK, RK_QUALITY_CHECK),
        ]
        for queue_name, routing_key in video_queues:
            queue = await _channel.declare_queue(
                queue_name,
                durable=True,
                arguments={
                    **QUEUE_ARGS,
                    "x-dead-letter-routing-key": "video",
                },
            )
            await queue.bind(EXCHANGE_VIDEO, routing_key=routing_key)

        # Declare alert queues
        alert_queues = [
            QUEUE_ALERT_TELEGRAM,
            QUEUE_ALERT_DASHBOARD,
        ]
        for queue_name in alert_queues:
            queue = await _channel.declare_queue(
                queue_name,
                durable=True,
                arguments={
                    **QUEUE_ARGS,
                    "x-dead-letter-routing-key": "alert",
                },
            )
            await queue.bind(EXCHANGE_ALERT)

        exchange_count = 3
        queue_count = len(video_queues) + len(alert_queues) + 2  # +2 DLQ
        logger.info(
            "RabbitMQ initialized",
            exchange_count=exchange_count,
            queue_count=queue_count,
        )

    except Exception as exc:
        raise QueueError(f"Failed to initialize RabbitMQ: {exc}") from exc


async def get_channel() -> AbstractChannel:
    """Return initialized channel. Raises QueueError if not initialized."""
    if _channel is None:
        raise QueueError(
            "RabbitMQ not initialized. Call init_rabbitmq() first."
        )
    return _channel


async def close_rabbitmq() -> None:
    """Close channel + connection gracefully."""
    global _connection, _channel

    if _channel is not None:
        try:
            await _channel.close()
        except Exception:
            logger.warning("Error closing RabbitMQ channel")
        _channel = None

    if _connection is not None:
        try:
            await _connection.close()
        except Exception:
            logger.warning("Error closing RabbitMQ connection")
        _connection = None

    logger.info("RabbitMQ connection closed")