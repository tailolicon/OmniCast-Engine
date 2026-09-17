# AGENTS.md -- OmniCast Engine

<!-- [VIBECODER-AGENTS-VERSION: v2.5.0] -->

## Global agent contracts

### Minecraft title + thumbnail packaging is mandatory

For **every Minecraft video task** — create, reup, localize, translate, dub, edit, remaster, republish, or upload — packaging is part of the video job, not an optional afterthought.

Before approving a Minecraft video for preview/publish, the agent MUST read and follow:

- `.agents/skills/minecraft-packaging/SKILL.md`
- `.agents/skills/minecraft-packaging/references/PLAYBOOK.md`
- `.agents/skills/minecraft-packaging/schemas/policy.json`

This contract applies even when the active workflow is Reup, Douyin Scout, Director, Remotion editing, a channel-specific profile, or another video skill.

Hard requirements:

1. **Never start from a generic image-generation prompt.** First understand the actual video/modpack and build an evidence-backed inventory of bosses, mobs, weapons, armor, structures, dimensions, mechanics, disasters, characters, rewards, and visually strong moments that really exist in the content.
2. **Classify the Minecraft packaging family before writing titles or thumbnail concepts.** Different genres require different packaging. Do not force boss/horror composition onto progression, 100-days, comedy, build/redstone, SMP/civilization, exploration, collection, or other formats.
3. **Use real content as the thumbnail's proof.** Prefer staged in-game capture, an actual source frame, or a render/composite of the actual game/mod asset. AI may improve presentation, lighting, background, effects, depth, or cleanup, but must not invent a boss, item, power, count, mechanic, location, or transformation that the video does not support.
4. **Title and thumbnail must complement rather than repeat each other.** Together they must create a clear promise, visible proof, stakes, and a curiosity gap.
5. **Generate genuinely different package concepts.** Variants must differ in click mechanism/visual story, not merely color, crop, text, or subject position.
6. **Research current comparable Minecraft winners when tools/quota are available.** Prefer recent vidIQ outliers, channel-relative breakout performance, and similar-thumbnail evidence over copying large-channel habits blindly. Distinguish concept-driven hits from recurring-series/IP hits.
7. **No unsupported clickbait.** Presentation may be dramatic; factual claims may not be fabricated. If evidence is insufficient, weaken the claim or choose a different hook.
8. **Run the packaging quality gates.** Do not declare the package finished merely because an image was rendered or a title was generated. The pair must pass the scoring/gating rules in the Minecraft packaging policy.
9. **Mobile readability is mandatory.** The thumbnail must still communicate its central conflict/reward at small feed size without requiring text reading.
10. **For reup/localization, re-package from the actual content rather than mechanically translating the source title/thumbnail.** Preserve real mod/entity identity and create a market-native package for the target language.

When these requirements conflict with speed, choose packaging quality and truthful evidence. The goal is not merely to produce a thumbnail and title; the goal is to produce the strongest truthful click proposition available in the actual Minecraft video.
