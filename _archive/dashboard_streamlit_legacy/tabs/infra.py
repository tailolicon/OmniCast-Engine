"""Infrastructure tab — Worker health cards with CPU/RAM/GPU gauges + heartbeat."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

import streamlit as st

from omnicast.dashboard.data_service import DashboardDataService


def render_infra(data_service: DashboardDataService) -> None:
    st.title("🔧 Infrastructure")

    workers = data_service.get_worker_statuses()

    if not workers:
        st.info("No worker heartbeats in Redis. Workers offline or Redis unreachable.")
        st.code("REDIS_URL in .env — confirm worker processes running", language="text")
        return

    # ── Summary ───────────────────────────────────────────────────────────
    n_healthy = sum(1 for w in workers if w.status == "healthy")
    n_degraded = sum(1 for w in workers if w.status == "degraded")
    n_offline = sum(1 for w in workers if w.status == "offline")

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Total Workers", len(workers))
    with m2:
        st.metric("🟢 Healthy", n_healthy)
    with m3:
        label = f"🟡 {n_degraded}" if n_degraded else "0"
        st.metric("Degraded", label)
    with m4:
        label = f"🔴 {n_offline}" if n_offline else "0"
        st.metric("Offline", label)

    st.divider()

    # ── Worker cards ──────────────────────────────────────────────────────
    for worker in workers:
        status_color = {
            "healthy": "#22c55e",
            "degraded": "#f59e0b",
            "offline": "#ef4444",
        }.get(worker.status, "#94a3b8")
        status_icon = {"healthy": "🟢", "degraded": "🟡", "offline": "🔴"}.get(worker.status, "⚪")

        st.markdown(
            f"""<div style="
                border-left: 4px solid {status_color};
                padding: 4px 12px;
                margin-bottom: 4px;
                border-radius: 4px;
                background: rgba(0,0,0,0.04);
            ">
                <strong>{status_icon} {worker.hostname}</strong>
                &nbsp;<code style="font-size:0.8em">{worker.worker_id}</code>
            </div>""",
            unsafe_allow_html=True,
        )

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            cpu_color = "inverse" if worker.cpu_percent > 80 else "normal"
            st.metric("CPU", f"{worker.cpu_percent:.1f}%",
                      delta=f"{'HIGH' if worker.cpu_percent > 80 else None}" if worker.cpu_percent > 80 else None,
                      delta_color="inverse")
        with c2:
            st.metric("RAM", f"{worker.ram_percent:.1f}%")
        with c3:
            if worker.gpu_temp is not None:
                temp_warn = "⚠️ " if worker.gpu_temp > 85 else ""
                st.metric("GPU Temp", f"{temp_warn}{worker.gpu_temp:.0f}°C")
            else:
                st.metric("GPU Temp", "—")
        with c4:
            now = datetime.now(timezone.utc)
            age_s = (now - worker.last_heartbeat).total_seconds()
            if age_s < 60:
                hb_str = f"{int(age_s)}s ago"
            elif age_s < 3600:
                hb_str = f"{int(age_s // 60)}m ago"
            else:
                hb_str = f"{int(age_s // 3600)}h ago"
            st.metric("Heartbeat", hb_str)

        if worker.status == "offline":
            st.error(f"⚠️ Worker offline — last seen {hb_str}")
        elif worker.current_task:
            st.caption(f"Current task: `{worker.current_task}`")
        else:
            st.caption("Idle")

        st.divider()
