"""NAS health monitoring.

Periodically check if NAS mount is alive and writable.
If NAS goes down → switch PathResolver to local fallback.
If NAS comes back → switch back + sync pending files.

Usage:
    checker = NASHealthChecker(
        resolver=path_resolver,
        check_interval=30,
    )
    await checker.start()
    # ... runs in background ...
    await checker.stop()
"""

import asyncio
import time
from pathlib import Path

import structlog

logger = structlog.get_logger()


class NASHealthChecker:
    """Monitor NAS availability and manage fallback.

    Args:
        resolver: PathResolver instance to control fallback
        check_interval: seconds between health checks
        probe_file: filename for write probe test
    """

    def __init__(
        self,
        resolver: "PathResolver",
        check_interval: int = 30,
        probe_file: str = ".omnicast_probe",
    ):
        self.resolver = resolver
        self.check_interval = check_interval
        self.probe_file = probe_file
        self._task: asyncio.Task | None = None
        self._running = False
        self.last_check: float = 0.0
        self.consecutive_failures: int = 0
        self.is_healthy: bool = True

    async def check_once(self) -> bool:
        """Perform single health check.

        Steps:
        1. Check if NAS mount point exists (path.is_dir())
        2. Write probe file with timestamp
        3. Read probe file back → verify content matches
        4. Delete probe file
        5. If all OK → return True
        6. If any step fails → return False

        Must complete within 5s timeout (asyncio.wait_for).
        Use asyncio.to_thread for all file ops.

        Returns:
            True if NAS is healthy, False otherwise
        """
        try:
            nas_path = self.resolver.nas_path

            # Step 1: Check if NAS mount point exists
            if not await asyncio.to_thread(nas_path.is_dir):
                return False

            probe_path = nas_path / self.probe_file
            timestamp = str(time.time())

            # Step 2: Write probe file with timestamp
            def _write_probe():
                probe_path.write_text(timestamp)

            await asyncio.wait_for(
                asyncio.to_thread(_write_probe), timeout=5.0
            )

            # Step 3: Read probe file back → verify content matches
            def _read_probe() -> str:
                return probe_path.read_text()

            content = await asyncio.wait_for(
                asyncio.to_thread(_read_probe), timeout=5.0
            )

            if content != timestamp:
                return False

            # Step 4: Delete probe file
            await asyncio.to_thread(probe_path.unlink, missing_ok=True)

            return True
        except (TimeoutError, OSError, Exception):
            return False

    async def _monitor_loop(self) -> None:
        """Background monitoring loop.

        Loop:
        1. await check_once()
        2. If healthy:
           - Reset consecutive_failures = 0
           - If was_unhealthy → log "NAS recovered", set resolver.set_fallback(False)
        3. If unhealthy:
           - Increment consecutive_failures
           - If consecutive_failures >= 3 (not first failure):
             - Log WARNING "NAS unavailable, switching to local"
             - resolver.set_fallback(True)
             - self.is_healthy = False
        4. Sleep check_interval

        3 consecutive failures before fallback → avoid flapping on transient issues.
        """
        was_unhealthy = False
        while self._running:
            healthy = await self.check_once()
            self.last_check = time.time()

            if healthy:
                self.consecutive_failures = 0
                if was_unhealthy:
                    logger.info("NAS recovered, switching back to NAS storage")
                    self.resolver.set_fallback(False)
                    self.is_healthy = True
                    was_unhealthy = False
            else:
                self.consecutive_failures += 1
                if self.consecutive_failures >= 3:
                    if not was_unhealthy:
                        logger.warning(
                            "NAS unavailable, switching to local",
                            consecutive_failures=self.consecutive_failures,
                        )
                    self.resolver.set_fallback(True)
                    self.is_healthy = False
                    was_unhealthy = True

            try:
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break

    async def start(self) -> None:
        """Start background monitoring task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("NAS health checker started", interval=self.check_interval)

    async def stop(self) -> None:
        """Stop background monitoring."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("NAS health checker stopped")

    async def get_status(self) -> dict:
        """Return health status for dashboard.

        Return:
            {
                "is_healthy": bool,
                "using_fallback": bool,
                "last_check": float (timestamp),
                "consecutive_failures": int,
                "nas_path": str,
                "local_path": str,
            }
        """
        return {
            "is_healthy": self.is_healthy,
            "using_fallback": self.resolver._use_local,
            "last_check": self.last_check,
            "consecutive_failures": self.consecutive_failures,
            "nas_path": str(self.resolver.nas_path),
            "local_path": str(self.resolver.local_path),
        }