# TASK C: Message Queue (RabbitMQ)

> **Depends on:** TASK_A hoàn thành (models/schemas.py có VideoTaskMessage, AlertMessage)
> **Output:** src/omnicast/queue/, tests/unit/test_queue.py, tests/integration/test_queue_integration.py
> **Parallel với:** TASK_B, D, E, F, G

## Context

OmniCast Engine dùng RabbitMQ cho:
1. Video production pipeline (task routing giữa Master ↔ Workers)
2. Alert distribution
3. Dead Letter Queue (DLQ) cho failed tasks

Tất cả messages persistent (disk-backed). Queue dùng quorum mode.

## Files cần tạo

```
src/omnicast/queue/
├── __init__.py
├── connection.py      # RabbitMQ connection management
├── publisher.py       # Publish messages to exchanges
└── consumer.py        # Consume messages from queues
```

## 1. Queue Topology

```
Exchanges:
  omnicast.video     (topic)  → route video production tasks
  omnicast.alert     (fanout) → broadcast alerts
  omnicast.dlq       (direct) → dead letter destination

Queues:
  video.scripting       ← bind: omnicast.video / routing_key=scripting
  video.rendering       ← bind: omnicast.video / routing_key=rendering
  video.uploading       ← bind: omnicast.video / routing_key=uploading
  video.quality_check   ← bind: omnicast.video / routing_key=quality_check

  alert.telegram        ← bind: omnicast.alert
  alert.dashboard       ← bind: omnicast.alert

  dlq.video             ← bind: omnicast.dlq / routing_key=video
  dlq.alert             ← bind: omnicast.dlq / routing_key=alert

Queue arguments (ALL production queues):
  x-queue-type: quorum           # Replicated, crash-safe
  x-delivery-limit: 5            # Max redelivery before DLQ
  x-dead-letter-exchange: omnicast.dlq
  x-dead-letter-routing-key: video (hoặc alert)
  x-message-ttl: 86400000        # 24h TTL
```

## 2. connection.py

```python
"""RabbitMQ connection management.

Usage:
    await init_rabbitmq("amqp://user:pass@localhost/")
    # ... use publisher/consumer ...
    await close_rabbitmq()
"""

import aio_pika
from aio_pika import connect_robust, ExchangeType
from aio_pika.abc import AbstractRobustConnection, AbstractChannel
import structlog

logger = structlog.get_logger()

_connection: AbstractRobustConnection | None = None
_channel: AbstractChannel | None = None
```

### Functions

```python
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

async def get_channel() -> AbstractChannel:
    """Return initialized channel. Raises QueueError if not initialized."""

async def close_rabbitmq() -> None:
    """Close channel + connection gracefully."""
```

### Queue/Exchange Names (constants)

```python
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
```

## 3. publisher.py

```python
"""Publish messages to RabbitMQ exchanges.

Usage:
    publisher = VideoPublisher()
    await publisher.publish_task(video_task_message, routing_key="rendering")
"""

import orjson
import aio_pika
from omnicast.models.schemas import VideoTaskMessage, AlertMessage

class VideoPublisher:
    """Publish video production tasks."""
    
    async def publish_task(self, message: VideoTaskMessage, routing_key: str) -> None:
        """Publish VideoTaskMessage to omnicast.video exchange.
        
        Args:
            message: VideoTaskMessage (Pydantic model)
            routing_key: one of RK_SCRIPTING, RK_RENDERING, etc.
        
        Implementation:
        1. Get channel via get_channel()
        2. Get exchange via channel.get_exchange(EXCHANGE_VIDEO)
        3. Serialize message: orjson.dumps(message.model_dump(mode="json"))
        4. Create aio_pika.Message with:
           - body = serialized bytes
           - delivery_mode = DeliveryMode.PERSISTENT
           - content_type = "application/json"
           - message_id = f"{message.video_id}_{message.status}"
           - priority = PRIORITY_MAP[message.priority]
        5. exchange.publish(msg, routing_key=routing_key)
        6. Log: "Published video task" with video_id, routing_key
        
        Raises:
            QueueError: if publish fails
        """
    
    async def publish_to_dlq(self, message: VideoTaskMessage, error: str) -> None:
        """Send failed task to DLQ with error details.
        
        - Add error to message details
        - Publish to EXCHANGE_DLQ with routing_key="video"
        """

class AlertPublisher:
    """Publish alerts to fanout exchange."""
    
    async def publish_alert(self, message: AlertMessage) -> None:
        """Publish AlertMessage to omnicast.alert exchange (fanout).
        
        - Serialize with orjson
        - DeliveryMode.PERSISTENT
        - No routing_key needed (fanout)
        """

# Priority mapping
PRIORITY_MAP = {
    "emergency": 9,
    "urgent": 7,
    "high": 5,
    "normal": 3,
    "low": 1,
}
```

## 4. consumer.py

