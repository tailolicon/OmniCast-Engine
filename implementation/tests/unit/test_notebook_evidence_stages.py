"""Source status must separate "the UI shows it" from "we checked it".

The 280-source run reported `indexed: 280` because the app's own source
counter reached 280 — a count, not a check. Nothing had verified that any URL
actually yielded a transcript, yet findings were then written as if 280 pieces
of evidence existed.
"""

from __future__ import annotations

from omnicast.analytics.notebook_research.manifest import RunManifest, SourceEntry


def _manifest(statuses: list[str]) -> RunManifest:
    m = RunManifest(channel_id="ch", notebook_key="K")
    m.sources = [SourceEntry(video_id=f"v{i}", upload_status=s)
                 for i, s in enumerate(statuses)]
    return m


def test_ui_indexed_is_not_evidence():
    m = _manifest(["ui_indexed"] * 5)
    assert m.evidence_sources() == []
    summary = m.evidence_summary()
    assert summary["ui_listed"] == 5
    assert summary["evidence_usable"] == 0


def test_only_corroborated_sources_count_as_evidence():
    """`transcript_verified` was documented as "verified but maybe too short"
    and then counted as evidence anyway — the weaker tier meant nothing. Only
    a quote located in the LOCAL transcript reaches `evidence_usable`."""
    m = _manifest(["ui_indexed", "transcript_verified", "evidence_usable",
                   "failed", "pending"])
    assert {s.video_id for s in m.evidence_sources()} == {"v2"}
    summary = m.evidence_summary()
    assert summary["evidence_usable"] == 1
    assert summary["total"] == 5


def test_legacy_indexed_still_counts_as_ui_listed_only():
    """Old manifests wrote `indexed`; they must not be promoted retroactively."""
    m = _manifest(["indexed"] * 3)
    assert m.all_indexed() is True          # UI completeness
    assert m.evidence_sources() == []       # but no evidence


def test_summary_reports_every_status_bucket():
    m = _manifest(["pending", "uploaded", "ui_indexed", "failed",
                   "evidence_usable"])
    by = m.evidence_summary()["by_status"]
    assert by == {"pending": 1, "uploaded": 1, "ui_indexed": 1, "failed": 1,
                  "evidence_usable": 1}


def test_verification_is_wired_into_the_state_machine():
    from pathlib import Path

    import omnicast.analytics.notebook_research.browser_provider as bp

    src = Path(bp.__file__).read_text(encoding="utf-8")
    # the probe exists, is called by the stage runner, and is sample-aware
    assert "def verify_sources(" in src
    assert "worker.verify_sources(" in src
    assert "verify_sample" in src
    # artifacts are scoped per notebook, not shared across runs
    assert 'base_dir) / manifest.notebook_key / "responses"' in src
    # citations are scoped to the answer that produced them
    assert "response_container" in src


def test_the_question_is_not_parsed_as_the_answer():
    """Ten live probes were recorded "no verbatim quote" while the screenshot
    showed a quote sitting in the reply. The captured turn included the
    QUESTION, and the question says "NO_TRANSCRIPT if that source has none" —
    so the failure token matched our own words every time. Any parser that
    searches for a token it also sends has this bug."""
    from omnicast.analytics.notebook_research.browser_provider import (
        NotebookLMWorker,
    )

    prompt = ('Look ONLY at the source titled "Retire to Something". '
              "Answer in exactly this format, nothing else:\n"
              "QUOTE: <8-14 words copied verbatim>\nAT: <mm:ss>\n"
              "STATUS: OK if you read the transcript, NO_TRANSCRIPT if that "
              "source has none.")
    captured = prompt + "\n\nQUOTE: the earnings test withholds one dollar | " \
                        "AT: 03:45 | STATUS: OK"
    body = NotebookLMWorker._strip_prompt_echo(captured, prompt)
    assert "NO_TRANSCRIPT" not in body.upper()
    assert body.startswith("QUOTE: the earnings test")


def test_a_reply_without_an_echo_is_left_alone():
    from omnicast.analytics.notebook_research.browser_provider import (
        NotebookLMWorker,
    )

    reply = "1| QUOTE: something verbatim here | AT: 01:00 | STATUS: OK"
    assert NotebookLMWorker._strip_prompt_echo(reply, "a totally different "
                                               "question about sources") == reply


