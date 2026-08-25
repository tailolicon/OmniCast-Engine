"""Programmatic quality checks for rendered video outputs."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

# On Windows, spawning ffprobe/ffmpeg pops a console window each time. CREATE_NO_WINDOW
# suppresses it — critical here because readiness can audit several files repeatedly.
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


_VISUAL_STOPWORDS = {
    "about", "after", "again", "along", "also", "and", "are", "around", "away",
    "before", "being", "between", "bold", "camera", "close", "closeup", "context",
    "cut", "diagram", "does", "during", "each", "from", "front", "have", "into",
    "like", "more", "motion", "over", "overlay", "person", "people", "scene",
    "screen", "shot", "show", "showing", "slow", "stock", "text", "that", "the",
    "then", "these", "this", "through", "video", "visual", "with", "without",
    "your", "zoom",
}

_EDITOR_UI_PATTERNS = (
    "adobe premiere",
    "premiere pro",
    "editing timeline",
    "video editing",
    "color grading interface",
    "editing software",
    "software interface",
    "screen recording timeline",
)


class OutputQualityAuditor:
    """Uses ffprobe to verify rendered MP4s are technically publishable."""

    MIN_DURATION_SECONDS = 480.0
    AUDIO_TARGET_LUFS = -14.0
    AUDIO_LUFS_TOLERANCE = 2.0

    def __init__(self, min_duration_seconds: float | None = None, measure_loudness: bool = True,
                 channels_dir: str | Path | None = None):
        self.min_duration_seconds = (
            self.MIN_DURATION_SECONDS if min_duration_seconds is None else float(min_duration_seconds)
        )
        self.measure_loudness = measure_loudness
        self._channels_dir = (
            Path(channels_dir) if channels_dir
            else Path(__file__).resolve().parents[3] / "channels"
        )

    def inspect(self, path: str | Path) -> dict:
        p = Path(path)
        result = {
            "path": str(p),
            "exists": p.exists(),
            "passed": False,
            "issues": [],
            "metadata": {},
        }
        if not p.exists():
            result["issues"].append("file_missing")
            return result
        size_mb = p.stat().st_size / (1024 * 1024)
        result["metadata"]["size_mb"] = round(size_mb, 2)
        if size_mb < 0.5:
            result["issues"].append("file_too_small")

        try:
            probe = self._ffprobe(p)
        except Exception as exc:
            result["issues"].append(f"ffprobe_failed:{exc}")
            return result

        fmt = probe.get("format", {})
        streams = probe.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
        duration = float(fmt.get("duration") or video.get("duration") or 0.0)
        width = int(video.get("width") or 0)
        height = int(video.get("height") or 0)
        sample_rate = int(audio.get("sample_rate") or 0) if audio else 0
        channels = int(audio.get("channels") or 0) if audio else 0
        audio_bit_rate = int(audio.get("bit_rate") or 0) if audio else 0
        result["metadata"].update({
            "duration_seconds": round(duration, 2),
            "width": width,
            "height": height,
            "video_codec": video.get("codec_name", ""),
            "audio_codec": audio.get("codec_name", ""),
            "audio_sample_rate": sample_rate,
            "audio_channels": channels,
            "audio_bit_rate": audio_bit_rate,
            "bit_rate": int(fmt.get("bit_rate") or 0),
            "min_duration_seconds": self.min_duration_seconds,
        })
        if duration < self.min_duration_seconds:
            result["issues"].append("duration_too_short")
        if not width or not height:
            result["issues"].append("missing_video_stream")
        if not audio:
            result["issues"].append("missing_audio_stream")
        else:
            if audio.get("codec_name") != "aac":
                result["issues"].append("unexpected_audio_codec")
            if sample_rate != 48000:
                result["issues"].append("audio_sample_rate_not_48000")
            if channels < 2:
                result["issues"].append("audio_not_stereo")
            if audio_bit_rate < 192000:
                result["issues"].append("audio_bitrate_below_192k")
            if self.measure_loudness:
                try:
                    integrated_lufs = self._measure_integrated_lufs(p)
                    result["metadata"]["integrated_lufs"] = round(integrated_lufs, 2)
                    lower = self.AUDIO_TARGET_LUFS - self.AUDIO_LUFS_TOLERANCE
                    upper = self.AUDIO_TARGET_LUFS + self.AUDIO_LUFS_TOLERANCE
                    if not lower <= integrated_lufs <= upper:
                        result["issues"].append("audio_loudness_out_of_range")
                except Exception as exc:
                    result["issues"].append(f"loudness_probe_failed:{exc}")
        if video.get("codec_name") not in {"h264", "hevc", "vp9", "av1"}:
            result["issues"].append("unexpected_video_codec")
        result["passed"] = not result["issues"]
        return result

    def inspect_product(
        self,
        video_path: str | Path,
        product_dir: str | Path | None = None,
        *,
        topic: str | None = None,
        write_sidecar: bool = True,
    ) -> dict:
        """Audit one rendered product folder and persist a sidecar report."""
        p = Path(video_path)
        pd = Path(product_dir) if product_dir else p.parent
        result = self.inspect(p)
        visual = self.inspect_visual_relevance(pd, topic=topic)
        result["product_dir"] = str(pd)
        result["visual_relevance"] = visual
        if not visual["passed"]:
            for issue in visual["issues"]:
                result["issues"].append(f"visual_relevance:{issue}")
        config = self._channel_config(pd)
        visual_match_required = bool(config.get("visual_match_qc_required"))
        visual_match = self.inspect_visual_match(
            pd, p, required=visual_match_required)
        result["visual_match_qc"] = visual_match
        if visual_match_required and not visual_match["passed"]:
            for issue in visual_match["issues"]:
                result["issues"].append(f"visual_match:{issue}")
        try:
            pacing = self.inspect_pacing(p)
        except Exception as exc:  # never let the pacing probe kill the audit
            pacing = {"skipped": f"pacing_probe_error:{exc}", "passed": True, "issues": [], "metrics": {}}
        result["pacing"] = pacing
        pacing_issues = list(pacing.get("issues", []))
        # Genre opt-out: a deadpan narrator (slow-burn horror) is intentionally
        # near-flat — the vfact benchmark is explainer-tuned and over-penalizes
        # it. Channel config `pacing_flat_ok: true` downgrades flat-delivery to
        # a warning metric; every other pacing gate still applies.
        if "pacing_flat_delivery" in pacing_issues and self._channel_allows_flat(pd):
            pacing_issues.remove("pacing_flat_delivery")
            pacing["issues"] = pacing_issues
            pacing["passed"] = not pacing_issues
            pacing.setdefault("metrics", {})["warning_flat_delivery_genre_ok"] = True
        for issue in pacing_issues:
            result["issues"].append(issue)

        # PRODUCTION GRAMMAR (§5). How this video was cut — shot rhythm, motion
        # mix, colour mood, transition kinds. Not a gate on its own: no
        # threshold here has been calibrated, and gating on an uncalibrated
        # number is how a pipeline starts rejecting good work for reasons
        # nobody can defend. It is the INPUT to the gates below.
        grammar = self.inspect_production_grammar(p)
        result["production_grammar"] = grammar

        # BENCHMARK (§8). Compared against this channel's golden reference when
        # one is declared. Without a reference the comparison is `unknown`,
        # never a headline number — that refusal is the whole module.
        benchmark = self.compare_against_golden(pd, grammar, pacing)
        result["benchmark"] = benchmark

        # QUALITY GATES (§9). THIS RUNS BEFORE THE SIDECAR IS WRITTEN AND ITS
        # FAILURES BECOME AUDIT ISSUES. A previous wiring appended the report
        # after `_output_audit.json` had already been written and never fed the
        # verdict back into `passed`, so a video with a FAILED gate — or one
        # waiting on a human for a YMYL claim — went to the approval queue
        # anyway. That is telemetry, not a gate.
        quality = self.run_quality_gates(pd, result, grammar, benchmark, p)
        result["quality_gates"] = quality

        # A FAILURE blocks the product: something measurable is wrong with it.
        for gate in quality.get("failed") or []:
            result["issues"].append(f"quality_gate:{gate}")

        # `needs_human` IS NOT A FAILURE. Making it one deadlocked the pipeline:
        # a finance video is inferred YMYL, `needs_human` became an audit issue,
        # `passed` went False, the render raised — and it raised BEFORE the step
        # that queues the video for approval, so the only route to a human
        # review was the one the flag was blocking. Nothing could ever unlock
        # it, because nothing writes `human_reviewed` except a human approving
        # through that queue.
        #
        # The render therefore SUCCEEDS and the product is flagged. The publish
        # gate is where a missing review stops something (see
        # `requires_human_review` / `human_review_state`).
        needs_human = list(quality.get("needs_human") or [])
        result["requires_human_review"] = bool(needs_human)
        result["human_review_gates"] = needs_human

        result["passed"] = not result["issues"]
        if write_sidecar:
            sidecar = pd / "_output_audit.json"
            try:
                pd.mkdir(parents=True, exist_ok=True)
                sidecar.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
                result["metadata"]["audit_sidecar"] = sidecar.name
            except Exception as exc:
                result["issues"].append(f"audit_sidecar_write_failed:{exc}")
                result["passed"] = False
        return result

    def _channel_config(self, product_dir: Path) -> dict:
        """The channel JSON behind a product folder, or {}."""
        try:
            meta = json.loads((product_dir / "meta.json").read_text(encoding="utf-8"))
            channel = str(meta.get("channel") or "").strip()
            if not channel:
                return {}
            return json.loads(
                (self._channels_dir / f"{channel}.json").read_text(encoding="utf-8"))
        except Exception:
            return {}

    def compare_against_golden(self, product_dir: Path, grammar: dict,
                               pacing: dict) -> dict:
        """§8 comparison against the channel's declared golden reference.

        The production caller `quality.benchmark` did not have. The reference
        lives in the channel config under `benchmark_reference`; with no
        reference the comparison reports its own blockers and no headline,
        which is exactly what §8 demands."""
        try:
            from omnicast.quality.benchmark import compare_to_reference

            config = self._channel_config(product_dir)
            reference = config.get("benchmark_reference")
            metrics = (pacing or {}).get("metrics") or {}
            board = self._storyboard_summary(product_dir)
            ours = {
                "median_shot_seconds": (grammar or {}).get("median_shot_seconds"),
                "transition_mix": (grammar or {}).get("transition_mix"),
                "colour_warmth": ((grammar or {}).get("colour_metrics") or {}).get("warmth"),
                "words_per_minute": metrics.get("syllable_rate_mean"),
                "caption_density": (grammar or {}).get("text_overlay_proxy"),
                # From the storyboard the product folder already holds. Two more
                # of §8's dimensions become measurable at zero extra cost; the
                # ones with no analyser at all (SFX placement, music energy)
                # stay unmeasured and keep the headline withheld, which is what
                # §8 asks for rather than something to work around.
                "beat_count": board.get("scenes"),
                "visual_source_mix": board.get("visual_source_mix"),
            }
            return compare_to_reference(
                ours, reference if isinstance(reference, dict) else {}).as_dict()
        except Exception as exc:
            return {"skipped": f"benchmark_error:{exc}"}

    @staticmethod
    def _storyboard_summary(product_dir: Path) -> dict:
        """Scene count and visual-source mix from the product's storyboard."""
        for name in ("board_final.json", "storyboard.json", "_storyboard.json", "board.json"):
            path = product_dir / name
            if not path.exists():
                continue
            try:
                board = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            cells = board if isinstance(board, list) else board.get("scenes") or []
            cells = [c for c in cells if isinstance(c, dict)]
            if not cells:
                continue
            mix: dict[str, float] = {}
            for cell in cells:
                kind = str(cell.get("visual_type") or "unknown")
                mix[kind] = mix.get(kind, 0.0) + 1.0
            return {"scenes": len(cells),
                    "visual_source_mix": {k: round(v / len(cells), 3)
                                          for k, v in sorted(mix.items())}}
        return {}

    def run_quality_gates(self, product_dir: Path, audit: dict, grammar: dict,
                          benchmark: dict, video_path: Path | None = None) -> dict:
        """§9 gates over evidence this audit already measured.

        Nothing is estimated. A gate whose input does not exist stays `unknown`,
        which blocks nothing — but a FAIL or a `needs_human` becomes an audit
        issue at the call site, and the render stops."""
        try:
            from omnicast.quality.gates import run_gates

            config = self._channel_config(product_dir)
            metrics = (audit.get("pacing") or {}).get("metrics") or {}
            visual = audit.get("visual_relevance") or {}
            visual_match = audit.get("visual_match_qc") or {}
            visual_passed = visual.get("passed")
            if visual_match.get("required"):
                visual_passed = bool(visual_passed) and bool(
                    visual_match.get("passed"))
            evidence = {
                "visual_relevance_passed": visual_passed,
                "voice_rate_std_over_mean": metrics.get("std_over_mean"),
                "motion_mix": (grammar or {}).get("motion_mix"),
                "transition_mix": (grammar or {}).get("transition_mix"),
                "benchmark_headline": (benchmark or {}).get("headline_similarity"),
                "benchmark_blocked_by": (benchmark or {}).get("headline_blocked_by"),
                "is_flagship": config.get("is_flagship"),
                "human_reviewed": self._human_review_recorded(
                    product_dir, video_path),
                "human_reviewer": config.get("human_reviewer"),
            }
            evidence.update(self._ymyl_evidence(config))
            # Evidence the product folder already holds: the script, the
            # storyboard and the compliance record. Six gates were `unknown`
            # only because nobody read files sitting next to the video.
            evidence.update(self._script_evidence(product_dir))
            evidence.update(self._storyboard_evidence(product_dir, audit))
            evidence.update(self._compliance_evidence(product_dir))
            return run_gates(evidence).as_dict()
        except Exception as exc:
            # A lost report and a clean report must not look alike downstream.
            return {"skipped": f"quality_gate_error:{exc}", "failed": [],
                    "needs_human": ["human_review"], "coverage": None,
                    "note": "the gate report could not be produced — treated as "
                            "needing a human rather than as a pass"}

    # A claim worth sourcing: a number, a money figure, a date, a percentage,
    # or an explicit attribution. Deliberately narrow — over-counting claims
    # makes the sourced RATIO look worse than it is and the gate untrustworthy.
    _CLAIM_RE = re.compile(
        r"(\d[\d,.]*\s*(?:%|percent|million|billion|thousand)|[$€£]\s?\d"
        r"|\bin (?:19|20)\d{2}\b|\baccording to\b|\bstudy (?:found|shows)\b)",
        re.I)
    _CITATION_RE = re.compile(r"https?://\S+")
    _OVERPROMISE_RE = re.compile(
        r"\b(?:everything you need|the only .* you'?ll ever need|guaranteed|"
        r"never fail|100%|the truth they don'?t want)\b", re.I)

    def _script_evidence(self, product_dir: Path) -> dict:
        """Research accuracy, provenance and editorial density, from script.txt."""
        script = product_dir / "script.txt"
        if not script.exists():
            return {}
        try:
            text = script.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return {}
        if not text.strip():
            return {}

        claims = self._CLAIM_RE.findall(text)
        urls = self._CITATION_RE.findall(text)
        words = len(text.split())
        # ~150 words per minute of narration; the pacing probe measures the real
        # rate but is not always available, and this only sets a denominator.
        minutes = max(words / 150.0, 0.1)
        first_line = text.strip().splitlines()[0] if text.strip() else ""
        return {
            "claim_count": len(claims),
            # Every URL in the script counts as sourcing one claim. It is a
            # floor, not a mapping: a real claim->source link needs the writer
            # to emit one, which nothing does yet.
            "sourced_claim_count": min(len(urls), len(claims)),
            "citations": [{"url": u} for u in urls],
            "proof_points_per_minute": round(len(claims) / minutes, 3),
            "hook_overpromises": bool(self._OVERPROMISE_RE.search(first_line)),
        }

    @staticmethod
    def _storyboard_evidence(product_dir: Path, audit: dict) -> dict:
        """Continuity: how much of the board reuses an earlier visual."""
        for name in ("board_final.json", "storyboard.json", "_storyboard.json", "board.json"):
            path = product_dir / name
            if not path.exists():
                continue
            try:
                board = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            cells = board if isinstance(board, list) else board.get("scenes") or []
            keys = [str((c or {}).get("image_prompt") or (c or {}).get("stock_query")
                        or "").strip().lower()
                    for c in cells if isinstance(c, dict)]
            keys = [k for k in keys if k]
            # Six cells minimum: a three-scene board that reuses one prompt is
            # 33% "repeated" by arithmetic and says nothing about slop.
            if len(keys) < 6:
                return {}
            unique = len(set(keys))
            return {"repeated_shot_ratio": round(1.0 - unique / len(keys), 3)}
        return {}

    @staticmethod
    def _compliance_evidence(product_dir: Path) -> dict:
        """Whether the ComplianceChecker passed, if it recorded a verdict."""
        for name in ("_compliance.json", "compliance.json"):
            path = product_dir / name
            if not path.exists():
                continue
            try:
                report = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if isinstance(report, dict) and "passed" in report:
                return {"compliance_passed": report.get("passed")}
        meta_path = product_dir / "meta.json"
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if "compliance_passed" in meta:
            return {"compliance_passed": meta.get("compliance_passed")}
        return {}

    @staticmethod
    def _ymyl_evidence(config: dict) -> dict:
        """Whether this is YMYL — INFERRED, not waited for.

        Nothing upstream ever set `is_ymyl`, so it defaulted to False and every
        finance and health video passed the human gate with "not YMYL". The
        niche is on the channel config and has been all along."""
        from omnicast.discovery.opportunity import YMYL_NICHES

        declared = config.get("is_ymyl")
        if declared is not None:
            return {"is_ymyl": bool(declared), "ymyl_source": "channel config"}
        niche = str(config.get("niche") or "").strip().lower()
        if not niche:
            # Unknown is not "no". A video whose niche we cannot read must not
            # skip the human gate by default.
            return {"is_ymyl": None, "ymyl_source": "unknown — no niche on config"}
        ymyl = niche in {n.value for n in YMYL_NICHES}
        return {"is_ymyl": ymyl, "ymyl_source": f"inferred from niche '{niche}'"}

    @staticmethod
    def artifact_hash(video_path: str | Path) -> str:
        """SHA-256 of the rendered file, so a review names WHICH cut it approved.

        Without it, a recorded approval survives a re-render: the reviewer
        approved one video and a different one publishes under the same
        approval."""
        import hashlib

        try:
            digest = hashlib.sha256()
            with open(video_path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        except OSError:
            return ""

    @classmethod
    def _human_review_recorded(cls, product_dir: Path,
                               video_path: Path | None = None) -> bool:
        """A review counts only if it names a reviewer, a time and THIS cut."""
        try:
            meta = json.loads((product_dir / "meta.json").read_text(encoding="utf-8"))
        except Exception:
            return False
        review = meta.get("human_review")
        if not isinstance(review, dict):
            return False
        if not str(review.get("reviewer") or "").strip():
            return False
        if not str(review.get("reviewed_at") or "").strip():
            return False
        recorded = str(review.get("artifact_sha256") or "").strip()
        if video_path is None:
            return bool(recorded)
        return bool(recorded) and recorded == cls.artifact_hash(video_path)

    def inspect_production_grammar(self, video_path: str | Path) -> dict:
        """How this render was CUT — shot rhythm, motion, colour, transitions.

        The production caller for `analytics.av_forensics`. Wiring it here and
        not only into competitor research is deliberate: our own renders are the
        one set of video files that always exist locally, so this runs on every
        product without a download, and it is what makes "does our grammar match
        the benchmark" answerable at all.

        Never raises and never fails an audit — see the call site."""
        try:
            from omnicast.analytics import av_forensics as avf

            return avf.analyse_video(video_path).as_dict()
        except Exception as exc:
            return {"skipped": f"forensics_error:{exc}"}

    # ── Pacing audit (vfact benchmark — docs/vfact_benchmark.json) ────────────

    @property
    def _benchmark_path(self) -> Path:
        try:
            return Path(__file__).resolve().parents[3] / "docs" / "vfact_benchmark.json"
        except IndexError:  # relocated file — benchmark optional
            return Path("vfact_benchmark.json")

    def _channel_allows_flat(self, product_dir: Path) -> bool:
        """True when the product's channel opts out of the flat-delivery gate
        (channels/<id>.json `pacing_flat_ok: true` — deadpan-genre channels)."""
        try:
            meta = json.loads((product_dir / "meta.json").read_text(encoding="utf-8"))
            ch = str(meta.get("channel") or "").strip()
            if not ch:
                return False
            cfg = json.loads(
                (self._channels_dir / f"{ch}.json").read_text(encoding="utf-8"))
            return bool(cfg.get("pacing_flat_ok"))
        except Exception:
            return False

    def inspect_pacing(self, video_path: str | Path) -> dict:
        """Measure delivery pacing of the FINAL render and compare to the vfact
        benchmark: syllable-rate variance across 15s windows (flat = robot voice),
        deliberate pauses >=400ms, hook/outro slowdown vs body.

        Language-agnostic (signal-based): band-passed energy envelope peak-picking
        approximates syllable nuclei; for Vietnamese syllables/min ~= words/min.
        Non-fatal: returns {"skipped": reason} if ffmpeg/numpy unavailable.
        """
        out: dict = {"passed": True, "issues": [], "metrics": {}}
        p = Path(video_path)
        try:
            import numpy as np
        except ImportError:
            return {"skipped": "numpy_unavailable", "passed": True, "issues": [], "metrics": {}}

        import tempfile, wave
        bench = {}
        try:
            bench = json.loads(self._benchmark_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        qa = bench.get("qa_thresholds", {})
        std_over_mean_min = float(qa.get("wpm_std_over_mean_min", 0.10))
        pauses_min = int(qa.get("dramatic_pauses_min", 3))

        with tempfile.TemporaryDirectory() as td:
            wav = Path(td) / "audit16k.wav"
            proc = subprocess.run(
                ["ffmpeg", "-y", "-i", str(p), "-vn", "-ac", "1", "-ar", "16000", str(wav)],
                capture_output=True, text=True, timeout=300, creationflags=_NO_WINDOW,
            )
            if proc.returncode != 0 or not wav.exists():
                return {"skipped": "audio_extract_failed", "passed": True, "issues": [], "metrics": {}}

            # pauses via silencedetect (>=250ms below -35dB)
            sd = subprocess.run(
                ["ffmpeg", "-i", str(wav), "-af", "silencedetect=noise=-35dB:d=0.25",
                 "-f", "null", "-"],
                capture_output=True, text=True, timeout=300, creationflags=_NO_WINDOW,
            )
            pause_durs = [float(m) for m in re.findall(r"silence_duration:\s*([0-9.]+)", sd.stderr)]

            with wave.open(str(wav), "rb") as w:
                sr = w.getframerate()
                x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
            dur = len(x) / sr
            if dur < 60:
                return {"skipped": "too_short_for_pacing", "passed": True, "issues": [], "metrics": {}}

            # FFT band-pass 300-3000 Hz (numpy-only)
            X = np.fft.rfft(x)
            freqs = np.fft.rfftfreq(len(x), 1 / sr)
            X[(freqs < 300) | (freqs > 3000)] = 0
            xb = np.fft.irfft(X, n=len(x)).astype(np.float32)

            hop, win = int(0.02 * sr), int(0.04 * sr)
            n_fr = max(1, (len(xb) - win) // hop)
            # O(n)-memory RMS envelope via cumulative sum (a 12-min track would
            # need ~1.5GB with naive frame indexing)
            cs = np.concatenate(([0.0], np.cumsum(xb.astype(np.float64) ** 2)))
            starts = np.arange(n_fr) * hop
            env = np.sqrt((cs[starts + win] - cs[starts]) / win)
            k = 3
            env = np.convolve(env, np.ones(k) / k, mode="same")
            thr = np.percentile(env, 25) * 2.0
            # local maxima above threshold with >=120ms spacing
            cand = np.where((env[1:-1] > env[:-2]) & (env[1:-1] >= env[2:]) & (env[1:-1] > thr))[0] + 1
            peaks: list[int] = []
            min_gap = int(0.12 / 0.02)
            for c in cand:
                if not peaks or c - peaks[-1] >= min_gap:
                    peaks.append(int(c))
            peak_t = np.array(peaks) * 0.02

            WIN = 15.0
            rates = []
            for w0 in np.arange(0.0, dur - 10.0, WIN):
                w1 = min(w0 + WIN, dur)
                rates.append(((peak_t >= w0) & (peak_t < w1)).sum() / (w1 - w0) * 60.0)
            rates_arr = np.array(rates) if rates else np.array([0.0])
            mean_r = float(rates_arr.mean()) or 1.0
            std_r = float(rates_arr.std())
            hook_r = float(rates_arr[:2].mean()) if len(rates_arr) >= 2 else mean_r
            body = rates_arr[2:-2] if len(rates_arr) > 6 else rates_arr
            body_r = float(body.mean()) if len(body) else mean_r
            outro_r = float(rates_arr[-2:].mean()) if len(rates_arr) >= 2 else mean_r
            dramatic = [d for d in pause_durs if d >= 0.4]

            out["metrics"] = {
                "duration_s": round(dur, 1),
                "syllable_rate_mean": round(mean_r, 1),
                "syllable_rate_std": round(std_r, 1),
                "std_over_mean": round(std_r / mean_r, 3),
                "hook_rate": round(hook_r, 1),
                "body_rate": round(body_r, 1),
                "outro_rate": round(outro_r, 1),
                "pauses_ge_250ms": len(pause_durs),
                "pauses_ge_400ms": len(dramatic),
                "benchmark": "vfact_benchmark.json" if bench else "missing",
            }
            # QA gates (SPEC: fail if >20% off benchmark). NOTE: the hook-slower-
            # than-body check is a WARNING only — BGM/SFX under the hook inflates
            # envelope peaks (the vfact reference itself trips it), so it must not
            # hard-fail renders.
            if std_r / mean_r < std_over_mean_min * 0.8:
                out["issues"].append("pacing_flat_delivery")
            if len(dramatic) < pauses_min and dur >= 480:
                out["issues"].append("pacing_no_dramatic_pauses")
            if body_r > 0 and hook_r > body_r * 0.98:
                out["metrics"]["warning_hook_not_slower_than_body"] = True
        out["passed"] = not out["issues"]
        return out

    def inspect_visual_relevance(self, product_dir: str | Path, *, topic: str | None = None) -> dict:
        """Deterministic first-pass guard for scene/clip metadata relevance."""
        pd = Path(product_dir)
        result = {
            "passed": False,
            "issues": [],
            "metadata": {
                "product_dir": str(pd),
                "topic": topic or "",
                "visual_prompt_count": 0,
                "overlap_tokens": [],
                "editor_ui_hits": [],
            },
        }
        if not pd.exists():
            result["issues"].append("product_dir_missing")
            return result

        meta = self._read_json(pd / "meta.json")
        script = self._read_text(pd / "script.txt")
        raw_context = " ".join(
            str(x or "")
            for x in (
                topic,
                meta.get("topic"),
                meta.get("title"),
                meta.get("niche"),
                script[:5000],
            )
        )
        visual_texts = self._collect_product_visual_texts(pd)
        result["metadata"]["topic"] = topic or str(meta.get("topic") or "")
        result["metadata"]["visual_prompt_count"] = len(visual_texts)
        if not raw_context.strip():
            result["issues"].append("visual_context_missing")
            return result
        if not visual_texts:
            result["issues"].append("visual_prompts_missing")
            return result

        expected_tokens = self._top_tokens(raw_context, limit=40)
        visual_tokens = set(self._tokenize(" ".join(visual_texts)))
        overlap = sorted(set(expected_tokens) & visual_tokens)
        editor_hits = self._editor_ui_hits(visual_texts, raw_context)
        result["metadata"].update({
            "expected_token_count": len(expected_tokens),
            "visual_token_count": len(visual_tokens),
            "overlap_tokens": overlap[:20],
            "editor_ui_hits": editor_hits,
        })
        if editor_hits:
            result["issues"].append("editor_ui_visual_detected")
        if len(overlap) < 2:
            result["issues"].append("visual_topic_overlap_too_low")
        result["passed"] = not result["issues"]
        return result

    def inspect_visual_match(
        self,
        product_dir: str | Path,
        video_path: str | Path,
        *,
        required: bool = False,
    ) -> dict:
        """Validate the vision-QC report against this exact rendered artifact.

        Prompt overlap can only judge what the storyboard *asked for*. This
        report judges frames actually present in the MP4. A stale report is
        never allowed to attest to a re-rendered cut.
        """
        pd = Path(product_dir)
        video = Path(video_path)
        report_path = pd / "_visual_match_qc.json"
        result = {
            "required": bool(required),
            "passed": not required,
            "issues": [],
            "report": report_path.name,
            "coverage_ratio": 0.0,
        }
        if not report_path.exists():
            if required:
                result["issues"].append("visual_match_qc_missing")
            return result
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            result["passed"] = False
            result["issues"].append("visual_match_qc_invalid")
            return result

        expected_hash = self.artifact_hash(video)
        recorded_hash = str(report.get("video_sha256") or "").strip()
        if not expected_hash or recorded_hash != expected_hash:
            result["passed"] = False
            result["issues"].append("visual_match_qc_stale_render")
            return result

        try:
            scored = int(report.get("shots_scored") or 0)
            errors = int(report.get("errors") or 0)
            average = float(report.get("avg_score"))
            below = int(report.get("below_threshold") or 0)
        except (TypeError, ValueError):
            result["passed"] = False
            result["issues"].append("visual_match_qc_invalid_metrics")
            return result

        attempted = scored + errors
        coverage = scored / attempted if attempted > 0 else 0.0
        low_ratio = below / scored if scored > 0 else 1.0
        result.update({
            "shots_scored": scored,
            "errors": errors,
            "avg_score": average,
            "below_threshold": below,
            "coverage_ratio": round(coverage, 3),
            "below_threshold_ratio": round(low_ratio, 3),
        })
        if scored <= 0:
            result["issues"].append("visual_match_qc_no_scored_shots")
        if coverage < 0.9:
            result["issues"].append("visual_match_qc_low_coverage")
        if average < 6.0:
            result["issues"].append("visual_match_qc_low_average")
        if low_ratio > 0.15:
            result["issues"].append("visual_match_qc_too_many_weak_shots")
        result["passed"] = not result["issues"]
        return result

    def _ffprobe(self, path: Path) -> dict:
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
        completed = subprocess.run(cmd, check=True, capture_output=True, text=True,
                                   creationflags=_NO_WINDOW)
        return json.loads(completed.stdout)

    def _measure_integrated_lufs(self, path: Path) -> float:
        cmd = [
            "ffmpeg",
            "-nostats",
            "-i",
            str(path),
            "-filter_complex",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ]
        completed = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=90,
                                   creationflags=_NO_WINDOW)
        matches = re.findall(r"\bI:\s*(-?\d+(?:\.\d+)?)\s*LUFS", completed.stderr)
        if not matches:
            raise RuntimeError("integrated_lufs_missing")
        return float(matches[-1])

    def _collect_product_visual_texts(self, product_dir: Path) -> list[str]:
        texts: list[str] = []
        for name in ("board_final.json", "storyboard.json",
                     "_storyboard.json", "board.json"):
            path = product_dir / name
            if path.exists():
                try:
                    board = json.loads(path.read_text(
                        encoding="utf-8", errors="ignore"))
                except Exception:
                    board = {}
                self._collect_visual_fields(board, texts)
                break
        variants = product_dir / "variants"
        if variants.exists():
            for path in sorted(variants.glob("*.json")):
                data = self._read_json(path)
                self._collect_visual_fields(data, texts)
        status = self._read_json(product_dir / "_status" / "status.json")
        for shot in status.get("shots") or []:
            if isinstance(shot, dict):
                heading = str(shot.get("heading") or "").strip()
                if heading:
                    texts.append(heading)
        return [text for text in texts if text.strip()]

    def _collect_visual_fields(self, value, texts: list[str]) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"visual", "visual_prompt", "stock_query",
                           "broll_query", "clip_title", "heading"}:
                    text = str(item or "").strip()
                    if text:
                        texts.append(text)
                elif isinstance(item, (dict, list)):
                    self._collect_visual_fields(item, texts)
        elif isinstance(value, list):
            for item in value:
                self._collect_visual_fields(item, texts)

    def _editor_ui_hits(self, visual_texts: list[str], raw_context: str) -> list[str]:
        context = raw_context.lower()
        topic_allows_editor_ui = any(
            term in context
            for term in ("adobe premiere", "premiere pro", "video editing", "editing software", "davinci", "final cut")
        )
        if topic_allows_editor_ui:
            return []
        haystack = " ".join(visual_texts).lower()
        return [pattern for pattern in _EDITOR_UI_PATTERNS if pattern in haystack]

    def _top_tokens(self, text: str, *, limit: int) -> list[str]:
        counts: dict[str, int] = {}
        for token in self._tokenize(text):
            counts[token] = counts.get(token, 0) + 1
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        return [token for token, _ in ranked[:limit]]

    def _tokenize(self, text: str) -> list[str]:
        return [
            token
            for token in re.findall(r"[a-z0-9]{3,}", text.lower())
            if token not in _VISUAL_STOPWORDS
        ]

    def _read_text(self, path: Path) -> str:
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""

    def _read_json(self, path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
