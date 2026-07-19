"""Resource-class concurrency via semaphores (M0, PR4).

In-process mirror of the RabbitMQ QoS-prefetch mechanism: bounds how many GPU /
CPU / NET jobs run concurrently so a burst of renders can't OOM the machine.
A class with 0 slots is unavailable (acquire raises SlotError).
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

from omnicast.jobengine.models import ResourceClass


class SlotError(Exception):
    ...


def _env_int(name: str, default: int) -> int:
    """Read a positive slot count from env, falling back to `default` on missing/invalid."""
    try:
        val = int(os.environ.get(name, ""))
        return val if val >= 0 else default
    except (TypeError, ValueError):
        return default


class SlotManager:
    def __init__(self, gpu: int | None = None, cpu: int | None = None, net: int | None = None):
        # Explicit args win; otherwise env OMNICAST_SLOTS_GPU/CPU/NET; otherwise 1/4/8.
        gpu = _env_int("OMNICAST_SLOTS_GPU", 1) if gpu is None else gpu
        cpu = _env_int("OMNICAST_SLOTS_CPU", 4) if cpu is None else cpu
        net = _env_int("OMNICAST_SLOTS_NET", 8) if net is None else net
        self.counts = {ResourceClass.GPU: gpu, ResourceClass.CPU: cpu, ResourceClass.NET: net}
        self._sems = {rc: asyncio.Semaphore(n) for rc, n in self.counts.items() if n > 0}

    @asynccontextmanager
    async def acquire(self, rc: ResourceClass):
        sem = self._sems.get(rc)
        if sem is None:
            raise SlotError(f"no slots configured for resource class {rc}")
        await sem.acquire()
        try:
            yield
        finally:
            sem.release()
