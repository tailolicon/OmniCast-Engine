---
name: minecraft-packaging
description: "Mandatory evidence-first title + thumbnail packaging system for any Minecraft video created, reuploaded, localized, dubbed, edited, or published by OmniCast. Classifies the video genre, inventories real game/mod assets, researches current winners, creates multiple truthful click concepts, and gates the final title-thumbnail pair."
allowed-tools: ["Read", "Write", "Edit", "Grep", "Glob", "Bash", "Task", "AskUserQuestion", "WebFetch"]
user-invocable: false
---

# Minecraft Packaging Skill

This skill owns the **click proposition** for Minecraft videos: title + thumbnail concept + evidence + variants + quality gate.

It is mandatory for Minecraft create/reup/localize/dub/edit/publish workflows. Packaging is not a cosmetic final step and must not be reduced to "write a catchy title" or "prompt an AI thumbnail".

Read before doing work:

- `references/PLAYBOOK.md` — creative decision system and genre formulas.
- `schemas/policy.json` — machine-readable gates, score weights, and output expectations.

## Core law

**Actual content first; packaging second; rendering last.**

Never invent the hook first and then force the video to look like it contains it. Find the strongest real hook already supported by the video/modpack, then dramatize its presentation truthfully.

The universal packaging equation is:

`PROMISE + PROOF + STAKES + CURIOSITY`

- **Promise:** what experience/result does the viewer get?
- **Proof:** what visible object/event/mechanic proves the promise is real?
- **Stakes:** why does the outcome matter or feel difficult/extreme?
- **Curiosity:** what unanswered question makes the viewer need the click?

## Required workflow

### Phase 1 — Understand the content

Inspect enough of the source video/script/modpack/job evidence to understand what actually happens. For reups/localizations, do not rely only on the source title or source thumbnail.

Build an evidence inventory containing, when applicable:

- bosses / horror mobs / enemies;
- weapons / armor / tools / upgrade tiers;
- player abilities / transformations / morphs;
- structures / bases / dimensions / biomes;
- disasters / environmental rules / survival constraints;
- NPCs / villagers / hunters / armies / factions;
- rare items / loot / rewards / collections;
- challenges / timers / counts / days / lives / rules;
- recurring characters / series IP;
- the strongest visual moments and their timestamps;
- mod or modpack identity when known.

Every proposed thumbnail hero asset and every strong factual title claim must trace back to this evidence.

### Phase 2 — Classify the packaging family

Assign one primary family and optional secondary family. Do not use one visual formula for every Minecraft video.

Primary families:

1. `boss_horror_threat`
2. `progression_upgrade_evolution`
3. `extreme_scale_swarm_hunters`
4. `survival_100_days_apocalypse`
5. `story_series_recurring_ip`
6. `comedy_troll_chaos`
7. `build_redstone_invention`
8. `exploration_secret_rare_discovery`
9. `collection_completion_capture`
10. `pvp_smp_civilization_war`
11. `rule_twist_minecraft_but`
12. `mod_showcase_mechanic_experiment`

Use the formulas and anti-patterns in `references/PLAYBOOK.md` for the chosen family.

### Phase 3 — Research the live market when possible

When vidIQ/web tools and quota are available, inspect current comparable Minecraft videos rather than relying only on static memory.

Research should include a useful subset of:

- recent Minecraft outliers;
- current high-VPH videos in the same packaging family;
- the target channel's recent and top-performing videos;
- similar thumbnails for the strongest relevant seed;
- current title/thumbnail change history when useful.

Prefer **channel-relative breakout/outlier evidence** over raw views alone. A 1M-view video on a 20K-subscriber channel can be more informative than a routine 3M-view upload on a 20M-subscriber channel.

Do not copy a competitor package. Extract mechanisms: scale contrast, threat, progression, scarcity, reversal, impossible odds, discovery, transformation, social conflict, etc.

### Phase 4 — Generate hooks before titles

Generate at least 12 hook candidates for normal jobs and up to 20 for high-value uploads.

Hooks must be based on verified content. Rank them by:

- instant understandability;
- visual spectacle;
- stakes;
- novelty;
- recognizable/interesting real asset;
- progression/transformation potential;
- curiosity gap;
- emotional polarity;
- target-market fit.

