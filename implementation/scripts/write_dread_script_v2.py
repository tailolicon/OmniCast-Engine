# -*- coding: utf-8 -*-
"""Hand-authored first-person horror script for true_dread_files_us.

Written by the operator's editor (not an LLM API call) to kill the AI-slop
tells the generated draft had: uniform staccato rhythm, verification cosplay,
database-symmetric structure, zero interiority. Produces the same product
artifacts the pipeline emits (script.txt + prosody sidecar script.json) so
render_real_video consumes it unchanged.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANNEL = "true_dread_files_us"
SLUG = "20260711_0001_3_true_night_shift_stories_that_made_me_quit"
TOPIC = "3 True Night Shift Stories That Made Me Quit"

# scene = (segment, voiceover, visual_prompt, pace, pause_ms, emphasis)
S = []

def sc(seg, vo, vis, pace="normal", pause=0, emph=None):
    S.append({"segment": seg, "voiceover": vo, "visual_prompt": vis,
              "sfx": "", "duration_s": round(len(vo.split()) / 2.4, 1),
              "pace": pace, "pause_after_ms": pause, "emphasis": emph or []})

# ── HOOK ─────────────────────────────────────────────────────────────────────
sc("HOOK",
   "I worked the overnight shift at a freight warehouse for three years. I quit in the middle of a shift, in February, without taking my last paycheck.",
   "grainy photoreal night photo: enormous dark warehouse interior, single sodium light far away", "slow", 700, ["quit in the middle of a shift"])
sc("HOOK",
   "I've never told anyone the whole thing. My wife knows a version of it. This is the real one.",
   "photoreal: dim kitchen at night, man sitting alone, face half lit by phone screen", "slow", 900, [])

# ── STORY 1: AISLE NINE (long, ~1050 words) ──────────────────────────────────
sc("Aisle Nine",
   "The warehouse sat off a county road about twenty minutes outside town. Frozen food distribution. My job was simple — I drove a forklift up and down thirty aisles, pulling pallets for the morning trucks, alone from ten at night until six.",
   "real footage: forklift driving through tall warehouse aisles at night", "normal", 0, [])
sc("Aisle Nine",
   "People think warehouses are quiet at night. They're not. The freezers cycle on and off, the racking creaks as the temperature drops, and the whole building pops and settles like it's stretching. Three years in, I could name every sound that place made.",
   "real footage: industrial freezer units, frost on metal racking, dim lights", "normal", 0, [])
sc("Aisle Nine",
   "Which is the only reason I noticed the night it made a sound I couldn't name.",
   "photoreal grainy: long dark warehouse aisle vanishing into blackness", "slow", 1100, ["couldn't name"])
sc("Aisle Nine",
   "It was a Tuesday in January. Maybe one thirty in the morning. I was at the far end of aisle nine, way at the back where the pick lights don't reach, and I heard what I can only describe as a shoe scuffing on concrete. One scuff. Behind me.",
   "real footage: worn concrete warehouse floor, forklift shadow stretching long", "normal", 600, ["One scuff"])
sc("Aisle Nine",
   "And here's the thing — that's not an alarming sound in most places. But I had locked the dock doors myself at midnight. There was one other key on that shift, and it was hanging in the office, and the office was dark.",
   "real footage: heavy chain and padlock on industrial door, night", "normal", 0, [])
sc("Aisle Nine",
   "I sat on that forklift with the engine idling and I told myself it was a pallet shifting. Wood does that. I even said it out loud, which I'd never done before. Like I needed to hear a voice, even mine.",
   "real footage: man's hands gripping forklift steering wheel", "slow", 0, [])
sc("Aisle Nine",
   "I finished the pull and drove back toward the front, and as I came around the end cap of aisle nine my headlights swept across the cross-aisle, and there was a man standing at the far end of it.",
   "grainy photoreal night photo: distant thin human silhouette at the end of a warehouse aisle, barely visible in shadow, unsettling", "slow", 1200, ["man standing"])
sc("Aisle Nine",
   "Far away. Maybe sixty meters. Just inside the reach of the light, so I couldn't see a face — just the shape of shoulders and a head, and the fact that the shape was facing me.",
   "grainy photoreal: same distant silhouette, slightly closer framing, sodium light halo", "slow", 800, [])
sc("Aisle Nine",
   "My first thought wasn't fear, honestly. It was anger. I thought some driver had gotten locked in, or a temp had hidden through closing, and now I'd have to do paperwork. I yelled hey. My voice went down that aisle and came back to me and the shape didn't move at all.",
   "real footage: warehouse aisle from low angle, lights flickering slightly", "normal", 0, [])
sc("Aisle Nine",
   "Didn't wave. Didn't shift its weight. You know how a person standing still is never actually still — there's sway, there's breathing. There wasn't.",
   "photoreal grainy: extreme long shot, motionless silhouette between racks", "slow", 1000, ["There wasn't"])
sc("Aisle Nine",
   "I drove toward it. I want to say that was brave but it was the forklift — you feel safe inside three tons of steel. I got maybe halfway down the aisle and I had to look down for half a second, just to steer around a pallet jack somebody had left out.",
   "real footage: forklift POV driving down warehouse aisle, obstacles", "fast", 0, [])
sc("Aisle Nine",
   "Half a second. When I looked up the aisle was empty.",
   "photoreal grainy: empty warehouse aisle, light cone with nothing in it", "slow", 1300, ["empty"])
sc("Aisle Nine",
   "I know what you're thinking, because it's what I thought. He stepped into a rack row. Fine. Except from where I was, I could see down the next three cross-rows on both sides as I passed them, one after another, and every single one was empty, and the dock door at that end was still chained.",
   "real footage: passing warehouse rack rows one by one, each empty", "normal", 600, [])
sc("Aisle Nine",
   "I searched that building for forty minutes with every light on. I checked the office. The key was where I'd left it. The dust on the mezzanine stairs didn't have a single print in it, and mine were the only boot marks by either dock.",
   "real footage: dusty metal stairs, single bare lightbulb, night", "normal", 0, [])
sc("Aisle Nine",
   "I didn't call anyone. What was I going to say? I finished the shift with the radio on loud, and by the drive home I had half convinced myself I'd seen a coat rack, a strapping machine, a shadow. The brain is good at that. Give it a week and it'll sand the edges off anything.",
   "real footage: dawn breaking over industrial parking lot, tired man walking to car", "normal", 0, [])
sc("Aisle Nine",
   "Three weeks later it was closer.",
   "grainy photoreal: warehouse aisle, thin silhouette noticeably nearer than before, still facing camera", "slow", 1400, ["closer"])
sc("Aisle Nine",
   "Same aisle. Same stillness. But now I could see that the coat I'd imagined wasn't a coat, it was just... dark. Like the shape was wearing the dark. And this time I hadn't heard a single sound before my lights found it — and that was worse. The scuff, at least, had been something a person makes.",
   "grainy photoreal: closer silhouette, head slightly tilted, no visible face, deep grain", "slow", 1100, [])
sc("Aisle Nine",
   "I didn't drive toward it that time. I reversed out of the aisle, parked by the office with my back to a wall, and sat there until the freezer cycle kicked in and made me jump so hard I hit the horn. When I forced myself to do a lap at four a.m., the building was empty. It was always empty. That was the problem.",
   "real footage: man sitting rigid in dim warehouse office, vending machine light", "normal", 800, [])
sc("Aisle Nine",
   "The last night, I never saw it at all. What happened was the sounds I knew — the pops, the creaks, the settling I'd spent three years learning — they stopped. All of them. At once. A building that size is never silent, and at two-forty in the morning it went silent the way a room does when someone walks in.",
   "real footage: still warehouse interior, absolute stillness, wide shot", "slow", 1200, ["silent"])
sc("Aisle Nine",
   "I left the forklift running in the middle of the floor. I took my thermos, I walked out the man door, and I sat in my truck until Dale showed up at five forty-five. Told him I was sick. Never went back inside. They mailed me my stuff and I let the last check go, because going in to sign for it meant standing in that office with my back to the floor.",
   "real footage: pickup truck alone in dark industrial lot, engine exhaust in cold air", "normal", 900, [])
sc("Aisle Nine",
   "It never touched me. It never even moved while I was looking. I want to be fair about that. But every time I saw it, it was closer, and I wasn't going to be there for the time it was close enough.",
   "grainy photoreal: warehouse aisle at night, empty, but oppressive framing", "slow", 1500, ["closer"])

# ── STORY 2: THE REGULAR (medium, ~650 words) ────────────────────────────────
sc("The Regular",
   "The second story isn't mine. It's my brother-in-law Marcus's, and I believe him, partly because he's the least imaginative man I've ever met, and partly because of how he tells it — which is reluctantly, and only ever once per telling.",
   "real footage: two men on a porch at night, beer bottles, low conversation", "normal", 0, [])
sc("The Regular",
   "Marcus ran the register at a twenty-four-hour gas station out on Route 60. The kind of place that's an island of white light with nothing around it. He liked the overnight because it was dead — a trucker at midnight, maybe a drunk at two, then nothing until the paper guy.",
   "real footage: isolated gas station glowing at night, empty road", "normal", 0, [])
sc("The Regular",
   "One night in November a man walked in around one fifteen. Older guy. Work jacket. Bought a coffee, paid in coins, counted them out slow. And on his way out he stopped at the door and asked — without turning around — is the back road to Millfield still closed?",
   "real footage: gas station interior at night, coffee machine, register counter", "normal", 500, [])
sc("The Regular",
   "Marcus said yeah, been closed since the flood. The man nodded and walked out, and Marcus watched him cross the lot and walk past the pumps, out of the light, going left. On foot. There was no car.",
   "grainy photoreal: man in work jacket walking out of gas station light into darkness", "slow", 900, ["no car"])
sc("The Regular",
   "At two forty the door chime went and the same man walked in. Same jacket. Same coffee. Paid in coins, counted slow. And at the door, without turning: is the back road to Millfield still closed?",
   "real footage: gas station door with chime, night reflections in glass", "slow", 800, ["same man"])
sc("The Regular",
   "Marcus figured drunk, or dementia, and it broke his heart a little, so he just said yeah, still closed, you doing okay? And the man stood there, hand on the door, back to him, for what Marcus swears was ten full seconds. Then he said — thank you — in a completely different voice. And left. Left going left again.",
   "grainy photoreal: view through gas station window, figure standing at edge of lot light, back turned", "slow", 1200, ["completely different voice"])
sc("The Regular",
   "The third time was four minutes past four. Marcus heard the chime and looked up and his whole body did the math before his brain did — because there hadn't been a soul in the lot, and the road was empty in both directions, and you can see that road for half a mile.",
   "real footage: empty two-lane road at night from gas station, both directions", "fast", 0, [])
sc("The Regular",
   "Same coins. Same question. Except this time, when Marcus didn't answer — he told me he physically couldn't, his mouth wouldn't do it — the man turned his head. Just enough. And Marcus said the face was ordinary. Completely ordinary. And that he still sees it when he can't sleep, because he says there was nothing behind it. Like a face hung on a hook.",
   "grainy photoreal extreme close: partial profile of an ordinary older face in fluorescent light, subtly wrong, heavy grain", "slow", 1500, ["nothing behind it"])
sc("The Regular",
   "Marcus locked the door when he left and spent the rest of the shift in the stockroom with a box cutter, watching the register camera on the little monitor. Nobody came in. The chime never went again. When his relief showed at six, there were three coffee cups in the trash can by the pumps. Stacked. He hadn't emptied that can all night, and he only remembered selling two coffees... and then he stopped telling me the story, and we talked about football.",
   "real footage: trash can by gas pumps at dawn, harsh morning light", "slow", 1300, ["Stacked"])
sc("The Regular",
   "He quit that same week. Different reason on the paperwork.",
   "real footage: help wanted sign taped in gas station window", "slow", 1000, [])

# ── STORY 3: FRESH SNOW (short, ~380 words) ──────────────────────────────────
sc("Fresh Snow",
   "The last one is short. I heard it from a man I worked highway maintenance with, years later, after I told him mine. He waited until the others left the break room. I think he'd been waiting years for someone to trade with.",
   "real footage: empty break room, vending machine hum, fluorescent light", "normal", 0, [])
sc("Fresh Snow",
   "Winter of 2009 he was running a one-man weigh station overnight, up in the hills. A booth, basically. A heater, a radio, a window on each side. It had snowed hard until midnight and then gone dead calm — and if you've been in snow country you know that silence. The world in a padded room.",
   "real footage: small lit booth in deep snow at night, absolute stillness", "slow", 700, [])
sc("Fresh Snow",
   "At three in the morning, something walked across his roof.",
   "photoreal grainy: low angle of small booth roof against night sky, snow falling lightly", "slow", 1400, ["across his roof"])
sc("Fresh Snow",
   "Not scrambled — walked. Four, five steps. Heel to toe, he said. The ceiling was maybe a foot over his head. He sat with his coffee halfway to his mouth and listened to it reach the edge of the roof. And stop.",
   "real footage: interior of booth, steam from coffee, man frozen mid-motion", "slow", 1100, ["And stop"])
sc("Fresh Snow",
   "He said it took him twenty minutes to open the door. I believe that. And when he finally walked the full circle around that booth with his flashlight, the snow was perfect. Roof, ground, everywhere. Two feet of fresh snow in every direction, without a single mark in it. Not even birds.",
   "grainy photoreal: flashlight beam over unbroken snow around small booth, pristine surface", "slow", 1400, ["without a single mark"])
sc("Fresh Snow",
   "He transferred to day shift that spring. He told me the part that stayed with him wasn't the steps. It was the stopping. Because things that stop... are deciding.",
   "photoreal grainy: booth window from outside at night, small figure of man visible inside, vast darkness around", "slow", 1600, ["deciding"])

# ── OUTRO ────────────────────────────────────────────────────────────────────
sc("OUTRO",
   "I don't have an explanation for any of this, and I've stopped wanting one. Some jobs put you alone in big dark places for money, and my honest advice is: when the place starts being wrong, believe it early. The check is not worth it.",
   "real footage: highway at night from car interior, taillights fading", "slow", 900, [])
sc("OUTRO",
   "If you've worked nights and you've got one of these — put it in the comments. I read all of them. Usually in the morning.",
   "real footage: sunrise through blinds, quiet room", "normal", 0, ["in the morning"])

# ── emit ─────────────────────────────────────────────────────────────────────
prod = ROOT / "output" / "products" / CHANNEL / SLUG
prod.mkdir(parents=True, exist_ok=True)

total_words = sum(len(s["voiceover"].split()) for s in S)
txt_parts, cur = [], None
for s in S:
    if s["segment"] not in ("HOOK", "OUTRO") and s["segment"] != cur:
        txt_parts.append(f"\n[{s['segment']}]\n")
        cur = s["segment"]
    txt_parts.append(s["voiceover"] + " ")
(prod / "script.txt").write_text("".join(txt_parts).strip() + "\n", encoding="utf-8")

(prod / "script.json").write_text(json.dumps({
    "topic": TOPIC, "channel_id": CHANNEL, "variant_id": "editor_v2",
    "score": 0, "scenes": S,
}, ensure_ascii=False, indent=1), encoding="utf-8")

(prod / "meta.json").write_text(json.dumps({
    "channel": CHANNEL, "topic": TOPIC, "slug": SLUG, "stage": "script",
    "script": "script.txt", "best_variant": "editor_v2", "score": None,
    "note": "hand-authored first-person rewrite (anti AI-slop pass)",
}, ensure_ascii=False, indent=1), encoding="utf-8")

print(f"scenes={len(S)} words={total_words} -> {prod}")