def test_the_answer_node_is_not_the_whole_exchange():
    """DOM probe 2026-07-28: a .chat-message-pair holds .from-user-container
    (our question) AND .to-user-container (the answer). The table called the
    pair "the current answer", so every saved response artifact opened with
    our own prompt — hook_shape_labelled.md begins with "I am giving you the
    performance labels…", which nobody at NotebookLM ever said."""
    from omnicast.analytics.notebook_research.selectors import SELECTORS

    css = [v for k, v in SELECTORS["response_container"] if k == "css"]
    assert css[0] == ".to-user-message-inner-content"
    assert css.index(".to-user-container") < css.index(".chat-message-pair")


def test_the_reasoning_trace_is_not_the_answer():
    """The trace lives inside the answer node. Captured mid-stream it is a
    page of "Analyzing Transcript Passages" and no answer at all — which the
    parser could not tell apart from a model that answered badly."""
    from omnicast.analytics.notebook_research.browser_provider import (
        NotebookLMWorker,
    )

    collapsed = ("Thoughts\nexpand_more\n"
                 "1 | QUOTE: you can control what you spend | AT: 05:31 | STATUS: OK")
    assert NotebookLMWorker._strip_thoughts(collapsed).startswith("1 | QUOTE:")

    streaming = "\n".join([
        "Thoughts", "expand_more", "neurology", "Initiating Quote Extraction",
        "I am now focused on extracting verbatim quotes.",
        "travel_explore", "Researched web sources for 'x'",
        "neurology", "Analyzing Video Transcript",
        "1 | QUOTE: the real answer arrives here | AT: 03:00 | STATUS: OK",
    ])
    out = NotebookLMWorker._strip_thoughts(streaming)
    assert "Researched web sources" not in out
    assert "1 | QUOTE: the real answer" in out

    plain = "1 | QUOTE: plain | AT: 1:00 | STATUS: OK"
    assert NotebookLMWorker._strip_thoughts(plain) == plain


def test_a_prompt_too_long_to_send_travels_as_several_turns():
    """4.6k characters landed in the box intact and nothing submitted them,
    while ~2.4k always went out. Splitting only between labels and task still
    left a 4.3k first turn — the label list itself has to be chunked."""
    import importlib.util
    import inspect

    from omnicast.analytics.notebook_research.browser_provider import (
        PROMPT_SPLIT,
        NotebookLMWorker,
    )

    src = inspect.getsource(NotebookLMWorker.run_prompt)
    assert "PROMPT_SPLIT in prompt_text" in src   # the worker honours the marker

    spec = importlib.util.spec_from_file_location(
        "s280", "scripts/notebooklm_scale_280.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    prompts = mod.build_prompts([f"Winner title number {i} about retirement"
                                 for i in range(26)],
                                [f"Control title number {i} about retirement"
                                 for i in range(26)])
    for text in prompts.values():
        turns = [t.strip() for t in text.split(PROMPT_SPLIT) if t.strip()]
        assert len(turns) > 2
        assert max(len(t) for t in turns) <= mod.TURN_CHAR_BUDGET + 400


def test_send_has_fallbacks_and_a_retry():
    """The 26-pair cohort prompts (~4.9k chars, 86 lines) all failed with
    "generation never started" while the text sat visibly in the box. Short
    prompts had always gone out on the first rung, so nothing had exercised
    the fallbacks — the ladder was untested code."""
    import inspect

    from omnicast.analytics.notebook_research.browser_provider import (
        NotebookLMWorker,
    )

    src = inspect.getsource(NotebookLMWorker.run_prompt)
    assert "Control+Enter" in src              # multi-line submit
    assert src.count("_attempt_send()") >= 2   # first pass and a retry
    assert "chars, " in src                    # the error names the prompt size


def test_verification_asks_about_many_sources_per_question():
    """One question per source is ~100s of UI wait. At 280 sources that is an
    eight-hour "check", which is a second project, not a gate. Batching is safe
    only because the answer is never trusted on its own — every quote is still
    matched against that video's own caption file."""
    from omnicast.analytics.notebook_research.browser_provider import (
        VERIFY_BATCH,
        NotebookLMWorker,
    )

    assert VERIFY_BATCH > 1
    import inspect
    src = inspect.getsource(NotebookLMWorker.verify_sources)
    assert "for start in range(0, len(targets), batch)" in src
    assert "questions_asked" in src          # the summary reports the real cost


