"""Shared chart helpers for dashboard tabs."""

from __future__ import annotations
import streamlit as st
import plotly.graph_objects as go
from omnicast.dashboard.models import ChannelHealth, PipelineItem


def kpi_card(label: str, value: str | int | float, delta: str | None = None) -> None:
    """Render single metric card with optional delta."""
    with st.container():
        st.metric(label=label, value=value, delta=delta)


def health_heatmap(channels: list[ChannelHealth]) -> go.Figure:
    """Plotly heatmap of channel health scores."""
    if not channels:
        # Return empty figure
        fig = go.Figure()
        fig.update_layout(title="Channel Health Heatmap")
        return fig

    # Extract channel names and health scores
    names = [ch.channel_name for ch in channels]
    scores = [ch.health_score for ch in channels]

    # Create simple heatmap visualization
    fig = go.Figure(data=go.Heatmap(
        z=[scores],
        x=names,
        y=["Health Score"],
        colorscale="RdYlGn",
        showscale=True,
    ))

    fig.update_layout(
        title="Channel Health Heatmap",
        xaxis_title="Channel",
        yaxis_title="",
        height=200,
    )

    return fig


def pipeline_status_bar(items: list[PipelineItem]) -> go.Figure:
    """Horizontal stacked bar: count per pipeline status."""
    if not items:
        fig = go.Figure()
        fig.update_layout(title="Pipeline Status Distribution")
        return fig

    # Count items by status
    status_counts = {}
    for item in items:
        status_counts[item.status] = status_counts.get(item.status, 0) + 1

    # Create stacked bar chart
    fig = go.Figure(data=[
        go.Bar(
            name=status,
            x=[count],
            y=["Pipeline"],
            orientation="h",
        )
        for status, count in status_counts.items()
    ])

    fig.update_layout(
        title="Pipeline Status Distribution",
        barmode="stack",
        xaxis_title="Count",
        yaxis_title="",
        height=200,
    )

    return fig
