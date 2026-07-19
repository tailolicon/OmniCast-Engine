"""In-memory async EventBus + persistence to the events table (M0, PR7).

Background jobs emit progress events; the API streams them to the cockpit via SSE
(no polling). Every event is also appended to the events table for audit/replay.
"""

from __future__ import annotations

import asyncio

from omnicast.jobengine import store


class EventBus:
    def __init__(self, db_path=None):
        self._db = db_path
        self._subs: set[asyncio.Queue] = set()

    def emit(self, event_type, *, job_id=None, **payload):
        store.append_event(event_type, job_id=job_id, payload=payload, db_path=self._db)
        ev = {"type": event_type, "job_id": job_id, "payload": payload}
        for q in list(self._subs):
            try:
                q.put_nowait(ev)
            except Exception:
                pass

    async def subscribe(self, *, job_id=None):
        """Async generator yielding live events (optionally filtered by job_id)."""
        q: asyncio.Queue = asyncio.Queue()
        self._subs.add(q)
        try:
            while True:
                ev = await q.get()
                if job_id is None or ev["job_id"] == job_id:
                    yield ev
        finally:
            self._subs.discard(q)
