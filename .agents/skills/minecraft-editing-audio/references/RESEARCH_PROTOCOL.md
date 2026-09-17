# Minecraft Audio/Edit Forensic Research Protocol

## Purpose

This protocol lets future workers study new high-performing Minecraft videos without reinventing the research method. The goal is to convert real creator behavior into measurable editing priors for OmniCast.

Do not ask only "is the edit good?" Measure what the editor actually does, when, and why.

---

# 1. Sample selection

For each research batch, sample across multiple Minecraft families rather than one channel only.

Recommended minimum batch:

- 3 boss/horror/threat videos;
- 3 progression/upgrade/challenge videos;
- 3 survival/100-days/apocalypse videos;
- 3 comedy/troll/story videos;
- optional SMP/civilization/build/mod-showcase examples.

Within each family, prefer a mixture of:

- recent high-VPH videos;
- channel-relative outliers;
- mature-channel hits;
- smaller-channel breakout hits.

Record source metadata, publish date, duration, channel size, views, and any available outlier/VPH context.

---

# 2. Required timeline annotations

Annotate the full video or representative windows with these tracks:

## Story state

One of:

- hook_cold_open
- setup_exposition
- exploration_travel
- comedy_light
- discovery_curiosity
- reveal_big
- progression_upgrade
- danger_build
- horror_stalker
- chase_action
- combat_normal
- boss_reveal
- boss_combat
- victory_reward
- failure_loss
- aftermath_breathing
- montage_progress

## Dialogue state

- speech_active
- speech_gap_short
- speech_gap_long
- source_dialogue_only
- nonverbal_reaction

## Music state

- no_music
- bed_low
- bed_medium
- foreground_music
- tension_riser
- hard_stop
- transition_crossfade
- new_cue
- same_cue_new_stem

## SFX state

Tag actual events:

- native_game_important
- editorial_impact
- editorial_whoosh
- riser
- comedy_sting
- reward_chime
- failure_sting
- UI_tick
- ambience_layer
- sound_bridge_prelap

## Visual edit state

- plain_cut
- punch_in
- zoom_out
- freeze_hold
- speed_ramp
- replay
- shake
- blur_focus
- highlight_glow
- kinetic_caption
- meme_cutaway
- transition_fx
- avatar_reaction

---

# 3. Metrics to extract

## Music metrics

Per video and per story state, measure:

- cue count;
- average cue duration;
- median cue duration;
- music-state changes per minute;
- percentage of time with no music;
- percentage of time with low/medium/foreground music;
- number and duration of intentional music stops;
- average delay between story-state transition and music-state transition;
- whether cue changes land on visible edit boundaries;
- whether cue edits appear to respect bars/phrases;
- whether music rises during speech gaps;
- whether music ducks continuously or dynamically;
- whether the same track is re-orchestrated/stemmed instead of replaced.

## Mix metrics

Where audio analysis allows, estimate:

- dialogue RMS/LUFS;
- music RMS/LUFS during dialogue;
- music RMS/LUFS during speech gaps;
- native game SFX RMS/LUFS;
- relative music-to-dialogue difference;
- relative game-SFX-to-dialogue difference;
- duck attack and release/fade durations;
- peak headroom around major impacts;
- percentage of native-game audio audibly retained.

Do not turn one creator's levels into universal thresholds. Aggregate by family and channel style.

## SFX metrics

Measure:

- editorial SFX events per minute;
- native-game important events per minute;
- editorial/native SFX ratio;
- impacts per major reveal;
- whooshes per visual transition;
- comedy stings per actual joke beat;
- repeated identical SFX frequency;
- layered-impact count at major events;
- pre-lap/sound-bridge usage.

## Visual edit metrics

Measure:

- cuts per minute;
- semantic edit events per minute;
- punch-ins per minute;
- freeze/hold usage;
- speed ramps per minute;
- shake events per minute;
- meme/cutaway frequency;
- average duration between high-intensity edit events;
- edit-density curve across setup → escalation → climax → aftermath.

The goal is to learn contrast, not maximize counts.

---

# 4. Key event forensic templates