Keep the strongest 3 **distinct click mechanisms**, not three rewrites of the same idea.

### Phase 5 — Build title-thumbnail pairs, not titles and thumbnails separately

For each shortlisted concept, define:

- title premise;
- thumbnail visual story;
- hero asset(s);
- supporting asset(s);
- what the title says;
- what the thumbnail says without text;
- the unanswered question created by combining them;
- the evidence supporting every factual claim.

The title and thumbnail must **complement** each other. Avoid simply writing the same noun/claim in both places.

### Phase 6 — Acquire thumbnail evidence/assets

Preferred asset order:

1. staged in-game screenshot using the actual mod/entity/item;
2. strong frame from the actual source video;
3. render of the actual model/texture/skin/entity;
4. composite made from actual verified game/mod assets;
5. AI-generated support elements only for presentation/background/effects when they do not alter factual identity.

AI is an art director, not a source of fictional game facts.

Allowed dramatic presentation includes:

- stronger camera perspective;
- closer boss framing;
- cinematic lighting;
- depth separation;
- particles / impact effects;
- cleaner background;
- pose selection;
- truthful HUD/health/progression cues;
- compositing multiple actual supported elements.

Not allowed without evidence:

- invented boss/entity;
- invented weapon/armor/power;
- invented dimension/structure;
- invented transformation;
- fake numerical scale;
- mechanic that never happens;
- presenting a source creator/player identity as the uploader's own gameplay when it is not.

### Phase 7 — Produce three meaningfully different variants

Default final candidate set: 3 package variants.

Variants must change the **reason to click**, for example:

- Variant A: threat / impossible confrontation;
- Variant B: progression / final power;
- Variant C: mystery / discovery / reversal.

Do not count these as meaningful variants:

- left vs right placement only;
- different outline color;
- slightly different crop;
- same composition with different text;
- same concept with a different glow.

### Phase 8 — Quality gates

Score title, thumbnail, and pair using `schemas/policy.json`.

No package is considered done if any hard gate fails.

Mandatory hard gates include:

- all strong factual claims have evidence;
- hero asset really exists in the content/modpack;
- thumbnail communicates at small/mobile size;
- no generic AI-fabricated substitute for a real mod asset;
- one dominant visual idea, not clutter;
- title and thumbnail complement rather than duplicate;
- package matches the actual genre/family;
- click promise is paid off by the video;
- candidate variants are conceptually different.

If a package scores poorly, return to hook selection or asset selection. Do not polish a fundamentally weak concept forever.

### Phase 9 — Publish/test/learn

When the publishing surface supports it, use up to 3 title/thumbnail combinations for A/B testing. Optimize for qualified watch time and downstream retention, not CTR in isolation.

Record the winner and the reason it likely won so channel-specific style packs can learn over time.

## Reup/localization contract

For Douyin/Bilibili/other-source Minecraft reups/localizations:

1. Understand the actual source content first.
2. Treat the source title/thumbnail as a lead, not truth.
3. Rebuild packaging for the target market instead of literal translation.
4. Preserve the exact identity of real mods, bosses, items, characters, and mechanics.
5. Verify hyperbolic numbers or claims before using them.
6. If the source package is strong, extract its mechanism but create an original market-native execution.
7. If the source package is weak, ignore it and package from the strongest real moment/mechanic in the video.

## Output contract

A completed Minecraft packaging pass should be able to provide this information, whether persisted as JSON/sidecars or carried in the job state:

```json
{
  "primary_family": "boss_horror_threat",
  "secondary_family": "progression_upgrade_evolution",
  "evidence_inventory": [],
  "market_research": [],
  "hook_candidates": [],
  "shortlist": [
    {
      "concept": "...",
      "title_candidates": [],
      "thumbnail_story": "...",
      "hero_assets": [],
      "evidence": [],
      "scores": {}
    }
  ],
  "selected_package": {},
  "hard_gates": {},
  "ab_variants": []
}
```

## Completion condition

Do not finish with "thumbnail generated" or "title generated".

Finish only when there is a **truthful, evidence-backed, genre-appropriate, mobile-readable, high-curiosity title-thumbnail pair** plus strong alternatives suitable for A/B testing.
