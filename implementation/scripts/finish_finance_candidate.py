"""Finance hospital pass — surgical edits on an approved-or-near build.

The regen roulette problem (live campaign 27/07: 76 → 73 → 81 → 77): every
fresh generation fixes one thing and perturbs another. When a build is already
strong, the cheaper, safer move is SURGERY: apply an explicit reviewed edit
table (delete scenes / rewrite voiceovers / rewrite visual prompts) to the best
variant, re-score with the same Critic, and only then run the fact ledger.
Mirror of the narrative channel's finish_candidate.py, for the claude_first
flow. The edit table is authored by the reviewing agent and lives next to the
research artifacts — every change is inspectable.

Usage:
    .venv/Scripts/python.exe scripts/finish_finance_candidate.py \
        --variant <path to variant_*.json> \
        --edits <path to edit table json> [--channel senior_wealth_us]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("OMNICAST_CLAUDE_BACKEND", "cli")


def rebuild_draft(scenes: list[dict], title: str):
    from omnicast.models.script import ScriptDraft, ScriptScene, ScriptSegment

    def _scene(s: dict) -> ScriptScene:
        return ScriptScene(
            voiceover=s["voiceover"], visual_prompt=s["visual_prompt"],
            sfx=s.get("sfx"), duration_s=float(s.get("duration_s") or 0),
            pace=s.get("pace", "normal"),
            pause_after_ms=int(s.get("pause_after_ms") or 0),
            emphasis=list(s.get("emphasis") or []))

    hook_scenes, outro_scenes = [], []
    seg_order: list[str] = []
    seg_scenes: dict[str, list] = {}
    for s in scenes:
        seg = s.get("segment", "")
        if seg == "HOOK":
            hook_scenes.append(_scene(s))
        elif seg == "OUTRO":
            outro_scenes.append(_scene(s))
        else:
            if seg not in seg_scenes:
                seg_order.append(seg)
                seg_scenes[seg] = []
            seg_scenes[seg].append(_scene(s))

    segments = []
    for i, name in enumerate(seg_order):
        scs = seg_scenes[name]
        content = " ".join(sc.voiceover for sc in scs)
        segments.append(ScriptSegment(
            index=i, heading=name, content=content,
            estimated_duration_seconds=int(sum(
                sc.duration_s or len(sc.voiceover.split()) / 2.5 for sc in scs)),
            scenes=scs))
    hook = " ".join(sc.voiceover for sc in hook_scenes)
    outro = " ".join(sc.voiceover for sc in outro_scenes)
    words = sum(len(sc.voiceover.split()) for sc in
                hook_scenes + outro_scenes
                + [x for seg in segments for x in seg.scenes])
    return ScriptDraft(
        variant_id="hospital", brief_title=title, hook=hook,
        hook_scenes=hook_scenes, segments=segments, outro=outro,
        outro_scenes=outro_scenes, word_count=words,
        estimated_duration_seconds=int(words / 2.5))


async def ledger_only(product_dir: Path, channel_id: str) -> int:
    """Re-run just the fact ledger on an already-approved hospital product."""
    from datetime import datetime, timezone

    from omnicast.agents.fact_ledger_agent import FactLedgerAgent
    from omnicast.compliance.fact_ledger import gate_fact_ledger, render_markdown
    from omnicast.config.niches import get_niche_config
    from omnicast.pipeline.steps import _llm_client
    from omnicast.storage import products as _products

    raw_cfg = json.loads((ROOT / "channels" / f"{channel_id}.json")
                         .read_text(encoding="utf-8"))
    niche_cfg = get_niche_config(*raw_cfg["niche_config_key"].split(".", 1))
    script_txt = (product_dir / "script.txt").read_text(encoding="utf-8")
    llm_claude = _llm_client("anthropic", db_path=ROOT / "output" / "vault.db")
    ledger = await FactLedgerAgent(llm=llm_claude).execute(
        script_txt, proof_sources=list(niche_cfg.proof_sources),
        current_year=datetime.now(timezone.utc).year, model_label="claude")
    report = gate_fact_ledger(script_txt, ledger)
    print(f"FACT LEDGER: {report.covered_count}/{report.claim_count} covered, "
          f"passed={report.passed}")
    for n in report.notes[:6]:
        print("  ", n[:150])
    (product_dir / "fact_ledger.json").write_text(json.dumps({
        "ledger": ledger.model_dump(mode="json"),
        "gate": report.model_dump(mode="json")}, indent=1, ensure_ascii=False),
        encoding="utf-8")
    (product_dir / "fact_ledger.md").write_text(
        render_markdown(ledger, report), encoding="utf-8")
    _products.write_meta(product_dir, content_locked=bool(report.passed),
                         production_ready=bool(report.passed),
                         fact_ledger_gate=report.model_dump(mode="json"))
    print(f"production_ready={report.passed}")
    return 0 if report.passed else 1


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant")
    ap.add_argument("--edits")
    ap.add_argument("--channel", default="senior_wealth_us")
    ap.add_argument("--ledger-only", default="",
                    help="product dir: skip edits+critic, redo the fact ledger")
    args = ap.parse_args()
    if args.ledger_only:
        return await ledger_only(Path(args.ledger_only), args.channel)
    if not (args.variant and args.edits):
        ap.error("--variant and --edits are required unless --ledger-only")

    variant = json.loads(Path(args.variant).read_text(encoding="utf-8"))
    edits = json.loads(Path(args.edits).read_text(encoding="utf-8"))
    scenes = list(variant["scenes"])

    # 1. Apply the edit table (indices refer to the ORIGINAL order).
    for idx_s, vo in edits.get("voiceover_replacements", {}).items():
        scenes[int(idx_s)]["voiceover"] = vo
    for idx_s, vis in edits.get("visual_replacements", {}).items():
        scenes[int(idx_s)]["visual_prompt"] = vis
    drop = set(edits.get("delete_scenes", []))
    scenes = [s for i, s in enumerate(scenes) if i not in drop]
    print(f"edits applied: {len(edits.get('voiceover_replacements', {}))} VO, "
          f"{len(edits.get('visual_replacements', {}))} visual, "
          f"{len(drop)} deleted -> {len(scenes)} scenes")

    # PAUSE CLAMP BEFORE SCORING — the pipeline clamps at sidecar-write time,
    # so the shipped prosody has ~0.6 pauses/min; scoring the unclamped scenes
    # cost pacing_compliance a point of parity (hospital run 1: "12 pauses,
    # double the benchmark" on scenes the clamp would have fixed anyway).
    est_min = max(1.0, sum(len(s["voiceover"].split()) for s in scenes) / 150.0)
    keep = max(3, round(est_min * 0.6))
    big = sorted((i for i, s in enumerate(scenes)
                  if (s.get("pause_after_ms") or 0) >= 400),
                 key=lambda i: -scenes[i]["pause_after_ms"])
    for i in big[keep:]:
        scenes[i]["pause_after_ms"] = 250
    over = [i for i, s in enumerate(scenes) if len(s["voiceover"].split()) > 25]
    print(f"pauses>=400ms after clamp: {min(len(big), keep)}; "
          f"over-25-word scenes: {len(over)} {over[:6]}")

    topic = variant.get("topic", "")
    draft = rebuild_draft(scenes, topic)
    print(f"rebuilt draft: {draft.word_count} words, "
          f"{len(draft.segments)} segments")

    # 2. Machine scan must be clean BEFORE we spend a critic call.
    from omnicast.agents.rubrics import finance_explainer as fe
    full_text = " ".join(s["voiceover"] for s in scenes)
    flags, caps = fe.finance_slop_signals(full_text)
    for f in flags:
        print("  MACHINE FLAG:", f[:140])
    if caps:
        print("  MACHINE CAPS:", caps)

    # 3. Critic re-score (same judge as the pipeline).
    from omnicast.agents.critic import CriticAgent
    from omnicast.config.channel import ChannelProfile
    from omnicast.config.niches import get_niche_config
    from omnicast.config.settings import get_settings
    from omnicast.models.script import TopicBrief
    from omnicast.pipeline.steps import _llm_client

    raw_cfg = json.loads((ROOT / "channels" / f"{args.channel}.json")
                         .read_text(encoding="utf-8"))
    channel = ChannelProfile(**raw_cfg)
    _nk = raw_cfg["niche_config_key"].split(".", 1)
    niche_cfg = get_niche_config(*_nk)
    settings = get_settings()
    vault_path = ROOT / "output" / "vault.db"
    llm_pro = _llm_client("deepseek", model=settings.deepseek_pro_model,
                          db_path=vault_path)
    brief = TopicBrief(
        title=topic, niche=channel.niche, market=channel.market,
        source="manual", angle="pain_hook",
        target_duration_min=channel.target_duration_min,
        brand_voice=channel.brand_voice, channel_id=channel.channel_id,
        sub_niche=channel.sub_niche,
        **TopicBrief.scope_fields_from_channel(channel, title=topic))
    brand = {"brand_voice": channel.brand_voice,
             "tone": raw_cfg.get("tone", ""),
             "hook_format": raw_cfg.get("hook_format", ""),
             "voice_persona": raw_cfg.get("voice_persona", "")}
    critic = CriticAgent(llm=llm_pro)
    fb = await critic.execute(draft, brief, niche_cfg=niche_cfg,
                              channel_brand=brand)
    print(f"\nCRITIC: {fb.total_score}/100 (VO {fb.voiceover_score}/70, "
          f"prod {fb.production_score}/30) approved={fb.approved}")
    for d in fb.dimensions:
        print(f"  {d.name:22s} {d.score:>3}/{d.max_score:<3} {d.feedback[:70]}")
    for r in fb.rejection_reasons[:6]:
        print("  REASON:", r[:130])
    if not fb.approved:
        print("NOT APPROVED — hospital pass does not promote. Fix and retry.")
        return 1

    # 4. Fact ledger (fail-closed) + product write.
    from datetime import datetime, timezone

    from omnicast.agents.fact_ledger_agent import FactLedgerAgent
    from omnicast.compliance.fact_ledger import gate_fact_ledger, render_markdown
    from omnicast.storage import products as _products

    llm_claude = _llm_client("anthropic", db_path=vault_path)
    script_txt = (draft.hook + "\n\n" + "".join(
        f"[{seg.heading}]\n{seg.content}\n\n" for seg in draft.segments)
        + draft.outro)
    ledger = await FactLedgerAgent(llm=llm_claude).execute(
        script_txt, proof_sources=list(niche_cfg.proof_sources),
        current_year=datetime.now(timezone.utc).year, model_label="claude")
    report = gate_fact_ledger(script_txt, ledger)
    print(f"\nFACT LEDGER: {report.covered_count}/{report.claim_count} covered, "
          f"passed={report.passed}")
    for n in report.notes[:5]:
        print("  ", n[:140])

    pd = _products.new_product_dir(args.channel, topic + " (hospital)")
    _products.script_path(pd).write_text(script_txt, encoding="utf-8")
    (pd / "fact_ledger.json").write_text(json.dumps({
        "ledger": ledger.model_dump(mode="json"),
        "gate": report.model_dump(mode="json")}, indent=1, ensure_ascii=False),
        encoding="utf-8")
    (pd / "fact_ledger.md").write_text(render_markdown(ledger, report),
                                       encoding="utf-8")
    # Prosody sidecar with the pipeline's pause clamp.
    est_min = max(1.0, sum(len(s["voiceover"].split()) for s in scenes) / 150.0)
    k = max(3, round(est_min * 0.6))
    big = sorted((i for i, s in enumerate(scenes)
                  if (s.get("pause_after_ms") or 0) >= 400),
                 key=lambda i: -scenes[i]["pause_after_ms"])
    for i in big[k:]:
        scenes[i]["pause_after_ms"] = 250
    (pd / "script.json").write_text(json.dumps({
        "topic": topic, "channel_id": args.channel,
        "variant_id": "hospital", "score": fb.total_score,
        "scenes": scenes}, indent=2, ensure_ascii=False), encoding="utf-8")
    _products.write_meta(
        pd, channel=args.channel, topic=topic, slug=pd.name,
        stage="script", script="script.txt", best_variant="hospital",
        score=fb.total_score, approved=True, script_approved=True,
        content_locked=bool(report.passed),
        production_ready=bool(report.passed), release_gate_version=1,
        script_sha256=hashlib.sha256(script_txt.encode()).hexdigest(),
        fact_ledger_gate=report.model_dump(mode="json"),
        hospital_source=str(args.variant))
    print(f"\nPRODUCT: {pd}")
    print(f"production_ready={report.passed}")
    return 0


if __name__ == "__main__":
    start = time.perf_counter()
    rc = asyncio.run(main())
    print(f"done in {time.perf_counter() - start:.1f}s")
    raise SystemExit(rc)
