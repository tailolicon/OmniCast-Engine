"""Revenue tab — Per-channel P&L table + cost breakdown pie chart."""

from __future__ import annotations

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from omnicast.dashboard.data_service import DashboardDataService


def render_revenue(data_service: DashboardDataService) -> None:
    st.title("💰 Revenue & Cost")

    # ── Period selector ───────────────────────────────────────────────────
    period = st.radio(
        "Period",
        options=[7, 14, 30, 90],
        format_func=lambda d: f"{d}d",
        horizontal=True,
        index=1,
    )

    rows = data_service.get_revenue_summary()
    cost_summary = data_service.get_cost_summary(days=period)

    # ── Top-level KPIs ────────────────────────────────────────────────────
    total_rev = sum(r.revenue_usd for r in rows)
    total_cost = cost_summary.total_usd or sum(r.cost_usd for r in rows)
    total_profit = total_rev - total_cost
    total_videos = sum(r.videos_count for r in rows)

    m1, m2, m3, m4, m5 = st.columns(5)
    with m1:
        st.metric("Revenue", f"${total_rev:.2f}")
    with m2:
        st.metric("Cost", f"${total_cost:.4f}")
    with m3:
        profit_delta = f"${total_profit:.2f}"
        st.metric("Profit", profit_delta, delta=profit_delta, delta_color="normal")
    with m4:
        st.metric("Videos", total_videos)
    with m5:
        if cost_summary.cost_per_video:
            st.metric("Cost/Video", f"${cost_summary.cost_per_video:.4f}")
        else:
            st.metric("Cost/Video", "—")

    st.divider()

    col_left, col_right = st.columns([3, 2])

    # ── Per-channel P&L table ─────────────────────────────────────────────
    with col_left:
        st.subheader("Per-Channel P&L")
        if not rows:
            st.info("No revenue data. Check DB connection.")
        else:
            import pandas as pd

            table_rows = []
            for r in rows:
                roi_str = f"{r.roi_pct:.1f}%" if r.roi_pct is not None else "—"
                profit_icon = "📈" if r.profit_usd >= 0 else "📉"
                table_rows.append({
                    "": profit_icon,
                    "Channel": r.channel_name,
                    "Revenue": f"${r.revenue_usd:.2f}",
                    "Cost": f"${r.cost_usd:.4f}",
                    "Profit": f"${r.profit_usd:.2f}",
                    "ROI": roi_str,
                    "Videos": r.videos_count,
                })
            df = pd.DataFrame(table_rows)
            st.dataframe(df, use_container_width=True, hide_index=True)

            # Bar chart: revenue vs cost per channel (top 10)
            top10 = rows[:10]
            if top10:
                fig = go.Figure()
                fig.add_bar(
                    name="Revenue",
                    x=[r.channel_name for r in top10],
                    y=[r.revenue_usd for r in top10],
                    marker_color="#22c55e",
                )
                fig.add_bar(
                    name="Cost",
                    x=[r.channel_name for r in top10],
                    y=[r.cost_usd for r in top10],
                    marker_color="#ef4444",
                )
                fig.update_layout(
                    barmode="group",
                    height=280,
                    margin=dict(l=0, r=0, t=30, b=60),
                    showlegend=True,
                    plot_bgcolor="rgba(0,0,0,0)",
                    paper_bgcolor="rgba(0,0,0,0)",
                    xaxis_tickangle=-30,
                    title="Revenue vs Cost (top 10 channels)",
                )
                st.plotly_chart(fig, use_container_width=True)

    # ── Cost breakdown pie ────────────────────────────────────────────────
    with col_right:
        st.subheader(f"Cost Breakdown ({period}d)")
        if cost_summary.by_category:
            fig_pie = px.pie(
                names=list(cost_summary.by_category.keys()),
                values=list(cost_summary.by_category.values()),
                color_discrete_sequence=px.colors.qualitative.Set3,
            )
            fig_pie.update_layout(
                height=300,
                margin=dict(l=0, r=0, t=20, b=0),
                paper_bgcolor="rgba(0,0,0,0)",
                showlegend=True,
            )
            st.plotly_chart(fig_pie, use_container_width=True)

            st.markdown("**Breakdown:**")
            for cat, amt in sorted(
                cost_summary.by_category.items(), key=lambda x: x[1], reverse=True
            ):
                pct = (amt / total_cost * 100) if total_cost > 0 else 0
                st.write(f"• **{cat}**: ${amt:.4f} ({pct:.1f}%)")
        else:
            st.info(f"No cost data for last {period} days.")
