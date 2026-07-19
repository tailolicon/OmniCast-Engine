"""Vault tab — Master-Detail Niche Vault. Read-write status editor. No expanders."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

_DEFAULT_VAULT = Path(__file__).resolve().parents[5] / "output" / "vault.db"

_STATUS_EMOJI = {
    "hot":      "🔴",
    "active":   "🟢",
    "watching": "🔵",
    "stale":    "⚫",
    "archived": "⚪",
}
_STATUS_ORDER = {"hot": 0, "active": 1, "watching": 2, "stale": 3, "archived": 4}
_ALL_STATUSES = ["hot", "active", "watching", "stale", "archived"]


# ── DB helpers ────────────────────────────────────────────────────────────────

def _get_vault_path() -> Path:
    return st.session_state.get("vault_db_path", _DEFAULT_VAULT)


def _connect(vault_path: Path) -> sqlite3.Connection | None:
    if not vault_path.exists():
        return None
    conn = sqlite3.connect(str(vault_path))
    conn.row_factory = sqlite3.Row
    return conn


def _load_niches(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("""
        SELECT
            n.niche_id,
            n.niche_name,
            n.market,
            n.status,
            n.original_score,
            n.current_health,
            n.saved_at,
            n.last_checked,
            n.niche_data,
            COUNT(s.script_id)                                        AS script_count,
            SUM(CASE WHEN s.approved=1 THEN 1 ELSE 0 END)            AS approved_count,
            SUM(CASE WHEN s.youtube_video_id IS NOT NULL THEN 1 ELSE 0 END) AS uploaded_count
        FROM niches n
        LEFT JOIN scripts s ON s.channel_id = json_extract(n.niche_data, '$.channel_id')
        GROUP BY n.niche_id
        ORDER BY n.current_health DESC
    """).fetchall()

    result = []
    for r in rows:
        nd: dict = {}
        try:
            nd = json.loads(r["niche_data"] or "{}")
        except Exception:
            pass
        result.append({
            "niche_id":       r["niche_id"],
            "niche_name":     r["niche_name"],
            "market":         r["market"],
            "status":         r["status"],
            "original_score": r["original_score"] or 0,
            "current_health": r["current_health"] or 0,
            "saved_at":       (r["saved_at"]     or "")[:10],
            "last_checked":   (r["last_checked"] or "—")[:10],
            "channel_id":     nd.get("channel_id", "—"),
            "script_count":   r["script_count"]   or 0,
            "approved_count": r["approved_count"] or 0,
            "uploaded_count": r["uploaded_count"] or 0,
            # Raw niche_data for detail panel
            "_niche_data":    nd,
        })
    return result


def _load_health_trend(conn: sqlite3.Connection, niche_id: str, days: int = 30) -> list[dict]:
    rows = conn.execute("""
        SELECT scan_date, health_score, status_change, notes, new_videos_count, micro_outlier_found
        FROM health_logs
        WHERE niche_id = ?
        ORDER BY scan_date DESC
        LIMIT ?
    """, (niche_id, days)).fetchall()
    return [dict(r) for r in rows]


def _update_niche_status(vault_path: Path, niche_id: str, new_status: str) -> bool:
    try:
        conn = sqlite3.connect(str(vault_path))
        conn.execute(
            "UPDATE niches SET status = ? WHERE niche_id = ?",
            (new_status, niche_id),
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        st.error(f"DB write failed: {e}")
        return False


# ── Section renderers ─────────────────────────────────────────────────────────

def _render_niche_data(nd: dict) -> None:
    """Render full niche_data JSON as structured UI. Core of Requirement 2."""
    if not nd:
        st.info("No niche_data available for this niche.")
        return

    # ── Audience ──────────────────────────────────────────────────────────
    audience = nd.get("audience_description") or nd.get("target_audience") or nd.get("audience")
    if audience:
        st.markdown("**👥 Target Audience**")
        st.markdown(
            f"<div style='background:#1e2130;border-left:3px solid #6366f1;"
            f"border-radius:6px;padding:10px 14px;margin-bottom:8px;"
            f"color:#cbd5e1;font-size:.85rem;'>{audience}</div>",
            unsafe_allow_html=True,
        )

    # ── Pain points ───────────────────────────────────────────────────────
    pain_points = nd.get("pain_points") or nd.get("audience_pain_points") or []
    if isinstance(pain_points, str):
        pain_points = [pain_points]
    if pain_points:
        st.markdown("**😤 Pain Points**")
        for i, p in enumerate(pain_points[:5], 1):
            st.markdown(
                f"<div style='background:#1e2130;border-left:3px solid #ef4444;"
                f"border-radius:6px;padding:8px 14px;margin-bottom:4px;"
                f"color:#cbd5e1;font-size:.83rem;'>{i}. {p}</div>",
                unsafe_allow_html=True,
            )

    # ── Content triggers ──────────────────────────────────────────────────
    triggers = (
        nd.get("content_triggers") or
        nd.get("triggers") or
        nd.get("emotional_triggers") or []
    )
    if isinstance(triggers, str):
        triggers = [triggers]
    if triggers:
        st.markdown("**⚡ Content Triggers**")
        for i, t in enumerate(triggers[:5], 1):
            st.markdown(
                f"<div style='background:#1e2130;border-left:3px solid #f59e0b;"
                f"border-radius:6px;padding:8px 14px;margin-bottom:4px;"
                f"color:#cbd5e1;font-size:.83rem;'>{i}. {t}</div>",
                unsafe_allow_html=True,
            )

    # ── Example channels ──────────────────────────────────────────────────
    examples = (
        nd.get("example_channels") or
        nd.get("competitors") or
        nd.get("reference_channels") or []
    )
    if examples:
        st.markdown("**📺 Example Channels (Competitors)**")
        if isinstance(examples, list) and isinstance(examples[0], dict):
            # list of {name, url, ...} objects
            for ex in examples[:4]:
                name = ex.get("name") or ex.get("channel_name") or str(ex)
                url  = ex.get("url") or ex.get("channel_url") or ""
                subs = ex.get("subscribers") or ex.get("sub_count") or ""
                sub_txt = f" · {subs}" if subs else ""
                link = f"[{name}]({url})" if url else f"**{name}**"
                st.markdown(f"- {link}{sub_txt}")
        else:
            for ex in examples[:4]:
                st.markdown(f"- {ex}")

    # ── Additional fields: hook style, monetisation, etc. ────────────────
    extra_keys = [
        ("hook_style",       "🎣 Hook Style"),
        ("monetisation",     "💰 Monetisation"),
        ("cpm_estimate",     "📈 CPM Estimate"),
        ("search_intent",    "🔍 Search Intent"),
        ("content_format",   "📋 Content Format"),
        ("growth_strategy",  "🚀 Growth Strategy"),
        ("value_proposition","💎 Value Proposition"),
    ]
    extra_found = [(k, label) for k, label in extra_keys if nd.get(k)]
    if extra_found:
        st.markdown("**📝 More Details**")
        for key, label in extra_found:
            val = nd[key]
            st.markdown(
                f"<div style='margin-bottom:4px;'>"
                f"<span style='color:#94a3b8;font-size:.78rem;'>{label}: </span>"
                f"<span style='color:#e2e8f0;font-size:.83rem;'>{val}</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

    # ── Raw JSON fallback ─────────────────────────────────────────────────
    known = {
        "channel_id", "audience_description", "target_audience", "audience",
        "pain_points", "audience_pain_points", "content_triggers", "triggers",
        "emotional_triggers", "example_channels", "competitors", "reference_channels",
        "hook_style", "monetisation", "cpm_estimate", "search_intent",
        "content_format", "growth_strategy", "value_proposition",
    }
    unknown = {k: v for k, v in nd.items() if k not in known}
    if unknown:
        with st.expander("📦 Raw niche_data (remaining fields)", expanded=False):
            st.json(unknown)


# ── Main render ───────────────────────────────────────────────────────────────

def render_vault() -> None:
    st.title("🗄️ Niche Vault")

    vault_path = _get_vault_path()
    conn = _connect(vault_path)

    if conn is None:
        st.warning(f"vault.db not found at: `{vault_path}`")
        st.info(
            "Run `python vault.py --save` after a scan to populate vault, "
            "or `python niche_flow.py --create <niche_id>` to auto-link."
        )
        return

    niches = _load_niches(conn)

    if not niches:
        st.info("Vault is empty. Run a scan and save with `python vault.py --save`.")
        conn.close()
        return

    # ── Summary KPIs ──────────────────────────────────────────────────────
    total    = len(niches)
    hot      = sum(1 for n in niches if n["status"] == "hot")
    active   = sum(1 for n in niches if n["status"] == "active")
    watching = sum(1 for n in niches if n["status"] == "watching")
    unlinked = sum(1 for n in niches
                   if n["channel_id"] == "—" and n["status"] not in ("stale", "archived"))

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total Niches", total)
    k2.metric("🔴 Hot",       hot)
    k3.metric("🟢 Active",    active)
    k4.metric("🔵 Watching",  watching)
    k5.metric("⚠️ Unlinked",  unlinked, help="Hot/Watching niches with no channel yet")

    st.divider()

    # ── Filters ───────────────────────────────────────────────────────────
    col_f1, col_f2, col_f3 = st.columns([2, 2, 1])
    with col_f1:
        status_filter = st.multiselect(
            "Status",
            _ALL_STATUSES,
            default=["hot", "active", "watching"],
        )
    with col_f2:
        market_options = sorted({n["market"] for n in niches})
        market_filter  = st.multiselect("Market", market_options, default=market_options)
    with col_f3:
        show_linked = st.checkbox("Linked only", value=False)

    filtered = [
        n for n in niches
        if n["status"] in status_filter
        and n["market"] in market_filter
        and (not show_linked or n["channel_id"] != "—")
    ]
    filtered.sort(key=lambda n: (_STATUS_ORDER.get(n["status"], 9), -n["current_health"]))

    st.caption(f"Showing {len(filtered)} / {total} niches · Click a row to inspect & change status")

    # ── Master table ──────────────────────────────────────────────────────
    rows = []
    for n in filtered:
        icon = _STATUS_EMOJI.get(n["status"], "⚪")
        rows.append({
            "":         icon,
            "Niche":    n["niche_name"],
            "Market":   n["market"],
            "Status":   n["status"],
            "Health":   n["current_health"],
            "Δ Score":  n["current_health"] - n["original_score"],
            "Scripts":  n["script_count"],
            "Uploaded": n["uploaded_count"],
            "Channel":  n["channel_id"],
            "Checked":  n["last_checked"],
        })

    df = pd.DataFrame(rows)

    selection = st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "":       st.column_config.TextColumn("", width="small"),
            "Health": st.column_config.ProgressColumn(
                "Health", min_value=0, max_value=100, format="%d"
            ),
            "Δ Score": st.column_config.NumberColumn("Δ Score", format="%+d"),
        },
        key="vault_table",
    )

    selected_rows = selection.selection.rows if selection.selection else []

    if not selected_rows:
        st.markdown(
            "<div style='color:#475569;font-size:.82rem;padding:8px 0;'>"
            "← Click a row to view full niche data and edit status</div>",
            unsafe_allow_html=True,
        )
        conn.close()
        return

    # ── Detail panel ──────────────────────────────────────────────────────
    idx  = selected_rows[0]
    n    = filtered[idx]
    icon = _STATUS_EMOJI.get(n["status"], "⚪")

    st.markdown(f"""
    <div class="detail-panel">
        <strong style="font-size:1rem;">{icon} {n['niche_name']}</strong>
        <span style="color:#64748b;font-size:.8rem;margin-left:10px;">
            {n['niche_id']} · {n['market']} · Health {n['current_health']}/100
        </span>
    </div>
    """, unsafe_allow_html=True)

    # ── Metrics + Status editor in a row ──────────────────────────────────
    ms1, ms2, ms3, ms4, ms5 = st.columns(5)
    ms1.metric("Health",   n["current_health"],
               delta=n["current_health"] - n["original_score"], help="vs. discovery score")
    ms2.metric("Scripts",  n["script_count"])
    ms3.metric("Approved", n["approved_count"])
    ms4.metric("Uploaded", n["uploaded_count"])

    with ms5:
        # Status editor (Requirement 3 — Vault)
        cur_idx  = _ALL_STATUSES.index(n["status"]) if n["status"] in _ALL_STATUSES else 0
        new_status = st.selectbox(
            "Status",
            _ALL_STATUSES,
            index=cur_idx,
            key=f"vault_status_{n['niche_id']}",
            format_func=lambda s: f"{_STATUS_EMOJI.get(s, '⚪')} {s}",
        )
        if st.button("💾 Save Status", key=f"vault_save_{n['niche_id']}",
                     use_container_width=True, type="primary",
                     disabled=(new_status == n["status"])):
            if _update_niche_status(vault_path, n["niche_id"], new_status):
                st.success(f"Status → **{new_status}**")
                st.rerun()

    # ── Channel link info ─────────────────────────────────────────────────
    st.divider()
    lc1, lc2, lc3, lc4 = st.columns(4)
    lc1.write(f"**Discovered:** {n['saved_at']}")
    lc2.write(f"**Last checked:** {n['last_checked']}")

    if n["channel_id"] != "—":
        lc3.write(f"**Channel:** `{n['channel_id']}`")
        lc4.code(f"python content_flow.py --channel {n['channel_id']}", language="bash")
    else:
        lc3.warning("No channel linked yet")
        lc4.code(f"python niche_flow.py --create {n['niche_id']}", language="bash")

    st.divider()

    # ── Full niche_data (Requirement 2) ───────────────────────────────────
    st.markdown("### 📋 Niche Intelligence")
    _render_niche_data(n["_niche_data"])

    st.divider()

    # ── Health trend ──────────────────────────────────────────────────────
    logs = _load_health_trend(conn, n["niche_id"])
    if logs:
        st.markdown("### 📈 Health Trend (last 30 scans)")

        df_logs = pd.DataFrame(logs)[["scan_date", "health_score", "new_videos_count"]]
        df_logs = df_logs.rename(columns={
            "scan_date":       "Date",
            "health_score":    "Health",
            "new_videos_count": "New Videos",
        })
        st.line_chart(df_logs.set_index("Date")["Health"])

        # Micro-outlier callout
        outliers = [l for l in logs if l.get("micro_outlier_found")]
        if outliers:
            st.success(f"🚀 Micro-outlier detected in **{len(outliers)}** scan(s)")

        # Status changes
        changes = [l for l in logs if l.get("status_change")]
        if changes:
            st.markdown("**Status changes:**")
            for c in changes[:5]:
                st.caption(f"{c['scan_date'][:10]}: {c['status_change']} — {c.get('notes','')[:80]}")
    else:
        st.caption("No health log history yet.")

    conn.close()
