from __future__ import annotations

from abc import ABC, abstractmethod

from omnicast.reup.core.jobs import JobContext

from .models import TranscriptionOptions, TranscriptionResult


class ASREngine(ABC):
    @abstractmethod
    def transcribe(
        self,
        context: JobContext,
        *,
        audio_path: str,
        options: TranscriptionOptions,
        duration_ms: int | None = None,
    ) -> TranscriptionResult:
        raise NotImplementedError

