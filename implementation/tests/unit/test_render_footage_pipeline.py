"""Render-path regression: the footage-channel visual pipeline.

The first Retirement Desk render shipped 15 minutes of text cards because of
two silent gaps that these tests pin closed:

  1. ``visual_style: "clean_trust"`` matched no ``_STYLE_MAP`` preset, so the
     channel silently fell back to the "editorial" look.
  2. The storyboard (and with it the ENTIRE stock/chart/web acquisition
     pipeline, including the audited chart engine) was only built when an
     image provider / veo / --all-stock was in play. A ``footage`` channel has
     none of those — the render went straight to per-shot text cards.
"""

from __future__ import annotations

from pathlib import Path

import channel_render

RENDERER = Path(channel_render.__file__).resolve().parent / "render_real_video.py"


def test_clean_trust_maps_to_dark_finance():
    assert channel_render._STYLE_MAP["clean_trust"] == "dark_finance"


def test_senior_wealth_us_resolves_off_the_editorial_fallback():
    params = channel_render.resolve("senior_wealth_us")
    assert params["style"] == "dark_finance"


def test_unmapped_visual_style_warns_instead_of_silent_fallback(capsys):
    params = channel_render._derive({"visual_style": "no_such_style"})
    assert params["style"] == "editorial"
    assert "matches no preset" in capsys.readouterr().out


def test_board_is_built_for_style_policy_channels():
    """The board-driven condition must include the channel_style policy term,
    and it must sit before the storyboard build it gates."""
    source = RENDERER.read_text(encoding="utf-8")
    cond = source.index(
        "if image_provider is not None or veo_mode or args.all_stock "
        "or _style_policy is not None:")
    build = source.index("Generating storyboard (continuity-aware prompts)")
    assert cond < build


def test_generated_image_without_provider_degrades_to_stock_not_text_card():
    source = RENDERER.read_text(encoding="utf-8")
    assert ('visual_type == "generated_image" and image_provider is None'
            in source)


def test_strict_mode_refuses_a_text_card_footage_video():
    source = RENDERER.read_text(encoding="utf-8")
    assert "refuses a text-card video" in source


def test_footage_channel_never_burns_internal_headings_on_screen():
    """Render v2 burned 'SCENE 38/160' + the storyboard prompt ('calendar
    birthday circled') on every shot and darkened/collided with real charts.
    On a footage channel without subtitles the overlay must be blank, and the
    guard must run BEFORE the HTML-overlay swap so nothing re-wraps it."""
    source = RENDERER.read_text(encoding="utf-8")
    guard = source.index('_style_policy.style_id == "footage"')
    html_swap = source.index('use_html = args.overlay == "html"')
    assert guard < html_swap


def test_senior_channel_uses_subtitles_for_readability():
    """Audience is 60-75: narration belongs in large synced captions, not in a
    heading scrim. The channel render override must pin subtitle=True."""
    params = channel_render.resolve("senior_wealth_us")
    assert params["subtitle"] is True


def test_senior_finance_thumbnail_uses_trust_layout():
    """A 60-75 finance audience must not inherit the generic MrBeast layout."""
    import render_real_video as rrv

    meta = {
        "niche": "finance",
        "visual_style": "clean_trust",
        "audience": {"age_range": "60-75"},
    }
    assert rrv._thumbnail_layout(meta) == "trust"


def test_ai_banned_trust_channel_can_package_from_its_licensed_real_footage():
    """Strict mode must not demand a synthetic Flow image from a channel that
    explicitly bans generated imagery. A real frame acquired for this render
    is a valid, provenance-preserving thumbnail source."""
    import render_real_video as rrv

    meta = {
        "niche": "finance",
        "visual_style": "clean_trust",
        "channel_style": "footage",
        "ban_generated_images": True,
    }
    assert rrv._allow_real_frame_thumbnail(meta) is True


def test_trust_thumbnail_composer_produces_a_clean_1280x720_package(tmp_path):
    from PIL import Image

    import clickbait

    bg = tmp_path / "real_frame.png"
    out = tmp_path / "thumb.png"
    Image.new("RGB", (960, 540), (92, 106, 118)).save(bg)
    clickbait.compose_thumbnail(
        bg, "$24,480 LIMIT", out, accent=(212, 175, 55), layout="trust")

    made = Image.open(out)
    assert made.size == (1280, 720)


