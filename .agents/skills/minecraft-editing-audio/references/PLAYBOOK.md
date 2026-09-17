# Minecraft BGM, SFX & Edit Playbook

## Purpose

This playbook defines how OmniCast should score, sound-design, and edit Minecraft videos. It is designed for original videos and localized/reup workflows where target-language dialogue is rebuilt while native game audio, music, and effects must remain coherent.

The goal is not maximal edit density. The goal is **controlled contrast**: ordinary moments feel alive, important beats feel stronger, and climaxes have somewhere to escalate from.

Professional editing references consistently support the same base principles: dialogue clarity comes first; music should duck under speech and rise in gaps; music changes should follow narrative/emotional state rather than arbitrary timing; sound effects should support story events; music phrase boundaries and sound bridges make transitions feel intentional; and using stems gives better control over dialogue/music interaction. These principles are adapted below specifically for Minecraft.

---

# 1. The hierarchy of sound

In spoken Minecraft videos, mix priorities are:

1. **Target voice / dialogue** — the story must be understood.
2. **Native game information** — important footsteps, hits, mobs, chest/inventory, gunfire, block breaking, explosions, ambience.
3. **Editorial BGM** — emotional/pacing layer.
4. **Editorial SFX** — punctuation, not wallpaper.

A video can sound busy while still being dead if game audio is destroyed and every event is replaced by generic whooshes/booms.

The native Minecraft sound layer is valuable because it proves actions are physically happening in the game world. Preserve it whenever possible.

---

# 2. Never choose BGM by timestamp; choose by story state

Before music selection, produce a `story_state_map` over the timeline.

Core states:

- `hook_cold_open`
- `setup_exposition`
- `exploration_travel`
- `comedy_light`
- `discovery_curiosity`
- `reveal_big`
- `progression_upgrade`
- `danger_build`
- `horror_stalker`
- `chase_action`
- `combat_normal`
- `boss_reveal`
- `boss_combat`
- `victory_reward`
- `failure_loss`
- `aftermath_breathing`
- `montage_progress`

A music change should normally require one of:

- emotional state changed;
- stakes changed;
- location/world identity changed strongly;
- a new progression phase began;
- a reveal/payoff occurred;
- a joke intentionally breaks the current tone;
- a climax begins or ends.

Do **not** change music merely because a scene cut occurred.

---

# 3. BGM state map

The following values are creative starting points, not fixed laws. BPM is a useful search/filter signal; perceived energy matters more than literal BPM.

## hook_cold_open

Purpose: make the first promise feel immediate.

Music character:

- medium/high energy or immediate tension;
- recognizable pulse quickly;
- little or no long intro;
- avoid slow 10-second fade-ins.

Edit treatment:

- enter close to an interesting musical phrase/downbeat;
- strong reveal may receive one impact;
- title text/logo should not interrupt the hook unless needed.

Do not maintain this intensity for minutes; cold-open energy needs somewhere to fall afterward.

## setup_exposition

Purpose: make explanation move without stealing attention.

Music character:

- sparse instrumental;
- low melodic complexity;
- little/no vocals;
- light groove, lo-fi, soft electronic, playful orchestral, or ambient depending on video identity;
- approximately low-to-medium perceived energy.

Editing:

- low density;
- restrained punch-ins/callouts only for information;
- no constant impact SFX.

## exploration_travel

Purpose: preserve flow and world feel.

Music character:

- relaxed groove / adventurous ambient;
- wider stereo texture;
- lower rhythmic urgency;
- allow game ambience to remain audible.

Editing:

- longer shots are allowed;
- occasional map/location cue;
- native footsteps/environment should carry some rhythm.

## comedy_light

Purpose: create playful expectation without telling the joke before it lands.

Music character:

- light quirky/plucky/groovy bed;
- do not use a comedy sting continuously.

Punchline technique:

1. reduce or stop music briefly before the punchline when useful;
2. let dialogue/visual land;
3. add one short reaction sting, impact, record-stop, UI error, or silence;
4. resume or switch music only after the joke beat.

Silence can be funnier than another meme SFX.

## discovery_curiosity

Purpose: tell the viewer that something matters before fully revealing it.

Music character:

- sparse pulse;
- pluck, clock-like element, subtle synth, pizzicato, mystery texture;
- restrained low end.

Editing:

- slow punch-in / highlight / focus isolation;
- do not reveal with a giant impact too early.

## reveal_big

Purpose: pay off curiosity.

Music technique:

