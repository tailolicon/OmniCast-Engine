"""Competitor research — one command, two providers, evidence-gated.

    python scripts/competitor_research.py --channel senior_wealth_us \
        --providers native,notebooklm-browser --resume --reconcile --promote-if-valid

PROVIDERS
  native              the production path: analytics.competitor_intel
                      .learn_for_channel (channel-wide + every declared pillar)
                      → vault → intel_gate. Always safe to run.
  notebooklm-browser  CHALLENGER: Playwright worker (notebook_research/) drives
                      NotebookLM over the exported packets, captures responses
                      + citations. AUTH_REQUIRED or UI failure NEVER stops the
                      native provider — it logs and moves on.

PROMOTION: NotebookLM output never writes to the vault directly. Findings that
parse into the CohortFinding schema go through competitor_evidence
.validate_findings (code-level checks); --promote-if-valid stores the accepted
set as an evidence artifact next to the run report. Compiling them into a
playbook row stays with the native learner until the reconciler ships —
stated here so the gap is a work item, not a surprise.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _load_channel(channel_id: str):
    from omnicast.config.channel import ChannelProfile
    raw = json.loads((ROOT / "channels" / f"{channel_id}.json")
                     .read_text(encoding="utf-8"))
    return ChannelProfile(**raw), raw


def run_native(channel, raw_cfg: dict, report: dict) -> None:
    from omnicast.analytics.competitor_intel import learn_for_channel

    async def _run():
        out = {}
        out["channel_wide"] = await learn_for_channel(channel)
        for p in raw_cfg.get("content_pillars") or []:
            pid = p.get("pillar_id", "")
            try:
                out[pid] = await learn_for_channel(channel, pillar_id=pid)
            except Exception as exc:  # noqa: BLE001
                out[pid] = {"error": str(exc)[:200]}
        return out

    results = asyncio.run(_run())
    report["native"] = {
        k: (v if isinstance(v, dict) else
            {"summary": str(v)[:200]} if v else None)
        for k, v in results.items()}


def run_notebooklm(channel_id: str, report: dict, headless: bool) -> None:
    from omnicast.analytics.notebook_research.browser_provider import (
        AuthRequired,
        NotebookLMWorker,
        run_notebook_stage,
    )
    from omnicast.analytics.notebook_research.manifest import RunManifest

    res = ROOT / "output" / "research" / channel_id
    pilot = res / "notebooklm" / "pilot"
    if not (pilot / "sources").exists():
        report["notebooklm"] = {"status": "skipped",
                                "reason": "no exported packets — run notebooklm_export.py"}
        return
    profile = ROOT / "output" / "notebooklm_profile"
    if not profile.exists():
        report["notebooklm"] = {"status": "auth_required",
                                "reason": "profile missing — run scripts/notebooklm_login.py once"}
        return
    # PRE-FLIGHT: a Chrome already holding this profile makes a second launch
    # open about:blank and hang (live run 3, 2026-07-26). Refuse instead —
    # never auto-kill someone else's session.
    try:
        import subprocess
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "@(Get-CimInstance Win32_Process -Filter \"Name = 'chrome.exe'\" | "
             "Where-Object { $_.CommandLine -match 'notebooklm_profile' }).Count"],
            capture_output=True, text=True, timeout=30)
        if int((out.stdout or "0").strip() or 0) > 0:
            report["notebooklm"] = {
                "status": "profile_locked",
                "reason": "another Chrome holds output/notebooklm_profile — close "
                          "it (or kill stale chrome.exe) and rerun"}
            return
    except Exception:
        pass

    base = res / "notebooklm" / "runs"
    manifest = RunManifest.load_or_create(base, channel_id,
                                          "SFR_CONTROLLED_CROSS_CHANNEL")
    cohort = json.loads((res / "cohort_packet.json").read_text(encoding="utf-8"))
    roles = {v["video_id"]: v["role"]
             for v in cohort["winners"] + cohort["controls"]}
    packets = []
    for f in sorted((pilot / "sources").glob("*.md")):
        vid = f.stem.split("_")[-1]
        packets.append((vid, roles.get(vid, ""), f))
    manifest.register_sources(packets)
    prompts = {}
    for pid, fname in (("source_audit", "1_source_audit.md"),
                       ("pair_comparison", "3_pair_comparison.md"),
                       ("cohort_synthesis", "4_cohort_synthesis.md")):
        prompts[pid] = (pilot / "prompts" / fname).read_text(encoding="utf-8")
        manifest.register_prompt(pid, prompts[pid])
    manifest.save(base)

    try:
        with NotebookLMWorker(profile_dir=profile, work_dir=base,
                              headless=headless) as worker:
            run_notebook_stage(manifest, base, worker, prompts)
        report["notebooklm"] = {
            "status": manifest.state.value,
            "sources": len(manifest.sources),
            "prompts_complete": sum(1 for j in manifest.prompts
                                    if j.status == "complete"),
        }
    except AuthRequired as exc:
        report["notebooklm"] = {"status": "auth_required", "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 — challenger must not kill the run
        report["notebooklm"] = {"status": "failed", "reason": str(exc)[:300],
                                "artifacts": str(base / "artifacts")}


def validate_and_maybe_promote(channel_id: str, report: dict,
                               promote: bool) -> None:
    from omnicast.analytics.competitor_evidence import (
        CohortFinding,
        validate_findings,
    )

    res = ROOT / "output" / "research" / channel_id
    findings_file = (res / "notebooklm" / "runs" / "responses"
                     / "cohort_synthesis.findings.json")
    if not findings_file.exists():
        report["validation"] = {"status": "no_structured_findings",
                                "note": "NotebookLM answers are prose until the parse "
                                        "step lands — nothing to validate yet"}
        return
    cohort = json.loads((res / "cohort_packet.json").read_text(encoding="utf-8"))
    pairs = {c["matched_to"]: c["video_id"] for c in cohort["controls"]
             if c.get("matched_to")}
    transcripts = {}
    for f in (res / "transcripts").glob("*_*.txt"):
        transcripts[f.stem.split("_", 1)[1]] = f.read_text(encoding="utf-8")
    findings = [CohortFinding(**d) for d in
                json.loads(findings_file.read_text(encoding="utf-8"))]
    vreport = validate_findings(findings, matched_pairs=pairs,
                                transcripts=transcripts)
    report["validation"] = vreport.model_dump(mode="json")
    if promote and vreport.accepted:
        out = res / "notebooklm" / "runs" / "responses" / "accepted_findings.json"
        out.write_text(json.dumps(
            [f.model_dump(mode="json") for f in findings
             if f.finding_id in vreport.accepted],
            ensure_ascii=False, indent=1), encoding="utf-8")
        report["promotion"] = {"stored": str(out),
                               "note": "playbook compilation stays with the native "
                                       "learner until the reconciler ships"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", default="senior_wealth_us")
    ap.add_argument("--providers", default="native")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--reconcile", action="store_true")
    ap.add_argument("--promote-if-valid", action="store_true")
    ap.add_argument("--headed", action="store_true",
                    help="show the browser window (default headless)")
    args = ap.parse_args()

    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    channel, raw_cfg = _load_channel(args.channel)
    report: dict = {"channel": args.channel, "providers": providers,
                    "started_at": datetime.now(timezone.utc).isoformat()}

    if "native" in providers:
        try:
            run_native(channel, raw_cfg, report)
        except Exception as exc:  # noqa: BLE001
            report["native"] = {"error": str(exc)[:300]}
    if "notebooklm-browser" in providers:
        run_notebooklm(args.channel, report, headless=not args.headed)

    validate_and_maybe_promote(args.channel, report, args.promote_if_valid)

    if args.reconcile:
        nb = report.get("notebooklm", {})
        report["reconcile"] = {
            "native_scopes": sorted(k for k, v in (report.get("native") or {}).items() if v),
            "notebooklm_status": nb.get("status", "not_run"),
            "note": "finding-level reconciliation lands with the structured parse step",
        }

    out = (ROOT / "output" / "research" / args.channel
           / f"research_run_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1, default=str),
                   encoding="utf-8")
    print(json.dumps({k: (v if not isinstance(v, dict) else
                          {kk: vv for kk, vv in list(v.items())[:4]})
                      for k, v in report.items()}, ensure_ascii=False, indent=1,
                     default=str))
    print(f"\nRun report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