def test_packaging_truth_guard_rejects_unsupported_breaking_news_language():
    import clickbait

    raw = {
        "title": (
            "Your Next Social Security Check Could Be Smaller — "
            "SSA Just Confirmed Why"
        ),
        "alternatives": [
            "Working While on Social Security? Where the Withheld Money Goes",
            "Breaking: A New Social Security Rule Changes Everything",
        ],
        "thumb_text": "SMALLER CHECK?",
        "thumb_prompt": "retirement paperwork",
    }
    script = (
        "For 2026, SSA applies an earnings limit. We will read the published "
        "rule and explain how withholding and later recalculation work."
    )

    guarded = clickbait._apply_packaging_truth_guard(raw, script)

    assert guarded["title"] == raw["alternatives"][0]
    assert guarded["truth_guard_replaced_title"] is True


def test_packaging_truth_guard_rejects_titles_that_call_withholding_a_loss():
    import clickbait

    raw = {
        "title": (
            "The Social Security Rule That Takes Back $1 for Every $2 You Earn"
        ),
        "alternatives": [
            "Working While on Social Security? What Happens to Your Check",
        ],
    }
    script = (
        "SSA withholds part of the current benefit. The benefits are not lost; "
        "a later recalculation increases the monthly benefit permanently."
    )

    guarded = clickbait._apply_packaging_truth_guard(raw, script)

    assert guarded["title"] == raw["alternatives"][0]
    assert guarded["truth_guard_replaced_title"] is True


def test_packaging_truth_guard_rejects_fake_secrecy_and_suddenness():
    import clickbait

    raw = {
        "title": (
            "Your Social Security Check Just Got Smaller — "
            "Here's What SSA Won't Tell You"
        ),
        "alternatives": [
            "The $24,480 Social Security Earnings Trap Explained",
        ],
    }
    script = (
        "This is a published 2026 SSA earnings-test rule. We are reading the "
        "agency page together; withholding is followed by recalculation."
    )

    guarded = clickbait._apply_packaging_truth_guard(raw, script)

    assert guarded["title"] == (
        "Working While on Social Security? Where the Withheld Money Goes"
    )


def test_outro_subline_supports_the_spoken_channel_promise_and_question():
    import render_real_video as rrv

    assert rrv._outro_subline(
        "We keep turning official rules into plain English."
    ) == "OFFICIAL RULES → PLAIN ENGLISH"
    assert rrv._outro_subline(
        "What would help you plan more: the current reduction or the later "
        "recalculation?"
    ) == "CURRENT REDUCTION  •  LATER RECALCULATION?"


def test_web_image_fetch_survives_a_running_event_loop():
    """Scene 53 of the first live footage run crashed the whole render:
    download_best_web_image uses sync Playwright, which refuses to start on a
    thread whose event loop is running (html_overlay's persistent loop). The
    call site must go through _syncrun, which hops to a worker thread."""
    import asyncio

    import render_real_video as rrv

    source = RENDERER.read_text(encoding="utf-8")
    assert "_syncrun(download_best_web_image" in source

    async def _with_running_loop():
        # Inside a running loop, _syncrun must still execute the function
        # (on a worker thread) instead of letting sync Playwright bail.
        return _probe()

    def _probe():
        try:
            asyncio.get_running_loop()
            return "loop-visible"
        except RuntimeError:
            return "no-loop"

    assert asyncio.run(_with_running_loop()) == "loop-visible"
    assert rrv._syncrun(_probe) == "no-loop"

    async def _via_syncrun():
        return rrv._syncrun(_probe)

    # The worker thread has no running loop — exactly why Playwright works.
    assert asyncio.run(_via_syncrun()) == "no-loop"


