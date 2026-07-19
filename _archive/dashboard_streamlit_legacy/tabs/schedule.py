"""Schedule tab — ChannelGuard upload velocity: weekly slots used vs limit per channel."""

from __future__ import annotations

import streamlit as st

from omnicast.dashboard.data_service import DashboardDataService


def render_schedule(data_service: DashboardDataService) -> None:
    st.title("📅 Upload Schedule")

    statuses = data_service.get_velocity_statuses()

    if not statuses:
        st.info("No channel profiles found — add JSON files to `channels/`.")
        return

    # ── Summary ───────────────────────────────────────────────────────────
    n_at_limit = sum(1 for s in statuses if s.at_limit)
    n_young = sum(1 for s in statuses if s.is_young)

    m1, m2, m3 = st.columns(3)
    with m1:
        st.metric("Channels", len(statuses))
    with m2:
        label = f"🚫 {n_at_limit}" if n_at_limit else "0"
        st.metric("At Limit This Week", label)
    with m3:
        st.metric("🌱 Young Channels (< 90d)", n_young)

    st.caption(
        "ChannelGuard rules: 🌱 Young channel (< 90 days) → max **3 uploads/week**. "
        "🏆 Mature → max **7 uploads/week**."
    )

    st.divider()

    # ── Per-channel velocity bars ─────────────────────────────────────────
    st.subheader("Weekly Velocity")

    for s in statuses:
        # Header
        age_badge = ""
        if s.age_days is not None:
            age_badge = f"🌱 {s.age_days}d" if s.is_young else f"🏆 {s.age_days}d"
        else:
            age_badge = "🌱 young"

        limit_badge = " 🚫 AT LIMIT" if s.at_limit else ""
        rpm_badge = f" · RPM floor ${s.rpm_floor:.0f}"

        col_label, col_bar = st.columns([2, 3])
        with col_label:
            st.markdown(
                f"**{s.channel_name}**  \n"
                f"`{s.channel_id}` · {age_badge}{rpm_badge}"
            )
            if s.at_limit:
                st.error(f"Limit reached ({s.uploads_this_week}/{s.max_weekly})")
            else:
                st.write(
                    f"{s.uploads_this_week} / {s.max_weekly} used · "
                    f"**{s.remaining} slot{'s' if s.remaining != 1 else ''} left**"
                )

        with col_bar:
            progress = s.uploads_this_week / s.max_weekly if s.max_weekly > 0 else 0
            bar_text = f"{s.uploads_this_week}/{s.max_weekly}"
            if s.at_limit:
                # Show as full (use 1.0)
                st.progress(1.0, text=f"⛔ {bar_text} — no more uploads this week")
            elif progress >= 0.67:
                st.progress(progress, text=f"🟡 {bar_text} — approaching limit")
            else:
                st.progress(progress, text=bar_text)

        st.write("")  # spacer

    st.divider()

    # ── Explanation ───────────────────────────────────────────────────────
    with st.expander("ℹ️ ChannelGuard rules"):
        st.markdown("""
        **Why upload limits?**

        YouTube's algorithm penalises new channels that flood uploads. ChannelGuard enforces:

        | Channel age | Max uploads/week |
        |---|---|
        | < 90 days (🌱 young) | 3 |
        | ≥ 90 days (🏆 mature) | 7 |

        **Age detection:** read from `channel_created_at` field in `channels/{id}.json`.
        If missing, the channel is treated as **young** (safe default).

        **Week boundary:** Monday 00:00 UTC.

        To override limits, update `channel_created_at` in the channel JSON file and restart the dashboard.
        """)
