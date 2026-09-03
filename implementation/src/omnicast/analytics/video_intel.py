"""Video Intelligence Analyzer — measure competitor production patterns.

WHAT CHANGED (strategic review §4, P0 item 5)

Every analyzer here used to return a constant:

    art_direction   = "cinematic"      # regardless of the video
    words_per_min   = 150              # never counted a word
    hook_type       = "question"       # never read the hook
    music_energy    = "medium"
    hook_strength   = 8

Those constants then flowed into `ProductionBlueprint`, which carried a
`confidence` of up to 0.8 — so a fabricated blueprint was indistinguishable from
a measured one, and downstream production copied "cinematic, 150wpm, open with a
question" into every niche. A placeholder that returns a plausible value is more
dangerous than one that raises: nothing downstream can tell.

Now each analyzer measures what its input actually supports, and says what it
could not measure:

  * words_per_min  — real word count over real duration
  * hook_type      — classified from the first 30 SECONDS of speech, with the
                     evidence that triggered the classification attached
  * structure      — beats detected from pauses and discourse markers in the
                     transcript's segment timings
  * visual style   — tallied from the frame descriptions handed in; with no
                     frames it reports "unknown", never "cinematic"

Anything unmeasurable comes back as "unknown" plus a note in `notes`, and
`build_blueprint` discounts confidence by how much of the blueprint was actually
measured rather than assumed. Aggregation also votes by majority instead of
taking `analyses[0]`, which silently made the first sample the answer.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from statistics import mean, median

import structlog

from omnicast.analytics.crawler import AnalyticsCrawler
from omnicast.analytics.models import ProductionBlueprint
from omnicast.shared.title_patterns import classify_title

logger = structlog.get_logger()

UNKNOWN = "unknown"
# House default. Named, so that a reader can grep for it and find this comment
# instead of finding a bare 0.5 in the middle of a constructor and assuming it
# came from somewhere. It never did.
DEFAULT_CROSSFADE_SECONDS = 0.5

# A gap this long between cues reads as a deliberate beat break rather than a
# breath. Deliberately conservative: over-segmenting invents structure.
BEAT_PAUSE_SECONDS = 2.0
# Minimum spacing between detected beats — stops micro-pauses inflating the count.
MIN_BEAT_SECONDS = 20.0
# Openers that mark a new section when they start a cue.
_DISCOURSE_MARKERS = (
    "first", "second", "third", "next", "finally", "but here", "now",
    "so here", "which brings", "let's talk", "number ", "step ",
    "meanwhile", "however", "and that's why", "the second", "the third",
)
_CTA_PATTERN = re.compile(
    r"\b(subscribe|hit the bell|like this video|link (in|below)|comment below|"
    r"check the description)\b", re.I)
_NUMBER_PATTERN = re.compile(
    r"(\d[\d,.]*\s*(%|percent|million|billion|thousand|k\b)|[$€£]\s?\d)", re.I)
_PAIN_WORDS = ("mistake", "wrong", "fail", "lose", "losing", "broke", "struggle",
               "problem", "worst", "trap", "stuck", "never work")
_PROMISE_WORDS = ("in this video", "i'll show", "we'll cover", "by the end",
                  "you'll learn", "here's how", "this is how")
_STORY_WORDS = ("in 19", "in 20", "once upon", "back in", "one day", "years ago",
                "it started", "there was a")

_ART_KEYWORDS = {
    "cinematic": ("cinematic", "film grain", "anamorphic", "shallow depth", "moody lighting"),
    "photorealistic": ("photo", "photoreal", "realistic", "documentary footage", "stock footage"),
    "anime": ("anime", "manga", "cel shaded", "illustrated character"),
    "minimal": ("minimal", "flat design", "white background", "clean layout", "simple"),
    "dark_gothic": ("gothic", "dark fantasy", "occult", "candlelit", "ominous"),
    "motion_graphics": ("motion graphic", "infographic", "chart", "diagram", "animated text"),
}
_TEXT_KEYWORDS = ("text overlay", "caption", "title card", "subtitle", "on-screen text",
                  "big text", "headline")
_FACE_KEYWORDS = ("talking head", "presenter", "host", "person speaking", "face to camera",
                  "man talking", "woman talking")
_WARM_COLORS = ("warm", "orange", "gold", "amber", "red", "sunset")
_COLD_COLORS = ("cold", "blue", "teal", "cyan", "icy", "navy")
_HEX_PATTERN = re.compile(r"#[0-9a-fA-F]{6}")


def _as_text(transcript) -> str:
    """Accept a plain string or anything with `.text` (analytics.transcript)."""
    return getattr(transcript, "text", transcript) or ""


def _segments(transcript):
    return tuple(getattr(transcript, "segments", ()) or ())


def _window(transcript, start: float, end: float) -> str:
    """First-N-SECONDS text when timings exist; else the whole string."""
    windowed = getattr(transcript, "window", None)
    if callable(windowed):
        text = windowed(start, end)
        if text:
            return text
        return ""
    return _as_text(transcript)


class VideoIntelligenceAnalyzer:
    """Analyze competitor video production patterns → ProductionBlueprint."""

    def __init__(self, crawler: AnalyticsCrawler | None = None) -> None:
        # Optional since P0.1 group 4. Every analyzer here is a pure function of
        # the transcript/frames handed in — the crawler was never touched — and
        # requiring one meant the only production pipeline that HAS transcripts
        # (competitor_intel) could not call this module without building a
        # dependency it has no use for. That friction is part of why the module
        # had no production caller at all.
        self.crawler = crawler

    # ── Structure ────────────────────────────────────────────────────────────

    async def analyze_structure(self, transcript, duration_seconds: float) -> dict:
        """Detect beats from real pauses and discourse markers.

        With segment timings this is a measurement. With a bare string it is
        not — and the result says so rather than passing duration/90 off as
        analysis."""
        segments = _segments(transcript)
        duration = float(duration_seconds or 0.0)
        notes: list[str] = []

        if not segments:
            notes.append("no segment timings: beats estimated from duration only")
            segment_count = max(3, int(duration / 90)) if duration else 0
            return {
                "intro_length": round(duration * 0.05, 1) if duration else 0.0,
                "segment_count": segment_count,
                "avg_segment_duration": (round(duration / segment_count, 1)
                                         if segment_count else 0.0),
                "outro_length": round(duration * 0.04, 1) if duration else 0.0,
                "transition_types": [],
                "measured": False,
                "notes": notes,
            }

        boundaries: list[float] = [segments[0].start]
        previous_end = segments[0].start + getattr(segments[0], "duration", 0.0)
        for seg in segments[1:]:
            text = (seg.text or "").strip().lower()
            gap = seg.start - previous_end
            marker = any(text.startswith(m) for m in _DISCOURSE_MARKERS)
            if (gap >= BEAT_PAUSE_SECONDS or marker) and \
                    seg.start - boundaries[-1] >= MIN_BEAT_SECONDS:
                boundaries.append(seg.start)
            previous_end = seg.start + getattr(seg, "duration", 0.0)

        covered = max(previous_end, 0.0)
        span = max(covered, duration)
        if len(boundaries) > 1:
            intro_length = round(boundaries[1] - boundaries[0], 1)
            outro_length = round(max(span - boundaries[-1], 0.0), 1)
        else:
            intro_length = round(span * 0.05, 1)
            outro_length = 0.0
            notes.append("no internal beat boundary found — single-segment video?")
        if duration and covered < duration * 0.8:
            notes.append(
                f"transcript covers {covered:.0f}s of a {duration:.0f}s video — "
                "late-video structure is not represented"
            )
        notes.append("transition types are not derivable from a transcript")

        segment_count = len(boundaries)
        return {
            "intro_length": intro_length,
            "segment_count": segment_count,
            "avg_segment_duration": round(span / segment_count, 1) if segment_count else 0.0,
            "outro_length": outro_length,
            "beat_starts": [round(b, 1) for b in boundaries],
            "transition_types": [],
            "measured": True,
            "notes": notes,
        }

    # ── Visual ───────────────────────────────────────────────────────────────

    async def analyze_forensics(self, video_path, *, transcript=None) -> dict:
        """A `visual` block measured from the FILE, not from descriptions of it.

        P1 §5. `analyze_visual_style` reads frame descriptions somebody else
        produced; if nobody did, every visual field is `unknown`. This reads the
        frames. It fills only what signal processing can honestly support —
        scene pacing, motion mix, colour mood, transition grammar — and leaves
        `art_direction` and `b_roll_ratio` alone, because a look and a presenter
        both need a vision model and guessing them here would put the exact
        placeholders back that this module was rewritten to remove."""
        from omnicast.analytics import av_forensics as avf

        report = avf.analyse_video(video_path, transcript=transcript)
        measured = report.field_status.get("shots") == avf.MEASURED

        block = {
            "measured": measured,
            "source": "av_forensics",
            "art_direction": UNKNOWN,   # needs a vision model
            "b_roll_ratio": 0.0,        # needs face detection to be meaningful
            "text_overlay_freq": 0.0,   # the proxy is NOT this number
            "color_mood": report.colour_mood,
            "scene_count": report.shot_count,
            "median_shot_seconds": report.median_shot_seconds,
            "cuts_per_minute": report.cuts_per_minute,
            "motion_mix": report.motion_mix,
            "transition_mix": report.transition_mix,
            "text_overlay_proxy": report.text_overlay_proxy,
            "silence_ratio": report.silence_ratio,
            "forensics": report.as_dict(),
            "notes": list(report.notes),
        }
        if report.field_status.get("colour") != avf.MEASURED:
            block["color_mood"] = UNKNOWN
        return block

    async def analyze_visual_style(self, frame_descriptions: list[str]) -> dict:
        """Tally visual traits across the frame descriptions supplied.

        With no frames this returns 'unknown'. The old code returned
        'cinematic' plus a two-colour palette it had never seen."""
        frames = [f for f in (frame_descriptions or []) if f and f.strip()]
        if not frames:
            return {
                "art_direction": UNKNOWN,
                "dominant_colors": [],
                "text_overlay_freq": 0.0,
                "talking_head_ratio": 0.0,
                "b_roll_ratio": 0.0,
                "color_mood": UNKNOWN,
                "frames_analysed": 0,
                "measured": False,
                "notes": ["no frame descriptions supplied — nothing was analysed"],
            }

        lowered = [f.lower() for f in frames]
        votes: Counter[str] = Counter()
        for style, words in _ART_KEYWORDS.items():
            hits = sum(1 for f in lowered if any(w in f for w in words))
            if hits:
                votes[style] = hits
        art_direction = votes.most_common(1)[0][0] if votes else UNKNOWN

        total = len(lowered)
        text_frames = sum(1 for f in lowered if any(w in f for w in _TEXT_KEYWORDS))
        face_frames = sum(1 for f in lowered if any(w in f for w in _FACE_KEYWORDS))

        colors: list[str] = []
        for f in frames:
            colors.extend(_HEX_PATTERN.findall(f))
        warm = sum(1 for f in lowered if any(w in f for w in _WARM_COLORS))
        cold = sum(1 for f in lowered if any(w in f for w in _COLD_COLORS))
        if warm or cold:
            color_mood = "warm" if warm > cold else "cold" if cold > warm else "neutral"
        else:
            color_mood = UNKNOWN

        notes: list[str] = []
        if art_direction == UNKNOWN:
            notes.append("no recognisable art-direction cue in the frame descriptions")
        if total < 5:
            notes.append(f"only {total} frame(s) described — ratios are coarse")

        return {
            "art_direction": art_direction,
            "dominant_colors": list(dict.fromkeys(colors))[:4],
            "text_overlay_freq": round(text_frames / total, 2),
            "talking_head_ratio": round(face_frames / total, 2),
            "b_roll_ratio": round(1.0 - face_frames / total, 2),
            "color_mood": color_mood,
            "frames_analysed": total,
            "measured": True,
            "notes": notes,
        }

    # ── Audio / pacing ───────────────────────────────────────────────────────

    async def analyze_audio_pattern(self, audio_features: dict, transcript=None,
                                    duration_seconds: float = 0.0) -> dict:
        """Real words-per-minute; music energy only when features are supplied."""
        features = audio_features or {}
        notes: list[str] = []

        text = _as_text(transcript)
        segments = _segments(transcript)
        spoken_seconds = float(duration_seconds or 0.0)
        if segments:
            spoken_seconds = max(
                spoken_seconds,
                max(s.start + getattr(s, "duration", 0.0) for s in segments),
            )
        words = len(text.split())
        if words and spoken_seconds > 0:
            wpm = round(words / (spoken_seconds / 60.0))
        else:
            wpm = 0
            notes.append("words-per-minute not measurable: needs transcript text + duration")

        if wpm == 0:
            pacing = UNKNOWN
        elif wpm < 130:
            pacing = "slow"
        elif wpm <= 165:
            pacing = "moderate"
        else:
            pacing = "fast"

        energy = features.get("music_energy")
        if not energy:
            rms = features.get("rms_mean")
            tempo = features.get("tempo")
            if rms is not None:
                energy = "high" if rms >= 0.15 else "medium" if rms >= 0.06 else "low"
            elif tempo is not None:
                energy = "high" if tempo >= 120 else "medium" if tempo >= 90 else "low"
            else:
                energy = UNKNOWN
                notes.append("no audio features supplied — music energy not measured")

        return {
            "music_energy": energy,
            "words_per_min": wpm,
            "voice_pacing": pacing,
            "word_count": words,
            "measured": bool(wpm),
            "notes": notes,
        }

    # ── Hook ─────────────────────────────────────────────────────────────────

    async def analyze_hook(self, first_30s_transcript) -> dict:
        """Classify the opening from what is actually said in it.

        Accepts a plain string or a Transcript — in which case the true first 30
        SECONDS are read, not the first N characters, which drifts badly between
        a fast talker and a slow one."""
        text = _window(first_30s_transcript, 0.0, 30.0).strip()
        if not text:
            return {
                "hook_type": "cold_open",
                "hook_strength": 0,
                "cta_present": False,
                "evidence": [],
                "words_in_hook": 0,
                "measured": bool(_segments(first_30s_transcript)),
                "notes": ["no speech in the first 30s (or no transcript supplied)"],
            }

        lowered = text.lower()
        evidence: list[str] = []

        has_question = "?" in text or lowered.startswith(
            ("what ", "why ", "how ", "did you", "have you"))
        number_match = _NUMBER_PATTERN.search(text)
        has_pain = any(w in lowered for w in _PAIN_WORDS)
        has_promise = any(w in lowered for w in _PROMISE_WORDS)
        has_story = any(w in lowered for w in _STORY_WORDS)
        second_person = bool(re.search(r"\byou(r|'re)?\b", lowered))

        if number_match:
            evidence.append(f"number/stat: {number_match.group(0).strip()}")
        if has_question:
            evidence.append("direct question")
        if has_pain:
            evidence.append("pain framing")
        if has_promise:
            evidence.append("explicit promise")
        if has_story:
            evidence.append("story opener")
        if second_person:
            evidence.append("second-person address")

        # Most specific device wins.
        if number_match and not has_promise:
            hook_type = "shock_stat"
        elif has_question:
            hook_type = "question"
        elif has_story:
            hook_type = "story"
        elif has_pain:
            hook_type = "pain"
        elif has_promise:
            hook_type = "preview"
        else:
            hook_type = "cold_open"

        # Derived, not the constant 8: distinct devices present, plus a bonus
        # for getting to the point quickly.
        strength = min(10, 2 * len(evidence) + (2 if len(text.split()) <= 60 else 0))

        return {
            "hook_type": hook_type,
            "hook_strength": strength,
            "cta_present": bool(_CTA_PATTERN.search(text)),
            "evidence": evidence,
            "words_in_hook": len(text.split()),
            "measured": True,
            "notes": [],
        }

    # ── Blueprint ────────────────────────────────────────────────────────────

    @staticmethod
    def _vote(values: list[str], default: str = UNKNOWN) -> str:
        """Majority vote, ignoring unknowns.

        Replaces `analyses[0].get(...)`, which quietly made whichever sample
        happened to be first into the consensus."""
        usable = [v for v in values if v and v != UNKNOWN]
        if not usable:
            return default
        return Counter(usable).most_common(1)[0][0]

    async def build_blueprint(self, niche: str, analyses: list[dict]) -> ProductionBlueprint:
        """Build ProductionBlueprint from aggregated analyses.

        Confidence is now sample size DISCOUNTED by measurement coverage: a
        blueprint assembled mostly from unmeasured defaults must not present
        itself as strongly as one built from real analysis."""
        if not analyses:
            return ProductionBlueprint(
                niche=niche,
                video_format=UNKNOWN,
                art_style=UNKNOWN,
                pacing_scene_duration=(2.0, 5.0),
                crossfade_seconds=0.3,
                music_energy=UNKNOWN,
                text_overlay_freq=0.0,
                b_roll_ratio=0.0,
                hook_type=UNKNOWN,
                intro_duration=0.0,
                target_duration_minutes=0,
                color_mood=UNKNOWN,
                confidence=0.0,
                sample_size=0,
                generated_at=datetime.now(timezone.utc),
            )

        structure = [a.get("structure", {}) for a in analyses if a.get("structure")]
        visual = [a.get("visual", {}) for a in analyses if a.get("visual")]
        audio = [a.get("audio", {}) for a in analyses if a.get("audio")]
        hook = [a.get("hook", {}) for a in analyses if a.get("hook")]

        blocks = structure + visual + audio + hook
        measured_blocks = sum(1 for block in blocks if block.get("measured"))
        coverage = measured_blocks / len(blocks) if blocks else 0.0

        assumed: list[str] = []
        notes: list[str] = []

        avg_intro = mean([s.get("intro_length", 20) for s in structure]) if structure else 20.0
        avg_segments = mean([s.get("segment_count", 5) for s in structure]) if structure else 5
        if not structure:
            assumed.extend(["intro_duration", "pacing_scene_duration"])
            notes.append("no structure analysis: intro and pacing are defaults")

        if visual:
            avg_broll = mean([v.get("b_roll_ratio", v.get("broll_ratio", 0.3)) for v in visual])
            avg_text = mean([v.get("text_overlay_freq", 0.3) for v in visual])
            art_direction = self._vote([v.get("art_direction", "") for v in visual])
            color_mood = self._vote([v.get("color_mood", "") for v in visual], default="neutral")
        else:
            avg_broll, avg_text = 0.0, 0.0
            art_direction, color_mood = UNKNOWN, UNKNOWN

        music_energy = self._vote([a.get("music_energy", "") for a in audio])
        hook_type = self._vote([h.get("hook_type", "") for h in hook])

        sample_size = len(analyses)
        if sample_size >= 10:
            base_confidence = 0.8
        elif sample_size >= 5:
            base_confidence = 0.6
        elif sample_size >= 3:
            base_confidence = 0.4
        else:
            base_confidence = 0.2
        # Unmeasured inputs cannot buy confidence. Floored at 25% of base so a
        # defaults-only blueprint reads as weak rather than as nothing at all.
        confidence = round(base_confidence * max(coverage, 0.25), 3)

        # ── the three values that were still invented ────────────────────────
        #
        # P0.1 group 4. Everything above this point was migrated from constant
        # to measurement in the previous pass; these three were not, and a
        # blueprint that is 80% measured and 20% invented is read as 100%
        # measured by anything downstream unless it says otherwise.

        # 1. FORMAT. "documentary" was hardcoded for every niche on earth. It is
        #    derivable — weakly — from the shape of the sampled titles, so
        #    derive it and fall back to unknown rather than to a genre.
        video_format = self._derive_format(analyses, hook_type)
        if video_format == UNKNOWN:
            notes.append("video_format: no title shapes to derive it from")

        # 2. RUNTIME. `segment_count * 2` was a guess dressed as arithmetic —
        #    it produced minutes from a count of beats. The sampled videos have
        #    real durations; use them.
        durations = [d for d in (float(a.get("duration_minutes", 0) or 0)
                                 for a in analyses) if d > 0]
        if durations:
            target_minutes = int(round(median(durations)))
        else:
            target_minutes = 0
            assumed.append("target_duration_minutes")
            notes.append(
                "target_duration_minutes: no video duration was supplied, so no "
                "runtime could be measured (0 = unknown, not 'make it 0 minutes')"
            )

        # 3. CROSSFADE. Not derivable from a transcript at all — it needs
        #    frame-level transition detection, which is the P1 audiovisual
        #    forensic analyzer. It stays a house default and is labelled as one.
        assumed.append("crossfade_seconds")
        notes.append(
            f"crossfade_seconds: house default {DEFAULT_CROSSFADE_SECONDS}s — "
            "transitions are not observable in a transcript (needs the "
            "audiovisual forensic analyzer)"
        )
        if not visual:
            assumed.extend(["art_style", "color_mood", "b_roll_ratio",
                            "text_overlay_freq"])
            notes.append("no frame descriptions: every visual field is unmeasured")
        else:
            # A forensics block measures colour but deliberately does not
            # measure art style, b-roll ratio or overlay frequency. Marking the
            # whole visual block as measured because ONE of its fields is would
            # relaunch the confusion this list exists to prevent.
            forensic_only = all(v.get("source") == "av_forensics" for v in visual)
            if forensic_only:
                assumed.extend(["art_style", "b_roll_ratio", "text_overlay_freq"])
                notes.append(
                    "visual measured by signal processing: colour mood and shot "
                    "rhythm are real; art style, b-roll ratio and overlay "
                    "frequency still need a vision model")
                if any(v.get("color_mood") not in (None, "", UNKNOWN) for v in visual):
                    notes.append("color_mood measured from sampled frames")

        # Pacing, best source first.
        #
        # 1. Real SHOT lengths from forensics. `pacing_scene_duration` is about
        #    how long a picture stays on screen, and a shot boundary is exactly
        #    that — the transcript can only ever approximate it from where the
        #    speaker pauses.
        shot_lengths = [v.get("median_shot_seconds") for v in visual
                        if v.get("median_shot_seconds")]
        if shot_lengths:
            centre = mean(shot_lengths)
            pacing = (round(centre * 0.5, 1), round(centre * 1.5, 1))
            # `.get(k, 0)` does NOT apply when the key exists with value None,
            # which a persisted or hand-built analyses list can carry.
            shots_seen = sum(int(v.get("scene_count") or 0) for v in visual)
            notes.append(
                f"pacing measured from {shots_seen} detected shot(s), not "
                "inferred from speech")
            return ProductionBlueprint(
                niche=niche,
                video_format=video_format,
                art_style=art_direction,
                pacing_scene_duration=pacing,
                crossfade_seconds=DEFAULT_CROSSFADE_SECONDS,
                music_energy=music_energy,
                text_overlay_freq=avg_text,
                b_roll_ratio=avg_broll,
                hook_type=hook_type,
                intro_duration=avg_intro,
                target_duration_minutes=target_minutes,
                color_mood=color_mood,
                confidence=confidence,
                sample_size=sample_size,
                generated_at=datetime.now(timezone.utc),
                assumed_fields=sorted(set(assumed)),
                notes=notes,
            )

        # 2. MEASURED transcript segment length. The original formula derived
        #    scene duration from intro length, which are different things.
        measured_segment = [s.get("avg_segment_duration", 0.0) for s in structure
                            if s.get("measured") and s.get("avg_segment_duration")]
        if measured_segment:
            centre = mean(measured_segment)
            pacing = (round(centre * 0.5, 1), round(centre * 1.5, 1))
        else:
            pacing = (round(avg_intro / 2, 1), round(avg_intro * 2, 1))
            if "pacing_scene_duration" not in assumed:
                assumed.append("pacing_scene_duration")

        return ProductionBlueprint(
            niche=niche,
            video_format=video_format,
            art_style=art_direction,
            pacing_scene_duration=pacing,
            crossfade_seconds=DEFAULT_CROSSFADE_SECONDS,
            music_energy=music_energy,
            text_overlay_freq=avg_text,
            b_roll_ratio=avg_broll,
            hook_type=hook_type,
            intro_duration=avg_intro,
            target_duration_minutes=target_minutes,
            color_mood=color_mood,
            confidence=confidence,
            sample_size=sample_size,
            generated_at=datetime.now(timezone.utc),
            assumed_fields=sorted(set(assumed)),
            notes=notes,
        )

    @staticmethod
    def _derive_format(analyses: list[dict], hook_type: str) -> str:
        """Infer the video format from the shape of the sampled titles.

        Weak evidence, honestly labelled, beats a hardcoded genre. The mapping
        uses the same deterministic tags as the rest of the system so a reader
        can check it: numbers imply a list, how-to implies an explainer, a story
        hook implies a story."""
        tags: Counter[str] = Counter()
        for analysis in analyses:
            patterns = analysis.get("title_patterns")
            if not patterns:
                title = analysis.get("title") or ""
                patterns = classify_title(title) if title.strip() else []
            tags.update(p for p in patterns if p)

        if not tags:
            return UNKNOWN
        total = sum(tags.values())
        if tags.get("number", 0) / total >= 0.4:
            return "listicle"
        if tags.get("how_to", 0) / total >= 0.3:
            return "explainer"
        if hook_type == "story":
            return "story"
        if tags.get("question", 0) / total >= 0.3:
            return "explainer"
        return UNKNOWN

    def aggregate_patterns(self, blueprints: list[ProductionBlueprint]) -> ProductionBlueprint:
        """Aggregate multiple blueprints into one consensus blueprint."""
        if not blueprints:
            raise ValueError("Cannot aggregate empty blueprint list")

        if len(blueprints) == 1:
            return blueprints[0]

        total_sample_size = sum(bp.sample_size for bp in blueprints)
        avg_intro = mean([bp.intro_duration for bp in blueprints])
        avg_broll = mean([bp.b_roll_ratio for bp in blueprints])
        avg_text = mean([bp.text_overlay_freq for bp in blueprints])
        avg_crossfade = mean([bp.crossfade_seconds for bp in blueprints])

        # Majority vote across blueprints — not blueprints[0].
        niche = blueprints[0].niche
        video_format = self._vote([bp.video_format for bp in blueprints], default="explainer")
        art_style = self._vote([bp.art_style for bp in blueprints])
        music_energy = self._vote([bp.music_energy for bp in blueprints])
        hook_type = self._vote([bp.hook_type for bp in blueprints])
        color_mood = self._vote([bp.color_mood for bp in blueprints], default="neutral")

        min_pacing = min(bp.pacing_scene_duration[0] for bp in blueprints)
        max_pacing = max(bp.pacing_scene_duration[1] for bp in blueprints)

        avg_confidence = mean([bp.confidence for bp in blueprints])

        return ProductionBlueprint(
            niche=niche,
            video_format=video_format,
            art_style=art_style,
            pacing_scene_duration=(min_pacing, max_pacing),
            crossfade_seconds=avg_crossfade,
            music_energy=music_energy,
            text_overlay_freq=avg_text,
            b_roll_ratio=avg_broll,
            hook_type=hook_type,
            intro_duration=avg_intro,
            target_duration_minutes=int(mean([bp.target_duration_minutes for bp in blueprints])),
            color_mood=color_mood,
            confidence=min(1.0, avg_confidence * 1.2),  # agreement across blueprints
            sample_size=total_sample_size,
            generated_at=datetime.now(timezone.utc),
        )