def test_chart_cell_reads_the_ledger_with_a_defined_json_name(tmp_path):
    """First live chart run died on `name '_json' is not defined` — the ledger
    read in _render_chart_cell used a function-local alias that only exists in
    other scopes. A readable ledger must reach the audit, not die on the read."""
    import render_real_video as rrv

    script = tmp_path / "script.txt"
    script.write_text("The limit is $24,480 versus $65,160.", encoding="utf-8")
    (tmp_path / "fact_ledger.json").write_text(
        '{"ledger": {"entries": []}, "gate": {"passed": false}}',
        encoding="utf-8")
    spec = {"labels": ["lane one", "lane two"], "values": [24480, 65160],
            "title": "2026 earnings limits", "source": "SSA 2026"}
    try:
        rrv._render_chart_cell(spec, tmp_path / "chart.png", script, 320, 180)
        raised = None
    except rrv.ChartAuditError as exc:
        raised = str(exc)
    # The un-gated ledger must fail the AUDIT (fail-closed), never the READ.
    assert raised is not None
    assert "unreadable" not in raised


def test_rate_shorthand_chart_degrades_to_stock_instead_of_audit_abort(tmp_path, capsys):
    """'$1 withheld per $2' storyboarded as bars of 1 and 2 is not a data
    chart. It must skip (stock fallback) BEFORE the ledger audit — the first
    live run aborted the whole render on it (exit 86)."""
    import render_real_video as rrv

    script = tmp_path / "script.txt"
    script.write_text("One dollar withheld for every two earned.", encoding="utf-8")
    spec = {"labels": ["withheld", "earned"], "values": [1, 2],
            "title": "$1 per $2 over the limit", "source": "SSA 2026"}
    ok = rrv._render_chart_cell(spec, tmp_path / "chart.png", script, 320, 180)
    assert ok is False
    assert "rate shorthand" in capsys.readouterr().out


def test_mixed_unit_chart_degrades_to_stock_instead_of_audit_abort(tmp_path, capsys):
    """Live board charted the $24,480 limit next to the '$1 per $2' rate as
    [24480, 2] — incommensurable units on one axis. Must skip before the
    audit (the second live run aborted on exactly this cell)."""
    import render_real_video as rrv

    script = tmp_path / "script.txt"
    script.write_text("The limit is $24,480; $1 withheld per $2 over.",
                      encoding="utf-8")
    spec = {"labels": ["Earnings Limit", "$1 Withheld Per $2 Over"],
            "values": [24480, 2], "title": "Lane One", "source": "SSA 2026"}
    ok = rrv._render_chart_cell(spec, tmp_path / "chart.png", script, 320, 180)
    assert ok is False
    assert "mixed units" in capsys.readouterr().out


def test_all_equal_chart_values_degrade_to_stock(tmp_path, capsys):
    """[100, 100] decoration bars ('Two Rules: One Bends, One Doesn't') compare
    nothing and are fabricated by construction — skip before the audit."""
    import render_real_video as rrv

    script = tmp_path / "script.txt"
    script.write_text("Two rules: one bends, one doesn't.", encoding="utf-8")
    spec = {"labels": ["Earnings Test", "Tax Rules"], "values": [100, 100],
            "title": "Two Rules", "source": "SSA 2026"}
    ok = rrv._render_chart_cell(spec, tmp_path / "chart.png", script, 320, 180)
    assert ok is False
    assert "identical" in capsys.readouterr().out


def test_extreme_scale_gap_chart_degrades_to_stock(tmp_path, capsys):
    """[24480, 50] — a dollar limit next to a derived percentage: the small
    bar draws as zero pixels. Ratio ≥ 100x marks the spec degenerate."""
    import render_real_video as rrv

    script = tmp_path / "script.txt"
    script.write_text("The limit is $24,480.", encoding="utf-8")
    spec = {"labels": ["Annual Limit", "% Withheld"], "values": [24480, 50],
            "title": "Lane One", "source": "SSA 2026"}
    ok = rrv._render_chart_cell(spec, tmp_path / "chart.png", script, 320, 180)
    assert ok is False
    assert "zero pixels" in capsys.readouterr().out


def test_chart_preflight_blocks_all_unsourced_cells_before_acquisition():
    """A mid-acquisition audit abort costs a ~10-min loop per discovery.
    The renderer must audit the whole board up front and list every failing
    chart cell at once — before any download or TTS."""
    source = RENDERER.read_text(encoding="utf-8")
    preflight = source.index("PRE-FLIGHT BLOCK")
    acquisition = source.index("Acquire per-scene visuals by type")
    assert preflight < acquisition


