"""Production tab — Pipeline table with row-click detail panel. No expander spam."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from omnicast.dashboard.data_service import DashboardDataService
from omnicast.dashboard.models import DashboardFilter


_STATUS_EMOJI = {
    "queued": "⏳", "researching": "🔍", "debating": "🤖",
    "rendering": "🎬", "uploading": "📤", "published": "✅", "failed": "❌",
}


def render_production(data_service: DashboardDataService) -> None:
    st.title("🎬 Production Pipeline")

    # ── Filters ───────────────────────────────────────────────────────────
    col_f1, col_f2, col_f3 = st.columns([2, 2, 1])
    with col_f1:
        status_filter = st.selectbox(
            "Status",
            ["All", "queued", "researching", "debating", "rendering", "uploading", "failed"],
            index=0,
        )
    with col_f2:
        channel_filter = st.text_input("Channel ID", placeholder="fin_retirement_us")
    with col_f3:
        limit = st.number_input("Limit", min_value=20, max_value=500, value=100, step=20)

    filter_obj = DashboardFilter(
        status=status_filter if status_filter != "All" else None,
        channel_id=channel_filter if channel_filter else None,
        limit=int(limit),
    )
    items = data_service.get_pipeline_items(filter=filter_obj)

    total_cost = sum(i.cost_usd for i in items)
    st.caption(f"**{len(items)}** items · LLM cost tổng: **${total_cost:.4f}**")

    if not items:
        st.info("Không có pipeline items nào.")
        return

    # ── Build dataframe ───────────────────────────────────────────────────
    rows = []
    for item in items:
        emoji = _STATUS_EMOJI.get(item.status, "❓")
        score_str = f"{item.critic_score:.0f}" if item.critic_score is not None else "—"
        rows.append({
            "Status":   f"{emoji} {item.status}",
            "Title":    item.title or "(untitled)",
            "Channel":  item.channel_id,
            "Niche":    item.niche,
            "Progress": item.progress_pct,
            "Cost $":   item.cost_usd,
            "Score":    score_str,
            "Started":  item.started_at.strftime("%m-%d %H:%M") if item.started_at else "—",
        })

    df = pd.DataFrame(rows)

    # ── Table with row selection ──────────────────────────────────────────
    st.markdown("**Click vào dòng bất kỳ để xem chi tiết ngay bên dưới:**")

    selection = st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Progress": st.column_config.ProgressColumn(
                "Progress", min_value=0, max_value=100, format="%d%%",
            ),
            "Cost $": st.column_config.NumberColumn(
                "Cost $", format="$%.4f",
            ),
        },
        key="prod_table",
    )

    # ── Detail panel (inline — no click to expand needed) ─────────────────
    selected_rows = selection.selection.rows if selection.selection else []

    if selected_rows:
        idx = selected_rows[0]
        item = items[idx]
        emoji = _STATUS_EMOJI.get(item.status, "❓")

        st.markdown(f"""
        <div class="detail-panel">
            <strong style="font-size:1rem;">{emoji} {item.title or item.video_id}</strong>
            <span style="color:#64748b;font-size:.8rem;margin-left:10px;">{item.status.upper()}</span>
        </div>
        """, unsafe_allow_html=True)

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.write(f"**Channel:** `{item.channel_id}`")
            st.write(f"**Niche:** {item.niche}")
        with c2:
            st.write(f"**Video ID:** `{item.video_id}`")
            st.write(f"**Started:** {item.started_at.strftime('%Y-%m-%d %H:%M') if item.started_at else '—'}")
        with c3:
            st.metric("LLM Cost", f"${item.cost_usd:.4f}")
        with c4:
            if item.critic_score is not None:
                icon = "🟢" if item.critic_score >= 75 else "🟡" if item.critic_score >= 50 else "🔴"
                st.metric("Critic Score", f"{icon} {item.critic_score:.1f}")
            else:
                st.metric("Critic Score", "—")

        st.progress(item.progress_pct / 100, text=f"Progress: {item.progress_pct:.0f}%")

    else:
        st.markdown(
            "<div style='color:#475569;font-size:.82rem;padding:10px 0;'>"
            "← Click vào 1 dòng để xem chi tiết</div>",
            unsafe_allow_html=True,
        )
