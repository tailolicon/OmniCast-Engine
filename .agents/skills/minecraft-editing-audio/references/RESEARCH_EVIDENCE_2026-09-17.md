# Research Evidence — Minecraft BGM/SFX/Edit

Date: 2026-09-17

Status: first research pass complete; competitor forensic batch pending local/AGY worker availability.

This file records the external evidence behind the current OmniCast audio/edit priors. It is intentionally separate from the creative playbook so later workers can distinguish researched principles from project-specific defaults.

---

## 1. Dialogue, music, ambience and SFX should remain separate roles

Adobe Premiere's Essential Sound workflow explicitly classifies Dialogue, Music, Sound Effects, and Ambience separately, enabling different loudness, repair and ducking behavior for each class.

Implication for OmniCast:

- do not flatten source gameplay, BGM, editorial SFX and target voice into one track;
- preserve independent control throughout the edit;
- localization needs a distinct source-speech-residual layer because its behavior differs from desired native game ambience/SFX.

Evidence:

- https://helpx.adobe.com/premiere/desktop/add-audio-effects/adjust-volume-and-levels/audio-editing-with-essential-sound-panel.html
- https://helpx.adobe.com/ph_fil/premiere-pro/how-to/create-audio-mix.html

---

## 2. Ducking should be event-sensitive and faded, not hard-gated

Adobe's current Premiere ducking controls expose:

- duck-against target type;
- sensitivity;
- amount/reduction;
- fade duration;
- fade position.

Adobe notes that faster fades fit faster music/speech while slower fades fit voiceover beds better. Frame.io also notes that fade position should begin before speech boundaries rather than causing the music to feel as if it suddenly stops the story.

Implication for OmniCast:

- BGM envelope must be generated from semantic speech/event boundaries;
- use attack/release/fade behavior rather than binary on/off volume;
- allow different duck envelopes for comedy, fast action dialogue and calm narration;
- keep human/manual override possible around key reveals and jokes.

Evidence:

- https://helpx.adobe.com/sg/premiere/desktop/add-audio-effects/adjust-volume-and-levels/automatically-duck-audio.html
- https://blog.frame.io/2024/08/07/insider-tips-premiere-pro-essential-sound-automation/

---

## 3. Music edits should respect bars and phrases

Artlist's music-editing guide recommends aligning visual/music edits with musical bars and phrases, often making structural music cuts just before the first beat of a new bar/phrase. Looping a complete or half phrase is less perceptually awkward than cutting mid-phrase.

Implication for OmniCast:

- track metadata should include BPM and phrase/beat grid when detectable;
- major visual changes can align to phrase boundaries when useful;
- track shortening/looping must prefer phrase-aware edits;
- story state chooses the cue; musical phrase chooses the clean transition point.

Evidence:

- https://artlist.io/blog/how-to-add-music-to-a-video/
- https://artlist.io/blog/music-bpm/

---

## 4. Good pacing requires breathing room

Artlist argues that uninterrupted dialogue/action removes the buildup that gives later moments impact, and recommends intentional gaps where music can come forward or a point/joke/emotion can land. Epidemic Sound similarly recommends using silence deliberately rather than filling every second with effects.

Implication for OmniCast:

- silence is a valid story state, not a pipeline failure;
- after major reveal/boss defeat/joke, allow short decompression when it improves impact;
- do not auto-fill every non-speech gap with narration or SFX;
- edit density should rise and fall rather than stay at climax level.

Evidence:

- https://artlist.io/blog/how-to-add-music-to-a-video/
- https://www.epidemicsound.com/blog/sound-design-tips-and-tricks/

---

## 5. Native/ambient sound creates realism and continuity

Artlist describes ambient sound as a way to create continuity across shots, prevent unnatural deadness, establish mood, and add realism/depth. Foley and world sounds provide physical texture.

For Minecraft, native game audio acts like production sound/foley:

- footsteps;
- block interactions;
- inventory/chests;
- mobs;
- weapons;
- explosions;
- weather;
- machinery;
- portals;
- environmental ambience.

Implication for OmniCast:

- preserve native game sound whenever source-language removal permits;
- never solve source-dialogue contamination by globally destroying the entire game soundscape unless no better fallback exists;
- game audio should remain perceptible enough to prove the world is alive.

Evidence:

- https://artlist.io/blog/royalty-free-sounds-why-you-should-start-using-artlist-sfx-in-your-videos/
- https://artlist.io/blog/video-sound/

---

## 6. Editorial SFX are punctuation, not wallpaper

Artlist groups common editorial effects into foley, whooshes/risers, impacts and ambience. Impacts are associated with dramatic plot points/events; whooshes often support actual movement/transition; risers build tension.

Implication for OmniCast:

- attach editorial SFX to semantic event types;
- ordinary scene cuts do not deserve automatic whooshes/booms;
- large impacts should be reserved for major visual/narrative beats;
- repeated identical effects should trigger an anti-template warning.

Evidence:

- https://artlist.io/blog/royalty-free-sounds-why-you-should-start-using-artlist-sfx-in-your-videos/

---

## 7. Sound bridges/pre-laps often outperform transition SFX