For every video, study at least these events when present.

## Hook

Measure first 30 seconds:

- when music begins;
- first strong SFX;
- first visual edit beyond cuts;
- whether the hook uses a cold open before explanation;
- whether music is already at climax energy or holds room to escalate.

## Reveal

Measure 5 seconds before to 5 seconds after:

- does music attenuate before reveal?
- is there a riser?
- is there a moment of silence?
- does the reveal hit land with an impact?
- does the cue change after payoff?
- is the edit a cut, zoom, hold, shake, or combination?

## Upgrade/reward

Measure:

- small upgrade vs major upgrade treatment;
- UI ticks vs major impact distinction;
- whether music phrase/beat aligns with reward;
- whether music lifts after the upgrade.

## Comedy punchline

Measure:

- does music stop before the line/action?
- is there a reaction hold?
- is the SFX before, on, or after the punchline?
- how quickly normal music resumes?

## Horror stalk/reveal

Measure:

- percentage of near-silence/negative space;
- prominence of footsteps/breathing/mob sound;
- whether music is a low drone instead of full track;
- how long suspense is held before shock/payoff;
- whether the editor avoids unnecessary whooshes/zoom spam.

## Boss reveal/fight

Measure:

- pre-reveal attenuation;
- reveal impact;
- music cue/stem change;
- native boss roar/game sound prominence;
- phase-change treatment;
- final-blow treatment;
- post-fight energy drop.

---

# 5. Pattern validity rules

Do not promote a behavior into an OmniCast default just because one successful creator used it.

A candidate pattern becomes a strong prior when at least one of these is true:

1. it repeats across 3+ independent successful creators in the same family;
2. it repeats across multiple high-performing videos from the same creator and is absent/weaker in lower-performing comparable uploads;
3. it matches established professional editing/audio practice and is supported by several creator examples;
4. it materially improves controlled A/B human audits in OmniCast outputs.

Label findings as:

- `universal_principle`
- `family_prior`
- `channel_style`
- `video_specific`
- `unproven_hypothesis`

Do not confuse channel style with universal law.

---

# 6. AGY research task template

When AGY/local analysis is available, give it the media files and require concrete measurements.

Suggested task:

```text
Analyze this Minecraft YouTube video as an audio/edit forensic benchmark.
Do not give generic editing advice.

Produce a timeline with:
- story-state changes;
- BGM cue starts/stops/changes;
- estimated BGM vs dialogue level differences;
- music-stop / negative-space events;
- editorial SFX and native-game SFX;
- punch-in/freeze/shake/speed-ramp/meme edit events;
- major reveal, upgrade, joke, danger, boss, reward and failure beats.

Compute per-minute densities and state-conditioned patterns.
Distinguish native game audio from added editorial SFX where possible.
Explain uncertainty rather than guessing.
Return both a human report and machine-readable JSON/CSV.
```

If several workers analyze videos, force all workers to use the same schema so results are aggregatable.

---

# 7. Research output schema

Each analyzed video should produce:

```json
{
  "video_id": "...",
  "family": "boss_horror_threat",
  "duration_s": 0,
  "story_states": [],
  "music_events": [],
  "sfx_events": [],
  "visual_edit_events": [],
  "mix_measurements": [],
  "key_event_windows": {
    "hook": [],
    "reveals": [],
    "upgrades": [],
    "comedy": [],
    "boss": [],
    "failures": [],
    "rewards": []
  },
  "metrics": {},
  "observed_patterns": [],
  "uncertainties": []
}
```

After a batch, aggregate by family and by creator.

---

# 8. What future workers should NOT do

Do not:

- judge by memory after casually watching;
- use one creator as the universal reference;
- count every loud sound as an editorial SFX;
- treat every cut as an edit beat;
- infer BGM changes solely from visual cuts;
- assume an English transcript reveals music timing;
- use a fixed "effects per minute" target without story state;
- promote copyright-risky source music as a reusable track recommendation;
- confuse loudness with emotional intensity;
- recommend timer-based rules because they are easy to automate.

The deliverable is a measurable model of **why the editor changed sound or picture at that moment**.
