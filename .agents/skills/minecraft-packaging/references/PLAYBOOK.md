# Minecraft YouTube Packaging Playbook

## Purpose

This document is the creative operating system for Minecraft YouTube packaging inside OmniCast. It exists so an agent can package wildly different Minecraft videos without falling back to one repetitive formula.

The objective is not "maximum clickbait" in the sense of making unsupported claims. The objective is **maximum truthful click pressure**: discover the strongest real visual/premise already present in the content and present it with the clearest possible stakes, spectacle, and curiosity.

The system is designed for:

- original Minecraft videos;
- modded Minecraft;
- boss/horror videos;
- progression/evolution videos;
- 100-days/survival/apocalypse videos;
- comedy/troll videos;
- SMP/civilization/PvP stories;
- mod showcases and mechanic experiments;
- reups/localizations/dubs from Douyin, Bilibili, or other sources.

---

# 1. The universal framework

Every strong package should answer four questions:

## PROMISE

What experience or outcome is being promised?

Examples:

- survive Verity;
- become strong enough to kill a Titan;
- escape 1,000 hunters;
- evolve a gun from weak to absurdly powerful;
- survive 100 days of a zombie apocalypse;
- discover an impossible structure;
- troll a friend with a trap;
- build an invention that changes the game.

## PROOF

What can the viewer see in the thumbnail that proves this is not empty wording?

The proof is usually a **real entity, real item, real structure, real transformation, real mechanic, or real moment** from the video/modpack.

## STAKES

Why should the viewer care about the outcome?

Common Minecraft stakes:

- player is tiny vs huge boss;
- one player vs overwhelming army;
- limited lives/time/resources;
- apocalypse/world destruction;
- rare reward;
- progression from weak to god-tier;
- friend/server conflict;
- losing a base/world/character;
- solving a mystery before something happens.

## CURIOSITY

What does the package deliberately not answer?

Examples:

- how can the player possibly beat this boss?
- what is the final weapon?
- what is inside the impossible structure?
- what happens at day 100?
- why is Verity afraid this time?
- how did one player survive 1,000 hunters?

A good title-thumbnail pair provides enough information to understand the premise, but not enough to close the loop.

---

# 2. Packaging is an evidence problem before it is a design problem

Never begin a Minecraft thumbnail by asking an image model to "make an epic Minecraft thumbnail."

Begin by extracting **thumbnail evidence**.

## Thumbnail Evidence Manifest

For each potentially strong asset or moment, record:

- canonical name;
- asset type: boss/mob/item/weapon/armor/structure/biome/mechanic/event/character;
- mod/modpack if known;
- whether it truly appears in the source;
- timestamps where visible;
- visual recognizability;
- scale potential;
- threat potential;
- reward/progression potential;
- emotional value;
- whether a clean screenshot/model/texture can be acquired;
- factual claims it can support.

Example:

```yaml
entity: verity
kind: boss_horror
appears_in_video: true
timestamps: [134.2, 471.6]
modpack_verified: true
visual_recognizability: 9
scale_potential: 9
threat_potential: 10
clean_asset_available: true
supports_claims:
  - hunted by Verity
  - trapped Verity
  - survived Verity
```

The thumbnail concept must be built from these verified pieces.

---

# 3. Asset truth hierarchy

Use this order of preference.

## Tier 1 — staged in-game capture

Best option when the modpack/world can be opened. Stage the actual boss/item/player in a cleaner camera arrangement while keeping factual identity intact.

Advantages:

- exact mod identity;
- Minecraft visual authenticity;
- controllable camera and lighting;
- strong viewer trust.

## Tier 2 — actual source frame

Extract a high-quality frame from the video when staging is unavailable.

Improve by:

- upscaling;
- segmentation;
- background cleanup;
- relighting;
- compositing;
- depth blur;
- effects.

## Tier 3 — actual model/texture render

Use the real entity/item model and textures from the mod/modpack, then pose/render it cleanly.

## Tier 4 — composite of verified assets

Combine real supported elements into a more dramatic but still truthful situation.

