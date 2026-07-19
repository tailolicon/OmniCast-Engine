"""ROI Calculator - per-video ROI tracking and aggregation."""

from __future__ import annotations
from datetime import datetime, timezone
import structlog
from omnicast.analytics.models import ROIRecord

logger = structlog.get_logger()


class ROICalculator:
    """Calculate ROI per video, per niche, per channel."""

    def calculate_video_roi(self, video_id: str, costs: dict[str, float],
                            revenue: float, channel_id: str = "ch1",
                            niche: str = "general") -> ROIRecord:
        """Calculate ROI for a single video. ROI = (revenue - cost) / cost."""
        total_cost = sum(costs.values())
        if total_cost == 0:
            roi = 0.0
        else:
            roi = (revenue - total_cost) / total_cost

        return ROIRecord(
            video_id=video_id,
            channel_id=channel_id,
            niche=niche,
            cost_breakdown=costs,
            total_cost=total_cost,
            revenue=revenue,
            roi=roi,
        )

    def aggregate_by_niche(self, records: list[ROIRecord]) -> dict[str, float]:
        """Aggregate average ROI by niche."""
        niche_rois = {}
        niche_counts = {}

        for record in records:
            if record.niche not in niche_rois:
                niche_rois[record.niche] = 0.0
                niche_counts[record.niche] = 0
            niche_rois[record.niche] += record.roi
            niche_counts[record.niche] += 1

        # Calculate averages
        for niche in niche_rois:
            if niche_counts[niche] > 0:
                niche_rois[niche] /= niche_counts[niche]

        return niche_rois

    def aggregate_by_channel(self, records: list[ROIRecord]) -> dict[str, float]:
        """Aggregate average ROI by channel."""
        channel_rois = {}
        channel_counts = {}

        for record in records:
            if record.channel_id not in channel_rois:
                channel_rois[record.channel_id] = 0.0
                channel_counts[record.channel_id] = 0
            channel_rois[record.channel_id] += record.roi
            channel_counts[record.channel_id] += 1

        # Calculate averages
        for channel in channel_rois:
            if channel_counts[channel] > 0:
                channel_rois[channel] /= channel_counts[channel]

        return channel_rois

    def find_negative_roi_niches(self, records: list[ROIRecord],
                                 min_videos: int = 5) -> list[str]:
        """Find niches with negative ROI (requires min_videos samples)."""
        niche_rois = self.aggregate_by_niche(records)
        niche_counts = {}

        for record in records:
            if record.niche not in niche_counts:
                niche_counts[record.niche] = 0
            niche_counts[record.niche] += 1

        negative_niches = []
        for niche, avg_roi in niche_rois.items():
            if avg_roi < 0 and niche_counts.get(niche, 0) >= min_videos:
                negative_niches.append(niche)

        return negative_niches
