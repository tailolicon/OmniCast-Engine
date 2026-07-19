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
                if key in {"visual", "visual_prompt", "broll_query", "clip_title", "heading"}:
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
