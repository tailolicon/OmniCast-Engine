"""Bilibili (bilibili.com nội địa) ingest."""
from omnicast.ingest.bilibili.client import (
    BilibiliAsset,
    BilibiliIngestConfig,
    BilibiliIngestError,
    fetch_series_entries,
    fetch_video,
    fetch_video_sync,
)

__all__ = [
    "BilibiliAsset",
    "BilibiliIngestConfig",
    "BilibiliIngestError",
    "fetch_series_entries",
    "fetch_video",
    "fetch_video_sync",
]
