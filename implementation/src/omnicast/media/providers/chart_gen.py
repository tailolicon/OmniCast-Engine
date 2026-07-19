"""Data-viz chart generator for stat scenes.

Renders a clean horizontal bar chart (sans-serif, light background, restrained)
with an optional hand-drawn-style RED annotation arrow pointing at the key bar and
a small source credit watermark — the "Epoch AI chart with a red arrow" device from
high-retention explainer videos. Output is a 1920x1080 PNG used as a scene image.

Safe + optional: returns False if matplotlib is unavailable so callers fall back.
"""
from __future__ import annotations

from pathlib import Path
import structlog

logger = structlog.get_logger()


def available() -> bool:
    try:
        import matplotlib  # noqa: F401
        return True
    except Exception:
        return False


def render_chart(
    data: list[tuple[str, float]],
    out_png: Path,
    *,
    title: str = "",
    highlight_label: str | None = None,
    source: str = "",
    w: int = 1920,
    h: int = 1080,
) -> bool:
    """Render labelled values as a horizontal bar chart PNG.

    data: list of (label, value). highlight_label: bar to mark with a red arrow.
    """
    if not available() or not data:
        return False
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager  # noqa: F401

        labels = [str(d[0]) for d in data]
        values = [float(d[1]) for d in data]
        n = len(data)

        dpi = 160
        fig, ax = plt.subplots(figsize=(w / dpi, h / dpi), dpi=dpi)
        fig.patch.set_facecolor("#f7f9fb")
        ax.set_facecolor("#f7f9fb")

        ypos = list(range(n))[::-1]  # first item on top
        base = "#1f9c93"            # teal, matches reference palette
        hi = "#e23b3b"
        colors = [hi if (highlight_label and lbl == highlight_label) else base
                  for lbl in labels]
        bars = ax.barh(ypos, values, color=colors, height=0.62, zorder=3)

        ax.set_yticks(ypos)
        ax.set_yticklabels(labels, fontsize=20, color="#1a2330")
        ax.tick_params(length=0)
        for s in ("top", "right", "left"):
            ax.spines[s].set_visible(False)
        ax.spines["bottom"].set_color("#c8d0d8")
        ax.set_xlim(0, max(values) * 1.18)
        ax.grid(axis="x", color="#e2e8ee", zorder=0)

        # value labels at bar ends
        for b, v in zip(bars, values):
            ax.text(b.get_width() + max(values) * 0.012,
                    b.get_y() + b.get_height() / 2,
                    f"{v:g}", va="center", ha="left", fontsize=18,
                    color="#1a2330", fontweight="bold")

        if title:
            import textwrap as _tw
            _t = "\n".join(_tw.wrap(title, width=52)[:2])
            fig.text(0.035, 0.965, _t, fontsize=25, fontweight="bold",
                     color="#0f1720", ha="left", va="top")

        # hand-drawn-style red arrow pointing at the highlighted bar
        if highlight_label and highlight_label in labels:
            idx = labels.index(highlight_label)
            yb = ypos[idx]
            xv = values[idx]
            ax.annotate("", xy=(xv + max(values) * 0.02, yb),
                        xytext=(xv + max(values) * 0.30, yb + 0.9),
                        arrowprops=dict(color=hi, lw=4, shrink=0.02,
                                        connectionstyle="arc3,rad=-0.3",
                                        headwidth=18, headlength=18), zorder=5)

        if source:
            fig.text(0.985, 0.02, source, ha="right", va="bottom",
                     fontsize=13, color="#7a8794")

        out_png.parent.mkdir(parents=True, exist_ok=True)
        fig.subplots_adjust(left=0.30, right=0.96, top=0.82, bottom=0.10)
        fig.savefig(str(out_png), facecolor=fig.get_facecolor())
        plt.close(fig)
        return out_png.exists() and out_png.stat().st_size > 0
    except Exception as e:
        logger.warning("chart_gen.render_failed", error=str(e))
        return False
