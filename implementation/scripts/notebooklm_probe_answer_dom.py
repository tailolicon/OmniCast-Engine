"""Find the element that holds ONLY the model's answer.

`.chat-message-pair` was chosen from a live probe as "the current answer". It
is not: it is the whole exchange. Every response artifact this project saved
therefore begins with our own prompt, and the source-verification parser read
the question's `NO_TRANSCRIPT` token as the model's verdict ten times in a row.
The reasoning trace ("Thoughts") lives in the same pair.

This dumps the structure of the last exchange so the selector table can name
the answer node instead of guessing at it. Read-only: it opens the notebook,
reads the DOM, writes a JSON, and closes. It sends nothing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from omnicast.analytics.notebook_research.browser_provider import (  # noqa: E402
    NotebookLMWorker,
)
from omnicast.analytics.notebook_research.manifest import RunManifest  # noqa: E402

JS = """
() => {
  const pairs = document.querySelectorAll('.chat-message-pair');
  if (!pairs.length) return {error: 'no .chat-message-pair found'};
  const pair = pairs[pairs.length - 1];
  const walk = (el, depth) => {
    if (depth > 4) return null;
    const kids = [...el.children].map(c => walk(c, depth + 1)).filter(Boolean);
    return {
      tag: el.tagName.toLowerCase(),
      cls: (el.className || '').toString().slice(0, 120),
      role: el.getAttribute('role') || '',
      textHead: (el.innerText || '').trim().slice(0, 90),
      len: (el.innerText || '').trim().length,
      children: kids,
    };
  };
  return {pairs: pairs.length, tree: walk(pair, 0)};
}
"""


def main() -> int:
    channel = sys.argv[1] if len(sys.argv) > 1 else "senior_wealth_us"
    key = sys.argv[2] if len(sys.argv) > 2 else "SFR_280_URL_FIRST"
    base = ROOT / "output" / "research" / channel / "notebooklm" / "runs"
    manifest = RunManifest.load_or_create(base, channel, key)
    if not manifest.notebook_url:
        print("REJECTED: manifest has no notebook_url")
        return 1

    profile = ROOT / "output" / "notebooklm_profile"
    with NotebookLMWorker(profile_dir=profile, work_dir=base,
                          headless=False) as worker:
        worker.auth_check()
        worker.resolve_notebook(manifest.notebook_key, manifest.notebook_url)
        worker.page.wait_for_timeout(4000)
        data = worker.page.evaluate(JS)

    out = base / "answer_dom_probe.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
