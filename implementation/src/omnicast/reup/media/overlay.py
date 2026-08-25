"""Cover regions, channel logo and a roaming anti-theft watermark.

Three things a reup channel needs on top of the picture:

* **cover regions** — the source still carries its own burned-in Chinese
  subtitles and the uploader's captions/handle. Those have to be hidden before
  the Vietnamese subtitle is drawn, or the two overlap into mush.
* **a channel logo** — fixed corner, sized and faded to taste.
* **a roaming watermark** — a faint mark that drifts across the frame so a
  re-uploader cannot simply crop one corner off.

Geometry is stored as *fractions of the frame*, not pixels, so a region drawn
against a 1080p preview still lands correctly when the same project is exported
as a 9:16 short.

Filters slot into `subtitle.hardsub.build_video_filter_graph` in this order:
resolution → covers → subtitles → logo → roaming watermark. Covers must precede
subtitles; drawing our text first and blurring afterwards would blur our own
words.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

CoverMode = Literal["blur", "pixelate", "box"]
LogoPosition = Literal[
    "top-left", "top-right", "bottom-left", "bottom-right", "top-center", "bottom-center"
]

OVERLAY_FILENAME = "overlays.json"

# Roaming path periods, in seconds. Deliberately co-prime-ish so x and y do not
# resynchronise for minutes — a mark that retraces a short loop is easy to mask
# out in a single pass.
ROAM_PERIOD_X = 37.0
ROAM_PERIOD_Y = 53.0


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass(slots=True)
class CoverRegion:
    """A rectangle to hide, in fractions of the frame (0–1)."""

    x: float
    y: float
    width: float
    height: float
    mode: CoverMode = "blur"
    # Blur radius / pixelation coarseness. Higher hides more but smears wider.
    strength: int = 12
    # How strongly the cover is applied. Below 1.0 the original shows through,
    # which reads as "softened" rather than "censored" — useful over artwork.
    opacity: float = 1.0
    label: str = ""

    def normalised(self) -> "CoverRegion":
        x, y = _clamp01(self.x), _clamp01(self.y)
        return CoverRegion(
            x=x,
            y=y,
            width=_clamp01(min(self.width, 1.0 - x)),
            height=_clamp01(min(self.height, 1.0 - y)),
            mode=self.mode,
            strength=max(1, int(self.strength)),
            opacity=_clamp01(self.opacity),
            label=self.label,
        )

    @property
    def is_empty(self) -> bool:
        region = self.normalised()
        return region.width <= 0.001 or region.height <= 0.001


@dataclass(slots=True)
class LogoOverlay:
    path: str = ""
    position: LogoPosition = "top-right"
    # Width as a fraction of frame width.
    scale: float = 0.12
    opacity: float = 0.85
    margin: int = 24
    enabled: bool = True

    @property
    def is_active(self) -> bool:
        return bool(self.enabled and self.path and Path(self.path).is_file())


@dataclass(slots=True)
class RoamingWatermark:
    """A faint mark that drifts, so cropping one corner does not remove it."""

    path: str = ""
    text: str = ""
    scale: float = 0.10
    opacity: float = 0.25
    # Fraction of the frame the mark wanders over (1.0 = corner to corner).
    travel: float = 0.9
    font_size: int = 42
    # Explicit font file. The Windows ffmpeg builds ship without fontconfig, so
    # drawtext without one dies with "Cannot load default config file".
    font_file: str = ""
    enabled: bool = False

    @property
    def is_active(self) -> bool:
        if not self.enabled:
            return False
        return bool(self.text) or bool(self.path and Path(self.path).is_file())

    @property
    def uses_image(self) -> bool:
        return bool(self.path and Path(self.path).is_file())


# The exported ASS declares no PlayResX/PlayResY, so libass falls back to its
# 384x288 reference. Every size and margin below is in that space — which is why
# font size 12 reads as a normal caption on 1080p (it is scaled by 1080/288).
ASS_REF_WIDTH = 384
ASS_REF_HEIGHT = 288

# ASS alignment follows the numeric keypad: 1-3 bottom, 4-6 middle, 7-9 top;
# 1/4/7 left, 2/5/8 centre, 3/6/9 right.
ASS_ALIGN_BOTTOM_CENTER = 2


@dataclass(slots=True)
class SubtitleStyle:
    """The knobs worth exposing on the burned-in Vietnamese subtitle.

    Position is an ASS anchor plus margins rather than free coordinates: libass
    lays text out from one of nine anchor points, so "drag anywhere" has to be
    expressed as "nearest anchor, then offset from that edge".
    """

    font_size: int = 12
    outline: int = 2
    shadow: int = 0
    margin_v: int = 48
    margin_l: int = 10
    margin_r: int = 10
    alignment: int = ASS_ALIGN_BOTTOM_CENTER
    font_name: str = "Arial"


def subtitle_anchor_from_fraction(
    x: float, y: float
) -> tuple[int, int, int, int]:
    """Map a dragged point to (alignment, margin_l, margin_r, margin_v).

    `x`/`y` are the centre of where the operator put the subtitle box, as
    fractions of the frame. The frame is split into thirds; the third the point
    lands in picks the anchor, and the distance to that anchor's edge becomes
    the margin — so the text ends up where it was dropped rather than snapping
    to the middle of the third.
    """
    x, y = _clamp01(x), _clamp01(y)

    column = 0 if x < 1 / 3 else (1 if x < 2 / 3 else 2)
    if y >= 2 / 3:
        row_base, from_bottom = 1, True          # 1-3
    elif y >= 1 / 3:
        row_base, from_bottom = 4, False         # 4-6, vertically centred
    else:
        row_base, from_bottom = 7, False         # 7-9, measured from the top
    alignment = row_base + column

    if from_bottom:
        margin_v = int(round((1.0 - y) * ASS_REF_HEIGHT))
    elif row_base == 7:
        margin_v = int(round(y * ASS_REF_HEIGHT))
    else:
        # Middle anchors ignore MarginV; keep the stored value harmless.
        margin_v = 0

    if column == 0:
        margin_l = int(round(x * ASS_REF_WIDTH))
        margin_r = 10
    elif column == 2:
        margin_l = 10
        margin_r = int(round((1.0 - x) * ASS_REF_WIDTH))
    else:
        margin_l = margin_r = 10

    return alignment, max(0, margin_l), max(0, margin_r), max(0, margin_v)


@dataclass(slots=True)
class OverlayConfig:
    covers: list[CoverRegion] = field(default_factory=list)
    logo: LogoOverlay = field(default_factory=LogoOverlay)
    roaming: RoamingWatermark = field(default_factory=RoamingWatermark)
    subtitle: SubtitleStyle = field(default_factory=SubtitleStyle)

    def to_dict(self) -> dict:
        return {
            "covers": [asdict(c) for c in self.covers],
            "logo": asdict(self.logo),
            "roaming": asdict(self.roaming),
            "subtitle": asdict(self.subtitle),
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "OverlayConfig":
        return cls(
            covers=[CoverRegion(**c) for c in (raw.get("covers") or [])],
            logo=LogoOverlay(**(raw.get("logo") or {})),
            roaming=RoamingWatermark(**(raw.get("roaming") or {})),
            subtitle=SubtitleStyle(**(raw.get("subtitle") or {})),
        )

    def render_fingerprint(self) -> dict | None:
        """What actually reaches the picture, for the export cache key.

        Only the layers that draw anything: an inactive logo or a cover the
        editor left at zero size changes no pixel, so it must not change the
        hash either — otherwise merely opening the editor would force a
        re-render. Returns None when nothing draws, which keeps the cache of
        jobs that never touched overlays valid.

        The subtitle style is deliberately absent: it travels into the ASS
        file, and the export already hashes that file's contents.
        """
        covers = [asdict(c.normalised()) for c in self.covers if not c.is_empty]
        logo = asdict(self.logo) if self.logo.is_active else None
        roaming = asdict(self.roaming) if self.roaming.is_active else None
        if not covers and logo is None and roaming is None:
            return None
        return {"covers": covers, "logo": logo, "roaming": roaming}


def config_path(project_root: Path) -> Path:
    return project_root / OVERLAY_FILENAME


def load_config(project_root: Path, channel_file: Path | None = None) -> OverlayConfig:
    """Overlays for a job, falling back to the channel's saved defaults.

    Boxes are per video — the source's Chinese text does not sit in the same
    place twice — but the branding around them (logo, roaming mark, subtitle
    style) belongs to the channel, and re-entering it on every reup is how it
    ends up inconsistent across a playlist.
    """
    path = config_path(project_root)
    if not path.is_file():
        return load_channel_defaults(channel_file) if channel_file else OverlayConfig()
    try:
        return OverlayConfig.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        # A corrupt overlay file must not stop a render; no overlays is a safe
        # state, a half-parsed one is not.
        return OverlayConfig()


CHANNEL_KEY = "reup_overlays"

# implementation/src/omnicast/reup/media/overlay.py → implementation/
_IMPL_ROOT = Path(__file__).resolve().parents[4]


def channel_file_for(channel_id: str | None) -> Path | None:
    """Path of a channel's config, or None when the job is not bound to one."""
    if not channel_id:
        return None
    candidate = _IMPL_ROOT / "channels" / f"{channel_id}.json"
    return candidate if candidate.is_file() else None


