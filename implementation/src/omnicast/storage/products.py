"""Single source of truth for per-product output paths.

One rendered video == one self-contained folder:

    output/products/{channel}/{YYYYMMDD_HHMM}_{slug}/
        script.txt          chosen script (the one that gets rendered)
        variants/           debate variants + their .json (audit trail)
        video.mp4
        video_thumb.png     (render writes <stem>_thumb.png)
        video_title.txt     (render writes <stem>_title.txt)
        _assets/  _status/   (render working dirs, isolated per product)
        meta.json           manifest linking everything + score/voice/duration

Every other module should import paths from HERE instead of hardcoding
`output/scripts` / `output/pipeline_renders` / `output/real`, so the layout
can be changed in ONE place.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

IMPL_ROOT = Path(__file__).resolve().parents[3]   # src/omnicast/storage/ → implementation/
OUTPUT_DIR = IMPL_ROOT / "output"
PRODUCTS_DIR = OUTPUT_DIR / "products"


def slugify(text: str, n: int = 50) -> str:
    return re.sub(r"[^\w]+", "_", (text or "").lower()).strip("_")[:n] or "untitled"


def new_product_dir(channel: str, topic: str, *, stamp: str | None = None) -> Path:
    """Create and return a fresh product folder for one (channel, topic) run."""
    stamp = stamp or time.strftime("%Y%m%d_%H%M")
    pd = PRODUCTS_DIR / channel / f"{stamp}_{slugify(topic)}"
    (pd / "variants").mkdir(parents=True, exist_ok=True)
    return pd


# --- well-known files inside a product dir ---
def script_path(pd: Path) -> Path: return pd / "script.txt"
def video_path(pd: Path) -> Path: return pd / "video.mp4"
def variants_dir(pd: Path) -> Path: return pd / "variants"
def meta_path(pd: Path) -> Path: return pd / "meta.json"


def is_product_dir(p: Path) -> bool:
    """True if p looks like a product folder (lives under products/ or has meta)."""
    try:
        return p.is_dir() and (meta_path(p).exists() or PRODUCTS_DIR in p.parents)
    except Exception:
        return False


def read_meta(pd: Path) -> dict:
    f = meta_path(pd)
    if f.exists():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def write_meta(pd: Path, **fields) -> dict:
    """Merge non-None fields into meta.json (creating it if missing)."""
    meta = read_meta(pd)
    meta.update({k: v for k, v in fields.items() if v is not None})
    meta.setdefault("created", time.strftime("%Y-%m-%dT%H:%M:%S"))
    meta["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    pd.mkdir(parents=True, exist_ok=True)
    meta_path(pd).write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


def release_issues(pd: Path) -> list[str]:
    """Return blockers for products that use quality-gate contract v1+.

    Legacy folders without ``release_gate_version`` stay renderable. New products
    fail closed unless narration and production metadata both passed release.
    """
    meta = read_meta(Path(pd))
    if not meta.get("release_gate_version"):
        return []
    issues = [
        field for field in ("script_approved", "content_locked", "production_ready")
        if meta.get(field) is not True
    ]
    if meta.get("stage") == "needs_edit":
        issues.append("stage_needs_edit")
    # Every production approval is bound to exact artifact bytes. Overrides take
    # their hashes from the signed review; automated releases store them in meta.
    if meta.get("production_ready") is True:
        is_override = "override" in str(meta.get("release_basis", ""))
        binding_source = meta
        script_issue = "script_release_hash_mismatch"
        storyboard_issue = "storyboard_release_hash_mismatch"
    else:
        is_override = False
        binding_source = {}
        script_issue = "script_release_hash_mismatch"
        storyboard_issue = "storyboard_release_hash_mismatch"
    if is_override:
        review_name = meta.get("final_review")
        review_file = Path(pd) / str(review_name or "")
        try:
            review = json.loads(review_file.read_text(encoding="utf-8")) if review_name else {}
        except (OSError, ValueError, TypeError):
            review = {}
        if not review:
            issues.append("final_review_missing")
        else:
            binding_source = review
            script_issue = "script_review_hash_mismatch"
            storyboard_issue = "storyboard_review_hash_mismatch"
    if meta.get("production_ready") is True and (not is_override or binding_source):
        bindings = [
            ("script_sha256", script_path(Path(pd)), script_issue, True),
            ("storyboard_sha256", Path(pd) / "script.json", storyboard_issue, False),
        ]
        for field, artifact, issue, required in bindings:
            expected = str(binding_source.get(field, "")).lower()
            exists = artifact.exists()
            if not required and not exists and not expected:
                continue
            actual = hashlib.sha256(artifact.read_bytes()).hexdigest() if exists else ""
            if not expected or expected != actual:
                issues.append(issue)
    return issues


def product_dir_for_asset(asset: Path) -> Path:
    """Resolve an asset nested below a product (for example ``variants/``).

    The nearest ancestor containing ``meta.json`` owns the release contract.
    Assets outside a manifested product retain their immediate parent so legacy
    scripts keep the historical permissive behaviour.
    """
    asset = Path(asset)
    start = asset if asset.is_dir() else asset.parent
    for candidate in (start, *start.parents):
        if meta_path(candidate).exists():
            return candidate
        if candidate == PRODUCTS_DIR:
            break
    return start


def publish_blockers(pd: Path) -> list[str]:
    """Reasons this product must not leave the machine.

    Kept SEPARATE from `release_issues()` on purpose. `release_issues()` gates
    the RENDER, and a re-render is the repair path for everything below — a
    packaging failure that blocked the next render would block the only route
    that clears it, which is the deadlock this project already shipped once with
    `needs_human`.

    A flag nothing reads is a comment. `render_real_video` writes
    `publishable=False` / `packaging_blocked` when a channel that declared
    `competitor_intel_required` could not get usable intel; until this function
    existed, the MP4 was still the channel's newest render and both the publish
    queue and the direct upload would happily take it.
    """
    meta = read_meta(Path(pd))
    issues: list[str] = []
    if meta.get("publishable") is False:
        issues.append("marked_unpublishable")
    blocked = str(meta.get("packaging_blocked") or "").strip()
    if blocked:
        issues.append(f"packaging_blocked: {blocked[:200]}")
    return issues


def publish_blockers_for_video(video: Path) -> list[str]:
    """All blockers that can be decided for a concrete rendered cut.

    Packaging blockers live on the product. Human review is additionally bound
    to the exact video bytes, so it belongs on this asset-aware path used by
    direct upload and the final platform adapter.
    """
    video = Path(video)
    return list(dict.fromkeys([
        *publish_blockers(product_dir_for_asset(video)),
        *human_review_blockers_for_video(video),
    ]))


def human_review_blockers_for_video(video: Path) -> list[str]:
    """Require a named, timestamped review of the exact current cut."""
    video = Path(video)
    meta = read_meta(product_dir_for_asset(video))
    if meta.get("requires_human_review") is not True:
        return []

    review = meta.get("human_review")
    if not isinstance(review, dict):
        return ["human_review_required: no human review has been recorded"]
    for field in ("reviewer", "reviewed_at", "artifact_sha256"):
        if not str(review.get(field) or "").strip():
            return [f"human_review_required: the recorded review has no {field}"]
    try:
        current = hashlib.sha256(video.read_bytes()).hexdigest()
    except OSError as exc:
        return [f"human_review_required: current cut could not be hashed ({exc})"]
    if review["artifact_sha256"] != current:
        return [
            "human_review_required: the recorded review covers a different cut"
        ]
    return []


def mark_packaging_ready(pd: Path) -> dict:
    """Clear a prior packaging failure after packaging succeeds.

    ``write_meta`` intentionally merges fields, so both failure markers must be
    replaced explicitly.  Keep this transition separate from render release
    gates: re-rendering is the repair path for a packaging failure.
    """
    return write_meta(
        Path(pd),
        packaging_blocked="",
        publishable=True,
    )


def release_issues_for_script(script: Path) -> list[str]:
    """Return release blockers for a concrete script asset.

    A gate-versioned product approves only its canonical ``script.txt``. Audit
    variants remain inspectable but cannot accidentally bypass the contract by
    living in a child directory without their own metadata.
    """
    script = Path(script)
    pd = product_dir_for_asset(script)
    meta = read_meta(pd)
    issues = release_issues(pd)
    if meta.get("release_gate_version"):
        try:
            is_canonical = script.resolve() == script_path(pd).resolve()
        except OSError:
            is_canonical = False
        if not is_canonical:
            issues.append("noncanonical_script")
    return list(dict.fromkeys(issues))


def _ffprobe(video: Path) -> dict:
    """Probe a video for the QC-relevant stream facts. Best-effort (returns {} if
    ffprobe missing/fails)."""
    import subprocess
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", str(video)],
            capture_output=True, text=True, timeout=60)
        data = json.loads(out.stdout or "{}")
    except Exception:
        return {}
    info: dict = {}
    fmt = data.get("format", {})
    if fmt.get("duration"):
        info["duration_s"] = round(float(fmt["duration"]), 1)
    if fmt.get("bit_rate"):
        info["bitrate_kbps"] = round(int(fmt["bit_rate"]) / 1000)
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and "width" in s:
            info["width"] = s["width"]
            info["height"] = s["height"]
            info["vcodec"] = s.get("codec_name")
            fr = s.get("avg_frame_rate", "0/1")
            try:
                num, den = fr.split("/")
                info["fps"] = round(int(num) / int(den), 2) if int(den) else None
            except Exception:
                pass
        elif s.get("codec_type") == "audio":
            info["acodec"] = s.get("codec_name")
            if s.get("sample_rate"):
                info["audio_sr"] = int(s["sample_rate"])
    return info


def _scan_variants(pd: Path) -> dict:
    """Variant scores from variants/*.json filenames (variant_<name>_score<NN>)."""
    out = []
    for f in sorted(variants_dir(pd).glob("variant_*_score*.txt")):
        m = re.search(r"variant_(.+?)_score(\d+)", f.stem)
        if m:
            out.append({"name": m.group(1), "score": int(m.group(2))})
    best = max(out, key=lambda v: v["score"], default=None)
    return {"variants": out, "variant_count": len(out),
            "best_variant": best["name"] if best else None,
            "best_score": best["score"] if best else None}


def build_manifest(pd: Path) -> dict:
    """Consolidate EVERYTHING about one product into meta.json for QC.

    Pulls from: dir name, channel config, variants/, script.txt, _status/status.json
    (QA + timeline + bgm + caption source), and ffprobe(video.mp4). Idempotent and
    re-runnable, so it also backfills older products. Returns the merged meta.
    """
    pd = Path(pd)
    name = pd.name
    m = re.match(r"(\d{8}_\d{4})_(.+)", name)
    stamp = m.group(1) if m else None
    fields: dict = {"slug": name, "stamp": stamp, "channel": pd.parent.name}

    # --- script ---
    sp = script_path(pd)
    if sp.exists():
        txt = sp.read_text(encoding="utf-8", errors="ignore")
        fields["script"] = sp.name
        fields["script_words"] = len(txt.split())
        fields["script_chars"] = len(txt)

    # --- variants / scores ---
    fields.update(_scan_variants(pd))

    # --- channel config: niche + resolved voice chain ---
    cfg_path = IMPL_ROOT / "channels" / f"{pd.parent.name}.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            fields["niche"] = cfg.get("niche")
            fields["market"] = cfg.get("market")
            fields["target_duration_min"] = cfg.get("target_duration_min")
            from omnicast.media.voice_router import resolve_channel_voice
            fields["voice_chain"] = [str(s) for s in resolve_channel_voice(cfg)]
        except Exception:
            pass

    # --- status.json: QA, timeline, bgm, caption source, scene count ---
    st_f = pd / "_status" / "status.json"
    if st_f.exists():
        try:
            st = json.loads(st_f.read_text(encoding="utf-8"))
            fields["run_id"] = st.get("run_id")
            fields["elapsed_s"] = st.get("elapsed")
            fields["stages"] = st.get("stages")
            fields["scene_count"] = len(st.get("shots") or [])
            if st.get("title"):
                fields["title"] = st["title"]
            qa = st.get("qa") or {}
            if qa:
                fields["qa_ok"] = qa.get("ok")
                fields["qa_summary"] = qa.get("summary")
                fields["qa_checks"] = qa.get("checks")
            # parse the log timeline for bgm track + caption (voice) source
            for line in st.get("log") or []:
                if "bgm:" in line:
                    fields["bgm"] = line.split("bgm:", 1)[1].strip()
                if "captions" in line and "(" in line:
                    src = line[line.find("(") + 1:line.find(")")]
                    fields["caption_source"] = src  # "edge timings" => edge voice used
            # infer the audio voice provider from the caption-timing source
            cs = (fields.get("caption_source") or "").lower()
            if "edge" in cs:
                fields["voice_provider_used"] = "edge"
            elif fields.get("voice_chain"):
                fields["voice_provider_used"] = fields["voice_chain"][0].split(":")[0]
        except Exception:
            pass

    # --- video probe ---
    v = video_path(pd)
    if v.exists():
        fields["video"] = v.name
        fields["size_mb"] = round(v.stat().st_size / (1024 * 1024), 2)
        probe = _ffprobe(v)
        if probe:
            fields["video_probe"] = probe
            if probe.get("duration_s"):
                fields["duration_s"] = probe["duration_s"]
    for stem, key in (("video_thumb.png", "thumbnail"), ("video_title.txt", "title_file")):
        if (pd / stem).exists():
            fields[key] = stem

    return write_meta(pd, **fields)


def iter_products(channel: str | None = None) -> list[Path]:
    """All product folders (optionally one channel), newest first by mtime."""
    if not PRODUCTS_DIR.exists():
        return []
    roots = [PRODUCTS_DIR / channel] if channel else [
        d for d in PRODUCTS_DIR.iterdir() if d.is_dir()]
    out: list[Path] = []
    for root in roots:
        if root.exists():
            out.extend(d for d in root.iterdir() if d.is_dir())
    return sorted(out, key=lambda p: p.stat().st_mtime, reverse=True)


def latest_video(channel: str) -> Path | None:
    for pd in iter_products(channel):
        v = video_path(pd)
        if v.exists():
            return v
    return None


def latest_script(channel: str) -> Path | None:
    for pd in iter_products(channel):
        s = script_path(pd)
        if s.exists():
            return s
    return None
