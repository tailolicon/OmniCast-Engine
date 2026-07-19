"""Compliance tab — Audit log with pass/fail counts, search, and detail expanders."""

from __future__ import annotations

import streamlit as st

from omnicast.dashboard.data_service import DashboardDataService
from omnicast.dashboard.models import DashboardFilter


def render_compliance(data_service: DashboardDataService) -> None:
    st.title("✅ Compliance Audit Log")

    # ── Filters ───────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        channel_filter = st.text_input("Channel ID", placeholder="fin_retirement_us")
    with col2:
        status_filter = st.selectbox("Status", ["All", "Passed", "Failed"])
    with col3:
        limit = st.number_input("Limit", min_value=10, max_value=500, value=100, step=10)

    filter_obj = DashboardFilter(
        channel_id=channel_filter if channel_filter else None,
        status=status_filter.lower() if status_filter != "All" else None,
        limit=int(limit),
    )

    entries = data_service.get_compliance_log(filter=filter_obj)

    if not entries:
        st.info("No compliance log entries matching filter.")
        return

    # ── Summary counts ────────────────────────────────────────────────────
    n_pass = sum(1 for e in entries if e.passed)
    n_fail = sum(1 for e in entries if not e.passed)
    pass_rate = (n_pass / len(entries) * 100) if entries else 0

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Total", len(entries))
    with m2:
        st.metric("✅ Passed", n_pass)
    with m3:
        label = f"❌ {n_fail}" if n_fail else "0"
        st.metric("Failed", label)
    with m4:
        color = "🟢" if pass_rate >= 90 else "🟡" if pass_rate >= 70 else "🔴"
        st.metric("Pass Rate", f"{color} {pass_rate:.1f}%")

    st.divider()

    # ── Detail expanders ──────────────────────────────────────────────────
    for entry in entries:
        icon = "✅" if entry.passed else "❌"
        n_violations = len(entry.violations)
        checks_passed = sum(entry.checks.values())
        checks_total = len(entry.checks)

        with st.expander(
            f"{icon} `{entry.video_id}` · {entry.channel_id} · "
            f"{entry.checked_at.strftime('%m-%d %H:%M') if entry.checked_at else '—'}"
        ):
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("Status", "PASS" if entry.passed else "FAIL")
            with c2:
                st.metric("Violations", n_violations)
            with c3:
                st.metric("Checks", f"{checks_passed}/{checks_total}")

            if entry.violations:
                st.markdown("**Violations:**")
                for v in entry.violations:
                    st.error(f"• {v}")

            if entry.checks:
                st.markdown("**Check breakdown:**")
                n_cols = min(3, len(entry.checks))
                cols = st.columns(n_cols)
                for i, (check_name, passed) in enumerate(entry.checks.items()):
                    icon_c = "✅" if passed else "❌"
                    with cols[i % n_cols]:
                        st.write(f"{icon_c} {check_name}")