Artlist recommends starting sound from the next shot before the visual cut to smooth and strengthen a transition. This is a sound bridge/pre-lap technique rather than adding a generic transition noise.

Minecraft examples:

- boss roar begins before the boss shot;
- explosion begins just before cutting to destruction;
- portal hum begins before entering the dimension;
- crowd/mob noise begins before revealing the swarm.

Implication for OmniCast:

- favor meaningful diegetic pre-laps around reveals/location changes;
- only add whoosh when the motion itself needs punctuation;
- remove the old global scene-change pop/boom behavior.

Evidence:

- https://artlist.io/blog/tips-that-will-take-your-sound-design-to-the-next-level/

---

## 8. Layering works best on selected major moments

Artlist shows that major impacts can combine multiple frequency-complementary layers rather than one generic hit. Epidemic also recommends layering while warning not to overuse bass.

Implication for OmniCast:

A major boss reveal might use:

- native boss roar;
- low sub impact;
- higher transient/metallic hit;
- short riser tail;
- music cue/stem transition.

But this treatment should be rare enough to remain special.

Evidence:

- https://artlist.io/blog/tips-that-will-take-your-sound-design-to-the-next-level/
- https://www.epidemicsound.com/blog/sound-design-tips-and-tricks/

---

## 9. Stems allow one cue to evolve with story intensity

Artlist defines stems as separate elements such as drums, bass, piano, etc., and notes that they let editors control music around dialogue/SFX and emotional moments without replacing the whole track.

Implication for OmniCast:

Prefer state evolution such as:

- exploration: pad/bass only;
- progression montage: add rhythm;
- danger build: add pulse/percussion;
- boss phase: full cue;
- dialogue-heavy explanation: remove dense drums/midrange stem;
- aftermath: strip back to pad/texture.

This creates continuity while still providing escalation.

Evidence:

- https://artlist.io/blog/new-music-stems/
- https://new-blog.artlist.io/blog/what-are-music-stems/

---

## 10. Gaming music should reflect game/content intensity

Epidemic Sound's analysis of gaming content reports that creators select music according to game intensity/nature; high-intensity gaming often uses high-energy styles while strongly narrative games use more action-oriented scoring.

Implication for OmniCast:

- do not choose one fixed channel playlist for every Minecraft genre;
- boss/horror, comedy, progression and survival need different cue libraries;
- channel identity should come from recurring palette/selection taste, not forcing the same emotional cue onto unrelated scenes.

Evidence:

- https://www.epidemicsound.com/blog/sound-of-gamers/

---

## 11. Horror depends heavily on negative space and diegetic threat sounds

Artlist's horror guidance specifically emphasizes negative space, footsteps, breathing, monster vocalizations and sonic textures. Epidemic describes suspense as the sustained journey between setup and shock/payoff rather than the shock itself.

Implication for Minecraft horror:

- use quieter beds/drones rather than constant melodic music;
- preserve actual monster/footstep/environmental sounds;
- let threat audio occur offscreen when useful;
- avoid zoom/whoosh spam that destroys uncertainty;
- silence immediately before a scare/reveal can increase impact.

Evidence:

- https://artlist.io/blog/scary-sound-effects/
- https://www.epidemicsound.com/blog/use-suspense-in-your-video-content/

---

## 12. Community/editor experience agrees audio work is a major quality separator

Creator/editor discussions repeatedly mention that audio ducking, ambience, music selection and sound design consume significant editing time but materially change perceived polish. One PartneredYouTube creator describes spending multiple days specifically selecting game OSTs and balancing ducking for a 25-minute finished video. Reddit evidence is anecdotal, so it should not define numerical rules, but it supports prioritizing this system rather than treating audio as a final add-on.

Evidence:

- https://www.reddit.com/r/PartneredYoutube/comments/1dmyha2
- https://www.reddit.com/r/VideoEditing/comments/1g0qmwo
- https://www.reddit.com/r/VideoEditingTips/comments/1q6gtxj

---

# Current confidence levels

## Strong / ready to encode as universal principles

- separate dialogue/music/SFX/ambience roles;
- semantic rather than timer-based edit/SFX decisions;
- dynamic ducking with fades;
- phrase-aware music edits;
- preserve intentional silence/negative space;
- native game audio is first-class;
- music/SFX intensity should follow narrative state;
- no global scene-change impact/pop;
- use sound bridges when semantically appropriate;
- preserve room for escalation.

## Strong family priors, not universal laws

- horror: reduced music density + stronger native threat sounds + negative space;
- boss/reveal: pre-reveal attenuation/riser + impact + cue/stem escalation;
- progression: phrase-aligned montage + differentiated minor/major reward SFX;
- comedy: strategic music interruption/hard-stop can emphasize punchlines;
- exploration: lower-density music and stronger ambience/native world sound.

## Still requires competitor forensic measurement

- actual preferred music cue length by Minecraft family;
- average BGM/dialogue level difference in successful Minecraft channels;
- exact duck attack/release distributions;
- SFX events per minute by family;
- cut/zoom/freeze density by family;
- frequency of music hard-stops in comedy/horror;
- how often top creators use stems vs full cue changes;
- whether specific measurable patterns correlate with stronger channel-relative performance.

Use `RESEARCH_PROTOCOL.md` for the next worker batch.
