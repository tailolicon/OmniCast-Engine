"""RabbitMQ queue management for OmniCast Engine.

Public API:
    from omnicast.queue.connection import (
        init_rabbitmq,
        get_channel,
        close_rabbitmq,
        EXCHANGE_VIDEO,
        EXCHANGE_ALERT,
        EXCHANGE_DLQ,
        QUEUE_SCRIPTING,
        QUEUE_RENDERING,
        QUEUE_UPLOADING,
        QUEUE_QUALITY_CHECK,
        QUEUE_ALERT_TELEGRAM,
        QUEUE_ALERT_DASHBOARD,
        QUEUE_DLQ_VIDEO,
        QUEUE_DLQ_ALERT,
    )
    from omnicast.queue.publisher import VideoPublisher, AlertPublisher
    from omnicast.queue.consumer import VideoConsumer, AlertConsumer, DLQConsumer
"""

from omnicast.queue.connection import (
    init_rabbitmq,
    get_channel,
    close_rabbitmq,
    EXCHANGE_VIDEO,
    EXCHANGE_ALERT,
    EXCHANGE_DLQ,
    QUEUE_SCRIPTING,
    QUEUE_RENDERING,
    QUEUE_UPLOADING,
    QUEUE_QUALITY_CHECK,
    QUEUE_ALERT_TELEGRAM,
    QUEUE_ALERT_DASHBOARD,
    QUEUE_DLQ_VIDEO,
    QUEUE_DLQ_ALERT,
)
from omnicast.queue.publisher import VideoPublisher, AlertPublisher
from omnicast.queue.consumer import VideoConsumer, AlertConsumer, DLQConsumer

__all__ = [
    "init_rabbitmq",
    "get_channel",
    "close_rabbitmq",
    "EXCHANGE_VIDEO",
    "EXCHANGE_ALERT",
    "EXCHANGE_DLQ",
    "QUEUE_SCRIPTING",
    "QUEUE_RENDERING",
    "QUEUE_UPLOADING",
    "QUEUE_QUALITY_CHECK",
    "QUEUE_ALERT_TELEGRAM",
    "QUEUE_ALERT_DASHBOARD",
    "QUEUE_DLQ_VIDEO",
    "QUEUE_DLQ_ALERT",
    "VideoPublisher",
    "AlertPublisher",
    "VideoConsumer",
    "AlertConsumer",
    "DLQConsumer",
]