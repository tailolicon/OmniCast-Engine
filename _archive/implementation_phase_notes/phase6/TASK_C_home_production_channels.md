# TASK_C: Home + Production Monitor + Channel Tabs

## Model: sonnet | Dependencies: TASK_A complete

Three Streamlit tabs: dashboard home (KPIs), production kanban, channel health.

## Interface

### src/omnicast/dashboard/tabs/home.py

```python
def render_home(data_service: DashboardDataService) -> None:
    """KPI cards + pipeline status bar + activity feed."""
```

### src/omnicast/dashboard/tabs/production.py

```python
def render_production(data_service: DashboardDataService) -> None:
    """Pipeline items table with status filter + progress bars."""
```

### src/omnicast/dashboard/tabs/channels.py

```python
def render_channels(data_service: DashboardDataService) -> None:
    """Channel health heatmap + per-channel detail expander."""
```

### src/omnicast/dashboard/components/charts.py

```python
def kpi_card(label: str, value: str | int | float, delta: str | None = None) -> None:
    """Render single metric card with optional delta."""

def health_heatmap(channels: list[ChannelHealth]) -> go.Figure:
    """Plotly heatmap of channel health scores."""

def pipeline_status_bar(items: list[PipelineItem]) -> go.Figure:
    """Horizontal stacked bar: count per pipeline status."""
```

## DO NOT

- No direct DB queries — use DashboardDataService only
- No Streamlit session_state for data caching — use st.cache_data
- Charts return Plotly figures, tabs call st.plotly_chart

## Tests

### tests/unit/test_dashboard_tabs.py

```python
import pytest
from datetime import datetime, timezone
from omnicast.dashboard.models import (
    SystemKPI, PipelineItem, ChannelHealth,
)
from omnicast.dashboard.components.charts import (
    kpi_card, health_heatmap, pipeline_status_bar,
)
import plotly.graph_objects as go


class TestKPICard:
    def test_no_error(self):
        # kpi_card renders via streamlit — just verify no exception
        # In unit test without streamlit, verify function signature
        assert callable(kpi_card)


class TestHealthHeatmap:
    def test_returns_figure(self):
        channels = [
            ChannelHealth(
                channel_id="ch1", channel_name="MythTales",
                channel_type="hub", health_score=85.0,
                videos_published=10, last_upload=datetime.now(timezone.utc),
                ctr_avg=5.0, retention_avg=40.0,
            ),
            ChannelHealth(
                channel_id="ch2", channel_name="TechBits",
                channel_type="spoke", health_score=60.0,
                videos_published=5, last_upload=datetime.now(timezone.utc),
                ctr_avg=3.0, retention_avg=30.0,
            ),
        ]
        fig = health_heatmap(channels)
        assert isinstance(fig, go.Figure)

    def test_empty_channels(self):
        fig = health_heatmap([])
        assert isinstance(fig, go.Figure)


class TestPipelineStatusBar:
    def test_returns_figure(self):
        items = [
            PipelineItem(
                video_id="v1", channel_id="ch1", niche="myth",
                status="rendering", started_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc), progress_pct=50.0,
            ),
            PipelineItem(
                video_id="v2", channel_id="ch1", niche="tech",
                status="uploading", started_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc), progress_pct=90.0,
            ),
        ]
        fig = pipeline_status_bar(items)
        assert isinstance(fig, go.Figure)

    def test_counts_statuses(self):
        items = [
            PipelineItem(
                video_id=f"v{i}", channel_id="ch1", niche="myth",
                status="rendering", started_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc), progress_pct=50.0,
            )
            for i in range(5)
        ]
        fig = pipeline_status_bar(items)
        assert isinstance(fig, go.Figure)

    def test_empty_items(self):
        fig = pipeline_status_bar([])
        assert isinstance(fig, go.Figure)
```
