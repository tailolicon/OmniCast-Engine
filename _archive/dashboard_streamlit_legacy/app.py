"""Streamlit entry point — Sidebar navigation, manual refresh, no auto-wipe."""

from pathlib import Path

import streamlit as st

from omnicast.dashboard.auth import require_auth
from omnicast.dashboard.data_service import DashboardDataService
from omnicast.dashboard.tabs.home import render_home
from omnicast.dashboard.tabs.production import render_production
from omnicast.dashboard.tabs.channels import render_channels
from omnicast.dashboard.tabs.infra import render_infra
from omnicast.dashboard.tabs.dlq import render_dlq
from omnicast.dashboard.tabs.triage import render_triage
from omnicast.dashboard.tabs.tokens import render_tokens
from omnicast.dashboard.tabs.compliance import render_compliance
from omnicast.dashboard.tabs.vault import render_vault
from omnicast.dashboard.tabs.revenue import render_revenue
from omnicast.dashboard.tabs.schedule import render_schedule
from omnicast.config.settings import get_settings

st.set_page_config(
    page_title="OmniCast Dashboard",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Layout */
[data-testid="stSidebar"] { border-right: 1px solid #2d3047; }
section.main > div { padding-top: 1rem; }

/* Tabs strip unused — sidebar nav replaces it */
/* Metrics */
[data-testid="stMetric"] {
    background: #1e2130;
    border: 1px solid #2d3047;
    border-radius: 10px;
    padding: 14px 18px !important;
}
[data-testid="stMetricLabel"] { color: #94a3b8 !important; font-size: 0.78rem !important; }
[data-testid="stMetricValue"] { color: #f1f5f9 !important; font-size: 1.6rem !important; font-weight: 700 !important; }

/* Expander */
[data-testid="stExpander"] {
    background: #1e2130;
    border: 1px solid #2d3047 !important;
    border-radius: 8px;
    margin-bottom: 6px;
}
[data-testid="stExpander"] summary { color: #e2e8f0 !important; }

/* Buttons */
[data-testid="stButton"] button {
    background: #2d3047; color: #e2e8f0;
    border: 1px solid #3d4263; border-radius: 6px;
    font-size: 0.82rem; transition: all 0.15s;
}
[data-testid="stButton"] button:hover {
    background: #3d4470; border-color: #6366f1; color: #fff;
}

/* Sidebar radio nav */
[data-testid="stSidebar"] [role="radiogroup"] label {
    display: block;
    padding: 8px 14px;
    border-radius: 6px;
    margin-bottom: 2px;
    cursor: pointer;
    font-size: 0.85rem;
    color: #94a3b8 !important;
    transition: all 0.15s;
}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {
    background: #2d3047;
    color: #e2e8f0 !important;
}
[data-testid="stSidebar"] [role="radiogroup"] [aria-checked="true"] ~ label,
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
    background: #2d3047;
    color: #f1f5f9 !important;
    font-weight: 600;
    border-left: 3px solid #6366f1;
}

/* Code */
[data-testid="stCode"] { background: #141622 !important; border: 1px solid #2d3047; border-radius: 6px; }

/* Progress */
[data-testid="stProgress"] > div > div { background: #6366f1; border-radius: 4px; }

/* Divider */
hr { border-color: #2d3047; margin: 16px 0; }

/* Scrollbar */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #141622; }
::-webkit-scrollbar-thumb { background: #3d4263; border-radius: 3px; }

/* Kill-switch pulse (referenced by sidebar paused banner) */
@keyframes pulse {
    0%   { box-shadow: 0 0 0 0 rgba(239,68,68,.55); }
    70%  { box-shadow: 0 0 0 8px rgba(239,68,68,0); }
    100% { box-shadow: 0 0 0 0 rgba(239,68,68,0); }
}

/* Alert banners */
.alert-banner { padding:12px 20px; border-radius:8px; margin-bottom:16px; font-weight:600; font-size:.9rem; }
.alert-banner.critical { background:rgba(239,68,68,.15); border:1px solid rgba(239,68,68,.4); color:#fca5a5; }
.alert-banner.warning  { background:rgba(234,179,8,.12);  border:1px solid rgba(234,179,8,.35); color:#fde047; }
.alert-banner.ok       { background:rgba(34,197,94,.1);   border:1px solid rgba(34,197,94,.3);  color:#86efac; }

/* Stage cards */
.stage-card { background:#1e2130; border:1px solid #2d3047; border-radius:10px; padding:14px 16px; text-align:center; }
.stage-card .stage-count { font-size:2rem; font-weight:800; margin:4px 0; }
.stage-card .stage-name  { font-size:.72rem; color:#94a3b8; text-transform:uppercase; letter-spacing:.05em; }

/* Component cards */
.comp-card { background:#1e2130; border:1px solid #2d3047; border-radius:8px; padding:12px 16px; margin-bottom:8px; }
.comp-card.ok   { border-left:3px solid #22c55e; }
.comp-card.warn { border-left:3px solid #eab308; }
.comp-card.error{ border-left:3px solid #ef4444; }
.comp-card .comp-name   { font-weight:600; color:#e2e8f0; font-size:.85rem; }
.comp-card .comp-detail { color:#94a3b8; font-size:.75rem; margin-top:2px; }

/* Detail panel */
.detail-panel {
    background:#1e2130; border:1px solid #6366f1;
    border-radius:10px; padding:16px 20px; margin-top:12px;
}
</style>
""", unsafe_allow_html=True)

# ── Auth ──────────────────────────────────────────────────────────────────────
user_email = require_auth()
if not user_email:
    st.error("Authentication required. Please access via Cloudflare Access.")
    st.stop()

# ── Data service (init once per session) ──────────────────────────────────────
if "data_service" not in st.session_state:
    settings = get_settings()
    root = Path(__file__).resolve().parents[5]
    st.session_state.data_service = DashboardDataService(
        db_url=settings.database_url,
        redis_url=settings.redis_url,
        channels_dir=root / "channels",
        vault_path=root / "output" / "vault.db",
    )

data_service: DashboardDataService = st.session_state.data_service

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🎬 OmniCast")
    st.divider()

    # ── KPI quick-look ────────────────────────────────────────────────────
    kpis = data_service.get_kpis()
    health_color = "#22c55e" if kpis.system_health >= 80 else "#eab308" if kpis.system_health >= 50 else "#ef4444"

    st.markdown(f"""
    <div style="background:#141622;border-radius:8px;padding:10px 14px;margin-bottom:6px;">
        <div style="font-size:.7rem;color:#64748b;">SYSTEM HEALTH</div>
        <div style="font-size:1.6rem;font-weight:800;color:{health_color};">{kpis.system_health:.0f}%</div>
    </div>
    <div style="background:#141622;border-radius:8px;padding:10px 14px;margin-bottom:6px;">
        <div style="font-size:.7rem;color:#64748b;">QUEUE</div>
        <div style="font-size:1.6rem;font-weight:800;color:#e2e8f0;">{kpis.queue_depth}</div>
    </div>
    """, unsafe_allow_html=True)

    if kpis.dlq_count > 0:
        st.markdown(f"""
        <div style="background:rgba(239,68,68,.15);border:1px solid rgba(239,68,68,.4);
                    border-radius:8px;padding:8px 14px;margin-bottom:6px;animation:pulse 1.5s infinite;">
            <span style="color:#fca5a5;font-weight:700;">💀 DLQ: {kpis.dlq_count} items</span>
        </div>
        """, unsafe_allow_html=True)

    # ── Kill-switch banner (Std 2.A) ─────────────────────────────────────
    if data_service.is_pipeline_paused():
        since = data_service.get_pipeline_paused_since() or ""
        since_short = since[11:19] if len(since) >= 19 else since
        st.markdown(f"""
        <div style="background:rgba(239,68,68,.25);border:2px solid #ef4444;
                    border-radius:8px;padding:8px 14px;margin-bottom:6px;
                    animation:pulse 1.2s infinite;">
            <div style="color:#fca5a5;font-weight:800;font-size:.82rem;">🛑 PIPELINE PAUSED</div>
            <div style="color:#fecaca;font-size:.7rem;">since {since_short} UTC · Triage → Resume</div>
        </div>
        """, unsafe_allow_html=True)

    st.divider()

    # ── Navigation (ONLY selected page renders — no wasted DB queries) ────
    _PAGES = [
        "🏠 Mission Control",
        "🎬 Production",
        "📡 Channels",
        "🔧 Infrastructure",
        "💀 DLQ",
        "🚦 Triage",
        "🔑 Tokens",
        "✅ Compliance",
        "🗄️ Niche Vault",
        "💰 Revenue",
        "📅 Schedule",
    ]
    current_page = st.radio(
        "Navigation",
        _PAGES,
        label_visibility="collapsed",
        key="nav_page",
    )

    st.divider()

    # ── Manual refresh (replaces st_autorefresh) ──────────────────────────
    # NO auto-refresh — prevents wiping edit state mid-work
    col_r, col_info = st.columns([1, 2])
    with col_r:
        if st.button("🔄", help="Refresh data", key="manual_refresh"):
            st.rerun()
    with col_info:
        st.caption("Manual refresh\n(no auto-wipe)")

    st.caption(f"👤 {user_email}")

# ── Render ONLY the selected page ─────────────────────────────────────────────
if current_page == "🏠 Mission Control":
    render_home(data_service)
elif current_page == "🎬 Production":
    render_production(data_service)
elif current_page == "📡 Channels":
    render_channels(data_service)
elif current_page == "🔧 Infrastructure":
    render_infra(data_service)
elif current_page == "💀 DLQ":
    render_dlq(data_service)
elif current_page == "🚦 Triage":
    render_triage(data_service)
elif current_page == "🔑 Tokens":
    render_tokens(data_service)
elif current_page == "✅ Compliance":
    render_compliance(data_service)
elif current_page == "🗄️ Niche Vault":
    render_vault()
elif current_page == "💰 Revenue":
    render_revenue(data_service)
elif current_page == "📅 Schedule":
    render_schedule(data_service)
