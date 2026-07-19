"""RabbitMQ dispatch + worker for distributed jobs (M0, PR6).

Resource slot == consumer QoS prefetch: a worker sets prefetch = its slot count
per resource-class queue (jobs.gpu / jobs.cpu / jobs.net), so RabbitMQ never hands
a worker more GPU jobs than it has GPU slots — bounded concurrency without a custom
scheduler. The pure helpers below are unit-tested; the live publish/consume path
needs a running broker (aio_pika) and is integration-tested separately.
"""

from __future__ import annotations

import orjson

from omnicast.jobengine.models import JobSpec, ResourceClass

EXCHANGE_JOBS = "omnicast.jobs"


def queue_name(rc: ResourceClass) -> str:
    return f"jobs.{rc.value}"


def prefetch_for(slots, rc: ResourceClass) -> int:
    return {ResourceClass.GPU: slots.slots_gpu,
            ResourceClass.CPU: slots.slots_cpu,
            ResourceClass.NET: slots.slots_net}[rc]


def encode_job(spec: JobSpec) -> bytes:
    return orjson.dumps(spec.model_dump(mode="json"))


def decode_job(body: bytes) -> JobSpec:
    return JobSpec(**orjson.loads(body))


async def publish(spec: JobSpec, *, channel) -> None:  # pragma: no cover - needs broker
    import aio_pika
    ex = await channel.get_exchange(EXCHANGE_JOBS)
    await ex.publish(aio_pika.Message(body=encode_job(spec), priority=spec.priority),
                     routing_key=spec.resource_class.value)


async def run_worker(engine, slots, rc, *, channel):  # pragma: no cover - needs broker
    await channel.set_qos(prefetch_count=max(1, prefetch_for(slots, rc)))
    queue = await channel.get_queue(queue_name(rc))
    async with queue.iterator() as it:
        async for msg in it:
            async with msg.process():
                await engine.execute(decode_job(msg.body))