def test_chart_scenes_render_static_full_frame():
    """Ken Burns on a chart PNG cropped the label column on a live run.
    motion_idx -1 must mean full-frame static, and chart backgrounds must be
    routed to it."""
    import render_real_video as rrv

    assert rrv._zoompan_expr(-1, 30) == ("1", "0", "0")
    source = RENDERER.read_text(encoding="utf-8")
    assert '-1 if bg.name.endswith("_chart.png")' in source


def test_board_patches_are_applied_by_the_renderer():
    """Index-keyed hand edits died TWICE when a config change re-rolled the
    storyboard cache. Curated decisions live in the product's
    board_patches.json (narration-keyed) and the renderer applies them on
    every build, before the router/preflight."""
    source = RENDERER.read_text(encoding="utf-8")
    patches = source.index("board_patches.json")
    router = source.index("Production mode router")
    preflight = source.index("PRE-FLIGHT BLOCK")
    assert patches < router < preflight


def test_hypothetical_chart_must_declare_example_source():
    """Codex render audit: a chart of worked-example figures credited 'SSA
    2025/2026'. Values covered ONLY by hypothetical entries force the source
    line to declare the example; real-figure charts keep authority credit."""
    from omnicast.compliance.fact_ledger import audit_chart_spec, script_sha256

    script = ("The limit is $24,480. Say her benefit is $1,940 a month, "
              "and it drops to roughly $1,428.")
    ledger_data = {
        "gate": {"passed": True},
        "ledger": {
            "script_sha256": script_sha256(script),
            "entries": [
                {"claim": "The limit is $24,480", "value": "$24,480",
                 "source_name": "SSA 2026 COLA Fact Sheet", "as_of": "2026"},
                {"claim": "it drops to roughly $1,428", "value": "$1,428",
                 "source_name": "worked example (hypothetical)", "as_of": "2026"},
            ],
        },
    }
    hypo_spec = {"title": "Benefit drop", "labels": ["Now", "Reduced"],
                 "values": [24480, 1428], "source": "SSA 2026"}
    fails = audit_chart_spec(hypo_spec, ledger_data, script)
    assert any("worked-example" in f for f in fails), fails

    hypo_spec["source"] = "Worked example (hypothetical benefit)"
    assert audit_chart_spec(hypo_spec, ledger_data, script) == []

    real_spec = {"title": "Limit", "labels": ["Now", "Reduced"],
                 "values": [24480, 1428],
                 "source": "SSA 2026, worked example"}
    # Mixed real+example with an honest combined credit passes too.
    assert audit_chart_spec(real_spec, ledger_data, script) == []


def test_collision_value_without_real_anchor_needs_example_source():
    """$2,040 is BOTH the real monthly limit and the example benefit. A chart
    of collision values alone must declare the example; adding a real-only
    anchor value ($5,430) restores authority credit (codex verify round)."""
    from omnicast.compliance.fact_ledger import audit_chart_spec, script_sha256

    script = ("The monthly line is $2,040, or $5,430 in the FRA year. "
              "Take a full benefit of $2,040 a month, it drops to $1,428.")
    ledger_data = {
        "gate": {"passed": True},
        "ledger": {
            "script_sha256": script_sha256(script),
            "entries": [
                {"claim": "monthly line is $2,040", "value": "$2,040",
                 "source_name": "SSA 2026 Monthly Exempt Amount", "as_of": "2026"},
                {"claim": "or $5,430 in the FRA year", "value": "$5,430",
                 "source_name": "SSA 2026 Monthly Exempt Amount", "as_of": "2026"},
                {"claim": "full benefit of $2,040 a month", "value": "$2,040",
                 "source_name": "worked example (hypothetical)", "as_of": "2026"},
                {"claim": "drops to $1,428", "value": "$1,428",
                 "source_name": "worked example (hypothetical)", "as_of": "2026"},
            ],
        },
    }
    # Collision value with no real-only anchor -> must declare example.
    ambiguous = {"title": "Full benefit", "labels": ["Monthly", "Weekly"],
                 "values": [2040, 2040.5], "source": "SSA 2026"}
    ambiguous["values"] = [2040]
    ambiguous["labels"] = ["Monthly"]
    ambiguous = {"title": "Full benefit", "labels": ["Benefit", "Reduced"],
                 "values": [2040, 1428], "source": "SSA 2026"}
    fails = audit_chart_spec(ambiguous, ledger_data, script)
    assert any("worked-example" in f for f in fails), fails

    # Real-only anchor present -> authority credit stands.
    anchored = {"title": "Monthly limits", "labels": ["Under FRA", "FRA year"],
                "values": [2040, 5430], "source": "SSA 2026"}
    assert audit_chart_spec(anchored, ledger_data, script) == []