## Tier 5 — generative support

AI may generate or improve:

- sky/background mood;
- smoke/fire/particles;
- light rays;
- impact effects;
- depth extensions;
- generic environmental dressing.

AI must not replace the central factual proof with a fictional lookalike.

---

# 4. Dramatic exaggeration: allowed vs forbidden

## Allowed presentation exaggeration

- put the real boss closer to camera;
- use a more dramatic FOV;
- make the player smaller through composition/perspective;
- choose the boss's strongest real pose;
- add cinematic lighting;
- isolate silhouettes;
- exaggerate depth;
- intensify real fire/explosion/particles;
- use a clean health bar/progression indicator when consistent with the premise;
- combine multiple real moments/assets to express the actual conflict.

## Forbidden factual exaggeration

Do not invent:

- a boss not in the video/modpack;
- an armor set that does not exist;
- a weapon that never appears;
- a transformation that never happens;
- a dimension/structure not present;
- a fake number of hunters/mobs;
- a fake "infinite" mechanic;
- a fake challenge rule;
- a fake final form;
- a fake relationship such as claiming the footage is the uploader's own gameplay when it is sourced from another creator.

A useful rule:

> Make the real thing look maximally dramatic; do not replace the real thing with a more clickable lie.

---

# 5. Genre/family classifier

Minecraft is not one niche. The agent must classify the content before packaging.

A video may have one primary and one secondary family.

## A. boss_horror_threat

Signals:

- named monster/boss;
- horror mod;
- stalking/hunting;
- giant creature;
- escape/survive/fight;
- player visibly weaker than threat.

Viewer emotion: fear, awe, impossible confrontation.

Strong click levers:

- scale contrast;
- proximity;
- monster face/silhouette;
- player vulnerability;
- chase;
- reversal (monster becomes afraid/trapped).

Title grammars:

- `I Survived [THREAT] in Minecraft`
- `[THREAT] Hunted Me Until I Did This...`
- `I Had to [UPGRADE/ESCAPE] Before [THREAT] Found Me`
- `This [MONSTER] Took Over My Minecraft World`
- `I Made [FEARED BOSS] Fear My World` — only if true.

Thumbnail grammars:

- giant boss 45–65% + tiny player 10–25%;
- boss behind player during chase;
- boss face + safe zone/base that looks insufficient;
- trapped boss + player holding the thing that made it possible.

Do not use a generic AI monster when a real mod monster exists.

---

## B. progression_upgrade_evolution

Signals:

- weapon tiers;
- armor upgrades;
- player levels;
- evolution;
- transformations;
- loot progression;
- weak-to-strong arc.

Viewer emotion: power fantasy and anticipation.

Strong click levers:

- before/after;
- final form conceal/reveal;
- weak item vs absurd final item;
- final reward vs boss requirement.

Title grammars:

- `Every [ACTION] Upgrades My [THING]`
- `I Had to Upgrade [THING] to Beat [BOSS]`
- `From [WEAK] to [OP] in Minecraft`
- `I Evolved [THING] Until It Became Unstoppable`

Thumbnail grammars:

- weak → strong visual ladder;
- weak item foreground vs enormous final item;
- final armor/player silhouette + boss in background;
- one visible transformation contrast rather than 10 tiny tiers.

The final form/item should be real and identifiable.

---

## C. extreme_scale_swarm_hunters

Signals:

- 100/1,000/1,000,000 enemies;
- hunter/manhunt;
- giant army;
- swarm;
- massive simulation;
- one-vs-many.

Viewer emotion: impossible odds.

Strong click levers:

- numerical scale;
- crowd density;
- tiny hero;
- enclosure/surrounding;
- escape path.

Title grammars:

- `I Beat Minecraft While [NUMBER] [ENEMIES] Hunted Me`
- `Minecraft, But [NUMBER] [THING] Try to Kill Me`
- `Can One Player Survive [NUMBER] [THREAT]?`

Thumbnail grammars:

