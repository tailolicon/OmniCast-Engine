"""Which platform does a pasted source link belong to?

Stdlib-only on purpose: vault_link imports this to stamp
`reup_jobs.source_platform`, and vault code must never drag in HTTP clients.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

_BILIBILI_HOSTS = ("bilibili.com", "b23.tv", "bili2233.cn")
_DOUYIN_HOSTS = ("douyin.com", "iesdouyin.com")

# A bare id pasted without a URL: BV1xxxxxxxxx or av170001.
_BARE_BILI_RE = re.compile(r"^(?:BV[0-9A-Za-z]{10}|av\d+)$")


def detect_source_platform(url: str) -> str:
    """'bilibili' | 'douyin' (douyin is the historical default)."""
    text = (url or "").strip()
    if _BARE_BILI_RE.match(text):
        return "bilibili"
    probe = text if "://" in text else f"https://{text}"
    host = (urlsplit(probe).hostname or "").lower()
    for h in _BILIBILI_HOSTS:
        if host == h or host.endswith("." + h):
            return "bilibili"
    for h in _DOUYIN_HOSTS:
        if host == h or host.endswith("." + h):
            return "douyin"
    return "douyin"