- prepare with a short reduction, filter, held note, or riser;
- hit/reveal on a musically useful accent/downbeat;
- then move into the next state rather than looping the reveal sting.

Editing:

- one decisive zoom/hold/highlight is stronger than five effects;
- 0.2–0.5 s visual hold can help a major reveal register when the source pacing is too fast.

## progression_upgrade

Purpose: sell power growth.

Music character:

- rhythmic, forward-driving;
- moderate/high energy;
- clear phrase structure;
- suitable for montage edits.

Editing:

- group upgrades into musical phrases rather than cutting every beat;
- strongest item/form should receive the strongest cue;
- use UI ticks/light impacts for intermediate upgrades, saving bass hit/flash for major tier jumps.

## danger_build

Purpose: increase anticipation before action.

Music character:

- pulse/drone/ostinato;
- gradually increasing density, percussion, or frequency range;
- do not start with full boss music.

Editing:

- shots can shorten gradually;
- subtle zooms/reframes;
- pre-lap danger SFX before the threat appears can create a sound bridge.

## horror_stalker

Purpose: uncertainty, not constant loudness.

Music character:

- low drone;
- sparse textures;
- irregular pulses;
- environmental sound often more important than melody.

Editing:

- use silence and room/game ambience aggressively;
- do not cover footsteps, breathing, mob noises, doors, caves with loud music;
- rare low impacts are more effective than constant booms.

## chase_action

Purpose: sustained urgency.

Music character:

- stronger percussion;
- faster perceived tempo;
- repetitive momentum that can survive dialogue ducking.

Editing:

- medium/high density;
- cuts may follow phrases/downbeats;
- native movement/weapon SFX should remain present;
- do not add whoosh on every camera movement.

## combat_normal

Purpose: clarity + kinetic impact.

Music character:

- energetic but not yet the maximum track in the project.

Editing:

- preserve hit/gun/explosion information;
- editorial impacts only on unusually important hits;
- small shake only for major impact, not every attack.

## boss_reveal

Purpose: create scale/identity.

Technique:

- often lower previous music just before appearance;
- use silence/low drone/riser for anticipation;
- boss appearance gets one large impact or sub hit;
- transition into a distinct boss cue.

The contrast before the reveal is part of the effect.

## boss_combat

Purpose: climax.

Music character:

- highest sustained energy available to the video;
- distinct identity from normal combat;
- strong rhythmic drive;
- ideally enough stems/layers to reduce density during dialogue without losing the cue.

Editing:

- high density is allowed, but action must remain readable;
- reserve strongest zoom/shake/flash for phase changes, near-death, final blow, major counterattack;
- do not make every second equally intense.

## victory_reward

Purpose: release tension and make success feel valuable.

Music character:

- bright/resolving/upward;
- celebratory groove or emotional release depending on tone.

Editing:

- reward chime/level-up cue when appropriate;
- allow music to rise during speech gaps;
- show loot/result clearly before moving on.

## failure_loss

Two modes:

Serious:
- strip music down;
- lower energy;
- ambience/piano/pad/minimal texture.

Comedy:
- abrupt stop or tiny failure sting;
- brief silence;
- avoid overlong meme sequence.

## aftermath_breathing

Purpose: reset viewer attention after a peak.

Music character:

- lower-energy reprise, ambience, or short silence.

This state is important. If the video never drops intensity, later climaxes stop feeling special.

## montage_progress

Purpose: compress repetitive work while retaining satisfying progress.

Music character:

- strong rhythm and obvious phrase structure;
- loopable;
- energy matched to work speed.

Editing:

- cut groups of actions to bars/phrases;
- time major milestones to phrase changes/downbeats;
- layer a few authentic game SFX above the music so the montage still feels physical.

---

# 4. Music transitions

Professional music editing commonly works best when cuts/loops respect bars and phrases rather than arbitrary waveform points.

Preferred transition types:

## Same emotional state

- stay on the same track when possible;
- remix/loop a phrase cleanly;
- use short crossfade if a new section is needed.

## Adjacent state

Example: exploration → curiosity.

- filter/reduce current track;
- crossfade or phrase transition into new cue;
- optionally pre-lap a texture from the next state.

## Hard tonal change

Example: comedy → monster appears.

- deliberate music stop or very short hard transition;
- silence can create the gap;
- one reveal impact;
- new state cue begins.

## Sound bridge

Let the next scene's sound begin before the visual cut when useful: mob roar, alarm, wind, explosion tail, portal, crowd, next BGM texture.

This is preferable to attaching an identical `whoosh/pop` to every transition.

---

