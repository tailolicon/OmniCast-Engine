---
name: minecraft-editing-audio
description: "Mandatory semantic audio + editing system for Minecraft create/reup/localize/dub/edit workflows. Controls source-dialogue suppression, BGM state, native/added SFX, edit beats, pacing, ducking, artifact gates, and anti-spam rules."
allowed-tools: ["Read", "Write", "Edit", "Grep", "Glob", "Bash", "Task", "AskUserQuestion", "WebFetch"]
user-invocable: false
---

# Minecraft Editing + Audio Skill

This skill owns **sound design and edit language** for Minecraft videos.

It is mandatory for Minecraft create/reup/localize/dub/edit workflows. A video is not finished merely because dialogue is dubbed and subtitles are present.

Read:

- `references/PLAYBOOK.md`
- `schemas/policy.json`

## Core law

**Edits must be caused by meaning, not by a timer.**

Never use rules like "zoom every 8 seconds", "add whoosh every transition", or "insert meme SFX every 20 seconds". Every edit cue must correspond to an event, emotion, reveal, escalation, joke, impact, danger, reward, or change in viewer attention.

## Required layered mix

Treat the soundtrack as separate roles:

1. `target_voice` — English/Vietnamese/other dub or host voice.
2. `source_background` — game ambience, native SFX, environmental audio, original music that is safe/desired to retain.
3. `source_speech_residual` — original-language speech that must not remain intelligible or produce distracting artifacts.
4. `editorial_bgm` — intentionally selected music for pacing/emotion.
5. `editorial_sfx` — added impacts, whooshes, risers, comedy stings, UI ticks, bass hits, etc.

Do not flatten these into one gain knob.

## Source-dialogue suppression contract

For localized/reup video, suppression must be driven by **source speech activity**, not only by whether target TTS is currently speaking.

Reason: if target dub is silent while the source speaker continues talking, original-language speech must still be suppressed.

Preferred order:

1. high-quality dialogue/background separation where it preserves ambience cleanly;
2. reconstruct background from non-vocal stem(s) with crossfades;
3. if separation creates audible buzzing/warble, use source-speech masks to duck only affected intervals;
4. restore source/game ambience outside source-speech intervals;
5. never leave distorted Chinese/original speech buzzing under target voice.

Do not continuously attenuate the whole game track if only source speech is the problem.

## Dynamic scene-state system

Classify each timeline beat into one or more states:

- `setup_calm`
- `exploration`
- `comedy`
- `discovery_reveal`
- `progression_upgrade`
- `danger_tension`
- `chase_action`
- `combat_boss`
- `victory_reward`
- `failure_loss`
- `horror_stalker`
- `exposition_dialogue`
- `silence_breathing_room`

BGM, SFX density, zoom intensity, captions, speed changes, and transitions must respond to this state.

## BGM principles

- BGM should support the emotional state, not run at one constant character all video.
- Prefer fewer strong cues with meaningful transitions over constant random track changes.
- Dialogue remains intelligible, but music should still be perceptible; avoid mixes where BGM is technically present but functionally inaudible.
- Raise music during non-dialogue, travel, montage, reveal, and aftermath moments.
- Duck music smoothly around important speech rather than hard-gating it.
- Use tension ramps before danger/reveal and release them after payoff.
- Boss/combat music should escalate only when the video actually escalates.
- Comedy can briefly interrupt/replace the current cue for a punchline, then return cleanly.

## SFX principles

Use two categories:

### Native/game SFX

Preserve whenever possible because they make Minecraft feel physical and alive: footsteps, hits, block breaks, inventory, chests, mobs, weapons, explosions, ambience.

### Editorial SFX

Add only to emphasize meaningful beats:

- impact/hit;
- reveal;
- level-up/upgrade;
- failure;
- joke reaction;
- danger arrival;
- UI/selection;
- transition when the visual transition itself needs a cue.

Do not replace every native event with an editorial effect. Native sound is the realism layer; editorial SFX is punctuation.

## Visual edit principles

Allowed semantic tools:

- punch-in / zoom;
- short freeze/hold;
- speed ramp;
- replay;
- shake/impact;
- highlight/glow;
- arrows/circles only when truly needed;
- kinetic captions/reaction text;
- cutaway/meme insert;
- crop/reframe;
- brief blur/focus isolation;
- on-screen avatar/host reaction when editorially justified.

Each effect must have a reason tied to the beat.

## Anti-template rules

Reject:

- periodic zooms;
- repeated identical whoosh/pop patterns;
- constant meme SFX;
- permanent shake;
- captions that animate identically for every sentence;
- BGM that never changes emotional state;
- over-editing calm/exposition scenes;
- silence being treated as an error;
- added effects masking native gameplay information.

## Edit-density curve

Editing density should breathe.

Typical pattern:

- setup/exposition: low;
- exploration: low-medium;
- discovery/reveal: short spike;
- comedy: event-driven spikes;
- chase/action: medium-high;
- boss climax: high but readable;
- aftermath: drop sharply;

Do not keep the entire video at climax density.

## QA gates

Before completion, verify:

- no intelligible source-language speech remains where it should be removed;
- no separator buzz/warble is audible on headphones;
- game ambience/SFX is not needlessly destroyed;
- BGM is audible but does not mask target voice;
- music transitions match scene-state changes;
- added SFX correspond to real events or editorial beats;
- no repetitive timer-based edit pattern dominates;
- edit density has contrast and breathing room;
- boss/reveal/comedy moments receive stronger treatment than ordinary traversal;
- silence is intentionally preserved where it improves impact.

## Completion receipt

Persist or report:

```json
{
  "minecraft_edit_audio_policy": "1.0.0",
  "source_speech_mask_used": true,
  "source_speech_residual_gate": "pass",
  "game_audio_preservation_gate": "pass",
  "bgm_state_map": [],
  "editorial_sfx_events": [],
  "edit_events": [],
  "anti_spam_gate": "pass",
  "headphone_artifact_gate": "pass"
}
```

A Minecraft reup/localization is not complete until both this skill and the Minecraft packaging skill have passed.
