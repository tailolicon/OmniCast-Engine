"""Mission Control tab — Alert banner, pipeline stages, component health, LIVE quick actions."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

import plotly.graph_objects as go
import streamlit as st

from omnicast.dashboard.data_service import DashboardDataService

# project root = 4 levels up from this file (tabs/dashboard/omnicast/src → implementation/)
_PROJECT_ROOT = __import__("pathlib").Path(__file__).resolve().parents[4]


# ══════════════════════════════════════════════════════════════════════════════
# Process runner — actual subprocess execution with live output
# ══════════════════════════════════════════════════════════════════════════════

def _proc_start(key: str, cmd: list[str]) -> None:
    """Launch subprocess, store handle + live output list in session_state."""
    output: list[str] = []
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(_PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as e:
        st.error(f"Command not found: {e}")
        return

    def _reader(p: subprocess.Popen, buf: list[str]) -> None:
        for line in p.stdout:  # type: ignore[union-attr]
            buf.append(line.rstrip())

    t = threading.Thread(target=_reader, args=(proc, output), daemon=True)
    t.start()

    st.session_state[key] = {
        "proc":       proc,
        "output":     output,
        "started_at": datetime.now(timezone.utc),
        "cmd":        " ".join(cmd),
        "done":       False,
        "returncode": None,
    }


def _proc_poll(key: str) -> dict | None:
    info = st.session_state.get(key)
    if not info:
        return None
    if not info["done"]:
        rc = info["proc"].poll()
        if rc is not None:
            info["done"] = True
            info["returncode"] = rc
    return info


def _proc_kill(key: str) -> None:
    info = st.session_state.get(key)
    if info and not info["done"]:
        try:
            info["proc"].terminate()
        except Exception:
            pass
        info["done"] = True
        info["returncode"] = -1


def _render_proc(key: str, label: str) -> None:
    """Render live output panel for a running/completed process."""
    info = _proc_poll(key)
    if not info:
        return

    elapsed = (datetime.now(timezone.utc) - info["started_at"]).total_seconds()
    output  = info["output"]

    if not info["done"]:
        # ── Running ───────────────────────────────────────────────────────
        st.markdown(
            f"<div style='background:rgba(245,158,11,.1);border:1px solid rgba(245,158,11,.4);"
            f"border-radius:8px;padding:10px 16px;margin:8px 0;"
            f"display:flex;justify-content:space-between;align-items:center;'>"
            f"<span style='color:#fcd34d;font-weight:600;'>⏳ {label} đang chạy... ({elapsed:.0f}s)</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

        if output:
            # Show last 40 lines in a fixed-height scrollable box
            log_text = "\n".join(output[-40:])
            st.code(log_text, language="bash")

        stop_col, _ = st.columns([1, 3])
        with stop_col:
            if st.button("⛔ Stop", key=f"stop_{key}", use_container_width=True):
                _proc_kill(key)
                st.rerun()

        # Poll — sleep then rerun to refresh output
        time.sleep(0.5)
        st.rerun()

    else:
        # ── Finished ──────────────────────────────────────────────────────
        rc = info["returncode"]
        if rc == 0:
            st.markdown(
                f"<div style='background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.4);"
                f"border-radius:8px;padding:10px 16px;margin:8px 0;'>"
                f"<span style='color:#86efac;font-weight:600;'>✅ {label} hoàn thành ({elapsed:.0f}s)</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f"<div style='background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.4);"
                f"border-radius:8px;padding:10px 16px;margin:8px 0;'>"
                f"<span style='color:#fca5a5;font-weight:600;'>❌ {label} thất bại (exit {rc}, {elapsed:.0f}s)</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

        if output:
            with st.expander("📋 Xem log đầy đủ", expanded=(rc != 0)):
                st.code("\n".join(output), language="bash")

        if st.button("✖ Đóng", key=f"close_{key}"):
            del st.session_state[key]
            st.rerun()


def _proc_is_running(key: str) -> bool:
    info = st.session_state.get(key)
    return bool(info and not info["done"])


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _rel(dt: datetime) -> str:
    diff = (datetime.now(timezone.utc) - dt).total_seconds()
    if diff < 60:    return "vừa xong"
    if diff < 3600:  return f"{int(diff//60)}p trước"
    if diff < 86400: return f"{int(diff//3600)}h trước"
    return f"{int(diff//86400)}d trước"


_STAGE_META = [
    ("queued",      "⏳ Hàng chờ",   "#6366f1"),
    ("researching", "🔍 Nghiên cứu", "#3b82f6"),
    ("debating",    "🤖 Debate LLM", "#8b5cf6"),
    ("rendering",   "🎬 Render",      "#f59e0b"),
    ("uploading",   "📤 Upload",      "#10b981"),
    ("failed",      "❌ Lỗi",         "#ef4444"),
]

# Process state keys
_PROC_NICHE    = "proc_discover_niches"
_PROC_PIPELINE = "proc_run_pipeline"
_PROC_REAUTH   = "proc_reauth"


# ══════════════════════════════════════════════════════════════════════════════
# Main render
# ══════════════════════════════════════════════════════════════════════════════

def render_home(data_service: DashboardDataService) -> None:

    # ── 1. Data fetch ──────────────────────────────────────────────────────
    kpis    = data_service.get_kpis()
    items   = data_service.get_pipeline_items()
    workers = data_service.get_worker_statuses()
    tokens  = data_service.get_token_statuses()
    acts    = data_service.get_activity_feed(limit=15)

    # ── 2. Alert banner ────────────────────────────────────────────────────
    alerts: list[str] = []
    if kpis.dlq_count > 0:
        alerts.append(f"💀 DLQ có {kpis.dlq_count} item lỗi — vào tab DLQ để xử lý")
    expired_tokens = [t for t in tokens if t.status == "expired"]
    if expired_tokens:
        names = ", ".join(t.channel_name for t in expired_tokens[:3])
        alerts.append(f"🔑 Token hết hạn: {names} — upload sẽ fail")
    offline_workers = [w for w in workers if w.status == "offline"]
    if offline_workers:
        alerts.append(f"🔴 {len(offline_workers)} worker offline")
    failed_count = sum(1 for i in items if i.status == "failed")
    if failed_count > 0:
        alerts.append(f"⚠️ {failed_count} video đang bị lỗi trong pipeline")

    if alerts:
        issues_html = "".join(f"<div>• {a}</div>" for a in alerts)
        st.markdown(f"""
        <div class="alert-banner critical">
            <span style="font-size:1.3rem;">🚨</span>
            <div><strong>CẦN XỬ LÝ NGAY</strong>{issues_html}</div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="alert-banner ok">
            <span style="font-size:1.3rem;">✅</span>
            <strong>Hệ thống hoạt động bình thường — không có vấn đề gì</strong>
        </div>
        """, unsafe_allow_html=True)

    # ── 3. KPI row ─────────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: st.metric("📹 Video hôm nay",  kpis.videos_today)
    with c2: st.metric("📡 Kênh active",    kpis.active_channels)
    with c3:
        delta = kpis.system_health - 100
        st.metric("❤️ System Health", f"{kpis.system_health:.0f}%",
                  delta=f"{delta:.0f}%" if delta != 0 else None, delta_color="inverse")
    with c4: st.metric("⏳ Queue",  kpis.queue_depth)
    with c5:
        dlq_val = f"🚨 {kpis.dlq_count}" if kpis.dlq_count > 0 else "0"
        st.metric("💀 DLQ", dlq_val)

    st.divider()

    # ── 4. Pipeline stages ─────────────────────────────────────────────────
    st.markdown("### 🏭 Pipeline — Đang xử lý")

    counts = {s: 0 for s, *_ in _STAGE_META}
    for item in items:
        if item.status in counts:
            counts[item.status] += 1

    cols = st.columns(len(_STAGE_META))
    for col, (stage, label, color) in zip(cols, _STAGE_META):
        n = counts[stage]
        border = f"border-top: 3px solid {color};"
        badge  = (
            f'<span style="background:{color};color:#fff;font-size:.65rem;'
            f'padding:2px 7px;border-radius:10px;margin-left:6px;">LIVE</span>'
            if n > 0 and stage != "failed" else ""
        )
        fail_style = "color:#ef4444;" if stage == "failed" and n > 0 else f"color:{color};"
        with col:
            st.markdown(f"""
            <div class="stage-card" style="{border}">
                <div class="stage-name">{label}{badge}</div>
                <div class="stage-count" style="{fail_style}">{n}</div>
            </div>
            """, unsafe_allow_html=True)

    st.divider()

    # ── 5. Two-column: Component health + Quick Actions ────────────────────
    col_left, col_right = st.columns([1, 1])

    # ── 5a. Component health ───────────────────────────────────────────────
    with col_left:
        st.markdown("### 🔌 Trạng thái hệ thống")

        db_ok  = data_service._get_engine() is not None
        db_cls = "ok" if db_ok else "error"
        db_txt = "Kết nối tốt" if db_ok else "Không kết nối được"
        st.markdown(f"""
        <div class="comp-card {db_cls}">
            <div class="comp-name">🗄️ PostgreSQL</div>
            <div class="comp-detail">{db_txt}</div>
        </div>""", unsafe_allow_html=True)

        r = data_service._get_redis()
        redis_ok = False
        if r:
            try: r.ping(); redis_ok = True
            except Exception: pass
        redis_cls = "ok" if redis_ok else "error"
        redis_txt = "Kết nối tốt" if redis_ok else "Không kết nối được"
        st.markdown(f"""
        <div class="comp-card {redis_cls}">
            <div class="comp-name">⚡ Redis</div>
            <div class="comp-detail">{redis_txt}</div>
        </div>""", unsafe_allow_html=True)

        n_healthy  = sum(1 for w in workers if w.status == "healthy")
        n_degraded = sum(1 for w in workers if w.status == "degraded")
        n_offline  = sum(1 for w in workers if w.status == "offline")
        total_w    = len(workers)
        if total_w == 0:
            w_cls = "warn"; w_txt = "Không có worker nào đang chạy"
        elif n_offline > 0:
            w_cls = "warn" if n_healthy > 0 else "error"
            w_txt = f"{n_healthy} healthy · {n_degraded} degraded · {n_offline} offline"
        else:
            w_cls = "ok"; w_txt = f"{n_healthy}/{total_w} healthy"
        st.markdown(f"""
        <div class="comp-card {w_cls}">
            <div class="comp-name">⚙️ Workers ({total_w})</div>
            <div class="comp-detail">{w_txt}</div>
        </div>""", unsafe_allow_html=True)

        n_expired = sum(1 for t in tokens if t.status == "expired")
        n_warn_t  = sum(1 for t in tokens if t.status == "warning")
        t_cls = "error" if n_expired > 0 else "warn" if n_warn_t > 0 else "ok"
        t_txt = (
            f"{n_expired} hết hạn — upload sẽ fail!" if n_expired > 0
            else f"{n_warn_t} sắp hết hạn (< 7 ngày)" if n_warn_t > 0
            else f"{len(tokens)} token còn hạn"
        )
        st.markdown(f"""
        <div class="comp-card {t_cls}">
            <div class="comp-name">🔑 OAuth Tokens</div>
            <div class="comp-detail">{t_txt}</div>
        </div>""", unsafe_allow_html=True)

        dlq_cls = "error" if kpis.dlq_count > 0 else "ok"
        dlq_txt = f"{kpis.dlq_count} item chờ xử lý" if kpis.dlq_count > 0 else "Sạch"
        st.markdown(f"""
        <div class="comp-card {dlq_cls}">
            <div class="comp-name">💀 Dead Letter Queue</div>
            <div class="comp-detail">{dlq_txt}</div>
        </div>""", unsafe_allow_html=True)

    # ── 5b. Quick Actions — THỰC SỰ CHẠY LỆNH ────────────────────────────
    with col_right:
        st.markdown("### ⚡ Tác vụ nhanh")

        # ── Run Pipeline ──────────────────────────────────────────────────
        st.markdown("**▶ Chạy pipeline**")
        channels     = data_service.get_channel_profiles()
        channel_opts = [c.channel_id for c in channels] if channels else []

        if channel_opts:
            sel_ch = st.selectbox(
                "Chọn kênh", channel_opts,
                label_visibility="collapsed", key="qa_channel",
            )
            pipe_running = _proc_is_running(_PROC_PIPELINE)
            if st.button(
                "▶ Chạy pipeline ngay",
                use_container_width=True,
                key="qa_run",
                type="primary",
                disabled=pipe_running,
            ):
                _proc_start(_PROC_PIPELINE, [
                    sys.executable, "run_pipeline.py", "--channel", sel_ch,
                ])
                st.rerun()
        else:
            st.warning("Không có channel nào. Thêm JSON vào `channels/`.")

        _render_proc(_PROC_PIPELINE, "Pipeline")

        st.divider()

        # ── Discover Niches ───────────────────────────────────────────────
        st.markdown("**🔍 Tìm niche mới**")
        niche_running = _proc_is_running(_PROC_NICHE)
        if st.button(
            "🔍 Discover Niches" if not niche_running else "⏳ Đang chạy...",
            use_container_width=True,
            key="qa_niche",
            type="primary",
            disabled=niche_running,
        ):
            _proc_start(_PROC_NICHE, [
                sys.executable, "run_pipeline.py", "--discover-niches",
            ])
            st.rerun()

        _render_proc(_PROC_NICHE, "Discover Niches")

        st.divider()

        # ── Re-auth Token ─────────────────────────────────────────────────
        st.markdown("**🔑 Gia hạn token**")
        expired = [t for t in tokens if t.status in ("expired", "warning")]
        if expired:
            sel_tok = st.selectbox(
                "Kênh cần re-auth",
                [t.channel_id for t in expired],
                label_visibility="collapsed",
                key="qa_token",
            )
            reauth_running = _proc_is_running(_PROC_REAUTH)
            if st.button(
                "🔑 Bắt đầu re-auth",
                use_container_width=True,
                key="qa_reauth",
                disabled=reauth_running,
            ):
                _proc_start(_PROC_REAUTH, [
                    sys.executable, "run_pipeline.py", "auth", "--channel", sel_tok,
                ])
                st.rerun()

            _render_proc(_PROC_REAUTH, f"Re-auth {sel_tok}")
            st.caption("⚠️ Re-auth sẽ mở browser để xác nhận OAuth — kiểm tra cửa sổ trình duyệt.")
        else:
            st.success("Tất cả token còn hạn ✅")

        st.divider()

        if st.button("🔄 Refresh ngay", use_container_width=True, key="qa_refresh"):
            st.rerun()

    st.divider()

    # ── 6. Recent outputs ─────────────────────────────────────────────────
    all_items = data_service.get_pipeline_items()
    published = [i for i in all_items if i.status == "published"]
    if published:
        st.markdown("### 🎉 Video vừa publish")
        for v in published[:5]:
            score_txt   = f"Score: {v.critic_score:.0f}" if v.critic_score else "Score: —"
            score_color = "#22c55e" if (v.critic_score or 0) >= 75 else "#eab308" if (v.critic_score or 0) >= 50 else "#ef4444"
            st.markdown(f"""
            <div style="background:#1e2130;border:1px solid #2d3047;border-radius:8px;
                        padding:10px 16px;margin-bottom:6px;display:flex;
                        justify-content:space-between;align-items:center;">
                <div>
                    <span style="color:#e2e8f0;font-weight:600;">{v.title or v.video_id}</span>
                    <span style="color:#64748b;font-size:.75rem;margin-left:10px;">{v.channel_id}</span>
                </div>
                <div style="text-align:right;">
                    <span style="color:{score_color};font-weight:700;font-size:.9rem;">{score_txt}</span>
                    <span style="color:#475569;font-size:.72rem;margin-left:10px;">${v.cost_usd:.4f}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
        st.divider()

    # ── 7. Activity feed ──────────────────────────────────────────────────
    st.markdown("### 📋 Nhật ký hoạt động")

    if not acts:
        st.markdown("""
        <div style="color:#475569;text-align:center;padding:20px;
                    background:#1e2130;border-radius:8px;border:1px dashed #2d3047;">
            Chưa có hoạt động nào — DB chưa kết nối hoặc pipeline chưa chạy
        </div>
        """, unsafe_allow_html=True)
    else:
        sev_color = {"info": "#22c55e", "warning": "#eab308", "error": "#ef4444"}
        for act in acts:
            c = sev_color.get(act.severity, "#64748b")
            t = _rel(act.timestamp)
            ch = (
                f"<span style='color:#6366f1;font-size:.72rem;margin-left:8px;'>{act.channel_id}</span>"
                if act.channel_id else ""
            )
            st.markdown(f"""
            <div style="display:flex;align-items:center;gap:10px;
                        padding:8px 12px;border-radius:6px;margin-bottom:4px;
                        background:#1a1d27;border-left:3px solid {c};">
                <div style="flex:1;font-size:.85rem;color:#cbd5e1;">{act.message}{ch}</div>
                <div style="font-size:.72rem;color:#475569;white-space:nowrap;">{t}</div>
            </div>
            """, unsafe_allow_html=True)
