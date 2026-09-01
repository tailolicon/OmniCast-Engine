<!-- GENERATED — replace every {{PLACEHOLDER}} with the queue item's fields before writing. -->

Write a production-ready YouTube script optimized for 70%+ audience retention.

TOPIC: {{TITLE}}
NICHE: health | MARKET: US
TARGET LENGTH: 10 minutes (~1500 spoken words)
VOICE: evidence-based health researcher

ANGLE: Open with the EXACT dollar amount or percentage the viewer is losing RIGHT NOW. Make them feel the pain in the first sentence.

KEY POINTS TO COVER:
- {{KEY_POINT_1}}
- {{KEY_POINT_2}}
- {{KEY_POINT_3}}

OUTPUT FORMAT — scene-based JSON, one object per 3-5 second screen cut:
  "vo"     — MAX 25 words. Natural spoken English. ZERO scripting jargon.
  "visual" — stock footage query, MAX 6 plain words: a concrete filmable subject (never text popups, graphics, or camera directions).
  "sfx"    — "heartbeat" | "flatline" | "whoosh" | "ting" | null
  "pace"   — "slow" | "normal" | "fast" — delivery speed for THIS scene (see PROSODY rules;
             slow = hook/big-stat/outro, fast = explanation runs & montage, mix required).
  "pause_after_ms" — 0 normally; 400-700 after a twist/question; 800-1500 for the 2-4
             biggest dramatic beats only.
  "emphasis" — array of 1-3 EXACT words from vo to vocally stress (numbers, twist words). [] if none.

For this niche, typical visuals include: medical imagery, healthy lifestyle, lab results
Primary SFX for key reveals: "heartbeat"
Authority proof source: PubMed studies

Use EXACTLY these section labels. Output valid JSON arrays only.

HOOK EXAMPLE (follow this energy and specificity):
  H scene vo: "72% of Americans over 40 have this vitamin deficiency — and your doctor isn't testing for it."

HOOK:
SCENES:
[
  {"vo": "[G — short warm spoken greeting (<=8 words) flowing straight into the topic, e.g. 'Hey, great to have you — today, [topic].']", "visual": "[medical imagery, healthy lifestyle, lab results — calm cinematic opener]", "sfx": null, "pace": "slow", "pause_after_ms": 0, "emphasis": []},
  {"vo": "[H — THE hook: pain-first, exact number/stat they are LOSING right now, a curiosity gap. Max 18 words. Self-contained (this becomes the TITLE). No 'imagine'/'picture this'.]", "visual": "[medical imagery, healthy lifestyle, lab results — most alarming version]", "sfx": "flatline", "pace": "slow", "pause_after_ms": 900, "emphasis": ["[the hook's key number/word]"]},
  {"vo": "[P — credible data point: 'According to PubMed studies, X%...']", "visual": "[PubMed studies report cover or chart displayed full screen]", "sfx": "heartbeat", "pace": "normal", "pause_after_ms": 0, "emphasis": ["[the stat]"]}
]

SEGMENT 1: [Curiosity-gap heading — 5 words max]
SCENES:
[
  {"vo": "[First punchy sentence setting up the core problem.]", "visual": "[medical imagery, healthy lifestyle, lab results]", "sfx": null},
  {"vo": "[Key statistic with source attribution.]", "visual": "[text-popup or chart animation showing the number]", "sfx": "heartbeat"},
  {"vo": "[Build tension — what happens if they do nothing.]", "visual": "[consequence visual matching niche: medical imagery, healthy lifestyle, lab results]", "sfx": null},
  {"vo": "[Natural open-loop in plain speech — MUST sound like normal conversation, NOT a label. E.g.: 'And there is a second trap most people never catch — I will show you in a few minutes.']", "visual": "[presenter on camera leaning forward]", "sfx": null}
]

SEGMENT 2: [Heading]
SCENES:
[
  {"vo": "[Continue story or data. Short punchy sentence.]", "visual": "[medical imagery, healthy lifestyle, lab results]", "sfx": null},
  {"vo": "[Key insight or data point with source.]", "visual": "[chart or text popup — blue-medical]", "sfx": "flatline"},
  {"vo": "[Rhetorical punch: restate the number simply. 'That is the real cost. Let it land.']", "visual": "[zoom in on number filling screen]", "sfx": null},
  {"vo": "[Bridge to next point.]", "visual": "[medical imagery, healthy lifestyle, lab results]", "sfx": null}
]

SEGMENT 3: [Heading]
SCENES:
[
  {"vo": "[Continue with next data point or evidence.]", "visual": "[medical imagery, healthy lifestyle, lab results]", "sfx": null},
  {"vo": "[Key data — most surprising finding.]", "visual": "[chart or graphic — concrete data]", "sfx": "heartbeat"},
  {"vo": "[Second natural open-loop in plain speech. E.g.: 'Before I show you the fix, there is one more thing most people miss — stay with me.']", "visual": "[presenter direct-to-camera]", "sfx": null},
  {"vo": "If this is changing how you see your health — tap Like. It keeps this research coming.", "visual": "[presenter smiling, relaxed, direct camera]", "sfx": "ting"}
]

SEGMENT 4: [Heading]
SCENES:
[
  {"vo": "[Continue with solution or key action step.]", "visual": "[medical imagery, healthy lifestyle, lab results]", "sfx": null},
  {"vo": "[Most actionable takeaway — specific and concrete.]", "visual": "[chart, comparison, or step graphic]", "sfx": null},
  {"vo": "I covered the exact protocol in another video — link below if you want the full breakdown.", "visual": "[presenter gestures to side or below]", "sfx": null}
]

