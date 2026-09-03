"""WBI signing for bilibili.com web API requests.

The algorithm is public knowledge (documented in the community
bilibili-API-collect project): the day's img_key+sub_key are shuffled through
a fixed index table into a 32-char mixin key; the request params (plus a `wts`
timestamp) are sorted, url-encoded with the characters ``!'()*`` stripped from
values, and md5(query + mixin) becomes `w_rid`.

Pure stdlib and pure functions — the key FETCH lives in client.py, so this
module is fully unit-testable without network.
"""
from __future__ import annotations

import hashlib
import time
import urllib.parse

_MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5,
    49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55,
    40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57,
    62, 11, 36, 20, 34, 44, 52,
]

_FILTERED_CHARS = "!'()*"


def mixin_key(img_key: str, sub_key: str) -> str:
    raw = (img_key or "") + (sub_key or "")
    return "".join(raw[i] for i in _MIXIN_KEY_ENC_TAB if i < len(raw))[:32]


def sign_params(
    params: dict, img_key: str, sub_key: str, *, wts: int | None = None
) -> dict[str, str]:
    """Return params + wts + w_rid, values as the exact strings to send.

    The signature covers the FILTERED values, so the request must carry those
    same filtered values — returning them together keeps caller and signature
    from drifting apart.
    """
    key = mixin_key(img_key, sub_key)
    out: dict[str, str] = {}
    for k, v in params.items():
        out[str(k)] = "".join(ch for ch in str(v) if ch not in _FILTERED_CHARS)
    out["wts"] = str(int(time.time()) if wts is None else int(wts))
    query = urllib.parse.urlencode(sorted(out.items()))
    out["w_rid"] = hashlib.md5((query + key).encode("utf-8")).hexdigest()
    return out