def test_persist_final_board_behavioral(tmp_path):
    """board_final.json must be written with a digest sidecar whose sha256
    matches the file content, and the call site must sit AFTER the acquisition
    loop — an early snapshot is not the rendered board (codex verify R2)."""
    import hashlib
    import json as _json

    import render_real_video as rrv

    board = [{"visual_type": "stock_video", "stock_query": "q"},
             {"visual_type": "chart", "chart_spec": {"title": "T"}}]
    sha = rrv._persist_final_board(board, tmp_path)
    text = (tmp_path / "board_final.json").read_text(encoding="utf-8")
    assert _json.loads(text) == board
    assert sha == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert (tmp_path / "board_final.sha256").read_text(encoding="utf-8") == sha

    source = RENDERER.read_text(encoding="utf-8")
    persist_call = source.index("_persist_final_board(board, script_path.parent)")
    acquisition = source.index("Acquire per-scene visuals by type")
    assert acquisition < persist_call


def test_apply_board_patches_behavioral():
    """The patch application itself, not its source text: narration matching,
    cell update, chart-source override, and zero-match safety."""
    import render_real_video as rrv

    board = [{"visual_type": "stock_video", "stock_query": "old"},
             {"visual_type": "chart",
              "chart_spec": {"title": "T", "source": "SSA 2026"}},
        "not-a-dict"]
    scenes = [rrv.Scene(heading="[a]", narration="Carol had no idea about this."),
              rrv.Scene(heading="[b]", narration="It drops to roughly $1,428."),
              rrv.Scene(heading="[c]", narration="Unrelated.")]
    patches = [
        {"narration_key": "carol had no idea",
         "set": {"visual_type": "stock_video",
                 "stock_query": "senior woman surprised reading letter"}},
        {"narration_key": "drops to roughly $1,428",
         "chart_source": "Worked example (hypothetical benefit)"},
        {"narration_key": "matches nothing", "set": {"stock_query": "x"}},
    ]
    applied = rrv._apply_board_patches(board, scenes, patches)
    assert applied == 2
    assert board[0]["stock_query"] == "senior woman surprised reading letter"
    assert board[0]["visual_type_locked"] is True
    assert board[1]["chart_spec"]["source"] == "Worked example (hypothetical benefit)"


def test_product_curated_visual_type_wins_over_the_generic_router():
    """A narration-keyed editor decision is a lock, not a suggestion. Otherwise
    the money regex immediately turns a repaired real-footage beat back into
    the fabricated chart it was curated to replace."""
    source = RENDERER.read_text(encoding="utf-8")
    lock_guard = source.index('if _cell.get("visual_type_locked")')
    router_override = source.index(
        '_cell["visual_type"] = _route.visual_type', lock_guard)
    assert lock_guard < router_override


def test_generic_router_preserves_explicit_evidence_and_requires_a_real_chart_spec():
    import render_real_video as rrv

    assert not rrv._router_can_override_visual(
        {"visual_type": "web_screenshot", "search_query": "https://ssa.gov"},
        "chart")
    assert not rrv._router_can_override_visual(
        {"visual_type": "stock_video"}, "chart")
    assert rrv._router_can_override_visual(
        {"visual_type": "stock_video",
         "chart_spec": {"labels": ["A", "B"], "values": [24480, 65160]}},
        "chart")
    assert not rrv._router_can_override_visual(
        {"visual_type": "stock_video", "visual_type_locked": True},
        "chart")


def test_dormant_chart_specs_are_cleared_in_preflight():
    """A rejected chart cell re-typed to stock kept its fabricated spec — a
    later type flip could reactivate it (codex finding 3)."""
    source = RENDERER.read_text(encoding="utf-8")
    assert "clearing dormant" in source
    assert '_cell.pop("chart_spec", None)' in source


