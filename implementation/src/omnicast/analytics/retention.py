"""Retention Analyst - analyze retention curves, find drop-off points."""

from __future__ import annotations
import structlog

logger = structlog.get_logger()


class RetentionAnalyst:
    """Analyze retention curves, find drop-off points, correlate with script segments."""

    def find_drop_points(self, retention_curve: list[float], threshold: float = 5.0) -> list[dict]:
        """Find points where retention drops more than threshold% between intervals."""
        if not retention_curve or len(retention_curve) < 2:
            return []

        drop_points = []
        for i in range(1, len(retention_curve)):
            prev = retention_curve[i - 1]
            curr = retention_curve[i]
            drop_pct = prev - curr

            if drop_pct > threshold:
                drop_points.append({
                    "index": i,
                    "prev_value": prev,
                    "curr_value": curr,
                    "drop_pct": drop_pct,
                })

        return drop_points

    def correlate_with_script(self, drop_points: list[dict],
                                script_segments: list[str]) -> list[dict]:
        """Map drop points to script segments by index."""
        if not drop_points or not script_segments:
            return []

        correlated = []
        for drop in drop_points:
            idx = drop["index"]
            # Map index to segment (approximate)
            segment_idx = min(idx // max(1, len(script_segments)), len(script_segments) - 1)
            segment = script_segments[segment_idx] if segment_idx < len(script_segments) else "unknown"

            correlated.append({
                "index": idx,
                "segment": segment,
                "drop_pct": drop["drop_pct"],
            })

        return correlated

    def summarize_patterns(self, video_analyses: list[dict]) -> dict[str, list[str]]:
        """Aggregate common drop-off patterns across multiple videos."""
        patterns = {"common_segments": [], "avg_drops": {}}

        segment_drops = {}
        for analysis in video_analyses:
            drops = analysis.get("drops", [])
            for drop in drops:
                segment = drop.get("segment", "unknown")
                drop_pct = drop.get("drop_pct", 0)

                if segment not in segment_drops:
                    segment_drops[segment] = []
                segment_drops[segment].append(drop_pct)

        # Calculate averages
        for segment, drops in segment_drops.items():
            avg_drop = sum(drops) / len(drops) if drops else 0
            patterns["avg_drops"][segment] = avg_drop

        # Find common segments (appearing in >50% of videos)
        threshold = len(video_analyses) * 0.5
        for segment, drops in segment_drops.items():
            if len(drops) >= threshold:
                patterns["common_segments"].append(segment)

        return patterns
