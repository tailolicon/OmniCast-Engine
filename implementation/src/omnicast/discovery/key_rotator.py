"""YouTube API key pool with automatic rotation on quota exhaustion.

Usage:
    rotator = YouTubeKeyRotator(["key1", "key2", "key3"])

    # In HTTP callers — replace self._http.get(..., params={"key": api_key})
    # with:
    resp = await youtube_get(http, url, params, rotator)
    # Automatically rotates key on 403/429, raises QuotaExhaustedError if all gone.
"""

from __future__ import annotations

import asyncio

import httpx
import structlog

logger = structlog.get_logger()

QUOTA_ERROR_CODES = {403, 429}


class QuotaExhaustedError(Exception):
    """All YouTube API keys have hit daily quota."""


class YouTubeKeyRotator:
    """Thread-safe API key pool. Rotates on quota exhaustion."""

    def __init__(self, keys: list[str]) -> None:
        active = [k for k in keys if k and k.strip()]
        if not active:
            raise ValueError("YouTubeKeyRotator requires at least one non-empty key")
        self._keys = active
        self._current_idx = 0
        self._exhausted: set[int] = set()
        self._lock = asyncio.Lock()

    @property
    def current_key(self) -> str:
        return self._keys[self._current_idx]

    @property
    def key_count(self) -> int:
        return len(self._keys)

    @property
    def available_count(self) -> int:
        return len(self._keys) - len(self._exhausted)

    async def mark_exhausted_and_rotate(self, exhausted_key: str) -> str:
        """Mark key as quota-exhausted and switch to next available.

        Returns new key. Raises QuotaExhaustedError if all keys exhausted.
        """
        async with self._lock:
            try:
                idx = self._keys.index(exhausted_key)
                self._exhausted.add(idx)
                logger.warning(
                    "YouTube API key quota hit",
                    key_index=idx,
                    exhausted=len(self._exhausted),
                    total=len(self._keys),
                    remaining=len(self._keys) - len(self._exhausted),
                )
            except ValueError:
                pass  # Key not in list — still try to rotate

            # Find next non-exhausted index
            for offset in range(1, len(self._keys) + 1):
                candidate = (self._current_idx + offset) % len(self._keys)
                if candidate not in self._exhausted:
                    self._current_idx = candidate
                    logger.info(
                        "Rotated YouTube API key",
                        new_index=self._current_idx,
                        available=self.available_count,
                    )
                    return self._keys[self._current_idx]

            raise QuotaExhaustedError(
                f"All {len(self._keys)} YouTube API key(s) exhausted for today. "
                "Add more keys via YOUTUBE_API_KEYS env var."
            )


async def youtube_get(
    http: httpx.AsyncClient,
    url: str,
    params: dict,
    rotator: YouTubeKeyRotator,
    max_retries: int = 3,
) -> httpx.Response:
    """GET with automatic key rotation on 403/429.

    Also implements automatic retries with exponential backoff for network errors (timeouts) 
    and 5xx server errors.
    Raises QuotaExhaustedError if all keys fail with quota errors.
    Raises httpx.HTTPStatusError for non-quota HTTP errors (e.g. 400).
    """
    last_status: int = 0

    for attempt in range(rotator.key_count):
        current_key = rotator.current_key
        params["key"] = current_key

        for retry in range(max_retries):
            try:
                resp = await http.get(url, params=params)
            except httpx.RequestError as exc:
                if retry == max_retries - 1:
                    raise exc  # Exhausted retries for network error
                await asyncio.sleep(2 ** retry)
                continue

            if resp.status_code >= 500:
                if retry == max_retries - 1:
                    resp.raise_for_status()
                await asyncio.sleep(2 ** retry)
                continue

            if resp.status_code not in QUOTA_ERROR_CODES:
                resp.raise_for_status()  # Raise on 4xx (non-quota)
                return resp

            last_status = resp.status_code
            break  # Break retry loop, go to key rotation

        # Quota error — try next key
        try:
            await rotator.mark_exhausted_and_rotate(current_key)
        except QuotaExhaustedError:
            raise QuotaExhaustedError(
                f"All {rotator.key_count} YouTube API key(s) exhausted "
                f"(last HTTP {last_status})"
            )

    raise QuotaExhaustedError(
        f"All {rotator.key_count} YouTube API key(s) exhausted "
        f"(last HTTP {last_status})"
    )