def test_batch_reply_is_parsed_per_slot_and_drifted_shapes_survive():
    from omnicast.analytics.notebook_research.browser_provider import (
        NotebookLMWorker,
    )

    reply = "\n".join([
        "Here you go:",
        "1| QUOTE: the earnings test withholds one dollar | AT: 04:12 | STATUS: OK",
        '**2.** QUOTE: "nobody tells you this part" | AT: 11:03 | STATUS: OK',
        "3) STATUS: NO_TRANSCRIPT",
        "- 5| QUOTE: your break even age is later | AT: 2:40 | STATUS: OK",
    ])
    got = NotebookLMWorker._parse_batch_probe(reply)
    assert got[1] == ("the earnings test withholds one dollar", "04:12", "OK")
    assert got[2][0] == "nobody tells you this part"      # quotes stripped
    assert got[3][2] == "NO_TRANSCRIPT"
    assert got[5][1] == "2:40"                            # single-digit minutes


def test_an_unanswered_slot_is_missing_not_silently_skipped():
    """A skipped slot would leave that source at its previous status, so an
    unanswered question would read exactly like a passed one."""
    from omnicast.analytics.notebook_research.browser_provider import (
        NotebookLMWorker,
    )

    got = NotebookLMWorker._parse_batch_probe(
        "1| QUOTE: something real here now | AT: 01:00 | STATUS: OK")
    assert 4 not in got


def test_probe_addresses_the_source_the_way_the_app_lists_it():
    """First live verification: 3/3 probes returned no quote. The probe asked
    for "the source whose URL ends with <id>" — the source list shows titles,
    and nothing in the notebook maps a URL suffix to a source."""
    from pathlib import Path

    import omnicast.analytics.notebook_research.browser_provider as bp

    src = Path(bp.__file__).read_text(encoding="utf-8")
    assert 'f\'"{title}"\' if title' in src        # titles lead the numbered list
    assert "source with URL ending" in src         # id only as the last resort
    assert "titles: dict[str, str] | None = None" in src
    # and the caller actually supplies them
    cli = (Path(bp.__file__).resolve().parents[4] / "scripts"
           / "notebooklm_scale_280.py").read_text(encoding="utf-8")
    assert "titles=title_by_id" in cli


def test_failed_probe_records_what_the_notebook_actually_said():
    """"probe returned no verbatim quote" cannot tell a source with no
    transcript from a refusal or a drifted reply format — three problems with
    three different fixes, and the first live failures were undiagnosable."""
    from pathlib import Path

    import omnicast.analytics.notebook_research.browser_provider as bp

    src = Path(bp.__file__).read_text(encoding="utf-8")
    assert "no verbatim quote for slot" in src
    assert '" | reply: "' in src or "| reply: " in src


def _vtt(tmp_path, video_id: str, line: str, at: str = "00:01:30.000"):
    p = tmp_path / f"{video_id}.en.vtt"
    end = at.replace("30.000", "38.000")
    p.write_text(f"WEBVTT\n\n{at} --> {end}\n{line}\n", encoding="utf-8")
    return tmp_path


def test_quote_must_be_found_in_the_local_transcript(tmp_path):
    """A well-formed QUOTE + timestamp proves the model can follow a format,
    not that it read anything. We hold the VTTs — so we check."""
    from omnicast.analytics.notebook_research.browser_provider import (
        NotebookLMWorker,
    )

    _vtt(tmp_path, "vid1", "the earnings test withholds one dollar for every two")
    ok, why = NotebookLMWorker._quote_matches_transcript(
        "vid1", "withholds one dollar for every two", "01:30", tmp_path)
    assert ok, why

    bad, why2 = NotebookLMWorker._quote_matches_transcript(
        "vid1", "a sentence that never appears anywhere at all", "01:30", tmp_path)
    assert not bad and "not present" in why2


def test_timestamp_far_from_the_quote_is_rejected(tmp_path):
    from omnicast.analytics.notebook_research.browser_provider import (
        NotebookLMWorker,
    )

    _vtt(tmp_path, "vid2", "the monthly grace test pays full checks that month")
    ok, why = NotebookLMWorker._quote_matches_transcript(
        "vid2", "grace test pays full checks", "45:00", tmp_path)
    assert not ok and "from where the quote actually appears" in why


def test_missing_local_transcript_is_not_evidence(tmp_path):
    from omnicast.analytics.notebook_research.browser_provider import (
        NotebookLMWorker,
    )

    ok, why = NotebookLMWorker._quote_matches_transcript(
        "nope", "anything at all here", "00:10", tmp_path)
    assert not ok and "no local transcript" in why