# 5. Music level and ducking

Dialogue must stay clear, but "music is technically present" is not enough. The viewer should perceive the emotional bed.

A useful initial mixing reference for spoken video is music roughly **15–20 dB below dialogue**, with about **20 dB under dialogue** being a common starting recommendation. Adjust by track density, voice timbre, device test, and scene importance.

Rules:

- target voice drives BGM ducking;
- use smooth attack/release/fades, not hard volume gates;
- in speech gaps, let music rise several dB so the cue becomes perceptible;
- sparse music can sit higher than dense midrange-heavy music;
- EQ/sidechain can be better than simply making music extremely quiet;
- for dense action, music may duck against critical native SFX too;
- do not duck native game ambience unnecessarily just because target voice is active.

For OmniCast localization specifically, **source-language suppression is a separate control path from BGM ducking**.

Source speech mask answers: "Is original-language speech present?"

Target voice mask answers: "Should BGM duck for intelligibility?"

Never conflate the two.

---

# 6. Music stems are preferred when available

Use stems to control density instead of only gain.

Example boss cue:

- dialogue-heavy moment: pad + bass, drums reduced;
- chase starts: drums enter;
- boss phase change: full percussion + high layer;
- final hit: transient/impact + full cue;
- aftermath: drums drop, pad remains.

This makes the score feel composed to the scene even when generated or library-based.

---

# 7. SFX taxonomy

## A. Native game SFX — realism/information

Examples:

- footsteps;
- block place/break;
- chest/inventory;
- mob vocalization;
- melee hits;
- guns/projectiles;
- explosions;
- doors;
- portal;
- weather/environment;
- item pickup;
- redstone/machine sounds.

Preserve these whenever they help the viewer understand the action.

## B. Editorial SFX — punctuation

### impact
Use for:
- major hit;
- boss appearance;
- tier jump;
- dramatic text/object landing.

### whoosh
Use for:
- meaningful fast camera move;
- object/UI entering rapidly;
- deliberate transition.

Do not attach to every cut.

### riser
Use for:
- danger/reveal build;
- final upgrade;
- pre-boss escalation.

### sub_drop / bass_hit
Use for:
- major threat;
- large reveal;
- catastrophic failure;
- boss phase.

Rare = powerful.

### UI_tick / click
Use for:
- progression list;
- selection;
- count increment;
- inventory visualization.

### reward_chime
Use for:
- rare loot;
- objective complete;
- upgrade success.

### comedy_sting
Use for:
- actual punchline/reaction.

Do not use because "nothing happened for 10 seconds."

### glitch/error
Use for:
- failure;
- impossible result;
- corrupted/horror mechanic;
- UI contradiction.

### ambience enhancement
Use for:
- cave/wind/rain/crowd/industrial/forest when the source background was damaged or needs continuity.

Ambience should generally be felt more than noticed.

---

# 8. Semantic visual edit map

Every edit event should store `event_type`, `purpose`, `source_evidence`, and `intensity`.

## reveal

Possible treatment:
- 1.05–1.15 punch-in;
- selective glow/highlight;
- brief hold;
- one impact;
- caption only if it adds meaning.

## major_upgrade

- progression graphic;
- flash/highlight;
- reward/impact SFX;
- stronger music accent;
- brief hold on final item.

## minor_upgrade

- subtle UI tick;
- small scale pop;
- no bass impact.

## joke

- allow setup to remain visually simple;
- punchline may use abrupt crop, freeze, reaction caption, tiny sting, or silence;
- do not stack all comedy effects at once.

## danger_arrival

- pre-lap threat sound;
- tension rise;
- slightly tighter framing;
- reveal only at payoff.

## major_hit

- very short shake;
- impact layer;
- optional 2–6 frame visual accent depending on fps/style;
- do not shake every attack.

## confusion / realization

- punch-in or crop;
- short text/callout if useful;
- lower music briefly to focus dialogue.

## travel / ordinary crafting

- usually no editorial SFX;
- game audio + low BGM is enough;
- montage only when repetition has no story value.

## scene transition

Use visual transition only when the relationship between scenes benefits from it.

Default should often be a clean cut supported by audio continuity.

No global `pop`/`boom` at every scene boundary.

---

# 9. Edit density is a curve, not a constant

Recommended relative density:

- exposition: 1/5
- exploration: 1–2/5
- comedy: 1/5 baseline with short 3–4/5 spikes
- discovery: 2/5 → reveal spike 4/5
- progression montage: 3/5
- danger build: 2/5 → 3/5
- chase: 4/5
- normal combat: 3–4/5
- boss climax: 4–5/5
- aftermath: 1/5

