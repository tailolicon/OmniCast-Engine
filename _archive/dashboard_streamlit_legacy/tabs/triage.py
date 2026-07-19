"""Triage tab — Kill-Switch + Human-in-the-Loop approvals queue.

Implements Standards 2.A (Kill-Switch) and 2.C (HITL) from Operator-Dashboard Design Standards.
Master-detail layout: pending approvals table on top of detail panel with Approve/Reject buttons.
No expanders, no auto-refresh.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from omnicast.dashboard.data_service import DashboardDataService


_KIND_LABEL = {
    "channel_name": "📛 Channel Name",
    "script":       "📝 Script",
    "rule_update":  "📜 Rule Update",
    "unknown":      "❓ Unknown",
}

_SEVERITY_BADGE = {
    "critical": ("🔴", "#ef4444"),
    "high":     ("🟠", "#f97316"),
    "medium":   ("🟡", "#eab308"),
    "low":      ("🔵", "#3b82f6"),
}


def _rel_time(dt: datetime | None) -> str:
    if not dt:
        return "—"
    diff = (datetime.now(timezone.utc) - dt).total_seconds()
    if diff < 60:    return "vừa xong"
    if diff < 3600:  return f"{int(diff // 60)}p trước"
    if diff < 86400: return f"{int(diff // 3600)}h trước"
    return f"{int(diff // 86400)}d trước"


def _render_kill_switch(data_service: DashboardDataService) -> None:
    """Top section: big red Emergency Stop / green Resume button with confirmation gate."""
    st.markdown("### ⛔ Emergency Stop")
    paused = data_service.is_pipeline_paused()
    since  = data_service.get_pipeline_paused_since()

    if paused:
        # ── PAUSED state ─────────────────────────────────────────────────
        since_txt = since[:19].replace("T", " ") if since else "—"
        st.markdown(f"""
        <div style="background:rgba(239,68,68,.15);border:2px solid #ef4444;
                    border-radius:10px;padding:18px 22px;margin-bottom:12px;">
            <div style="color:#fca5a5;font-weight:800;font-size:1.1rem;">
                🛑 PIPELINE ĐANG TẠM DỪNG
            </div>
            <div style="color:#fecaca;font-size:.85rem;margin-top:6px;">
                Workers sẽ không pull job mới. Paused since: <code>{since_txt} UTC</code>
            </div>
        </div>
        """, unsafe_allow_html=True)

        c1, _ = st.columns([1, 3])
        with c1:
            if st.button(
                "▶ Resume Pipeline",
                key="kill_resume",
                use_container_width=True,
                type="primary",
            ):
                if data_service.resume_pipeline():
                    st.success("✅ Pipeline đã được resume.")
                    st.rerun()
                else:
                    st.error("❌ Resume thất bại (Redis không khả dụng).")
    else:
        # ── RUNNING state — confirm-then-pause (anti fat-finger) ─────────
        st.markdown("""
        <div style="background:rgba(34,197,94,.08);border:1px solid rgba(34,197,94,.3);
                    border-radius:10px;padding:14px 20px;margin-bottom:12px;">
            <span style="color:#86efac;font-weight:600;">🟢 Pipeline đang chạy bình thường</span>
            <div style="color:#94a3b8;font-size:.78rem;margin-top:4px;">
                Bấm Emergency Stop để ngăn workers pull job mới (không huỷ job đang chạy dở).
            </div>
        </div>
        """, unsafe_allow_html=True)

        confirm_key = "kill_confirm_pending"
        if st.session_state.get(confirm_key):
            warn_c, yes_c, no_c = st.columns([2, 1, 1])
            with warn_c:
                st.markdown(
                    "<div style='color:#fde047;font-weight:600;padding-top:6px;'>"
                    "⚠️ Xác nhận: dừng toàn bộ pipeline?</div>",
                    unsafe_allow_html=True,
                )
            with yes_c:
                if st.button("⛔ XÁC NHẬN DỪNG", key="kill_yes",
                             use_container_width=True, type="primary"):
                    if data_service.pause_pipeline():
                        st.session_state[confirm_key] = False
                        st.warning("🛑 Pipeline đã được tạm dừng.")
                        st.rerun()
                    else:
                        st.error("❌ Pause thất bại (Redis không khả dụng).")
            with no_c:
                if st.button("↩ Huỷ", key="kill_no", use_container_width=True):
                    st.session_state[confirm_key] = False
                    st.rerun()
        else:
            c1, _ = st.columns([1, 3])
            with c1:
                if st.button(
                    "⛔ EMERGENCY STOP",
                    key="kill_pause",
                    use_container_width=True,
                ):
                    st.session_state[confirm_key] = True
                    st.rerun()


def _render_triage_queue(data_service: DashboardDataService) -> None:
    """Bottom section: master-detail approvals table."""
    st.markdown("### 🚦 Pending Approvals (Human-in-the-Loop)")
    st.caption(
        "Các quyết định sinh tử do AI agent submit chờ con người duyệt. "
        "Click vào dòng để xem payload và bấm Approve/Reject."
    )

    items = data_service.get_triage_items(limit=100)

    if not items:
        st.markdown("""
        <div class="alert-banner ok">
            ✅ Không có item nào chờ duyệt — agents đang vận hành trong giới hạn an toàn.
        </div>
        """, unsafe_allow_html=True)
        return

    # ── Summary ───────────────────────────────────────────────────────────
    by_kind: dict[str, int] = {}
    for it in items:
        by_kind[it["kind"]] = by_kind.get(it["kind"], 0) + 1
    counts_txt = " · ".join(
        f"{_KIND_LABEL.get(k, k)}: **{v}**" for k, v in sorted(by_kind.items())
    )
    st.markdown(f"**{len(items)}** items pending — {counts_txt}")

    # ── Master table ──────────────────────────────────────────────────────
    rows = []
    for it in items:
        sev_icon, _ = _SEVERITY_BADGE.get(it["severity"], ("⚪", "#64748b"))
        rows.append({
            "":          sev_icon,
            "Type":      _KIND_LABEL.get(it["kind"], it["kind"]),
            "Title":     it["title"][:120],
            "Submitted by": it["submitted_by"],
            "Age":       _rel_time(it["created_at"]),
        })

    df = pd.DataFrame(rows)

    selection = st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "":     st.column_config.TextColumn("", width="small"),
            "Type": st.column_config.TextColumn("Type", width="small"),
            "Title": st.column_config.TextColumn("Title", width="large"),
        },
        key="triage_table",
    )

    selected_rows = selection.selection.rows if selection.selection else []

    if not selected_rows:
        st.markdown(
            "<div style='color:#475569;font-size:.82rem;padding:8px 0;'>"
            "← Click vào 1 dòng để xem payload và duyệt</div>",
            unsafe_allow_html=True,
        )
        return

    # ── Detail panel ──────────────────────────────────────────────────────
    idx = selected_rows[0]
    it  = items[idx]
    kind_label  = _KIND_LABEL.get(it["kind"], it["kind"])
    sev_icon, sev_color = _SEVERITY_BADGE.get(it["severity"], ("⚪", "#64748b"))

    st.markdown(f"""
    <div class="detail-panel">
        <strong style="font-size:1rem;">{sev_icon} {kind_label}</strong>
        <span style="color:#64748b;font-size:.8rem;margin-left:10px;">
            ID: {it["item_id"]} · submitted by <code>{it["submitted_by"]}</code> · {_rel_time(it["created_at"])}
        </span>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"**Title:** {it['title']}")

    # Payload viewer
    st.markdown("**Payload (read-only — agents không cho phép sửa từ Triage):**")
    payload = it["payload"]
    if payload:
        try:
            pretty = json.dumps(payload, indent=2, ensure_ascii=False)
        except Exception:
            pretty = str(payload)
        st.code(pretty, language="json")
    else:
        st.caption("(no payload)")

    # Operator note (optional)
    note_key = f"triage_note_{it['item_id']}"
    note = st.text_area(
        "Operator note (optional — sẽ lưu vào details.operator_note)",
        value=st.session_state.get(note_key, ""),
        height=80,
        key=note_key,
        placeholder="VD: Tên ổn, đúng tone niche. Hoặc: Reject vì trùng kênh hiện có.",
    )

    # Action buttons
    c_app, c_rej, _ = st.columns([1, 1, 2])
    with c_app:
        if st.button(
            "✅ Approve",
            key=f"triage_approve_{it['item_id']}",
            use_container_width=True,
            type="primary",
        ):
            if data_service.approve_triage(it["item_id"], note=note):
                st.success(f"Approved item {it['item_id']}.")
                st.session_state.pop(note_key, None)
                st.rerun()
            else:
                st.error("Approve thất bại (DB không khả dụng).")
    with c_rej:
        if st.button(
            "❌ Reject",
            key=f"triage_reject_{it['item_id']}",
            use_container_width=True,
        ):
            if data_service.reject_triage(it["item_id"], note=note):
                st.warning(f"Rejected item {it['item_id']}.")
                st.session_state.pop(note_key, None)
                st.rerun()
            else:
                st.error("Reject thất bại (DB không khả dụng).")


def render_triage(data_service: DashboardDataService) -> None:
    """Main entry — Std 2.A + 2.C."""
    st.title("🚦 Triage — Command & Control")
    _render_kill_switch(data_service)
    st.divider()
    _render_triage_queue(data_service)