- tiny player vs wall/sea of enemies;
- high-angle crowd composition;
- one safe island/door/base surrounded by threats.

Numbers must be supported. If exact count is not known, use a truthful non-numeric formulation.

---

## D. survival_100_days_apocalypse

Signals:

- day count;
- hardcore;
- zombie apocalypse;
- frozen/ocean/desert survival;
- long-term base development;
- escalating disaster.

Viewer emotion: journey + endurance + payoff.

Strong click levers:

- Day 1 vs Day 100;
- base transformation;
- primitive gear vs final gear;
- hostile environment;
- final threat.

Title grammars:

- `I Survived 100 Days in [WORLD/THREAT]`
- `100 Days in a [ZOMBIE/HORROR/etc.] Minecraft World`
- `I Had 100 Days to Survive [DISASTER]`

Thumbnail grammars:

- split before/after;
- final base with disaster closing in;
- player evolution from weak to strong;
- one iconic environmental rule.

Do not clutter a 100-days thumbnail with every event from the run.

---

## E. story_series_recurring_ip

Signals:

- recurring named character;
- ongoing series;
- viewers already know a persona/world;
- episode numbers;
- familiar relationships.

Viewer emotion: attachment + continuation.

Strong click levers:

- recurring face/skin/character identity;
- new conflict;
- relationship change;
- cliffhanger.

Title grammar:

`[KNOWN IP/CHARACTER] + [NEW PROBLEM/EVENT]`

For established series, novelty does not need to come entirely from the title. The familiar IP itself carries click value.

For a new channel, do not imitate a mature channel's generic episode naming before the audience knows the IP.

---

## F. comedy_troll_chaos

Signals:

- prank/troll;
- friends reacting;
- traps;
- ridiculous accidents;
- social conflict;
- meme-heavy pacing.

Viewer emotion: anticipation of reaction.

Strong click levers:

- victim + trap;
- impossible misunderstanding;
- reaction moment;
- obvious setup with unknown outcome.

Title grammars:

- `I Trolled My Friend Using [THING]`
- `My Friend Had No Idea I [DID THIS]`
- `This Minecraft Trap Went Completely Wrong`

Thumbnail grammars:

- trap clearly readable + victim approaching;
- prankster/player + victim reaction;
- two-state setup/outcome when useful.

Do not make the thumbnail so visually noisy that the joke requires explanation.

---

## G. build_redstone_invention

Signals:

- build project;
- base/megabase;
- redstone machine;
- engineering;
- automation;
- farm/invention.

Viewer emotion: wonder + competence + usefulness.

Strong click levers:

- final build clarity;
- scale;
- function;
- before/after;
- one surprising capability.

Title grammars:

- `I Built [IMPOSSIBLE/USEFUL THING] in Minecraft`
- `I Made a [MACHINE] That [RESULT]`
- `This Redstone Build [UNEXPECTED RESULT]`

Thumbnail grammars:

- final build dominates;
- simple input → output visual;
- player for scale only;
- avoid unnecessary boss/horror language.

---

## H. exploration_secret_rare_discovery

Signals:

- secret base;
- impossible room/structure;
- rare item;
- hidden biome;
- mystery;
- footprints/clues;
- "what is inside?"

Viewer emotion: curiosity/discovery.

Strong click levers:

- partially concealed answer;
- locked door/portal/chest;
- one clue;
- rare recognizable object.

Title grammars:

- `I Found Minecraft's [RAREST/SECRET] [THING]`
- `What's Inside This [IMPOSSIBLE STRUCTURE]?`
- `I Followed [CLUE] and Found...`

Thumbnail grammars:

- reveal only 60–80% of the mystery;
- doorway/portal with intriguing silhouette;
- clue → hidden target.

Do not reveal the entire answer in both title and thumbnail.

---

## I. collection_completion_capture

Signals:

- every mob;
- every boss;
- every item;
- capture/collect/defeat all;
- museum/zoo/arena.

Viewer emotion: completion + scale.

Title grammars:

- `I Trapped EVERY [CATEGORY] in Minecraft`
- `I Collected Every [THING]`
- `[ENTITY] vs ALL Minecraft Bosses`