```python
"""Consume messages from RabbitMQ queues.

Usage:
    consumer = VideoConsumer(queue_name="video.rendering")
    await consumer.start(callback=handle_render_task)
    # ... runs until cancelled ...
    await consumer.stop()
"""

from collections.abc import Callable, Awaitable
from omnicast.models.schemas import VideoTaskMessage, AlertMessage

class VideoConsumer:
    """Consume video tasks from a specific queue."""
    
    def __init__(self, queue_name: str):
        self.queue_name = queue_name
        self._consumer_tag: str | None = None
    
    async def start(
        self,
        callback: Callable[[VideoTaskMessage], Awaitable[None]],
    ) -> None:
        """Start consuming messages.
        
        Args:
            callback: async function that processes VideoTaskMessage.
                     If callback raises → message is NACK'd (redelivered).
                     If callback returns normally → message is ACK'd.
        
        Implementation:
        1. Get channel
        2. Get queue via channel.get_queue(self.queue_name)
        3. queue.consume(self._on_message)
        4. Store callback for use in _on_message
        
        _on_message logic:
          async with message.process():  # auto-ack on success, nack on exception
              body = orjson.loads(message.body)
              task = VideoTaskMessage.model_validate(body)
              await callback(task)
        
        Error handling:
          - If message fails to deserialize → nack(requeue=False) → goes to DLQ
          - If callback raises → message requeued (up to x-delivery-limit)
          - Log all errors with message_id
        """
    
    async def stop(self) -> None:
        """Cancel consumer. Graceful: wait for current message to finish."""

class AlertConsumer:
    """Consume alerts from alert queue."""
    
    def __init__(self, queue_name: str):
        self.queue_name = queue_name
    
    async def start(
        self,
        callback: Callable[[AlertMessage], Awaitable[None]],
    ) -> None:
        """Same pattern as VideoConsumer but deserializes AlertMessage."""
    
    async def stop(self) -> None: ...

class DLQConsumer:
    """Consume from Dead Letter Queue for manual review/retry.
    
    DLQ messages have extra headers:
      x-death: [{count, reason, queue, time, exchange, routing-keys}]
    
    Parse x-death to get: original queue, failure count, first failure time.
    """
    
    def __init__(self, queue_name: str):
        self.queue_name = queue_name
    
    async def start(
        self,
        callback: Callable[[dict], Awaitable[None]],
    ) -> None:
        """Consume DLQ messages. Callback receives raw dict with x-death metadata."""
    
    async def stop(self) -> None: ...
```

## 5. Tests

### tests/unit/test_queue.py

```python
"""Unit tests using mocked aio_pika.

Test cases:
1. test_video_publisher_serializes_correctly
   - Create VideoTaskMessage
   - Mock channel + exchange
   - Call publish_task
   - Verify: exchange.publish called with correct body (deserialize and check)
   - Verify: delivery_mode == PERSISTENT
   - Verify: routing_key matches

2. test_video_publisher_priority_mapping
   - Publish with priority="urgent"
   - Verify: message.priority == 7

3. test_alert_publisher_fanout
   - Publish AlertMessage
   - Verify: exchange.publish called with no routing_key (empty string)

4. test_video_consumer_ack_on_success
   - Mock queue.consume
   - Simulate message arrival
   - Callback succeeds → verify message.ack() called

5. test_video_consumer_nack_on_callback_failure
   - Callback raises Exception
   - Verify: message NOT ack'd (requeue for retry)

6. test_video_consumer_invalid_json_nack_no_requeue
   - Message body is invalid JSON
   - Verify: nack(requeue=False) → goes to DLQ

7. test_dlq_consumer_parses_x_death_headers
   - Message with x-death headers
   - Verify: callback receives metadata with original queue, failure count
"""
```

### tests/integration/test_queue_integration.py

```python
"""Integration tests with real RabbitMQ via testcontainers.

@pytest.fixture(scope="module")
async def rabbitmq_container():
    # Start RabbitMQ container
    # init_rabbitmq(url)
    # yield
    # close_rabbitmq()

Test cases:
1. test_publish_and_consume_video_task
   - Publish VideoTaskMessage to QUEUE_RENDERING
   - Consume from QUEUE_RENDERING
   - Verify: received message matches published

2. test_message_persistence
   - Publish message
   - Restart container (simulate crash)
   - Consume → message still there

3. test_dlq_after_max_retries
   - Publish message
   - Consumer always raises (simulating failure)
   - After x-delivery-limit → message appears in DLQ queue
"""
```

## 6. DO NOT

- ❌ Đừng dùng pika (sync) — dùng aio-pika (async)
- ❌ Đừng dùng classic queues — dùng quorum queues (x-queue-type: quorum)
- ❌ Đừng dùng transient messages — luôn DeliveryMode.PERSISTENT
- ❌ Đừng auto-ack — dùng manual ack (message.process() context manager)
- ❌ Đừng serialize bằng pickle — dùng orjson (JSON)
- ❌ Đừng hardcode queue names — import constants từ connection.py
- ❌ Đừng catch Exception chung trong consumer — chỉ catch specific errors, let others bubble

## 7. Acceptance Criteria

```bash
uv run pytest tests/unit/test_queue.py -v
docker compose up -d rabbitmq
uv run pytest tests/integration/test_queue_integration.py -v
uv run pyright src/omnicast/queue/
```
