"""Channels tab — Master-Detail with inline brand editor. No expanders."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from omnicast.dashboard.data_service import DashboardDataService


_FONT_LABELS: dict[str, str] = {
    "sans_modern":      "Sans Modern",
    "serif_editorial":  "Serif Editorial",
    "mono_tech":        "Mono Tech",
    "display_bold":     "Display Bold",
    "humanist":         "Humanist",
}

_FONT_OPTIONS = list(_FONT_LABELS.keys())


def _age_info(channel_created_at: str | None) -> tuple[int | None, bool]:
    """Return (age_days, is_young). is_young = age < 90 days or no date."""
    if not channel_created_at:
        return None, True
    try:
        created = datetime.fromisoformat(channel_created_at).date()
        age_days = (date.today() - created).days
        return age_days, age_days < 90
    except Exception:
        return None, True


def _save_channel_json(channels_dir: Path, channel_id: str, updates: dict) -> bool:
    """Merge updates into channels/{channel_id}.json and write back."""
    path = channels_dir / f"{channel_id}.json"
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.update(updates)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception as e:
        st.error(f"Write failed: {e}")
        return False


def render_channels(data_service: DashboardDataService) -> None:
    st.title("📡 Channels")

    channels = data_service.get_channel_profiles()

    if not channels:
        st.info("No channel profiles found. Add JSON files to `channels/` directory.")
        return

    # ── Summary row ───────────────────────────────────────────────────────
    total_channels = len(channels)
    monetized  = sum(1 for c in channels if c.monetized)
    at_risk    = sum(1 for c in channels if c.active_strikes > 0)
    config_only= sum(1 for c in channels if c.status == "config_only")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total Channels",   total_channels)
    m2.metric("Monetized",        monetized)
    m3.metric("Active Strikes",   f"⚠️ {at_risk}" if at_risk else "0")
    m4.metric("Config Only (no DB)", config_only)

    st.divider()

    # ── Filters ───────────────────────────────────────────────────────────
    col_f1, col_f2 = st.columns([3, 1])
    with col_f1:
        search = st.text_input("Search channels", placeholder="retirement, fin_, ...")
    with col_f2:
        show_only = st.selectbox("Show", ["All", "Monetized", "Strikes", "Config only"])

    filtered = channels
    if search:
        q = search.lower()
        filtered = [
            c for c in filtered
            if q in c.name.lower() or q in c.channel_id.lower()
            or q in c.niche.lower() or q in c.sub_niche.lower()
        ]
    if show_only == "Monetized":
        filtered = [c for c in filtered if c.monetized]
    elif show_only == "Strikes":
        filtered = [c for c in filtered if c.active_strikes > 0]
    elif show_only == "Config only":
        filtered = [c for c in filtered if c.status == "config_only"]

    st.caption(f"Showing **{len(filtered)}** of {total_channels} channels · Click a row to inspect & edit")

    # ── Master table ──────────────────────────────────────────────────────
    rows = []
    for ch in filtered:
        age_days, is_young = _age_info(ch.channel_created_at)
        age_str = (
            f"🌱 {age_days}d" if (age_days is not None and is_young)
            else (f"🏆 {age_days}d" if age_days is not None else "🌱 new")
        )
        status_icon = "✅" if ch.monetized else ("⚙️" if ch.status == "config_only" else "📺")
        strike_flag = f"🚨×{ch.active_strikes}" if ch.active_strikes > 0 else "—"

        rows.append({
            "": status_icon,
            "Channel":   ch.name,
            "ID":        ch.channel_id,
            "Niche":     ch.niche,
            "Age":       age_str,
            "Videos":    ch.videos_published,
            "Revenue $": ch.revenue_total,
            "Health":    ch.health_score,
            "Strikes":   strike_flag,
        })

    df = pd.DataFrame(rows)

    selection = st.dataframe(
        df,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Revenue $": st.column_config.NumberColumn("Revenue $", format="$%.0f"),
            "Health":    st.column_config.ProgressColumn("Health", min_value=0, max_value=100, format="%d"),
            "":          st.column_config.TextColumn("", width="small"),
        },
        key="channels_table",
    )

    selected_rows = selection.selection.rows if selection.selection else []

    if not selected_rows:
        st.markdown(
            "<div style='color:#475569;font-size:.82rem;padding:8px 0;'>"
            "← Click a row to view details and edit brand settings</div>",
            unsafe_allow_html=True,
        )
        return

    # ── Detail + Edit panel ───────────────────────────────────────────────
    idx = selected_rows[0]
    ch  = filtered[idx]
    age_days, is_young = _age_info(ch.channel_created_at)

    age_badge = (
        f"🌱 {age_days}d old (young)" if (age_days is not None and is_young)
        else (f"🏆 {age_days}d (mature)" if age_days is not None else "🌱 young (no date)")
    )
    status_icon = "✅" if ch.monetized else ("⚙️" if ch.status == "config_only" else "📺")

    st.markdown(f"""
    <div class="detail-panel">
        <strong style="font-size:1rem;">{status_icon} {ch.name}</strong>
        <span style="color:#64748b;font-size:.8rem;margin-left:10px;">
            {ch.channel_id} · {age_badge}
        </span>
    </div>
    """, unsafe_allow_html=True)

    # Strike alert
    if ch.active_strikes > 0:
        st.error(f"⚠️ {ch.active_strikes} active strike(s). Review YouTube Studio immediately.")

    # ── Metrics row ───────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Videos",    ch.videos_published)
    c2.metric("Revenue",   f"${ch.revenue_total:.0f}")
    c3.metric("Cost",      f"${ch.cost_total:.2f}")
    c4.metric("CTR avg",   f"{ch.ctr_avg:.2f}%" if ch.ctr_avg else "—")
    c5.metric("RPM avg",   f"${ch.rpm_avg:.2f}" if ch.rpm_avg else "—")

    if ch.last_upload:
        st.caption(f"Last upload: {ch.last_upload.strftime('%Y-%m-%d %H:%M UTC')}")

    st.divider()

    # ── Two-column: Audience signals | Brand editor ───────────────────────
    col_info, col_edit = st.columns([1, 1])

    with col_info:
        st.markdown("##### 📊 Audience Signals")
        ai1, ai2, ai3 = st.columns(3)
        ai1.metric("Competitors", ch.competitor_count)
        ai2.metric("Subreddits",  ch.subreddit_count)
        ai3.metric("Target",      f"{ch.target_duration_min} min")
        st.caption(f"RPM floor: ${ch.rpm_floor:.2f} · Sub-niche: {ch.sub_niche}")

        st.divider()
        st.markdown("##### ⚡ Quick Actions")
        st.code(f"python run_pipeline.py --channel {ch.channel_id}", language="bash")
        if ch.status == "config_only":
            st.info("Channel not in DB yet. Run pipeline to initialize.")

    with col_edit:
        st.markdown("##### 🎨 Brand Identity — **Edit**")
        st.caption("Changes write directly to `channels/{id}.json`")

        edit_prefix = f"ch_edit_{ch.channel_id}"

        # Color picker
        cur_color = ch.brand_color_hex or "#1A1A2E"
        new_color = st.color_picker("Brand color", value=cur_color,
                                     key=f"{edit_prefix}_color")
        # Show swatch + hex
        st.markdown(
            f"<div style='display:flex;align-items:center;gap:8px;margin-bottom:8px;'>"
            f"<div style='width:28px;height:28px;background:{new_color};"
            f"border-radius:4px;border:1px solid #555;'></div>"
            f"<code style='font-size:.8rem;'>{new_color}</code></div>",
            unsafe_allow_html=True,
        )

        # Font vibe
        cur_font_idx = _FONT_OPTIONS.index(ch.font_vibe) if ch.font_vibe in _FONT_OPTIONS else 0
        new_font = st.selectbox(
            "Font vibe",
            options=_FONT_OPTIONS,
            format_func=lambda k: _FONT_LABELS[k],
            index=cur_font_idx,
            key=f"{edit_prefix}_font",
        )

        # Tone + Persona
        new_tone    = st.text_input("Tone",     value=ch.tone or "",          key=f"{edit_prefix}_tone")
        new_persona = st.text_input("Persona",  value=ch.voice_persona or "", key=f"{edit_prefix}_persona")
        new_hook    = st.text_area("Hook format", value=ch.hook_format or "", height=100,
                                   key=f"{edit_prefix}_hook")

        # Save button
        if st.button("💾 Update Channel", key=f"{edit_prefix}_save",
                     use_container_width=True, type="primary"):
            updates = {
                "brand_color_hex": new_color,
                "font_vibe":       new_font,
                "tone":            new_tone,
                "voice_persona":   new_persona,
                "hook_format":     new_hook,
            }
            if _save_channel_json(data_service._channels_dir, ch.channel_id, updates):
                # Invalidate profile cache so next render picks up changes
                data_service._profiles = None
                st.success(f"✅ `channels/{ch.channel_id}.json` updated.")
                st.rerun()
            # error already shown inside _save_channel_json
