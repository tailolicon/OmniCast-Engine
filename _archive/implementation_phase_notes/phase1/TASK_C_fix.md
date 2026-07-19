# TASK C FIX: Consumer Missing `await` on `nack()`

> **Severity:** BUG — messages silently ack'd instead of going to DLQ
> **Files:** `src/omnicast/queue/consumer.py`
> **Estimated time:** 5 min

## Root Cause

`message.nack(requeue=False)` is called WITHOUT `await`. This creates a coroutine that never executes. The `message.process()` context manager then ack's the message on normal exit — so invalid JSON gets ack'd (lost) instead of nack'd (sent to DLQ).

## Fix

### consumer.py — VideoConsumer._on_message (2 locations)

```python
# FIND (line ~68):
                message.nack(requeue=False)

# REPLACE WITH:
                await message.nack(requeue=False)
```

```python
# FIND (line ~79):
                message.nack(requeue=False)

# REPLACE WITH:
                await message.nack(requeue=False)
```

### consumer.py — AlertConsumer._on_message (2 locations)

```python
# FIND (line ~135):
                message.nack(requeue=False)

# REPLACE WITH:
                await message.nack(requeue=False)
```

```python
# FIND (line ~145):
                message.nack(requeue=False)

# REPLACE WITH:
                await message.nack(requeue=False)
```

## Total: 4 lines changed (add `await` prefix)

## Verify

```bash
uv run pytest tests/unit/test_queue.py -v
uv run pyright src/omnicast/queue/consumer.py
```

## DO NOT

- Do NOT change any other code
- Do NOT refactor consumer structure
- Do NOT touch publisher.py or connection.py