Thumbnail grammars:

- hero/collector + small curated set of recognizable representatives;
- central final/rarest target;
- collection container/arena.

Do not squeeze dozens of tiny entities into the thumbnail.

---

## J. pvp_smp_civilization_war

Signals:

- factions;
- SMP betrayal;
- civilization simulation;
- server war;
- prison;
- army;
- territory.

Viewer emotion: social stakes + power + story.

Strong click levers:

- clear sides;
- one betrayal/problem;
- territory/objective;
- asymmetrical power.

Title grammars:

- `I Started a Minecraft Civilization War`
- `How I Took Over This Minecraft SMP`
- `I Secretly Lived Inside Their SMP`
- `I Built an Army to [GOAL]`

Thumbnail grammars:

- faction A vs faction B;
- one player hidden inside enemy territory;
- crown/base/flag as objective;
- army scale without visual clutter.

---

## K. rule_twist_minecraft_but

Signals:

- custom rules;
- unusual drops;
- blocks spread/copy;
- gravity/world behavior changes;
- one mechanic changes the run.

Viewer emotion: "what happens if...?"

Title grammars:

- `Minecraft, But Every [THING] [RULE]`
- `Minecraft, But [SIMPLE EXTREME MECHANIC]`
- `Every Time I [ACTION], [WORLD CHANGE]`

Thumbnail grammars:

Show the rule visually, not merely with text. One before/after or cause/effect is often strongest.

---

## L. mod_showcase_mechanic_experiment

Signals:

- one mod is the product;
- experiments;
- boss battles;
- mob comparisons;
- item mechanics;
- "what if" testing.

Viewer emotion: spectacle + curiosity.

Title grammars:

- `[BOSS] vs ALL [CATEGORY]`
- `What Happens If [MECHANIC]?`
- `I Tested Minecraft's [MOST EXTREME] [THING]`

Thumbnail grammars:

- versus composition;
- experiment setup;
- clear object + consequence.

---

# 6. Click levers library

Use click levers intentionally. Do not stack every lever into every video.

## Scale contrast

`tiny player ↔ huge boss/world/crowd`

Best for boss, swarm, build scale, disasters.

## Progression gap

`weak ↔ final form`

Best for upgrades/evolution/100-days.

## Impossible odds

`1 ↔ 1000`

Best for hunters/swarm/civilization.

## Reversal

Take an expected power relationship and flip it.

Examples:

- feared monster becomes trapped;
- weak mob defeats bosses;
- player becomes the thing that normally hunts them.

## Scarcity/rarity

Use only when the item/location is actually rare/special in the content.

## Mystery concealment

Show enough to prove something interesting exists, but hide the final answer.

## Countdown/time pressure

Use when the actual video has time/day/round constraints.

## Social conflict

Friend, server, army, betrayal, prank, rivalry.

## Transformation

Physical change, morph, gear evolution, base evolution, world evolution.

---

# 7. Thumbnail composition system

## One-frame rule

The central idea should be understandable in roughly one second on a phone.

## Attention zones

Prefer 1–3 meaningful zones.

Common boss layout:

- hero threat: 45–65% of composition;
- player/hero: 10–25%;
- one proof/supporting object: remaining visual attention.

Common progression layout:

- before/weak state;
- after/final state;
- optional boss/reward target.

Common discovery layout:

- player/clue;
- hidden opening/target;
- controlled darkness/negative space.

## Text

Default: **zero text**.

Use text only when the image cannot communicate a critical abstract property.

Good text:

- `DAY 1` / `DAY 100`
- `FINAL FORM`
- `LEVEL 100`
- a short numeric multiplier if factual.

Avoid paragraphs, captions, or repeating the title.

## Mobile test

At small size, verify:

- hero subject is still identifiable;
- threat/reward relationship remains obvious;
- player silhouette does not disappear;
- text, if any, remains readable;
- background does not merge with subject;
- the thumbnail does not require knowledge of tiny UI details.

