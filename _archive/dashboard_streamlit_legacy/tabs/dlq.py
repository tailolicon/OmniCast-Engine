"""DLQ tab — Table view + row-click detail/edit panel. No expander spam, no state wipe."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from omnicast.dashboard.data_service import DashboardDataService


def render_dlq(data_service: DashboardDataService) -> None:
    st.title("💀 Dead Letter Queue")

    items = data_service.get_dlq_items(limit=100)

    if not items:
        st.markdown("""
        <div class="alert-banner ok">✅ DLQ trống — không có item lỗi nào.</div>
        """, unsafe_allow_html=True)
        return

    # ── Summary ───────────────────────────────────────────────────────────
    st.metric("Items trong DLQ", len(items))
    st.caption("Click vào dòng bất kỳ để xem lỗi, sửa payload và retry — **không bị mất khi refresh**.")

    # ── Table ─────────────────────────────────────────────────────────────
    rows = []
    for item in items:
        rows.append({
            "ID":        item.item_id,
            "Queue":     item.queue_name,
            "Error":     item.error_message[:80] + ("…" if len(item.error_message) > 80 else ""),
            "Retries":   item.retry_count,
            "Failed At": item.failed_at.strftime("%m-%d %H:%M") if item.failed_at else "—",
        })

    df = pd.DataFrame(rows)

    selection = st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Error": st.column_config.TextColumn("Error (preview)", width="large"),
            "Retries": st.column_config.NumberColumn("Retries", width="small"),
        },
        key="dlq_table",
    )

    selected_rows = selection.selection.rows if selection.selection else []

    if not selected_rows:
        st.markdown(
            "<div style='color:#475569;font-size:.82rem;padding:8px 0;'>"
            "← Click vào 1 dòng để xem full error + sửa payload</div>",
            unsafe_allow_html=True,
        )
        return

    # ── Detail + Edit panel ───────────────────────────────────────────────
    idx  = selected_rows[0]
    item = items[idx]

    st.markdown(f"""
    <div class="detail-panel">
        <strong>💀 {item.queue_name}</strong>
        <span style="color:#64748b;font-size:.78rem;margin-left:10px;">ID: {item.item_id} · Retries: {item.retry_count}</span>
    </div>
    """, unsafe_allow_html=True)

    # Full error
    st.markdown("**Full error:**")
    st.error(item.error_message)

    # Pretty-print payload
    try:
        pretty = json.dumps(json.loads(item.payload_summary), indent=2, ensure_ascii=False)
    except Exception:
        pretty = item.payload_summary

    # ── Action buttons (1 row) ────────────────────────────────────────────
    st.markdown("**Actions:**")
    b1, b2, b3 = st.columns([1, 1, 2])

    with b1:
        if st.button("🔁 Retry ngay", key=f"retry_{item.item_id}", use_container_width=True):
            if data_service.retry_dlq_item(item.item_id):
                st.success("Re-queued thành công.")
                st.rerun()
            else:
                st.error("Retry thất bại (DB error).")

    with b2:
        discard_key = f"discard_confirm_{item.item_id}"
        if st.session_state.get(discard_key):
            if st.button("✅ Xác nhận xoá", key=f"disc_yes_{item.item_id}",
                         use_container_width=True, type="primary"):
                if data_service.discard_dlq_item(item.item_id):
                    st.session_state[discard_key] = False
                    st.success("Đã discard.")
                    st.rerun()
        else:
            if st.button("🗑️ Discard", key=f"disc_{item.item_id}", use_container_width=True):
                st.session_state[discard_key] = True
                st.rerun()

    # ── Edit payload (persistent trong session_state — KHÔNG bị auto-refresh xoá) ──
    st.markdown("**✏️ Sửa payload (fix JSON lỗi rồi Save & Retry):**")
    st.caption("Lỗi thường gặp: thiếu dấu phẩy `,` · ngoặc kép `\"` chưa đóng · trailing comma")

    # Dùng session_state để lưu nội dung đang sửa — không bị mất khi rerun
    edit_key = f"dlq_edit_payload_{item.item_id}"
    if edit_key not in st.session_state:
        st.session_state[edit_key] = pretty

    edited = st.text_area(
        "Payload JSON",
        value=st.session_state[edit_key],
        height=320,
        key=f"dlq_textarea_{item.item_id}",
        label_visibility="collapsed",
    )
    # Sync về session_state để giữ qua rerun
    st.session_state[edit_key] = edited

    # Live JSON validation
    try:
        json.loads(edited)
        st.markdown(
            "<span style='color:#22c55e;font-size:.82rem;'>✅ JSON hợp lệ</span>",
            unsafe_allow_html=True,
        )
        json_valid = True
    except json.JSONDecodeError as e:
        st.markdown(
            f"<span style='color:#ef4444;font-size:.82rem;'>❌ JSON lỗi: {e}</span>",
            unsafe_allow_html=True,
        )
        json_valid = False

    save_c, cancel_c = st.columns([1, 1])
    with save_c:
        if st.button(
            "💾 Save & Retry",
            key=f"save_{item.item_id}",
            disabled=not json_valid,
            use_container_width=True,
            type="primary",
        ):
            if data_service.update_dlq_payload(item.item_id, edited):
                if data_service.retry_dlq_item(item.item_id):
                    st.success("Payload đã lưu và item re-queued.")
                    del st.session_state[edit_key]
                    st.rerun()
                else:
                    st.error("Lưu payload OK nhưng retry thất bại.")
            else:
                st.error("Lưu payload thất bại (DB error).")
    with cancel_c:
        if st.button("↩ Reset về gốc", key=f"cancel_{item.item_id}", use_container_width=True):
            st.session_state[edit_key] = pretty
            st.rerun()
