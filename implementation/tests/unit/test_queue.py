"""Unit tests using mocked aio_pika.

Test cases:
1. test_video_publisher_serializes_correctly
2. test_video_publisher_priority_mapping
3. test_alert_publisher_fanout
4. test_video_consumer_ack_on_success
5. test_video_consumer_nack_on_callback_failure
6. test_video_consumer_invalid_json_nack_no_requeue
7. test_dlq_consumer_parses_x_death_headers
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from omnicast.models.schemas import VideoTaskMessage, AlertMessage
from omnicast.models.enums import VideoStatus, TaskPriority, AlertSeverity
from omnicast.shared.errors import QueueError


@pytest.fixture
def sample_video_task() -> VideoTaskMessage:
    return VideoTaskMessage(
        video_id=42,
        channel_id=1,
        status=VideoStatus.RENDERING,
        priority=TaskPriority.URGENT,
    )


@pytest.fixture
def sample_alert() -> AlertMessage:
    return AlertMessage(
        severity=AlertSeverity.CRITICAL,
        source="test_worker",
        alert_type="test_alert",
        message="Test alert message",
    )


@pytest.fixture
def mock_channel() -> AsyncMock:
    channel = AsyncMock()
    mock_exchange = AsyncMock()
    channel.get_exchange = AsyncMock(return_value=mock_exchange)
    mock_queue = AsyncMock()
    channel.get_queue = AsyncMock(return_value=mock_queue)
    return channel


@pytest.fixture
def mock_exchange(mock_channel: AsyncMock) -> AsyncMock:
    return mock_channel.get_exchange.return_value


# === Publisher Tests ===


class TestVideoPublisher:
    async def test_video_publisher_serializes_correctly(
        self, sample_video_task: VideoTaskMessage, mock_channel: AsyncMock, mock_exchange: AsyncMock
    ):
        """Test that VideoTaskMessage is serialized correctly with PERSISTENT delivery."""
        import orjson
        from aio_pika import DeliveryMode

        with patch("omnicast.queue.publisher.get_channel", return_value=mock_channel):
            from omnicast.queue.publisher import VideoPublisher

            publisher = VideoPublisher()
            await publisher.publish_task(sample_video_task, routing_key="rendering")

            # Verify exchange.publish was called
            mock_exchange.publish.assert_called_once()
            call_args = mock_exchange.publish.call_args
            msg = call_args[0][0]
            routing_key = call_args[1]["routing_key"]

            # Verify routing_key
            assert routing_key == "rendering"

            # Verify delivery_mode
            assert msg.delivery_mode == DeliveryMode.PERSISTENT

            # Verify body is correct JSON
            import orjson
            body = orjson.loads(msg.body)
            assert body["video_id"] == 42
            assert body["channel_id"] == 1
            assert body["status"] == "rendering"

    async def test_video_publisher_priority_mapping(
        self, sample_video_task: VideoTaskMessage, mock_channel: AsyncMock, mock_exchange: AsyncMock
    ):
        """Test that priority='urgent' maps to message.priority == 7."""
        with patch("omnicast.queue.publisher.get_channel", return_value=mock_channel):
            from omnicast.queue.publisher import VideoPublisher

            publisher = VideoPublisher()
            await publisher.publish_task(sample_video_task, routing_key="rendering")

            call_args = mock_exchange.publish.call_args
            msg = call_args[0][0]

            # urgent → 7
            assert msg.priority == 7

    async def test_video_publisher_low_priority(
        self, mock_channel: AsyncMock, mock_exchange: AsyncMock
    ):
        """Test that priority='low' maps to message.priority == 1."""
        low_task = VideoTaskMessage(
            video_id=1,
            channel_id=1,
            status=VideoStatus.QUEUED,
            priority=TaskPriority.LOW,
        )

        with patch("omnicast.queue.publisher.get_channel", return_value=mock_channel):
            from omnicast.queue.publisher import VideoPublisher

            publisher = VideoPublisher()
            await publisher.publish_task(low_task, routing_key="scripting")

            call_args = mock_exchange.publish.call_args
            msg = call_args[0][0]
            assert msg.priority == 1

    async def test_video_publisher_publish_to_dlq(
        self, sample_video_task: VideoTaskMessage, mock_channel: AsyncMock, mock_exchange: AsyncMock
    ):
        """Test publishing to DLQ with error details."""
        with patch("omnicast.queue.publisher.get_channel", return_value=mock_channel):
            from omnicast.queue.publisher import VideoPublisher

            publisher = VideoPublisher()
            await publisher.publish_to_dlq(sample_video_task, error="TimeoutError")

            mock_exchange.publish.assert_called_once()
            call_args = mock_exchange.publish.call_args
            msg = call_args[0][0]
            routing_key = call_args[1]["routing_key"]

            assert routing_key == "video"

            import orjson
            body = orjson.loads(msg.body)
            assert body["error"] == "TimeoutError"
            assert body["video_id"] == 42


class TestAlertPublisher:
    async def test_alert_publisher_fanout(
        self, sample_alert: AlertMessage, mock_channel: AsyncMock, mock_exchange: AsyncMock
    ):
        """Test that AlertMessage is published with no routing_key (empty string)."""
        with patch("omnicast.queue.publisher.get_channel", return_value=mock_channel):
            from omnicast.queue.publisher import AlertPublisher

            publisher = AlertPublisher()
            await publisher.publish_alert(sample_alert)

            mock_exchange.publish.assert_called_once()
            call_args = mock_exchange.publish.call_args
            routing_key = call_args[1]["routing_key"]

            # Fanout → empty routing_key
            assert routing_key == ""

            # Verify body
            import orjson
            body = orjson.loads(call_args[0][0].body)
            assert body["severity"] == "critical"
            assert body["alert_type"] == "test_alert"


# === Consumer Tests ===


class TestVideoConsumer:
    async def test_video_consumer_ack_on_success(
        self, sample_video_task: VideoTaskMessage, mock_channel: AsyncMock
    ):
        """Test that message is ack'd when callback succeeds."""
        import orjson

        mock_queue = mock_channel.get_queue.return_value
        mock_message = AsyncMock()
        mock_message.body = orjson.dumps(sample_video_task.model_dump(mode="json"))
        mock_message.message_id = "42_rendering"
        mock_message.process = MagicMock()
        mock_message.process.return_value.__aenter__ = AsyncMock(return_value=mock_message)
        mock_message.process.return_value.__aexit__ = AsyncMock(return_value=False)

        callback = AsyncMock()

        with patch("omnicast.queue.consumer.get_channel", return_value=mock_channel):
            from omnicast.queue.consumer import VideoConsumer

            consumer = VideoConsumer(queue_name="video.rendering")
            consumer._callback = callback
            await consumer._on_message(mock_message)

            # Verify callback was called
            callback.assert_called_once()

    async def test_video_consumer_nack_on_callback_failure(
        self, sample_video_task: VideoTaskMessage, mock_channel: AsyncMock
    ):
        """Test that message is NOT ack'd when callback raises (requeue for retry)."""
        import orjson

        mock_queue = mock_channel.get_queue.return_value
        mock_message = AsyncMock()
        mock_message.body = orjson.dumps(sample_video_task.model_dump(mode="json"))
        mock_message.message_id = "42_rendering"
        mock_message.process = MagicMock()
        mock_message.process.return_value.__aenter__ = AsyncMock(return_value=mock_message)
        mock_message.process.return_value.__aexit__ = AsyncMock(return_value=False)

        async def failing_callback(task: VideoTaskMessage) -> None:
            raise RuntimeError("Processing failed")

        with patch("omnicast.queue.consumer.get_channel", return_value=mock_channel):
            from omnicast.queue.consumer import VideoConsumer

            consumer = VideoConsumer(queue_name="video.rendering")
            consumer._callback = failing_callback
            # Callback exception should propagate (message.process() context manager handles nack)
            with pytest.raises(RuntimeError, match="Processing failed"):
                await consumer._on_message(mock_message)

    async def test_video_consumer_invalid_json_nack_no_requeue(
        self, mock_channel: AsyncMock
    ):
        """Test that invalid JSON → nack(requeue=False) → goes to DLQ."""
        mock_queue = mock_channel.get_queue.return_value
        mock_message = AsyncMock()
        mock_message.body = b"not valid json {{{"
        mock_message.message_id = "invalid_msg"
        mock_message.process = MagicMock()
        mock_message.process.return_value.__aenter__ = AsyncMock(return_value=mock_message)
        mock_message.process.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_message.nack = AsyncMock()

        with patch("omnicast.queue.consumer.get_channel", return_value=mock_channel):
            from omnicast.queue.consumer import VideoConsumer

            consumer = VideoConsumer(queue_name="video.rendering")
            consumer._callback = AsyncMock()
            await consumer._on_message(mock_message)

            # Verify nack was called with requeue=False
            mock_message.nack.assert_called_once_with(requeue=False)