---

# 8. Title design system

## A good Minecraft title usually contains 2–3 of these elements

- goal;
- constraint/rule;
- threat;
- transformation;
- scale;
- rare object;
- social conflict;
- time limit;
- reversal.

Do not stuff all of them into one title.

## Front-load the hook

Put the strongest concept early enough that mobile truncation does not hide it.

Weak:

`Today I Played Minecraft With My Friends And Eventually Found...`

Stronger:

`I Survived Verity While My Entire Server Hunted Me`

## Specific nouns beat vague adjectives

Prefer:

- Titan;
- Verity;
- 1,000 Hunters;
- Zombie Apocalypse;
- Every Horror Mob;
- Final Weapon.

Over:

- crazy thing;
- insane challenge;
- unbelievable moment.

## One dominant claim

A title should usually sell one main premise.

## Market-native localization

When translating/repacking into English or another language, write as a native YouTube title for that market rather than preserving source-language syntax.

Literal translation is evidence, not final copy.

---

# 9. Title and thumbnail must form an information gap

Bad pair:

Title: `I Fought a Giant Titan`

Thumbnail text: `GIANT TITAN`

Both communicate the same fact.

Better pair:

Title: `I Had to Upgrade Every Weapon Before Fighting This Titan`

Thumbnail: actual Titan occupying most of frame + tiny player holding the visually strongest real final weapon.

Title communicates **rule/progression**.

Thumbnail communicates **scale/stakes/proof**.

Viewer mentally asks:

`How strong did he have to become to beat THAT?`

That question is the click engine.

---

# 10. Research with vidIQ

When current research is available, use it as evidence, not as an oracle.

## Recommended research sequence

1. target channel recent videos;
2. target channel top videos;
3. Minecraft outliers within the relevant family;
4. similar thumbnails for 1–3 useful seeds;
5. recent/high-VPH videos when trend sensitivity matters;
6. title/thumbnail history where a proven video changed packaging.

## Interpret correctly

Do not conclude "this works" merely because a huge channel has millions of views.

Prefer signals such as:

- breakout score;
- views relative to subscriber base/channel norm;
- VPH;
- repeated patterns across at least several independent channels;
- performance differences within the same creator.

## Series vs concept

A mature creator can get huge views from a generic recurring-series title because the series itself is an IP.

A new channel cannot assume the same privilege.

For weak/new channel identity, favor a highly legible **concept-driven package**.

---

# 11. Concept generation procedure

For each video:

## Step A — list real click assets

Identify:

- biggest threat;
- biggest reward;
- weirdest mechanic;
- strongest transformation;
- largest scale contrast;
- best-known entity;
- rarest discovery;
- strongest social conflict;
- strongest visually readable moment.

## Step B — create 12–20 hook statements

Do not write polished titles yet.

Examples:

- "tiny player vs real Titan"
- "every kill upgrades the gun"
- "one player surrounded by 1,000 hunters"
- "day 1 hut vs day 100 fortress"
- "Verity is trapped instead of hunting the player"

## Step C — score hooks

Reject hooks that are difficult to explain visually.

A strong rule of thumb:

> If the core premise needs more than one sentence to explain before the thumbnail makes sense, the packaging is probably weak.

## Step D — shortlist 3 distinct mechanisms

Example for one Titan video:

- A: impossible boss scale;
- B: weak-to-final weapon progression;
- C: survival/chase before the Titan catches the player.

## Step E — make titles for each concept

Create multiple title variants within each concept, then pair only the strongest with its visual story.

---

# 12. Variant design

Three strong A/B variants should answer three different click motivations.

Example:

## Variant A — Threat

Title: `This Titan Was Too Strong for My Minecraft World`

Visual: actual Titan fills frame; tiny damaged player.

## Variant B — Progression

Title: `I Upgraded Every Weapon to Beat This Titan`

Visual: final real weapon + Titan.

## Variant C — Time pressure

Title: `I Had to Get Stronger Before the Titan Found Me`

Visual: player/base foreground; Titan approaching.

