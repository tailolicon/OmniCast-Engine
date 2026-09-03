"""Douyin ingest.

Thin OmniCast-shaped facade over a vendored subset of
`jiji262/douyin-downloader` (MIT) in `_vendor/`. The vendored tree carries the
parts that are expensive to get right and cheap to get wrong — `a_bogus`/
`X-Bogus` request signing, msToken/ttwid handling, and no-watermark URL
selection — and is kept unmodified apart from import rebinding so it can be
refreshed from upstream.

Import from here, never from `_vendor` directly.
"""

from omnicast.ingest.douyin.client import (
    DouyinAsset,
    DouyinIngestConfig,
    DouyinIngestError,
    fetch_video,
    fetch_video_sync,
)

__all__ = [
    "DouyinAsset",
    "DouyinIngestConfig",
    "DouyinIngestError",
    "fetch_video",
    "fetch_video_sync",
]
