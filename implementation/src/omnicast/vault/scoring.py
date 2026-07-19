"""Dynamic health score calculation for vault niches.

Scoring philosophy (Operator-tested rules):
- Freshness decay: small/slow — niche age alone shouldn't kill it
- Saturation: 3+ DEDICATED channels (≥5 videos on topic, subs >50k) = real threat
- Single big channel posting 1 video = algorithm boost, NOT saturation
- Micro-outlier: <10k subs channel nailing the niche = starvation signal = HOT
- VPD: measured on NEW videos (last 14d), not decaying old videos
"""
from __future__ import annotations

from omnicast.vault.models import NicheStatus


def calculate_health_score(
    original_score: int,
    days_since_save: int,
    new_videos_count: int,       # evidence channels: new videos last 14d
    avg_new_vpd: float,          # vpd of those new videos
    original_vpd: float,         # vpd at save time (from evidence)
    dedicated_competitors: int,  # channels ≥5 topic videos, subs >50k
    micro_outlier_found: bool,   # <10k subs channel nổ outlier mới
) -> int:
    score = float(original_score)

    # 1. Freshness decay — gentle: -2 per 30 days, max -10
    #    Niche stays good until competitors appear, not just because of age
    freshness_penalty = min((days_since_save // 30) * 2, 10)
    score -= freshness_penalty

    # 2. Evidence channel still active? (new videos in last 21 days)
    # -30 if silent: channel stopping upload = demonetized / copyright strike / dead.
    # -10 was too soft — score 90 → 80 still looks healthy (WATCHING), masking danger.
    if new_videos_count == 0:
        score -= 30  # RED FLAG: originator abandoned niche
    elif avg_new_vpd > 0 and original_vpd > 0:
        vpd_ratio = avg_new_vpd / original_vpd
        if vpd_ratio < 0.3:
            score -= 8   # new videos much weaker than originals
        elif vpd_ratio > 1.2:
            score += 5   # new videos accelerating

    # 3. Competitor saturation — Gemini's rule:
    #    3+ dedicated channels = real saturation (NOT 1 big channel = 1 video)
    if dedicated_competitors >= 5:
        score -= 30  # saturated
    elif dedicated_competitors >= 3:
        score -= 20  # getting crowded
    elif dedicated_competitors >= 1:
        score -= 8   # first competitor appeared
    # dedicated_competitors == 0 → no penalty

    # 4. Micro-outlier signal = content starvation = HOT indicator
    # +10 only (was +25 — caused all niches to inflate to HOT regardless of score)
    # HOT status is separately gated by derive_status() requiring score >= 70.
    if micro_outlier_found:
        score += 10

    return max(0, min(100, int(score)))


def derive_status(
    health_score: int,
    micro_outlier_found: bool,
    dedicated_competitors: int,
    current_status: NicheStatus,
) -> NicheStatus:
    """Derive new status from health score + signals."""

    # ACTIVE stays ACTIVE — manual transition only (user decided to create channel)
    if current_status == NicheStatus.ACTIVE:
        return NicheStatus.ACTIVE

    # ARCHIVED stays ARCHIVED
    if current_status == NicheStatus.ARCHIVED:
        return NicheStatus.ARCHIVED

    # HOT: REQUIRES real-time trigger (micro_outlier) + score still strong.
    # Removed: `score >= 90` alone is NOT enough — that's just coasting on old data.
    # A 2-month-old niche at 91 pts has no new market signal → WATCHING, not HOT.
    if micro_outlier_found and health_score >= 75:
        return NicheStatus.HOT

    # STALE: score collapsed OR saturated by many competitors
    if health_score < 50 or dedicated_competitors >= 5:
        return NicheStatus.STALE

    # Otherwise: watching
    return NicheStatus.WATCHING