SEGMENT 5: [Heading — resolve BOTH open loops from segments 1 and 3]
SCENES:
[
  {"vo": "[Resolve open loop from segment 1 — deliver the exact payoff promised.]", "visual": "[the reveal: specific number, chart, or comparison]", "sfx": "heartbeat"},
  {"vo": "[Key resolution data — the proof the payoff is real.]", "visual": "[chart or animation showing result]", "sfx": null},
  {"vo": "[Resolve open loop from segment 3 — deliver that payoff too.]", "visual": "[second reveal — concrete visual]", "sfx": "heartbeat"},
  {"vo": "[Final empowering takeaway. Actionable. What they can do TODAY.]", "visual": "[presenter direct-to-camera, confident]", "sfx": null}
]

OUTRO:
SCENES:
[
  {"vo": "One question: what is the one health habit you want to fix this month? Drop it below.", "visual": "[presenter leaning forward, engaged, direct camera]", "sfx": null},
  {"vo": "[EXPLICIT subscribe invite — MUST contain the word 'subscribe', framed with empathy/shared-identity tied to this topic, NOT generic. E.g.: 'If you are fighting this every single day, subscribe — I break down one real fix like this every week, and you should not have to figure it out alone.']", "visual": "[presenter direct-to-camera, warm]", "sfx": null},
  {"vo": "[Next video tease — use the NEXT QUEUED VIDEO title from above, add a curiosity gap. E.g.: 'Next: [exact title] — that one could save you even more.']", "visual": "[thumbnail-style teaser or presenter pointing]", "sfx": "whoosh"}
]

TOPICS ALREADY PUBLISHED ON THIS CHANNEL (do NOT duplicate):
- {{TOPICS_DONE}}

NEXT QUEUED VIDEO (use this EXACT title for the outro teaser):
- {{NEXT_TOPIC}}

HARD RULES — non-negotiable:
1. Output ONLY the script. Start with "HOOK:" on line 1. No preamble, no meta-text.
2. Every SCENES block must be a valid JSON array. No trailing commas. Use double quotes only.
3. "vo" field: 18-25 words per scene — use the FULL budget. Do NOT write thin
   8-12 word lines; each scene must carry a complete, substantive thought (a stat,
   an example, a consequence). Never exceed 25. Natural spoken English ONLY.
   BANNED WORDS in 'vo': hook, segment, B-roll, CTA, open loop, outro, narration,
   "let's dive in", "moving on", "as we discussed", "let me walk you through",
   "in today's video", "don't forget to like", "smash that subscribe button"
4. Open loops MUST be natural speech in 'vo' — not labels or brackets.
5. Segment 5 MUST resolve BOTH open loops from segments 1 and 3.
6. LENGTH IS MANDATORY: total vo words across ALL scenes MUST be 1500-1750
   words (a ~10-minute video at ~150 wpm). A short script is a FAILURE — YouTube
   needs 8+ minutes of content to enable mid-roll ads. Since each scene is capped at 25
   words, you MUST write MANY scenes (70+ total) to reach the word count.
7. Each SEGMENT's SCENES array MUST contain 10-16 scenes (the examples above show only
   3-4 — EXPAND every segment to 10-16 rich scenes with distinct visuals). Keep adding
   substantive scenes (more data points, examples, mini-stories) until total ≥ 1500 words.
8. YOUTUBE POLICY (mandatory — violations make the video unusable/demonetized):
   - NO scam/false promises: "get rich quick", "guaranteed income/profit", "100% guaranteed",
     "miracle cure", "double your money", "risk-free", "free money", "doctors hate".
   - NO advertiser-unfriendly words: profanity, graphic violence, self-harm, drugs, sexual content.
   - Make CLAIMS specific + sourced, not sensational. Advice framed as education, not promises.
9. FACTUAL GROUNDING (mandatory — fabricated stats get the channel flagged for misinformation):
   - Use ONLY statistics/numbers that appear in KEY POINTS above, or that are genuinely
     well-known public facts (e.g. "the S&P 500 has averaged about 10% annually").
   - Do NOT invent precise figures (specific percentages, dollar amounts, study results)
     and attach a fake source to them. If you lack a sourced number, speak QUALITATIVELY
     ("most retirees underestimate this", "studies consistently show") instead of a fake precise stat.
   - When you DO cite a number, attribute it only to a real, checkable source named in
     KEY POINTS / proof sources — never to a made-up "2024 report" that may not exist.
   - Rule of thumb: a viewer fact-checking any number in this script must find it TRUE.
10. PREMIUM EDITORIAL (mandatory — a counted, citation-reading script reads as AI and FAILS review):
   - NO listicle: never write "Number one/two/three…" as the spine. Group by named MECHANISM headings
     (e.g. "The Fat Paralysis", "The Roughage Blockade") + a narrative arc connecting them.
   - SHOW-DON'T-READ: 'vo' says findings qualitatively ("the latest data shows…"); NEVER read source
     name/year aloud. Put the source in the 'visual' field (e.g. "PubMed study page on screen") so it shows, not tells.
   - METAPHOR: each abstract mechanism gets ONE vivid FILMABLE metaphor; its 'visual' is a real scene
     (e.g. "traffic jam on a narrow alley", "truck flipped across a lane"), never an idiom.
   - EMPATHY: include ≥2 scenes naming the real felt sensation (fermenting, foaming, stuck in the throat hours later).
   - CTA from shared experience, not "keeps this channel going".
11. PROSODY IS MANDATORY: every scene object MUST carry "pace", "pause_after_ms", "emphasis".
   Target mix: 15-25% slow, 25-40% fast, rest normal; 3-6 pauses >=400ms total; every key
   stat listed in its scene's emphasis. An all-"normal" script is a FAILURE (flat robot voice).

