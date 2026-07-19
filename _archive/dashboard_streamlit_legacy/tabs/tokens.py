"""Tokens tab — OAuth token health per channel: status badge, expiry, re-auth CLI hint."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from omnicast.dashboard.data_service import DashboardDataService


_STATUS_COLOR = {
    "healthy": "🟢",
    "warning": "🟡",
    "expired": "🔴",
    "unknown": "⚪",
}


def render_tokens(data_service: DashboardDataService) -> None:
    st.title("🔑 OAuth Tokens")

    tokens = data_service.get_token_statuses()

    if not tokens:
        st.info("No channel profiles found — add JSON files to `channels/`.")
        return

    # ── Summary table (compact) ───────────────────────────────────────────
    now = datetime.now(timezone.utc)
    rows = []
    for t in tokens:
        icon = _STATUS_COLOR.get(t.status, "⚪")
        if t.expires_at:
            diff = (t.expires_at - now).total_seconds()
            if diff > 0:
                days = int(diff // 86400)
                hrs = int((diff % 86400) // 3600)
                expires_str = f"{days}d {hrs}h"
            else:
                expires_str = "EXPIRED"
        else:
            expires_str = "—"

        rows.append({
            "": icon,
            "Channel": t.channel_name,
            "ID": t.channel_id,
            "Status": t.status,
            "Expires In": expires_str,
            "Last Refresh": t.last_refresh.strftime("%m-%d %H:%M") if t.last_refresh else "—",
            "Scopes": len(t.scopes),
        })

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Summary badges
    n_expired = sum(1 for t in tokens if t.status == "expired")
    n_warn = sum(1 for t in tokens if t.status == "warning")
    n_unknown = sum(1 for t in tokens if t.status == "unknown")
    if n_expired:
        st.error(f"🔴 **{n_expired} expired** token(s) — pipeline will fail for these channels!")
    if n_warn:
        st.warning(f"🟡 **{n_warn} warning** — expiring within 7 days.")
    if n_unknown:
        st.info(f"⚪ **{n_unknown} unknown** — no token data in Redis (channel never authorized?).")

    st.divider()

    # ── Detail expanders ──────────────────────────────────────────────────
    st.subheader("Detail")
    for t in tokens:
        icon = _STATUS_COLOR.get(t.status, "⚪")
        with st.expander(f"{icon} {t.channel_name} · `{t.channel_id}` · {t.status}"):
            c1, c2 = st.columns(2)
            with c1:
                st.write(f"**Status:** {t.status}")
                if t.expires_at:
                    diff = (t.expires_at - now).total_seconds()
                    if diff > 0:
                        days = int(diff // 86400)
                        hrs = int((diff % 86400) // 3600)
                        st.write(f"**Expires:** {t.expires_at.strftime('%Y-%m-%d %H:%M UTC')} ({days}d {hrs}h)")
                    else:
                        st.error(f"**EXPIRED** at {t.expires_at.strftime('%Y-%m-%d %H:%M UTC')}")
                else:
                    st.write("**Expires:** —")

            with c2:
                if t.last_refresh:
                    st.write(f"**Last refresh:** {t.last_refresh.strftime('%Y-%m-%d %H:%M UTC')}")
                else:
                    st.write("**Last refresh:** Never")
                if t.scopes:
                    st.write(f"**Scopes ({len(t.scopes)}):** `{', '.join(t.scopes[:3])}{'...' if len(t.scopes) > 3 else ''}`")
                else:
                    st.write("**Scopes:** none cached")

            if t.status in ("warning", "expired", "unknown"):
                st.markdown("**Re-authorize:**")
                st.code(
                    f"python run_pipeline.py auth --channel {t.channel_id}",
                    language="bash",
                )
                st.caption(
                    "This opens a browser OAuth flow. "
                    "New token stored in Redis under `token:{channel_id}`."
                )