def load_channel_defaults(channel_file: Path | None) -> OverlayConfig:
    """Channel-level overlay defaults, read from `channels/<id>.json`.

    Kept in the channel config the renderer already treats as source of truth
    rather than a new store of its own.
    """
    if channel_file is None or not channel_file.is_file():
        return OverlayConfig()
    try:
        payload = json.loads(channel_file.read_text(encoding="utf-8"))
        return OverlayConfig.from_dict(payload.get(CHANNEL_KEY) or {})
    except (OSError, ValueError, TypeError):
        return OverlayConfig()


def save_channel_defaults(channel_file: Path, config: OverlayConfig) -> None:
    """Store overlays on the channel without disturbing the rest of its config."""
    payload: dict = {}
    if channel_file.is_file():
        try:
            payload = json.loads(channel_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {}
    if not isinstance(payload, dict):
        raise ValueError(f"{channel_file.name} is not a channel config object")
    payload[CHANNEL_KEY] = config.to_dict()
    channel_file.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def save_config(project_root: Path, config: OverlayConfig) -> Path:
    path = config_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(config.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _sync_ass_style(project_root, config.subtitle)
    return path


def _sync_ass_style(project_root: Path, style: SubtitleStyle) -> None:
    """Mirror the subtitle style into the file the ASS exporter reads.

    `subtitle.export._load_ass_style` reads
    `presets/styles/default_ass_style.json`; writing there is what makes a font
    size chosen in the editor actually reach the burned-in subtitle, without
    threading the config through every export call site.
    """
    style_path = project_root / "presets" / "styles" / "default_ass_style.json"
    payload: dict = {}
    if style_path.is_file():
        try:
            payload = json.loads(style_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = {}
    payload.setdefault("style_preset_id", "default-ass")
    payload.setdefault("name", "Mac dinh ASS")
    ass = dict(payload.get("ass_style_json") or {})
    ass.update(
        {
            "FontName": style.font_name,
            "FontSize": max(1, int(style.font_size)),
            "Outline": max(0, int(style.outline)),
            "Shadow": max(0, int(style.shadow)),
            "MarginV": max(0, int(style.margin_v)),
            "MarginL": max(0, int(style.margin_l)),
            "MarginR": max(0, int(style.margin_r)),
            "Alignment": int(style.alignment) if 1 <= int(style.alignment) <= 9 else 2,
        }
    )
    payload["ass_style_json"] = ass
    style_path.parent.mkdir(parents=True, exist_ok=True)
    style_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def build_cover_filters(
    regions: list[CoverRegion], *, in_label: str, index: int
) -> tuple[list[str], str, int]:
    """Filters that hide each region. Returns (filters, out_label, next_index)."""
    filters: list[str] = []
    current = in_label

    for region in regions:
        region = region.normalised()
        if region.is_empty:
            continue

        # Expressed against iw/ih so the same fractions work at any resolution.
        geometry = (
            f"w=iw*{region.width:.5f}:h=ih*{region.height:.5f}"
            f":x=iw*{region.x:.5f}:y=ih*{region.y:.5f}"
        )

        if region.mode == "box":
            nxt = f"[cv{index}]"
            filters.append(
                f"{current}drawbox={geometry}:color=black@{region.opacity:.3f}:t=fill{nxt}"
            )
            current, index = nxt, index + 1
            continue

        if region.mode == "pixelate":
            # Shrink then blow back up with no interpolation.
            factor = max(2, region.strength)
            treatment = (
                f"scale=iw/{factor}:ih/{factor}:flags=neighbor,"
                f"scale=iw*{factor}:ih*{factor}:flags=neighbor"
            )
        else:
            treatment = f"boxblur={region.strength}:{max(1, region.strength // 4)}"

        split_a, split_b = f"[ca{index}]", f"[cb{index}]"
        patch = f"[cp{index}]"
        nxt = f"[cv{index}]"
        filters.append(f"{current}split{split_a}{split_b}")
        filters.append(f"{split_b}crop={geometry},{treatment}{patch}")
        # crop and drawbox read iw/ih, but overlay's expression context defines
        # only W/H (main) and w/h (the patch) — iw there is "Undefined constant".
        # A partially transparent patch lets the original bleed through.
        if region.opacity < 0.999:
            faded = f"[cf{index}]"
            filters.append(
                f"{patch}format=rgba,colorchannelmixer=aa={region.opacity:.3f}{faded}"
            )
            patch = faded
        filters.append(
            f"{split_a}{patch}overlay=x=W*{region.x:.5f}:y=H*{region.y:.5f}{nxt}"
        )
        current, index = nxt, index + 1

    return filters, current, index


def build_logo_filters(
    logo: LogoOverlay, *, in_label: str, logo_input_index: int, index: int
) -> tuple[list[str], str, int]:
    """Overlay a fixed-corner logo scaled to a fraction of frame width."""
    if not logo.is_active:
        return [], in_label, index

    rgba = f"[lg{index}a]"
    scaled = f"[lg{index}b]"
    base = f"[lg{index}c]"
    nxt = f"[lg{index}]"

    filters = [
        f"[{logo_input_index}:v]format=rgba,"
        f"colorchannelmixer=aa={_clamp01(logo.opacity):.3f}{rgba}",
        f"{rgba}{in_label}scale2ref=w=main_w*{_clamp01(logo.scale):.4f}:h=ow/mdar{scaled}{base}",
        f"{base}{scaled}overlay={_position_expr(logo.position, logo.margin)}{nxt}",
    ]
    return filters, nxt, index + 1


def build_roaming_filters(
    mark: RoamingWatermark, *, in_label: str, image_input_index: int | None, index: int
) -> tuple[list[str], str, int]:
    """A drifting mark. Image if one is configured, otherwise drawn text."""
    if not mark.is_active:
        return [], in_label, index

    travel = _clamp01(mark.travel)
    # Two sine waves at different periods trace a Lissajous path: it covers the
    # frame without ever settling, and never repeats within a short clip.
    x_expr = f"(W-w)*({(1 - travel) / 2:.4f}+{travel:.4f}*(0.5+0.5*sin(2*PI*t/{ROAM_PERIOD_X})))"
    y_expr = f"(H-h)*({(1 - travel) / 2:.4f}+{travel:.4f}*(0.5+0.5*sin(2*PI*t/{ROAM_PERIOD_Y})))"

    if mark.uses_image and image_input_index is not None:
        rgba = f"[rm{index}a]"
        scaled = f"[rm{index}b]"
        base = f"[rm{index}c]"
        nxt = f"[rm{index}]"
        filters = [
            f"[{image_input_index}:v]format=rgba,"
            f"colorchannelmixer=aa={_clamp01(mark.opacity):.3f}{rgba}",
            f"{rgba}{in_label}scale2ref=w=main_w*{_clamp01(mark.scale):.4f}:h=ow/mdar{scaled}{base}",
            f"{base}{scaled}overlay=x='{x_expr}':y='{y_expr}'{nxt}",
        ]
        return filters, nxt, index + 1

    nxt = f"[rm{index}]"
    # drawtext has no overlay pair, so w/h in the expressions become text_w/h.
    text_x = x_expr.replace("W-w", "w-text_w").replace("(H-h)", "(h-text_h)")
    text_y = y_expr.replace("H-h", "h-text_h").replace("(W-w)", "(w-text_w)")
    escaped = _escape_drawtext(mark.text)
    font = mark.font_file or find_default_font()
    font_arg = f":fontfile='{_escape_filter_path(font)}'" if font else ""
    filters = [
        f"{in_label}drawtext=text='{escaped}'{font_arg}"
        f":fontsize={max(8, int(mark.font_size))}"
        f":fontcolor=white@{_clamp01(mark.opacity):.3f}"
        f":shadowcolor=black@{_clamp01(mark.opacity) * 0.6:.3f}:shadowx=2:shadowy=2"
        f":x='{text_x}':y='{text_y}'{nxt}"
    ]
    return filters, nxt, index + 1


# Fonts that carry Vietnamese diacritics, most preferred first.
_FONT_CANDIDATES = (
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/tahoma.ttf",
    "C:/Windows/Fonts/calibri.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def find_default_font() -> str:
    """A font drawtext can actually load, or "" if none is present."""
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return ""


def _escape_filter_path(path: str) -> str:
    """`C:/…` must become `C\\:/…` — a bare colon ends the filter option."""
    return str(path).replace("\\", "/").replace(":", r"\:")


def _position_expr(position: LogoPosition, margin: int) -> str:
    margin = max(0, int(margin))
    horizontal = {
        "left": f"{margin}",
        "right": f"main_w-overlay_w-{margin}",
        "center": "(main_w-overlay_w)/2",
    }
    vertical = {
        "top": f"{margin}",
        "bottom": f"main_h-overlay_h-{margin}",
    }
    vertical_key, _, horizontal_key = position.partition("-")
    return (
        f"{horizontal.get(horizontal_key, horizontal['right'])}:"
        f"{vertical.get(vertical_key, vertical['top'])}"
    )


def _escape_drawtext(text: str) -> str:
    """drawtext parses its own mini-language; these characters end the value."""
    out = text.replace("\\", "\\\\")
    for char in (":", "'", "%", ","):
        out = out.replace(char, f"\\{char}")
    return out
