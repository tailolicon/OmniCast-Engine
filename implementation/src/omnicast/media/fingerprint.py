"""Content fingerprinting for duplicate/similarity detection."""

from __future__ import annotations
import hashlib
from pathlib import Path
import structlog
from omnicast.media.models import ContentFingerprint
from omnicast.shared.errors import MediaError

logger = structlog.get_logger()


class FingerprintModule:
    """Not a BaseMediaModule — stateless utility, no dry-run needed."""

    def fingerprint_script(self, script_text: str) -> str:
        """SHA-256 hash of normalized script text."""
        normalized = " ".join(script_text.lower().split())
        return hashlib.sha256(normalized.encode()).hexdigest()

    def fingerprint_visual(self, image_paths: list[str]) -> list[str]:
        """Perceptual hash (pHash) of key frame images using imagehash library.
        Returns list of hex hash strings."""
        # Placeholder for actual perceptual hashing
        # In production: use imagehash.phash() on each image
        return [hashlib.md5(path.encode()).hexdigest() for path in image_paths]

    def fingerprint_audio(self, audio_path: str) -> str:
        """Chromaprint fingerprint of audio using librosa + hashlib.
        Steps: load audio → extract chroma features → hash."""
        # Placeholder for actual audio fingerprinting
        # In production: use librosa to load audio, extract chroma features, hash
        return hashlib.md5(audio_path.encode()).hexdigest()

    def fingerprint_structure(self, intro_duration: float, scene_count: int,
                               transition_types: list[str]) -> str:
        """Hash of structural metadata: intro length, scene count, transitions."""
        sig = f"{intro_duration:.1f}|{scene_count}|{','.join(sorted(transition_types))}"
        return hashlib.sha256(sig.encode()).hexdigest()[:16]

    def build_fingerprint(self, video_id: str, script_text: str = "",
                           image_paths: list[str] | None = None,
                           audio_path: str = "",
                           intro_duration: float = 0.0,
                           scene_count: int = 0,
                           transition_types: list[str] | None = None) -> ContentFingerprint:
        """Build complete ContentFingerprint from raw inputs."""
        return ContentFingerprint(
            video_id=video_id,
            script_hash=self.fingerprint_script(script_text) if script_text else "",
            visual_hashes=self.fingerprint_visual(image_paths) if image_paths else [],
            audio_fingerprint=self.fingerprint_audio(audio_path) if audio_path else "",
            structure_signature=self.fingerprint_structure(
                intro_duration, scene_count, transition_types or []
            ),
        )

    def check_duplicate(self, new: ContentFingerprint,
                         existing: list[ContentFingerprint],
                         threshold: float = 0.7) -> ContentFingerprint | None:
        """Return first existing fingerprint with similarity > threshold, or None."""
        for fp in existing:
            if new.similarity_score(fp) > threshold:
                return fp
        return None
