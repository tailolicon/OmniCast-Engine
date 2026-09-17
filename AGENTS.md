# AGENTS.md -- OmniCast Engine

<!-- [VIBECODER-AGENTS-VERSION: v2.5.0] -->

## Global agent contracts

### Minecraft title + thumbnail packaging is mandatory

For **every Minecraft video task** — create, reup, localize, translate, dub, edit, remaster, republish, or upload — packaging is part of the video job, not an optional afterthought.

### FIRST-ACTION REQUIREMENT FOR MINECRAFT TASKS

If the user asks for any Minecraft video task, **before planning the work, choosing a title, generating a thumbnail, running the reup pipeline, or making any creative packaging/audio/edit decision**, the agent MUST explicitly read the full contents of these files from the active OmniCast workspace:

Packaging:
- `.agents/skills/minecraft-packaging/SKILL.md`
- `.agents/skills/minecraft-packaging/references/PLAYBOOK.md`
- `.agents/skills/minecraft-packaging/schemas/policy.json`

Audio/editing:
- `.agents/skills/minecraft-editing-audio/SKILL.md`
- `.agents/skills/minecraft-editing-audio/references/PLAYBOOK.md`
- `.agents/skills/minecraft-editing-audio/schemas/policy.json`

Do not rely on memory, a summary, a prior chat, or the fact that these paths are listed here. The files must be read in the current session before the Minecraft task proceeds. If the active workspace does not contain them, stop the affected Minecraft step and report that the live OmniCast workspace is missing the required policy rather than silently falling back to generic title/thumbnail/audio/edit behavior.

This contract applies even when the active workflow is Reup, Douyin Scout, Director, Remotion editing, a channel-specific profile, or another video skill.

Packaging hard requirements:

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

Audio/edit hard requirements:

1. **Edits and SFX must be caused by semantic events, never fixed timers.** No periodic zooms, whooshes, impacts, meme sounds, or track changes.
2. **Build a story-state map before choosing BGM.** Music must follow setup, exploration, comedy, curiosity, progression, danger, horror, chase, combat, boss, victory, failure, and aftermath states as appropriate.
3. **Preserve native Minecraft/game audio whenever it carries physical or gameplay information.** Editorial SFX are punctuation, not a replacement for game sound.
4. **Localized/reup video must suppress original-language speech using source-speech activity, not target-dub activity.** A pause in the target dub must never expose continuing source speech.
5. **BGM must remain perceptible while dialogue stays intelligible.** Use dynamic ducking/level changes and stems where useful rather than burying music globally.
6. **No global scene-change pop/boom mechanism.** Clean cuts and sound bridges are valid defaults; transitions get SFX only when the transition itself has editorial meaning.
7. **Edit density must breathe.** Ordinary traversal/exposition remains restrained; reveal/comedy/action/boss beats may spike; aftermath must be allowed to drop.
8. **Headphone and small-speaker QA are mandatory.** Reject source-speech residuals, separator buzz/warble, pumping, tiny pops, inaudible BGM, or SFX that mask dialogue.
9. **Persist an edit/audio receipt** showing source speech mask, BGM state map, SFX/edit events, anti-spam gate, game-audio preservation, and artifact QA.

When these requirements conflict with speed, choose packaging/audio quality and truthful evidence. The goal is not merely to produce a thumbnail, title, dub, or edited timeline; the goal is to produce a strong, coherent Minecraft video whose click proposition, music, native sound, SFX, and editing all respond to what is actually happening in the content.
