"""Flow API bridge — talk to Flow's own backend instead of driving its UI.

WHY THIS EXISTS. `flow_browser.py` clicks the Flow web UI. That works for
images, but the UI is where Flow's capabilities are hardest to reach: its
`convert()` cannot pass a first frame, so image→video — and therefore the
whole first/last-frame chain that makes consecutive shots cohere — was
unreachable, and the storyboard had to fall back to the paid Gemini API.

Flow's backend supports all of it. This module reaches it directly, on the
operator's Google AI subscription credits rather than pay-as-you-go API
billing, which are two entirely separate meters.

HOW AUTH WORKS (discovered live, 2026-08-01). Flow's web app holds a NextAuth
session; `GET https://labs.google/fx/api/auth/session` returns an
`access_token` alongside the profile. That token is the bearer for
`aisandbox-pa.googleapis.com`. So the flow is:

    logged-in Playwright profile  →  /fx/api/auth/session  →  access_token
                                  →  Bearer on aisandbox-pa REST calls

Requests are issued from INSIDE the page (`page.evaluate` + `fetch`) rather
than from Python. That is deliberate: the page already carries the right
origin, cookies and headers, so there is no token plumbing to get wrong and
nothing to refresh separately. The token never leaves the browser, and it is
never logged here.

CALIBRATION STATUS — read this before trusting a method:
  * VERIFIED live: `access_token()`, `app_config()`, `model_statuses()`,
    `user_settings()`. All returned 200 against the real backend.
  * NOT YET CALIBRATED: the generate and upload calls. The operation NAMES are
    known from Flow's own client bundle (see `OPERATIONS`), and the REST paths
    below were harvested from the same bundle, but the exact request bodies
    have not been confirmed against a live call. They are declared here so the
    contract is written down; `is_calibrated()` reports False until a capture
    run pins the payloads, and callers must check it rather than assume.

Nothing in this module spends credits except the generate calls, which are the
uncalibrated ones — reading config and models is free.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()

FLOW_ORIGIN = "https://labs.google"
SESSION_PATH = "/fx/api/auth/session"
API_BASE = "https://aisandbox-pa.googleapis.com"

#: REST paths seen in Flow's client bundle. Those marked VERIFIED returned 200.
PATHS = {
    "app_config": "/v1/flow/appConfig",            # VERIFIED
    "model_statuses": "/v1/flow/models/statuses",  # VERIFIED
    "user_settings": "/v1/flow/userSettings",      # VERIFIED
    "upload_image": "/v1/flow/uploadImage",        # path known, body not pinned
    "projects": "/v1/flow/projects/",
    "scene": "/v1/flow/scene/",
    "media": "/v1/flowMedia/",
    "entities": "/v1/flow/entities",
}

#: Generation operations named in Flow's bundle. `generateVideoWithInterpolation`
#: is the first+last-frame path — the one the storyboard needs for a coherent
#: cut between shots, and the reason this module exists.
OPERATIONS = (
    "generateImage",
    "generateVideo",                    # text → video
    "generateVideoFirstFrame",          # image → video, image is frame 1
    "generateVideoWithReferences",      # reference-conditioned video
    "generateVideoWithInterpolation",   # first + last frame → video  (FLF)
    "generateVideoEditVideo",
    "extendVideo",
    "uploadMedia",
)

#: Live model health, read 2026-08-01. `model_statuses()` returns the current
#: set; this is only the shape to expect.
KNOWN_MODEL_KEYS = ("veo_3_1_quality", "veo_3_1_fast", "veo_3_1_lite", "abra")

#: `uploadMedia` input shape, read off the bundle's zod schema.
UPLOAD_MEDIA_INPUT = {
    "mediaCategory": "MEDIA_CATEGORY_… (e.g. _VIDEO, _SUBJECT)",
    "mimeType": "image/png",
    "rawBytes": "<base64, no data: prefix>",
    "storeUserMediaEnabled": True,
}

#: Video RPC paths, all confirmed to exist (they answer 400, not 404).
VIDEO_ENDPOINTS = {
    "text": "/v1/video:batchAsyncGenerateVideoText",
    "start_image": "/v1/video:batchAsyncGenerateVideoStartImage",
    "start_end_image": "/v1/video:batchAsyncGenerateVideoStartAndEndImage",  # FLF
    "reference_images": "/v1/video:batchAsyncGenerateVideoReferenceImages",
    "extend": "/v1/video:batchAsyncGenerateVideoExtendVideo",
    "edit": "/v1/video:batchAsyncGenerateVideoEditVideo",
    "camera_control": "/v1/video:batchAsyncGenerateVideoCameraControl",
    "upsample": "/v1/video:batchAsyncGenerateVideoUpsampleVideo",
}

#: reCAPTCHA Enterprise site key served on labs.google/fx. EVERY media
#: generation carries a fresh token in `clientContext.recaptchaContext`; the
#: token can only be minted by the page (`grecaptcha.enterprise.execute`),
#: which is precisely why a bridge needs a live Flow tab and why Python alone
#: can never call these endpoints.
RECAPTCHA_SITE_KEY = "6LdsFiUsAAAAAIjVDZcuLhaHiDn5nnHVXVRQGeMV"

#: Request envelope, recovered field by field from the server's own rejections
#: (the video endpoints answer with "Unknown name X: Cannot find field", so the
#: schema can be walked by elimination without spending a generation).
#:
#: ACCEPTED at the top level: clientContext, mediaGenerationContext, requests.
#: ACCEPTED inside requests[0]: videoModelKey, aspectRatio, seed, textInput.
#: ACCEPTED inside textInput: prompt, structuredPrompt.
#: REJECTED: useNewMedia, a nested clientContext, a top-level structuredPrompt,
#:           videoModelName, modelKey, videoAspectRatio, and — as top-level
#:           prompt names — prompt, textPrompt, promptText, text, videoPrompt.
#:
#: The schema is settled: `textInput: {prompt: …}` stops producing schema
#: errors entirely and the response turns into 404 "Requested entity was not
#: found", which is a DIFFERENT failure — validation passed and the call fell
#: over on entity binding instead.
#:
#: OUTSTANDING: that 404. The request almost certainly needs to name a real
#: scene as well as a project — `sceneId`, `sceneContext` and `entityContext`
#: all exist in the bundle's field vocabulary, and `/v1/flow/scene:*` routes
#: answer 200. Listing projects over `fetch` from the page failed CORS, so the
#: scene id has to come from the page's own state rather than a REST list.
VIDEO_REQUEST_ENVELOPE = {
    "clientContext": {
        "recaptchaContext": {"token": "<minted in page>",
                             "applicationType": "RECAPTCHA_APPLICATION_TYPE_WEB"},
        "projectId": "<uuid from the project URL>",
        "tool": "PINHOLE",
        "sessionId": ";<epoch millis>",
    },
    "mediaGenerationContext": {"batchId": "<uuid>"},
    "requests": [{
        "videoModelKey": "veo_3_1_fast",           # or veo_3_1_quality / _lite
        "aspectRatio": "VIDEO_ASPECT_RATIO_LANDSCAPE",
        "seed": 12345,
        "textInput": {"prompt": "…"},              # CONFIRMED
        # For the image endpoints, the bundle's vocabulary gives the fields:
        # "startImage": {...}  → batchAsyncGenerateVideoStartImage
        # "endImage":   {...}  → …StartAndEndImage (the FLF pair)
        # plus referenceImages / videoInputs / imageId for the other modes.
    }],
}

#: UI PATH (calibrated 2026-08-01, for when the API path is not yet finished).
#: Flow's new UI has no VIDEO tab — mode lives in the model chip's popover, and
#: the popover only opens for a REAL mouse event (`page.mouse.click`); a
#: synthetic `el.click()` silently does nothing, the same constraint that makes
#: h2dev_flow drive Flow through chrome.debugger. Sequence:
#:
#:   1. click the model chip (reads "🍌 Nano Banana Pro" or "Video · 8s")
#:   2. click the `videocam` tab → duration chips 4s / 8s appear
#:      (an 8s generation costs 12 subscription credits)
#:   3. Escape to close, then type into the Slate.js prompt box with REAL
#:      keystrokes, then click `arrow_forward`
#:
#: ATTACHING A FIRST FRAME — verified end to end in the operator's own Chrome.
#: In video mode the prompt bar grows two SLOTS, "Bắt đầu" (first frame) and
#: "Kết thúc" (last frame): Flow's native equivalent of Jellyfish's
#: first_frame/last_frame pair, and the reason `START_AND_END_IMAGE` exists in
#: the capability list. The working sequence is:
#:   a. `set_input_files` on the hidden `input[type=file]` — uploads into the
#:      project library (no file chooser needed, no credits)
#:   b. CLICK THE "Bắt đầu" SLOT — this opens a picker SCOPED to that slot
#:   c. click the asset (it is `role="option"` inside the dialog)
#:   d. click "Thêm vào câu lệnh"; a thumbnail replaces the slot label
#: Two near-misses to avoid, both of which silently degrade to text→video and
#: return a different actor in a different room:
#:   * the generic prompt-bar "+" opens an UNSCOPED picker that adds the asset
#:     to the project and binds it to NEITHER slot;
#:   * the "+" badge on a library tile does the same.
#: Only the slot-scoped picker binds a first frame.
#:
#: UI VARIES BY PROFILE. A Playwright profile on the same account rendered the
#: OLDER prompt bar (a single "+", no slots) while the operator's Chrome had
#: the newer one. Automation must detect the slots and refuse to generate when
#: they are absent rather than spend credits on an unconditioned clip.
#:
#: Collect results from `<video>` elements only — `_all_media_srcs` also returns
#: `<img>`, and the attached still is an img, so a naive pick downloads a JPEG
#: named .mp4.
FLOW_UI_NOTES = "see the comment block above this constant"

MINT_RECAPTCHA_JS = """
async (siteKey) => new Promise((res, rej) => {
  grecaptcha.enterprise.ready(async () => {
    try { res(await grecaptcha.enterprise.execute(siteKey, {action: 'generate_video'})); }
    catch (e) { rej(e); }
  });
})
"""

_GET_TOKEN_JS = """
async () => {
  const r = await fetch('%s', {credentials: 'include'});
  if (!r.ok) return {ok: false, status: r.status};
  const s = await r.json();
  return {ok: !!s.access_token, expires: s.expires || null,
          email: (s.user && s.user.email) || null};
}
""" % SESSION_PATH

#: Issues one authenticated request from the page. The token is fetched inside
#: the browser on every call and never crosses into Python — a token in a log
#: line or a traceback is a credential leak, and the cheapest way to guarantee
#: that never happens is to never hold it.
_CALL_JS = """
async ([method, url, body]) => {
  const s = await (await fetch('%s', {credentials: 'include'})).json();
  if (!s || !s.access_token) return {ok: false, status: 401, body: 'NO_ACCESS_TOKEN'};
  const init = {
    method,
    headers: {'Authorization': 'Bearer ' + s.access_token,
              'Content-Type': 'application/json'},
  };
  if (body) init.body = typeof body === 'string' ? body : JSON.stringify(body);
  const r = await fetch(url, init);
  const text = await r.text();
  let parsed = null;
  try { parsed = JSON.parse(text); } catch (e) {}
  return {ok: r.ok, status: r.status, json: parsed,
          body: parsed ? null : text.slice(0, 4000)};
}
""" % SESSION_PATH


class FlowApiError(RuntimeError):
    pass


class FlowApi:
    """Authenticated access to Flow's backend, through a live Flow page.

    `page_provider` is any callable returning a Playwright page already on a
    `labs.google/fx` URL — in practice `_FlowSession._ensure_page`. Calls must
    be made on that session's own thread; `FlowProvider` already funnels work
    through a single-thread executor for exactly this reason.
    """

    def __init__(self, page_provider) -> None:
        self._page_provider = page_provider

    # -- plumbing ------------------------------------------------------

    def _call(self, method: str, path: str, body: Any = None) -> dict:
        page = self._page_provider()
        url = path if path.startswith("http") else API_BASE + path
        res = page.evaluate(_CALL_JS, [method, url, body])
        if not isinstance(res, dict):
            raise FlowApiError(f"unexpected bridge result for {path}")
        if not res.get("ok"):
            raise FlowApiError(
                f"{method} {path} → {res.get('status')}: "
                f"{(res.get('body') or res.get('json') or '')!s:.300}")
        return res.get("json") or {}

    def session_ok(self) -> dict:
        """Is the Flow session live? Returns {ok, expires, email} — no token."""
        page = self._page_provider()
        return page.evaluate(_GET_TOKEN_JS)

    # -- verified, free ------------------------------------------------

    def app_config(self) -> dict:
        return self._call("GET", PATHS["app_config"])

    def model_statuses(self) -> dict:
        """Live model health, e.g. veo_3_1_quality / veo_3_1_fast / …"""
        return self._call("GET", PATHS["model_statuses"])

    def user_settings(self) -> dict:
        return self._call("GET", PATHS["user_settings"])

    def healthy_model_keys(self) -> list[str]:
        try:
            rows = self.model_statuses().get("modelStatus") or []
        except FlowApiError:
            return []
        return [r.get("modelKey") for r in rows
                if str(r.get("status", "")).endswith("HEALTHY") and r.get("modelKey")]

    # -- not yet calibrated --------------------------------------------

    @staticmethod
    def is_calibrated() -> bool:
        """Whether the generate/upload payloads have been pinned to a live call.

        False today. Callers MUST branch on this instead of calling and hoping:
        a wrong body against a generation endpoint either 400s or, worse,
        succeeds while spending credits on something nobody asked for.
        """
        return False

    def upload_image(self, *_a, **_kw):
        raise FlowApiError(
            "upload_image is not calibrated yet — the path "
            f"({PATHS['upload_image']}) is known but the request body is not. "
            "Run a capture against a live Flow upload first.")

    def generate_video(self, *_a, **_kw):
        raise FlowApiError(
            "video generation is not calibrated yet. Known operations: "
            + ", ".join(OPERATIONS)
            + ". The first/last-frame path is generateVideoWithInterpolation.")
