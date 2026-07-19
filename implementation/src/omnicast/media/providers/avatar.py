"""Talking-head (avatar) providers — audio-driven character video.

Avatar generation is a distinct modality from prompt-driven img2vid
(`IVideoProvider.convert`): it takes a *portrait image* + a *narration audio*
clip and produces a video of that character speaking (lip-sync + head motion).

Two backends, same Protocol (autovio swap-by-config pattern):

    ITalkingHeadProvider
    ├── SadTalkerProvider        — LOCAL. Runs on 4GB GPU / CPU-only torch.
    │                             Shells out to a cloned SadTalker repo's
    │                             inference.py. Free, no API key. Slow on CPU.
    └── ComfyUIHunyuanProvider   — REMOTE. Talks to a ComfyUI server running
                                  HunyuanVideo-Avatar (needs >=10GB VRAM host).
                                  Submit /prompt workflow + poll history.

Hardware note: HunyuanVideo-Avatar needs >=10GB VRAM even optimized, so it
cannot run on a 4GB box — it is wired as a remote provider only.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Protocol

import httpx

from omnicast.media.providers.image_gemini import MediaError
from omnicast.media.providers.interfaces import ModelOption


class ITalkingHeadProvider(Protocol):
    """Protocol for audio-driven talking-head (avatar) providers."""

    id: str
    name: str
    models: list[ModelOption]

    async def animate(
        self,
        image_path: str,
        audio_path: str,
        *,
        model: str | None = None,
        resolution: tuple[int, int] | None = None,
        output_path: str,
    ) -> str:
        """Animate a portrait image so it speaks the given audio.

        Args:
            image_path: Absolute path to the source portrait image.
            audio_path: Absolute path to the narration audio (wav/mp3).
            model: Optional model/preset ID. None = provider default.
            resolution: Optional (width, height). None = provider default.
            output_path: Absolute path where the talking-head mp4 is written.

        Returns:
            Absolute path to the generated talking-head video.

        Raises:
            MediaError: If animation fails.
        """
        ...


# ─── Local: SadTalker (fits 4GB / CPU) ──────────────────────────────────────


class SadTalkerProvider:
    """Local talking-head via a cloned SadTalker repo (subprocess).

    Requires SadTalker checked out + checkpoints downloaded. Point to it with
    the ``SADTALKER_HOME`` env var (dir containing ``inference.py`` and
    ``checkpoints/``). On CPU-only torch it runs but is slow (minutes/clip).
    """

    id = "sadtalker"
    name = "SadTalker (local)"
    models = [
        ModelOption(
            id="full",
            name="Full (head motion + enhancer)",
            description="Best quality; --preprocess full --enhancer gfpgan",
        ),
        ModelOption(
            id="fast",
            name="Fast (cropped, no enhancer)",
            description="Faster on CPU; --preprocess crop, no enhancer",
        ),
    ]

    def __init__(self, home: str | None = None) -> None:
        self.home = Path(home or os.environ.get("SADTALKER_HOME", "")).expanduser()

    def _ensure_ready(self) -> Path:
        if not self.home or not self.home.exists():
            raise MediaError(
                "SadTalker not found. Clone https://github.com/OpenTalker/SadTalker, "
                "download its checkpoints, then set SADTALKER_HOME to that directory."
            )
        inference = self.home / "inference.py"
        if not inference.exists():
            raise MediaError(f"inference.py missing under SADTALKER_HOME={self.home}")
        if not (self.home / "checkpoints").exists():
            raise MediaError(
                f"SadTalker checkpoints/ missing under {self.home}. "
                "Run its scripts/download_models.sh first."
            )
        return inference

    async def animate(
        self,
        image_path: str,
        audio_path: str,
        *,
        model: str | None = None,
        resolution: tuple[int, int] | None = None,
        output_path: str,
    ) -> str:
        inference = self._ensure_ready()
        preset = model or "full"
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        result_dir = out.parent / "_sadtalker"
        result_dir.mkdir(parents=True, exist_ok=True)

        size = 512 if (resolution and max(resolution) > 256) else 256
        cmd = [
            "python", str(inference),
            "--source_image", str(Path(image_path).resolve()),
            "--driven_audio", str(Path(audio_path).resolve()),
            "--result_dir", str(result_dir.resolve()),
            "--size", str(size),
            "--still",
        ]
        if preset == "full":
            cmd += ["--preprocess", "full", "--enhancer", "gfpgan"]
        else:
            cmd += ["--preprocess", "crop"]

        proc = await asyncio.to_thread(
            subprocess.run, cmd, capture_output=True, text=True, cwd=str(self.home)
        )
        if proc.returncode != 0:
            raise MediaError(
                f"SadTalker failed ({proc.returncode}): {proc.stderr[-1500:]}"
            )

        produced = sorted(result_dir.glob("**/*.mp4"), key=lambda p: p.stat().st_mtime)
        if not produced:
            raise MediaError("SadTalker produced no mp4 output")
        produced[-1].replace(out)
        return str(out.resolve())


# ─── Local CPU: procedural audio-driven talking head (py3.13, no GPU) ────────


class ProceduralTalkingHeadProvider:
    """Audio-driven talking head with no neural model — runs anywhere.

    Animates a portrait's jaw/mouth proportional to the narration's loudness
    envelope (RMS), plus a subtle head-bob, then muxes the narration audio.
    Pure OpenCV + NumPy + librosa, CPU-only, fast — the reliable local fallback
    when the neural backends (SadTalker / HunyuanVideo-Avatar) can't run here.

    Not photoreal lip-sync: it is amplitude-driven mouth motion, an honest
    "talking puppet". Quality << Hunyuan, but it actually runs on a 4GB/CPU box.
    """

    id = "procedural"
    name = "Procedural talking head (CPU)"
    models = [ModelOption(id="jaw", name="Jaw/mouth envelope", description="RMS-driven mouth open + head bob")]

    FPS = 25

    def _detect_mouth_box(self, img) -> tuple[int, int, int, int]:
        import cv2

        h, w = img.shape[:2]
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        faces = cv2.CascadeClassifier(cascade_path).detectMultiScale(gray, 1.1, 5)
        if len(faces):
            fx, fy, fw, fh = max(faces, key=lambda f: f[2] * f[3])
        else:  # heuristic: centered face in upper-middle
            fw, fh = int(w * 0.5), int(h * 0.6)
            fx, fy = (w - fw) // 2, int(h * 0.12)
        # mouth band: lower third of the face
        mx = fx + int(fw * 0.28)
        mw = int(fw * 0.44)
        my = fy + int(fh * 0.60)
        mh = int(fh * 0.34)
        return mx, my, mw, mh

    @staticmethod
    def _envelope(audio_path: str, n_frames: int):
        import librosa
        import numpy as np

        y, sr = librosa.load(audio_path, sr=16000, mono=True)
        hop = max(1, len(y) // max(1, n_frames))
        rms = librosa.feature.rms(y=y, frame_length=hop * 2, hop_length=hop)[0]
        if rms.max() > 0:
            rms = rms / rms.max()
        # resample envelope to exactly n_frames
        idx = np.linspace(0, len(rms) - 1, n_frames).astype(int)
        env = rms[idx]
        # ease + floor so the mouth never fully freezes mid-word
        return np.clip(env**0.7, 0.0, 1.0)

    def _animate_frame(self, base, box, amount: float, bob: int):
        import cv2
        import numpy as np

        img = base.copy()
        mx, my, mw, mh = box
        # jaw drop: stretch the mouth band downward by `open_px`
        open_px = int(mh * 0.55 * amount)
        if open_px > 0:
            band = img[my:my + mh, mx:mx + mw]
            stretched = cv2.resize(band, (mw, mh + open_px))
            y0 = my
            y1 = min(base.shape[0], my + mh + open_px)
            img[y0:y1, mx:mx + mw] = stretched[: y1 - y0]
            # dark mouth cavity ellipse
            cy = my + mh - open_px // 2
            cv2.ellipse(
                img, (mx + mw // 2, cy), (mw // 3, max(2, open_px // 2)),
                0, 0, 360, (18, 12, 14), -1,
            )
        # subtle head bob (vertical roll)
        if bob:
            img = np.roll(img, bob, axis=0)
        return img

    async def animate(
        self,
        image_path: str,
        audio_path: str,
        *,
        model: str | None = None,
        resolution: tuple[int, int] | None = None,
        output_path: str,
    ) -> str:
        import asyncio

        def _run() -> None:
            import math
            import subprocess
            import tempfile

            import cv2
            import soundfile as sf

            base = cv2.imread(image_path)
            if base is None:
                raise MediaError(f"Cannot read portrait image: {image_path}")
            if resolution:
                base = cv2.resize(base, resolution)

            info = sf.info(audio_path)
            duration = info.frames / float(info.samplerate)
            n_frames = max(1, int(duration * self.FPS))
            env = self._envelope(audio_path, n_frames)
            box = self._detect_mouth_box(base)

            h, w = base.shape[:2]
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            silent = out.with_name(out.stem + "_silent.mp4")

            writer = cv2.VideoWriter(
                str(silent), cv2.VideoWriter_fourcc(*"mp4v"), self.FPS, (w, h)
            )
            for i in range(n_frames):
                bob = int(round(2 * math.sin(i / 6.0) * (0.4 + env[i])))
                writer.write(self._animate_frame(base, box, float(env[i]), bob))
            writer.release()

            # mux narration audio onto the silent animation
            cmd = [
                "ffmpeg", "-y", "-i", str(silent), "-i", str(audio_path),
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-shortest", str(out),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            silent.unlink(missing_ok=True)
            if proc.returncode != 0:
                raise MediaError(f"procedural avatar mux failed: {proc.stderr[-800:]}")

        await asyncio.to_thread(_run)
        if not Path(output_path).exists():
            raise MediaError("Procedural avatar produced no output")
        return str(Path(output_path).resolve())


# ─── Remote: ComfyUI + HunyuanVideo-Avatar (needs GPU host) ──────────────────


class ComfyUIHunyuanProvider:
    """Remote talking-head via a ComfyUI server running HunyuanVideo-Avatar.

    Follows the autovio submit-job + poll pattern over ComfyUI's HTTP API:
    upload assets, POST /prompt with the workflow graph, poll /history/{id}
    until the output node has a video, then download via /view.

    Point at the host with ``COMFYUI_URL`` (e.g. http://gpu-host:8188) and
    supply the workflow template via ``COMFYUI_HUNYUAN_WORKFLOW`` (a path to a
    ComfyUI API-format workflow JSON exported from the Hunyuan-Avatar graph).

    NOTE: cannot run on a 4GB box; requires a >=10GB VRAM ComfyUI host.
    """

    id = "comfyui-hunyuan"
    name = "HunyuanVideo-Avatar (ComfyUI, remote)"
    models = [
        ModelOption(
            id="hunyuan-avatar",
            name="HunyuanVideo-Avatar",
            description="Tencent 13B audio-driven talking-head; remote GPU only",
        ),
    ]

    def __init__(
        self,
        base_url: str | None = None,
        workflow_path: str | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("COMFYUI_URL", "")).rstrip("/")
        self.workflow_path = workflow_path or os.environ.get(
            "COMFYUI_HUNYUAN_WORKFLOW", ""
        )

    def _load_workflow(self) -> dict:
        if not self.base_url:
            raise MediaError("COMFYUI_URL not configured (remote ComfyUI host)")
        if not self.workflow_path or not Path(self.workflow_path).exists():
            raise MediaError(
                "COMFYUI_HUNYUAN_WORKFLOW not set or missing. Export an "
                "API-format workflow JSON from the Hunyuan-Avatar ComfyUI graph."
            )
        return json.loads(Path(self.workflow_path).read_text(encoding="utf-8"))

    async def _upload(self, client: httpx.AsyncClient, path: str) -> str:
        p = Path(path)
        files = {"image": (p.name, p.read_bytes())}
        r = await client.post(f"{self.base_url}/upload/image", files=files)
        r.raise_for_status()
        return r.json().get("name", p.name)

    @staticmethod
    def _patch_workflow(
        wf: dict, image_name: str, audio_name: str
    ) -> dict:
        """Inject uploaded asset names into LoadImage / LoadAudio nodes.

        Best-effort: matches node class_type. The exact node titles depend on
        the exported graph, so this fills the common cases and leaves the rest.
        """
        for node in wf.values():
            ct = node.get("class_type", "")
            if ct in ("LoadImage",) and "image" in node.get("inputs", {}):
                node["inputs"]["image"] = image_name
            if "Audio" in ct and "audio" in node.get("inputs", {}):
                node["inputs"]["audio"] = audio_name
        return wf

    async def animate(
        self,
        image_path: str,
        audio_path: str,
        *,
        model: str | None = None,
        resolution: tuple[int, int] | None = None,
        output_path: str,
    ) -> str:
        wf = self._load_workflow()
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        async with httpx.AsyncClient(timeout=60.0) as client:
            image_name = await self._upload(client, image_path)
            audio_name = await self._upload(client, audio_path)
            graph = self._patch_workflow(wf, image_name, audio_name)

            r = await client.post(f"{self.base_url}/prompt", json={"prompt": graph})
            r.raise_for_status()
            prompt_id = r.json()["prompt_id"]

            video_rel: dict | None = None
            for _ in range(240):  # up to ~20 min (240 * 5s)
                await asyncio.sleep(5)
                h = await client.get(f"{self.base_url}/history/{prompt_id}")
                if h.status_code != 200:
                    continue
                hist = h.json().get(prompt_id)
                if not hist:
                    continue
                outputs = hist.get("outputs", {})
                for node_out in outputs.values():
                    vids = node_out.get("gifs") or node_out.get("videos") or []
                    if vids:
                        video_rel = vids[0]
                        break
                if video_rel:
                    break

            if not video_rel:
                raise MediaError("Hunyuan-Avatar (ComfyUI) timed out or produced no video")

            params = {
                "filename": video_rel["filename"],
                "subfolder": video_rel.get("subfolder", ""),
                "type": video_rel.get("type", "output"),
            }
            v = await client.get(f"{self.base_url}/view", params=params)
            v.raise_for_status()
            out.write_bytes(v.content)

        return str(out.resolve())