class TestDLQConsumer:
    async def test_dlq_consumer_parses_x_death_headers(
        self, mock_channel: AsyncMock
    ):
        """Test that callback receives metadata with original queue, failure count."""
        import orjson

        mock_queue = mock_channel.get_queue.return_value
        mock_message = AsyncMock()
        mock_message.body = orjson.dumps({"video_id": 42, "status": "failed"})
        mock_message.message_id = "dlq_42_failed"
        mock_message.headers = {
            "x-death": [
                {
                    "count": 3,
                    "reason": "rejected",
                    "queue": "video.rendering",
                    "time": 1700000000,
                    "exchange": "omnicast.video",
                    "routing-keys": ["rendering"],
                }
            ]
        }
        mock_message.process = MagicMock()
        mock_message.process.return_value.__aenter__ = AsyncMock(return_value=mock_message)
        mock_message.process.return_value.__aexit__ = AsyncMock(return_value=False)

        received_data = {}

        async def capture_callback(data: dict) -> None:
            received_data.update(data)

        with patch("omnicast.queue.consumer.get_channel", return_value=mock_channel):
            from omnicast.queue.consumer import DLQConsumer

            consumer = DLQConsumer(queue_name="dlq.video")
            consumer._callback = capture_callback
            await consumer._on_message(mock_message)

            # Verify x-death info was parsed
            assert "x_death" in received_data
            x_death = received_data["x_death"]
            assert x_death["original_queue"] == "video.rendering"
            assert x_death["failure_count"] == 3