def test_stat_label_figures_are_audited_too():
    """The kinetic LABEL renders on screen; a number in it bypassed the YMYL
    gate (codex finding 4a)."""
    source = RENDERER.read_text(encoding="utf-8")
    assert "cell.get('stat_label') or ''" in source.replace('"', "'")


def test_ymyl_visual_preflight_catches_a_stale_year_before_asset_download():
    import render_real_video as rrv
    from omnicast.compliance.fact_ledger import script_sha256

    script = "For 2026 the earnings limit is $24,480."
    ledger = {
        "gate": {"passed": True},
        "ledger": {
            "script_sha256": script_sha256(script),
            "entries": [{
                "claim": script,
                "value": "$24,480",
                "source_name": "SSA Working While Retired",
                "as_of": "2026",
            }],
        },
    }
    bad = [{"visual_type": "web_search_image",
            "search_query": "SSA earnings limit 2025",
            "stat_number": "$24,480",
            "stat_label": "2025 EARNINGS LIMIT"}]
    assert "2025" in " ".join(rrv._audit_visual_numeric_fields(bad, ledger))

    good = [{"visual_type": "web_screenshot",
             "search_query": "https://www.ssa.gov/benefits/retirement/planner/whileworking.html",
             "stat_number": "$24,480",
             "stat_label": "2026 EARNINGS LIMIT"}]
    assert rrv._audit_visual_numeric_fields(good, ledger) == []


def test_stat_overlay_preserves_an_official_web_screenshot():
    """A verified SSA page is real source imagery. Adding a kinetic stat must
    not silently replace that evidence with generic stock footage."""
    import render_real_video as rrv

    assert not rrv._stat_visual_needs_stock("web_screenshot")
    assert not rrv._stat_visual_needs_stock("stock_video")
    assert not rrv._stat_visual_needs_stock("chart")
    assert rrv._stat_visual_needs_stock("generated_image")
    assert rrv._stat_visual_needs_stock("web_search_image")


def test_ymyl_evidence_visual_binding_uses_verified_official_page():
    """A YMYL evidence beat should resolve to the verified evidence pack URL,
    never to whichever third-party image ranks first in web search."""
    import render_real_video as rrv

    scenes = [rrv.Scene(
        heading="[evidence]",
        narration=("According to that same SSA page, only earnings through "
                   "the month before full retirement age are counted."),
    )]
    board = [{
        "visual_type": "web_search_image",
        "search_query": "SSA earnings test month before full retirement age",
    }]
    evidence_pack = {"entries": [{
        "evidence_id": "E6",
        "claim": ("SSA counts only earnings through the month before full "
                  "retirement age, not earnings for the entire year."),
        "quote": ("We only count your earnings up to the month before you "
                  "reach your full retirement age."),
        "source_url": (
            "https://www.ssa.gov/benefits/retirement/planner/whileworking.html"
        ),
    }]}

    assert rrv._bind_ymyl_evidence_visuals(
        board, scenes, evidence_pack) == 1
    assert board[0]["visual_type"] == "web_screenshot"
    assert board[0]["search_query"].startswith("https://www.ssa.gov/")
    assert board[0]["evidence_id"] == "E6"
    assert board[0]["visual_type_locked"] is True


def test_ymyl_evidence_binding_replaces_unverified_official_looking_url():
    """A .gov hostname is not enough: a guessed path can be a 404/error page.
    The exact URL must come from the verified evidence pack."""
    import render_real_video as rrv

    scenes = [rrv.Scene(
        heading="[calculator]",
        narration=("SSA links an earnings test calculator so you can see how "
                   "work may affect benefit payments."),
    )]
    board = [{
        "visual_type": "web_screenshot",
        "search_query": (
            "https://www.ssa.gov/benefits/retirement/planner/earnings-test.html"
        ),
    }]
    pack = {"entries": [{
        "evidence_id": "E10",
        "claim": "SSA links an earnings test calculator for people still working.",
        "quote": "use our earnings test calculator to see how your earnings could affect your benefit payments",
        "source_url": (
            "https://www.ssa.gov/benefits/retirement/planner/whileworking.html"
        ),
    }]}

    assert rrv._bind_ymyl_evidence_visuals(board, scenes, pack) == 1
    assert board[0]["search_query"].endswith("/whileworking.html")
    assert board[0]["evidence_id"] == "E10"


