from __future__ import annotations

from pathlib import Path
from threading import Lock

from omnicast.reup.core.jobs import JobContext
from omnicast.reup.core.settings import AppSettings

from .base import ASREngine
from .models import SegmentDraft, TranscriptionOptions, TranscriptionResult, WordTimestamp


# Loading `small` cost 86 seconds on a measured run: a round trip to
# huggingface.co to check the revision, then CTranslate2 reading the weights.
# Both are per-process constants, but the engine rebuilt the model for every
# job — so every dub paid it again. Keyed by the settings that change the
# weights actually loaded.
_MODEL_CACHE: dict[tuple[str, str, str, str], object] = {}
_MODEL_LOCK = Lock()


def _load_model(model_name: str, *, device: str, compute_type: str, download_root: str | None):
    key = (model_name, device, compute_type, str(download_root or ""))
    cached = _MODEL_CACHE.get(key)
    if cached is not None:
        return cached
    with _MODEL_LOCK:
        if key in _MODEL_CACHE:
            return _MODEL_CACHE[key]
        from faster_whisper import WhisperModel

        # Try the disk cache first. Otherwise every single load waits on a
        # huggingface.co revision check that cannot change the answer, and an
        # offline machine fails at the ASR stage instead of just working.
        # `download_root` is often None (default HF cache), so this cannot be
        # decided by looking for the file — ask, and fall back if it is absent.
        try:
            model = WhisperModel(
                model_name, device=device, compute_type=compute_type,
                download_root=download_root, local_files_only=True,
            )
        except Exception:
            model = WhisperModel(
                model_name, device=device, compute_type=compute_type,
                download_root=download_root,
            )
        _MODEL_CACHE[key] = model
        return model


class FasterWhisperEngine(ASREngine):
    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings

    def transcribe(
        self,
        context: JobContext,
        *,
        audio_path: str,
        options: TranscriptionOptions,
        duration_ms: int | None = None,
    ) -> TranscriptionResult:
        try:
            import faster_whisper  # noqa: F401
        except ImportError as exc:  # pragma: no cover - runtime dependency
            raise RuntimeError("faster-whisper chua duoc cai dat") from exc

        context.report_progress(5, "Dang khoi tao faster-whisper")
        model = _load_model(
            options.model_name,
            device="cuda" if self._settings.gpu_enabled else "cpu",
            compute_type=options.compute_type or ("float16" if self._settings.gpu_enabled else "int8"),
            download_root=self._settings.model_cache_dir,
        )

        segments, info = model.transcribe(
            audio=audio_path,
            language=options.language,
            vad_filter=options.vad_filter,
            word_timestamps=options.word_timestamps,
            condition_on_previous_text=options.condition_on_previous_text,
            no_speech_threshold=options.no_speech_threshold,
            vad_parameters={
                "threshold": options.vad_threshold,
                "min_silence_duration_ms": options.vad_min_silence_ms,
                "max_speech_duration_s": options.vad_max_speech_s,
            },
        )

        draft_segments: list[SegmentDraft] = []
        detected_language = getattr(info, "language", options.language)
        for index, segment in enumerate(segments):
            context.cancellation_token.raise_if_canceled()
            words: list[WordTimestamp] = []
            for word in getattr(segment, "words", []) or []:
                words.append(
                    WordTimestamp(
                        start_ms=int(float(getattr(word, "start", 0.0)) * 1000),
                        end_ms=int(float(getattr(word, "end", 0.0)) * 1000),
                        text=str(getattr(word, "word", "")).strip(),
                        probability=float(getattr(word, "probability", 0.0))
                        if getattr(word, "probability", None) is not None
                        else None,
                    )
                )

            start_ms = int(float(getattr(segment, "start", 0.0)) * 1000)
            end_ms = int(float(getattr(segment, "end", 0.0)) * 1000)
            text = str(getattr(segment, "text", "")).strip()
            draft_segments.append(
                SegmentDraft(
                    segment_index=index,
                    start_ms=start_ms,
                    end_ms=end_ms,
                    source_text=text,
                    language=detected_language,
                    words=words,
                )
            )

            if duration_ms:
                progress = min(95, max(10, int((end_ms / max(duration_ms, 1)) * 90)))
                context.report_progress(progress, f"ASR segment {index + 1}")

        context.report_progress(98, "Da xong transcribe, dang persist")
        return TranscriptionResult(
            source_audio_path=Path(audio_path),
            detected_language=detected_language,
            duration_ms=duration_ms,
            segments=draft_segments,
        )

