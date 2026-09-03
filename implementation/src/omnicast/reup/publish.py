"""Move a finished dub into the per-channel product layout.

The dub pipeline works inside `output/reup/<aweme_id>/`, which is a *working*
directory: caches, segment cuts, half a dozen subtitle attempts, and an export
named after the Chinese source. Everything else in OmniCast delivers into
`output/products/<channel>/<date>_<slug>/` — one folder per finished video, with
`video.mp4`, `script.txt` and `meta.json` in known places. Reup was the only
producer that never landed there, so its output sat outside the library.

The video is copied, not moved and not hard-linked. Moving it would break the
export cache, which checks its output still exists. Hard-linking looked free
but was wrong: ffmpeg rewrites the export path on the next render, and a link
means those bytes ARE the delivered product — so a re-export mutates a video
already published, and an interrupted one corrupts it. The copy is written to a
temp name and swapped in, so a product is either the old file or the new one.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from omnicast.storage.products import (
    iter_products,
    new_product_dir,
    read_meta,
    script_path,
    variants_dir,
    video_path,
    write_meta,
)

# A job with no channel still has to land somewhere findable rather than being
# left in the working directory. The leading underscore keeps it sorted apart
# from real channels.
UNASSIGNED_CHANNEL = "_chua_gan_kenh"


def resolve_product_dir(channel: str | None, aweme_id: str, title: str) -> Path:
    """The product folder for this source video, creating it on first publish.

    Looked up by `source_aweme_id` in existing meta rather than recomputed from
    the title, so re-exporting after a title change updates the same folder
    instead of scattering a second copy next to the first.
    """
    channel_dir = channel or UNASSIGNED_CHANNEL
    for candidate in iter_products(channel_dir):
        if str(read_meta(candidate).get("source_aweme_id") or "") == str(aweme_id):
            return candidate
    return new_product_dir(channel_dir, title or f"douyin_{aweme_id}")


def _publish_file(src: Path, dst: Path) -> None:
    """Copy `src` to `dst` atomically — never leave a half-written product."""
    staging = dst.with_name(dst.name + ".incoming")
    staging.unlink(missing_ok=True)
    try:
        shutil.copy2(src, staging)
        os.replace(staging, dst)
    finally:
        staging.unlink(missing_ok=True)


def publish_reup_product(
    *,
    channel: str | None,
    aweme_id: str,
    exported_video: Path,
    title: str,
    source_url: str = "",
    subtitle_paths: list[Path] | None = None,
    script_lines: list[str] | None = None,
    cover_path: Path | None = None,
    **meta_fields,
) -> Path:
    """Publish one finished dub and return its product folder."""
    product_dir = resolve_product_dir(channel, aweme_id, title)
    variants_dir(product_dir).mkdir(parents=True, exist_ok=True)

    if exported_video.is_file():
        _publish_file(exported_video, video_path(product_dir))

    # The source's own cover, as a starting point for the Vietnamese thumbnail.
    if cover_path is not None and cover_path.is_file():
        _publish_file(cover_path, product_dir / f"thumb{cover_path.suffix or '.jpg'}")

    for subtitle in subtitle_paths or []:
        if subtitle.is_file():
            _publish_file(subtitle, product_dir / f"subtitles{subtitle.suffix}")

    if script_lines:
        script_path(product_dir).write_text("\n".join(script_lines), encoding="utf-8")

    write_meta(
        product_dir,
        kind="reup",
        channel=channel or UNASSIGNED_CHANNEL,
        title=title,
        source_url=source_url,
        source_aweme_id=str(aweme_id),
        source_language="zh",
        target_language="vi",
        **meta_fields,
    )
    return product_dir