def test_ban_generated_images_channel_flag_closes_both_paths():
    """YMYL trust channel: AI imagery must be impossible even with a provider
    configured (codex finding 4b). Both the disable and the no-reload guard
    must reference the flag."""
    source = RENDERER.read_text(encoding="utf-8")
    assert source.count('channel_meta.get("ban_generated_images")') >= 2
    import json as _json
    cfg = _json.loads(
        (RENDERER.parent / "channels" / "senior_wealth_us.json")
        .read_text(encoding="utf-8"))
    assert cfg.get("ban_generated_images") is True


def test_visual_qc_report_keeps_every_below_threshold_row():
    """A truncated worst-list hid 2 failures from an external audit (codex
    finding 2)."""
    qc = (RENDERER.parent / "visual_match_qc.py").read_text(encoding="utf-8")
    assert "low[:20]" not in qc


def test_renderer_purges_stale_per_shot_artifacts():
    """A 154-shot re-render on top of a 160-shot _assets dir left 6 stale
    scene_XX files; visual QC globbed them into a 160-shot timeline and scored
    every late frame against the wrong narration. The purge must exist and run
    before composing."""
    source = RENDERER.read_text(encoding="utf-8")
    purge = source.index("purged {_stale} stale per-shot artifacts")
    compose = source.index("Composing")
    assert purge < compose


def test_shot_splitter_never_breaks_numbers():
    """The enumeration splitter counted thousands-separator commas as list
    separators: '$7,760' shipped as '$7' | '760 of your own benefit' across a
    shot boundary — the TTS then SPOKE the mangled halves on a finance video.
    Number-internal commas must never split; real enumerations still must."""
    import render_real_video as rrv

    hook = rrv.Scene(
        heading="[hook]",
        narration=("Work part-time in 2026, earn $40,000, and Social Security "
                   "will hold back $7,760 of your own benefit."))
    shots = rrv.split_into_shots([hook], 18)
    narrs = [s.narration for s in shots]
    assert any("$7,760" in n for n in narrs), narrs
    assert any("$40,000" in n for n in narrs), narrs

    listing = rrv.Scene(
        heading="[list]",
        narration=("The tool handles email drafts, meeting notes, travel plans, "
                   "grocery lists, and daily reminders."))
    burst = rrv.split_into_shots([listing], 18)
    assert len(burst) >= 2  # genuine comma series still cuts to montage shots


def test_web_shot_embeds_screenshot_as_data_uri():
    """The browser-mockup page is set_content() (origin about:blank); Chromium
    blocks file:// subresources there, so the old file-URI embed shipped a
    blank white 'browser window' while reporting success. The embed must be a
    data: URI and the capture must verify the image actually decoded."""
    from pathlib import Path

    import channel_render

    ws = (Path(channel_render.__file__).resolve().parent / "src" / "omnicast"
          / "media" / "providers" / "web_shot.py")
    source = ws.read_text(encoding="utf-8")
    assert "data:image/png;base64," in source
    assert "temp_raw.resolve().as_uri()" not in source
    assert "naturalWidth > 0" in source


def test_small_decimal_chart_values_still_reach_the_audit(tmp_path):
    """A 2.8% vs 2.5% COLA comparison is REAL data — the shorthand guard must
    not swallow it (decimals pass through to the fail-closed audit)."""
    import render_real_video as rrv

    script = tmp_path / "script.txt"
    script.write_text("COLA was 2.5 percent, now 2.8 percent.", encoding="utf-8")
    (tmp_path / "fact_ledger.json").write_text(
        '{"ledger": {"entries": []}, "gate": {"passed": false}}',
        encoding="utf-8")
    spec = {"labels": ["2025", "2026"], "values": [2.5, 2.8],
            "title": "COLA", "source": "SSA 2026"}
    try:
        rrv._render_chart_cell(spec, tmp_path / "chart.png", script, 320, 180)
        raised = None
    except rrv.ChartAuditError as exc:
        raised = str(exc)
    assert raised is not None  # reached the audit and failed closed there