These are narrative intensity labels, not mandatory effect counts.

An anti-spam limiter may cap repeated effects, but **a timer must never be the trigger**.

---

# 10. Source-language removal in localized/reup videos

This is independent from editorial BGM.

The correct model is:

`source_speech_activity -> suppress/reconstruct only where needed`

not:

`target_voice_activity -> mute original track`

If the Chinese/source speaker continues while English TTS pauses, source speech must still be suppressed.

Preferred pipeline:

1. source speech activity detection;
2. high-quality voice/background separation;
3. preserve non-vocal/game components;
4. inspect for separator warble/buzz;
5. where separation is worse than the source, dynamically duck/mask the contaminated region rather than polluting the whole video;
6. preserve or reconstruct ambience across mask boundaries with crossfades;
7. target dub is mixed independently;
8. editorial BGM/SFX are applied only after the speech/background layer is stable.

Headphone QA is mandatory because low-level source-language artifacts are easier to hear on headphones.

---

# 11. Order of operations

Do not add music/SFX before the foundational audio is stable.

Recommended pipeline:

1. understand story/events;
2. align target dub;
3. build source-speech activity mask;
4. create clean game/background layer;
5. QA residual source speech/artifacts;
6. create story-state map;
7. choose/compose BGM cues;
8. perform BGM transitions and ducking;
9. preserve/restore native SFX;
10. add editorial SFX;
11. add semantic visual edits;
12. mix/master;
13. headphone QA + phone/laptop-speaker QA;
14. render receipt.

---

# 12. Automated planner schema

A semantic planner should output events resembling:

```json
{
  "start": 132.40,
  "end": 137.10,
  "state": "discovery_curiosity",
  "event": "rare_weapon_found",
  "importance": 0.86,
  "bgm": {
    "family": "curious_pulse",
    "energy": 0.35,
    "transition": "phrase_crossfade",
    "duck_against_target_voice": true
  },
  "sfx": [
    {
      "type": "reward_chime",
      "at": 135.22,
      "purpose": "rare_item_payoff",
      "intensity": 0.45
    }
  ],
  "visual_edits": [
    {
      "type": "punch_in",
      "at": 135.12,
      "scale": 1.09,
      "purpose": "direct_attention_to_item"
    }
  ]
}
```

Low-confidence events should default to fewer edits, not more.

---

# 13. Anti-AI / anti-template gate

Fail the edit if any of these patterns dominate:

- zoom at fixed intervals;
- identical whoosh every transition;
- identical bass hit for every reveal;
- BGM switches on a timer rather than story states;
- one looped music track for the entire video regardless of emotion;
- every caption uses identical pop animation;
- every item pickup gets the same reward sting;
- permanent camera shake;
- native Minecraft audio becomes inaudible;
- BGM is so low it has no emotional function;
- source-language artifacts buzz under the dub;
- no quiet aftermath after climactic passages.

The desired result should feel edited by someone who understood the event, not by a scheduler.

---

# 14. QA listening tests

## Dialogue-first pass

Can every target line be understood without effort?

## Music-only awareness pass

Without staring at the timeline, can a listener perceive when the emotional state changes?

If no, the score is too flat or too quiet.

## Native-game pass

Mute editorial BGM/SFX temporarily. Does the remaining game layer still communicate physical action?

If no, the source-cleaning stage destroyed too much.

## SFX subtraction pass

Temporarily mute editorial SFX. Add back only effects whose absence makes a meaningful event weaker/less clear.

## Headphone artifact pass

Check source-language residuals, separation buzz, pumping, phase artifacts, abrupt gates, and tiny pops.

## Phone/laptop speaker pass

Check whether music disappears entirely on small speakers and whether effects dominate dialogue.

---

# 15. Research-derived principles to preserve

The durable rules behind this playbook are:

- dialogue is the anchor of spoken video audio;
- music should duck dynamically rather than be permanently buried;
- letting music rise in dialogue gaps makes scoring feel intentional;
- one unchanging loop becomes emotionally flat;
- music cuts/loops work better around bars/phrases;
- sound bridges can smooth or strengthen transitions;
- stems let editors reduce density without destroying the emotional cue;
- SFX should focus viewer attention and support story events;
- ambience creates continuity and realism;
- effects are strongest when used selectively;
- editing choices must serve story and pacing rather than demonstrate effects.

For Minecraft specifically, combine those principles with aggressive preservation of native game audio and semantic event detection.