These are real variants because each tells a different story.

---

# 13. Reup/localization packaging

For reup/localization workflows, the source package is not the final package.

## Do

- inspect the actual video;
- identify actual modpack/entity/item/mechanic;
- verify any number/extreme claim;
- choose the strongest real click proposition for the target audience;
- rewrite the title idiomatically;
- create a fresh thumbnail using real source/mod assets;
- preserve recognizable boss/item identity;
- choose a target-market hook family based on current research when possible.

## Do not

- literally translate the source title and call it done;
- copy the source thumbnail composition pixel-for-pixel;
- fabricate a more clickable boss;
- misrepresent another player's footage as your own recording;
- assume a Chinese/Douyin title's hyperbole is factually correct without checking.

---

# 14. Quality scoring

The canonical numeric weights live in `../schemas/policy.json`. Use them as a gate, not as fake precision.

A strong package should score highly in all three layers:

## Hook strength

- instantly understandable;
- visually demonstrable;
- strong stakes;
- novelty;
- curiosity;
- real recognizable asset;
- target-market fit.

## Thumbnail strength

- clear focal point;
- mobile-readable;
- actual-content fidelity;
- visual stakes;
- contrast/depth;
- curiosity;
- clean rather than cluttered;
- complements title.

## Title strength

- clear premise;
- concrete nouns/numbers;
- meaningful stakes/goal;
- curiosity gap;
- novelty;
- natural target-language phrasing;
- complements thumbnail;
- honest payoff.

A package that fails a hard gate is rejected even if its average numeric score is high.

---

# 15. Anti-patterns

Reject or rework these patterns.

## Generic AI boss

A random cinematic monster that only vaguely resembles the actual mod entity.

## Thumbnail soup

Ten mobs, five items, multiple arrows, particles everywhere, four text labels.

## Decorative clickbait

Glow, red circles, arrows, emoji, and explosions added to a concept that has no strong premise.

## Same formula every upload

Boss big/player small on progression, redstone, comedy, build, and story videos alike.

## Title-thumbnail duplication

Both surfaces say exactly the same thing.

## Unverified extreme number

"1,000,000" because it sounds good, despite no evidence.

## Mature-series imitation

Using generic `Episode 18` packaging on a new channel that has not built recurring IP.

## Prompt-first workflow

"Generate an epic Minecraft thumbnail" before understanding the video.

## Polishing a weak hook

If the concept is not interesting at feed size, extra lighting and effects will not save it. Return to hook selection.

---

# 16. Learning loop

After publishing/A-B testing, capture:

- winning title;
- winning thumbnail concept;
- CTR where available;
- watch time / retention implications;
- traffic context;
- what click lever won;
- family classification;
- whether the promise was paid off cleanly;
- whether comments reveal confusion/misleading packaging.

Over time, update channel-specific priors:

- which families work for that channel;
- recurring entities viewers recognize;
- preferred visual density;
- title length/voice;
- whether audience responds better to threat, progression, comedy, discovery, or scale.

Do not turn these learnings into rigid repetition. Use them as priors, then continue testing novel concepts.

---

# 17. Final checklist

Before calling a Minecraft package complete:

- [ ] I know what type of Minecraft video this is.
- [ ] I inspected the actual content rather than trusting metadata alone.
- [ ] The thumbnail hero asset really exists in the video/modpack.
- [ ] Every strong number/claim has evidence.
- [ ] The package has one dominant idea.
- [ ] The title and thumbnail communicate different but complementary information.
- [ ] The premise is readable on mobile.
- [ ] The thumbnail does not depend on tiny details or excessive text.
- [ ] I created at least three conceptually different strong variants.
- [ ] I checked current comparable winners when tools/quota allowed.
- [ ] The final package passes all hard gates.
- [ ] The video actually pays off the click promise.

The desired outcome is not simply a beautiful Minecraft thumbnail. It is a package where a scrolling viewer understands the conflict/reward almost instantly, sees credible proof that it is real, feels the stakes, and still has one compelling unanswered question that only the video can answer.
