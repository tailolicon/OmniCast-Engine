"""Critic Agent — two-stage adversarial review (VO + production), 100-point scoring."""

from __future__ import annotations

import structlog

from omnicast.agents.base import BaseAgent
from omnicast.llm.client import LLMClient
from omnicast.models.script import ScriptDraft, CriticFeedback, CriticDimension, TopicBrief, spoken_word_floor
from omnicast.shared.errors import AgentError
from omnicast.config.niches import NicheConfig, get_niche_config

logger = structlog.get_logger()

# ── Score group maxima ────────────────────────────────────────────────────────
VO_MAX = 70          # voiceover group ceiling
PROD_MAX = 30        # production group ceiling

# Routing thresholds (75% of each group)
VO_PASS = 53         # int(70 * 0.75)
PROD_PASS = 23       # int(30 * 0.75)

# Overall approval (legacy, used by DebateConfig)
HUB_THRESHOLD = 85
SPOKE_THRESHOLD = 70

# ── VO dimension weights (sum = 70) ──────────────────────────────────────────
# hook_quality + anti_ai_cliche + retention_structure + human_editorial
# + niche_compliance + pacing_compliance = 70
VO_DIMS = {
    "hook_quality":         25,
    "anti_ai_cliche":       15,
    "retention_structure":  10,
    "human_editorial":      10,
    "niche_compliance":      5,
    "pacing_compliance":     5,
}

# ── Production dimension weights (sum = 30) ───────────────────────────────────
PROD_DIMS = {
    "visual_concreteness":  25,
    "sfx_appropriateness":   5,
}

# ── Niche-specific fatal rules (injected into niche_compliance rubric) ────────
NICHE_FATAL_RULES: dict[str, list[str]] = {
    "finance": [
        "Any form of 'guaranteed returns' / 'guaranteed profit' → niche_compliance = 0 immediately",
        "Specific stock/fund recommendation without disclaimer → niche_compliance ≤ 2",
        "Claiming specific future price targets → niche_compliance = 0",
        "Promising viewer will achieve specific dollar outcome → niche_compliance = 0",
        "Narrator claiming to BE a licensed advisor/CPA/planner or to have clients "
        "('as a financial advisor…', 'my clients…') → niche_compliance = 0 "
        "(synthetic-voice channel: credentials would be fabricated)",
    ],
    "finance.retirement_senior": [
        "Same rules as finance PLUS:",
        "'You will have $X at retirement' without showing math/assumptions → niche_compliance = 0",
        "Social Security / IRS / Medicare number without naming source + year → niche_compliance ≤ 2",
        "Personalized directive ('you should claim at 62') instead of educational framing → niche_compliance ≤ 2",
    ],
    "finance.retirement": [
        "Same rules as finance PLUS:",
        "'You will have $X at retirement' without showing math/assumptions → niche_compliance = 0",
        "Social Security claim without citing SSA data → niche_compliance ≤ 2",
    ],
    "finance.crypto": [
        "Same rules as finance PLUS:",
        "Any 'this coin will X' price prediction → niche_compliance = 0",
        "Claiming regulatory certainty ('this is definitely legal') → niche_compliance = 0",
    ],
    "health": [
        "Medical claim without citation (e.g. 'cures', 'treats', 'prevents', 'reverses') → niche_compliance = 0",
        "Specific dosage recommendation → niche_compliance ≤ 2",
        "Claim that overrides doctor advice ('you don't need your doctor for this') → niche_compliance = 0",
        "Fabricated/unverifiable statistic (a precise number a fact-checker can't confirm) → niche_compliance ≤ 2. "
        "NOTE: the stat must be REAL, but the 'vo' should state it QUALITATIVELY ('the latest data shows…') — "
        "reading the journal name/year ALOUD ('a 2023 X journal review found…') is an AI-tell, NOT a requirement; "
        "the source belongs on screen (visual), not in the narration.",
    ],
    "health.nutrition": [
        "Same rules as health PLUS:",
        "Extreme dietary claim without peer-reviewed citation → niche_compliance = 0",
        "'Superfood' or 'miracle' language → niche_compliance ≤ 2",
    ],
    "mythology": [
        "Presenting unresolved historical theory as established fact → niche_compliance ≤ 2",
        "Fabricating quotes attributed to real historical figures → niche_compliance = 0",
    ],
    "psychology": [
        "Misattributing research to wrong author/institution → niche_compliance = 0",
        "Clinical diagnostic language used for general audiences without disclaimer → niche_compliance ≤ 2",
    ],
    "tech": [
        "Security advice that could expose user to greater risk → niche_compliance = 0",
        "Claiming a product is 'completely safe' / 'unhackable' → niche_compliance = 0",
    ],
}


def _get_fatal_rules(niche_key: str) -> list[str]:
    """Return fatal rules for niche, with sub-niche fallback to parent."""
    if niche_key in NICHE_FATAL_RULES:
        return NICHE_FATAL_RULES[niche_key]
    parent = niche_key.split(".")[0]
    return NICHE_FATAL_RULES.get(parent, [
        "No misleading claims. No fabricated data. No guaranteed outcomes.",
    ])


from omnicast.agents.rubrics import narrative_horror as _nh
from omnicast.agents.rubrics import finance_explainer as _fe


def _rubric_dims(is_narrative: bool, rubric_id: str = ""):
    """(VO_DIMS, PROD_DIMS, VO_PASS, PROD_PASS) for the genre. Narrative horror uses
    its own story-dimension set (continuity/voice/fear/variety/originality); a
    niche may also name an explicit rubric (NicheConfig.rubric_id) that swaps the
    explainer value system (e.g. YMYL accuracy-first finance). The subtotals still
    land in the 70/30 buckets so routing + approval are unchanged."""
    if is_narrative:
        return _nh.VO_DIMS, _nh.PROD_DIMS, _nh.VO_PASS, _nh.PROD_PASS
    if rubric_id == _fe.RUBRIC_ID:
        return _fe.VO_DIMS, _fe.PROD_DIMS, _fe.VO_PASS, _fe.PROD_PASS
    return VO_DIMS, PROD_DIMS, VO_PASS, PROD_PASS


def _canonical_spoken(draft: ScriptDraft) -> str:
    """The ONE true spoken narration of a draft — no double counting, nothing lost.

    Bug this fixes: the old code did `[draft.hook] + [every scene incl hook_scenes]
    + [draft.outro]`, which counted the hook AND its scene-copies (and the outro)
    twice, while dropping legacy segments that have `content` but no `scenes`.
    Rule: per section, use the SCENES' voiceover if present, else the joined text."""
    parts: list[str] = []
    if draft.hook_scenes:
        parts += [s.voiceover for s in draft.hook_scenes]
    elif draft.hook:
        parts.append(draft.hook)
    for seg in draft.segments:
        if seg.scenes:
            parts += [s.voiceover for s in seg.scenes]
        elif getattr(seg, "content", ""):
            parts.append(seg.content)
    if draft.outro_scenes:
        parts += [s.voiceover for s in draft.outro_scenes]
    elif draft.outro:
        parts.append(draft.outro)
    return " ".join(p for p in parts if p).strip()


def _narrative_slop_signals(text: str) -> tuple[list[str], dict[str, int]]:
    """Deterministic anti-slop scan for first-person horror. Returns (flag messages,
    caps) where caps maps a dimension name to a HARD maximum that CriticAgent.execute
    ENFORCES in Python — not a polite request the LLM may ignore."""
    import re
    low = text.lower()
    flags: list[str] = []
    caps: dict[str, int] = {}

    # caps target the NARRATIVE dimension set (see rubrics/narrative_horror.py):
    # slop motifs/phrases → originality; template repetition → structural_variety.
    # Self-reassurance pattern — count ALL variants (the writer evades a single-phrase
    # ban with "I wanted to believe / I figured it was / I convinced myself").
    itm = len(re.findall(r"\bi (told myself|wanted to believe|figured it was|"
                         r"convinced myself|kept telling myself)\b", low))
    if itm > 1:
        flags.append(f'self-reassurance pattern used {itm}x ("I told myself / wanted to '
                     f'believe / figured it was") — the #1 AI tell; max once/video')
        caps["originality"] = min(caps.get("originality", 99), 4)
    if re.search(r"\bsome (things|questions|answers|nights)\b[^.]{0,40}"
                 r"(you don'?t want|better left|stay a maybe|unanswered|on purpose)", low):
        flags.append('aphoristic/philosophical coda ("some things you don\'t want an '
                     'explanation for…") — banned; a real account ends blunt')
        caps["originality"] = min(caps.get("originality", 99), 5)
    if (re.search(r"\bone of us (called|ran|found|didn'?t)\b", low)
            or re.search(r"\bfound out later how\b[^.]{0,40}\blined up\b", low)):
        flags.append('intro wrapper speaks for / spoils the other narrators '
                     '("one of us called, one ran…") — each story must open in its own voice')
        caps["structural_variety"] = min(caps.get("structural_variety", 99), 7)
    proof = len(re.findall(r"\b(sheriff'?s? logs?|\bdmv\b|annual crime report|safety audit|"
                           r"tread width|ring camera|\d+\s*days? of footage|"
                           r"incident reports? (show|logged))\b", low))
    if proof >= 2:
        flags.append(f'proof-stacking ({proof}x official corroboration: logs/DMV/audits/'
                     f'camera timestamps) — reads as AI faking authenticity, not a real memory')
        caps["originality"] = min(caps.get("originality", 99), 5)
    if (re.search(r"\btall\b[^.]{0,45}\b(still|motionless|not moving)\b", low)
            or re.search(r"standing (perfectly|completely) still", low)
            or re.search(r"\b(perfectly|completely) (still|motionless)\b", low)):
        flags.append('"tall / standing perfectly still" figure — banned default motif (Law 5)')
        caps["originality"] = min(caps.get("originality", 99), 4)
    if re.search(r"\bthree (knocks|taps|raps|nights|times)\b", low):
        flags.append('rule-of-three (three knocks/nights…) — use uneven numbers')
        caps["originality"] = min(caps.get("originality", 99), 5)
    if (len(set(re.findall(r"\b(first|second|third|fourth) night\b", low))) >= 2
            or ("night one" in low and "night two" in low)):
        flags.append('day-by-day "first/second/third night" escalation — compress/vary')
        caps["structural_variety"] = min(caps.get("structural_variety", 99), 7)
    if re.search(r"\b(comment(s)? below|vote (on|which)|let me know in|which (room|road|story|case|one) "
                 r"(we|i|to) (open|do|tell|pick)|i read every)\b", low):
        flags.append('in-character CTA (comment/vote) — breaks first-person; BANNED in outro')
        caps["originality"] = min(caps.get("originality", 99), 3)
    still = len(re.findall(r"\bstill\b", low))
    if still >= 10:
        flags.append(f'filler "still" used {still}x — trim ~20%')
    sents = [s.strip().lower() for s in re.split(r"[.!?]\s+", text) if len(s.strip()) > 25]
    for a, b in zip(sents, sents[1:]):
        if a[:32] == b[:32]:
            flags.append('two adjacent sentences begin identically — duplication/padding')
            caps["originality"] = min(caps.get("originality", 99), 5)
            break
    return flags, caps


class CriticAgent(BaseAgent):
    """Two-stage adversarial critic.

    Scores scripts on 8 dimensions across two groups:
      VO group (70pts):         hook_quality, anti_ai_cliche, retention_structure,
                                human_editorial, niche_compliance, pacing_compliance
      Production group (30pts): visual_concreteness, sfx_appropriateness

    Routing signals returned in CriticFeedback:
      voiceover_score < VO_PASS (53)           → Writer.revise()
      voiceover_score >= VO_PASS, prod < 23    → VisualDirectorAgent
    """

    def __init__(self, llm: LLMClient) -> None:
        super().__init__(llm)

    @property
    def name(self) -> str:
        return "critic"

    @property
    def system_prompt(self) -> str:
        return self._build_system_prompt(niche_cfg=None)

    @staticmethod
    def _load_active_policy_rules() -> str:
        """Load human-approved policy rules from vault.db for injection into critic prompt."""
        try:
            from pathlib import Path as _Path
            from omnicast.vault import db as _vdb
            _VDB = _Path(__file__).resolve().parents[3] / "output" / "vault.db"
            _vdb.init_db(_VDB)
            rules = _vdb.get_active_rules(_VDB)
            if not rules:
                return ""
            rule_lines = "\n".join(f"  - {r.get('rule_text', str(r))}" for r in rules[:20])
            return (
                "\n\nACTIVE YOUTUBE POLICY RULES (human-approved — penalize violations in niche_compliance):\n"
                + rule_lines
            )
        except Exception:
            return ""

    def _build_system_prompt(self, niche_cfg: NicheConfig | None, channel_brand: dict | None = None) -> str:
        insider = niche_cfg.insider_angle if niche_cfg else "top YouTube creator"
        
        voice_persona = (channel_brand or {}).get("voice_persona", "")
        tone = (channel_brand or {}).get("tone", "")
        brand_voice = (channel_brand or {}).get("brand_voice", "")
        
        channel_rules = ""
        if brand_voice or tone or voice_persona:
            channel_rules = (
                "CRITICAL CHANNEL IDENTITY TO ENFORCE:\n"
                f"{f'- Persona: {voice_persona}' if voice_persona else ''}\n"
                f"{f'- Tone: {tone}' if tone else ''}\n"
                f"{f'- Brand Voice: {brand_voice}' if brand_voice else ''}\n"
                "If the script sounds generic and fails to embody this specific identity, penalize heavily in anti_ai_cliche and human_editorial. "
            )

        return (
            f"You are a ruthless YouTube script critic who has studied the top 1% of "
            f"{insider} channels. "
            f"{channel_rules}"
            "You score scripts across TWO independent groups: VO quality (70pts) and "
            "Production quality (30pts). "
            "Be harsh but precise. A script that retains 70%+ of viewers for 10 minutes "
            "scores 80+ total. Most scripts fail — be skeptical. "
            "Score based on YOUTUBE PERFORMANCE, not academic quality. "
            "ALWAYS respond with valid JSON only. No markdown, no text outside JSON."
            + self._load_active_policy_rules()
        )

    async def execute(
        self,
        draft: ScriptDraft,
        brief: TopicBrief,
        *,
        threshold: int = SPOKE_THRESHOLD,
        niche_cfg: NicheConfig | None = None,
        channel_brand: dict | None = None,
    ) -> CriticFeedback:
        """Review a script draft. Returns CriticFeedback with split VO/production scores."""
        if niche_cfg is None:
            niche_cfg = get_niche_config(brief.niche.value, brief.sub_niche)

        system = self._build_system_prompt(niche_cfg, channel_brand=channel_brand)
        prompt = self._build_review_prompt(draft, brief, niche_cfg)

        try:
            response, feedback = await self.call_llm_structured(
                [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                output_schema=CriticFeedback,
                # DeepSeek-v4-pro is a REASONING model: reasoning tokens count against
                # the output budget. With the fuller prompt (untruncated VO + genre
                # rubric) 8192 got entirely consumed by reasoning → zero JSON → empty
                # parse → crash. Give room for reasoning AND the JSON body.
                max_tokens=20000,
                temperature=0.3,
            )

            # Inject variant_id if LLM omitted
            if not feedback.variant_id:
                feedback = feedback.model_copy(update={"variant_id": draft.variant_id})

            # ── CANONICAL, CAPPED, CONSISTENT SCORING ──────────────────────────
            # Trust NOTHING the model reports about maxima or totals. Use the
            # genre's CANONICAL dimension maxima (ignore model-declared max_score),
            # drop unknown names, fill missing dims with 0, hard-clamp banned-motif
            # dims, and — for the variance re-score — average PER DIMENSION so the
            # final total ALWAYS equals sum(dimensions) and caps can't be bypassed.
            _is_narr = getattr(niche_cfg, "content_format", "explainer") == "narrative"
            _rid = getattr(niche_cfg, "rubric_id", "") or ""
            _VOD, _PRD, _VP, _PP = _rubric_dims(_is_narr, _rid)
            _MAXES = {**_VOD, **_PRD}                       # canonical name -> max
            if _is_narr:
                _caps = _narrative_slop_signals(_canonical_spoken(draft))[1]
            elif _rid == _fe.RUBRIC_ID:
                # YMYL hard caps (persona ban, guarantees, personalized advice)
                # are enforced HERE in Python, not requested from the LLM.
                _caps = _fe.finance_slop_signals(_canonical_spoken(draft))[1]
            else:
                _caps = {}

            def _normalize(dims) -> dict:
                got: dict[str, int] = {}
                for d in dims:
                    if d.name in _MAXES and d.name not in got:   # unknown/dup dropped
                        got[d.name] = max(0, min(int(d.score), _MAXES[d.name]))
                out: dict[str, int] = {}
                for name in _MAXES:                              # missing -> 0
                    v = got.get(name, 0)
                    if name in _caps:                            # deterministic cap
                        v = min(v, _caps[name])
                    out[name] = v
                return out

            scores = _normalize(feedback.dimensions)
            _pre_total = sum(scores.values())

            if 68 <= _pre_total <= 88:
                try:
                    _, fb2 = await self.call_llm_structured(
                        [{"role": "system", "content": system},
                         {"role": "user", "content": prompt}],
                        output_schema=CriticFeedback, max_tokens=20000, temperature=0.3)
                    s2 = _normalize(fb2.dimensions)
                    if sum(s2.values()):
                        logger.info("Critic double-score", first=_pre_total, second=sum(s2.values()))
                        scores = {n: round((scores[n] + s2[n]) / 2) for n in _MAXES}
                        for n in _caps:                          # caps survive averaging
                            scores[n] = min(scores[n], _caps[n])
                        feedback = feedback.model_copy(update={"continuity_issues": list(
                            dict.fromkeys(list(feedback.continuity_issues) + list(fb2.continuity_issues)))})
                except Exception as _dse:
                    logger.warning("Critic double-score skipped", error=str(_dse))

            # story_shapes repetition → cap structural_variety (repeated endings are
            # the sameness the variety dimension exists to punish).
            _shapes = [s.strip().lower() for s in getattr(feedback, "story_shapes", []) if s and s.strip()]
            if _is_narr and "structural_variety" in scores and len(_shapes) >= 2 \
                    and len(set(_shapes)) < len(_shapes):
                scores["structural_variety"] = min(scores["structural_variety"],
                                                   _MAXES["structural_variety"] // 2)

            # CONTINUITY HARD CAP — a logic hole cannot score >65. Reduce VO dims
            # (continuity first) so total ≤ 65 while total STILL equals sum(dims).
            if _is_narr and feedback.continuity_issues:
                _prod_now = sum(scores[n] for n in _PRD)
                _deficit = sum(scores[n] for n in _VOD) - max(0, 65 - _prod_now)
                for _n in (["continuity"] + [n for n in _VOD if n != "continuity"]):
                    if _deficit <= 0:
                        break
                    _cut = min(scores.get(_n, 0), _deficit)
                    scores[_n] -= _cut
                    _deficit -= _cut

            vo_score = sum(scores[n] for n in _VOD)
            prod_score = sum(scores[n] for n in _PRD)
            total = vo_score + prod_score

            # Rebuild dimensions from the FINAL scores → total == sum(dimensions),
            # canonical maxima (model-declared maxima discarded).
            _fb_text = {d.name: d.feedback for d in feedback.dimensions}
            feedback = feedback.model_copy(update={"dimensions": [
                CriticDimension(name=n, score=scores[n], max_score=_MAXES[n],
                                feedback=_fb_text.get(n, "")) for n in _MAXES]})

            # Hard gate: BOTH groups must pass independently (no "perfect VO + zero
            # visuals = approved" exploit).
            both_groups_pass = vo_score >= _VP and prod_score >= _PP

            # Hard gate 2 — LENGTH (deterministic; the LLM critic approved a
            # 692-word/4.6-min script at 84 despite the machine flag). A script
            # under ~90% of the word floor cannot run mid-roll ads → NEVER
            # approved, regardless of score. Routes back to Writer whose revise
            # path now re-expands to the floor.
            _words = len(_canonical_spoken(draft).split())
            _floor = spoken_word_floor(getattr(brief, "target_duration_min", None))
            length_ok = _words >= int(_floor * 0.9)

            # Hard gate 3 — FINANCE FATAL. A deterministic persona/guarantee/
            # advice hit is a policy violation, not a scoring matter: a capped
            # script can still total 84 and clear both group floors (measured),
            # so the flag itself must force rejection (codex audit finding 4).
            _fin_fatal = (not _is_narr and _rid == _fe.RUBRIC_ID
                          and bool(_caps) and _fe.fatal_caps(_caps))

            _updates = {
                "voiceover_score": vo_score,
                "production_score": prod_score,
                "total_score": total,
                "approved": (total >= threshold and both_groups_pass
                             and length_ok and not _fin_fatal),
            }
            _reasons = list(feedback.rejection_reasons)
            if _fin_fatal:
                _reasons.append(
                    "HARD GATE (finance YMYL, machine-verified): advisor-persona / "
                    "guarantee / personalized-advice language — never approved; "
                    "rewrite in educational register (sources speak, narrator explains)")
            if not length_ok:
                _reasons.append(
                    f"HARD GATE: only {_words} spoken words (needs {_floor}+ for "
                    f"{max(8, int(getattr(brief, 'target_duration_min', 0) or 0))} min / mid-roll ads) — "
                    "expand with more scenes, never approved under the floor")
            if _is_narr and feedback.continuity_issues:
                _reasons += [f"CONTINUITY (score capped ≤65): {c}"
                             for c in feedback.continuity_issues]
            if _reasons != list(feedback.rejection_reasons):
                _updates["rejection_reasons"] = _reasons
            feedback = feedback.model_copy(update=_updates)

            # Routing. Length and continuity are WRITER problems — an under-length
            # or logically-broken script must go back to the Writer to expand/fix,
            # NEVER to the VisualDirector (which only touches visuals).
            if feedback.approved:
                route = "approved"
            elif _fin_fatal or (not length_ok) or (_is_narr and feedback.continuity_issues):
                route = "writer"
            elif vo_score >= _VP and prod_score < _PP:
                route = "visual_director"
            else:
                route = "writer"

            logger.info(
                "Critic review completed",
                variant_id=draft.variant_id,
                vo_score=vo_score,
                prod_score=prod_score,
                total=total,
                script_only=round(vo_score * 100 / 70),   # STORY quality /100, prod excluded
                continuity_issues=len(feedback.continuity_issues),
                approved=feedback.approved,
                both_groups_pass=both_groups_pass,
                route=route,
            )
            return feedback

        except Exception as exc:
            raise AgentError(f"Critic review failed: {exc}") from exc

    async def compare_variants(
        self,
        variant_a: ScriptDraft,
        variant_b: ScriptDraft,
        brief: TopicBrief,
    ) -> str:
        """Pairwise comparison for Elo tournament. Returns winner variant_id."""
        def _scene_preview(draft: ScriptDraft) -> str:
            lines = [f"HOOK: {draft.hook[:120]}"]
            for seg in draft.segments[:2]:
                if seg.scenes:
                    lines.append(f"{seg.heading}: {seg.scenes[0].voiceover[:80]}...")
                else:
                    lines.append(f"{seg.heading}: {seg.content[:80]}...")
            return "\n".join(lines)

        prompt = (
            f"Compare these two script variants for: {brief.title}\n\n"
            f"Variant A:\n{_scene_preview(variant_a)}\n\n"
            f"Variant B:\n{_scene_preview(variant_b)}\n\n"
            "Which will have higher YouTube retention? Answer only \"A\" or \"B\"."
        )
        try:
            response = await self.call_llm([{"role": "user", "content": prompt}], temperature=0.2)
            winner = response.content.strip().upper()
            return winner if winner in ("A", "B") else "A"
        except Exception as exc:
            raise AgentError(f"Variant comparison failed: {exc}") from exc

    # ── Review prompt ─────────────────────────────────────────────────────────

    def _build_review_prompt(
        self,
        draft: ScriptDraft,
        brief: TopicBrief,
        niche_cfg: NicheConfig,
    ) -> str:
        niche_key = f"{brief.niche.value}.{brief.sub_niche}" if getattr(brief, "sub_niche", "") else brief.niche.value
        fatal_rules = _get_fatal_rules(niche_key)
        fatal_block = "\n".join(f"  - {r}" for r in fatal_rules)

        # ── Shooting script format ────────────────────────────────────────
        scene_lines: list[str] = []
        pacing_violations: list[str] = []
        scene_counter = 0

        # Hook scenes
        if draft.hook:
            hook_scenes = self._draft_hook_scenes(draft)
            for i, sc in enumerate(hook_scenes, 1):
                scene_counter += 1
                wc = len(sc["vo"].split())
                flag = " ⚠OVER25" if wc > 25 else ""
                scene_lines.append(
                    f"[HOOK-S{i}] ({wc}w){flag} | SFX: {sc['sfx']} | "
                    f"VISUAL: {sc['visual'][:50]} | VO: \"{sc['vo']}\""
                )
                if wc > 25:
                    pacing_violations.append(f"HOOK-S{i} ({wc}w)")

        # Segment scenes
        for seg in draft.segments:
            if seg.scenes:
                for i, sc in enumerate(seg.scenes, 1):
                    scene_counter += 1
                    wc = len(sc.voiceover.split())
                    flag = " ⚠OVER25" if wc > 25 else ""
                    sfx = sc.sfx or "null"
                    pr = getattr(sc, "pace", "normal")
                    pau = getattr(sc, "pause_after_ms", 0)
                    prosody = f"{pr}" + (f"+{pau}ms" if pau else "")
                    scene_lines.append(
                        f"[S{seg.index}-SC{i}] ({wc}w){flag} | PACE: {prosody} | SFX: {sfx} | "
                        f"VISUAL: {sc.visual_prompt[:50]} | VO: \"{sc.voiceover}\""
                    )
                    if wc > 25:
                        pacing_violations.append(f"S{seg.index}-SC{i} ({wc}w)")
            else:
                # Legacy: no scenes, show the FULL content block (never truncate VO)
                scene_lines.append(
                    f"[S{seg.index}] {seg.heading} | VO: \"{seg.content}\" | (no scene data)"
                )

        # Outro (full text — never truncate; continuity + the ending live here)
        if draft.outro:
            wc = len(draft.outro.split())
            scene_lines.append(f"[OUTRO] ({wc}w) | VO: \"{draft.outro}\"")

        shooting_script = "\n".join(scene_lines)
        pacing_warn = (
            f"\n⚠ PACING VIOLATIONS ({len(pacing_violations)} scenes exceed 25 words): "
            + ", ".join(pacing_violations)
            if pacing_violations else "\n✓ All scenes ≤ 25 words"
        )

        # ── Machine-computed prosody stats (vfact benchmark) ──────────────
        all_scenes = list(draft.hook_scenes or [])
        for _seg in draft.segments:
            all_scenes.extend(_seg.scenes or [])
        all_scenes.extend(draft.outro_scenes or [])
        n_sc = len(all_scenes) or 1
        n_slow = sum(1 for s in all_scenes if getattr(s, "pace", "normal") == "slow")
        n_fast = sum(1 for s in all_scenes if getattr(s, "pace", "normal") == "fast")
        n_pause = sum(1 for s in all_scenes if getattr(s, "pause_after_ms", 0) >= 400)
        n_emph = sum(1 for s in all_scenes if getattr(s, "emphasis", []))
        est_min = max(1.0, sum(len(s.voiceover.split()) for s in all_scenes) / 150.0)
        prosody_stats = (
            f"\n═══ PROSODY STATS (machine-computed vs vfact benchmark) ═══\n"
            f"scenes={n_sc} | slow={n_slow} ({n_slow*100//n_sc}%, target 15-25%) | "
            f"fast={n_fast} ({n_fast*100//n_sc}%, target 25-40%) | "
            f"pauses>=400ms={n_pause} (target 3-6 per 10min, est length {est_min:.1f}min) | "
            f"scenes-with-emphasis={n_emph}"
        )

        # ── Deterministic banned-phrase / length flags (LLM critics repeatedly
        # miss these — surface them as hard evidence with deduction orders) ────
        full_text = _canonical_spoken(draft).lower()
        total_words = len(full_text.split())
        _BANNED = [
            "keeps this channel going", "smash that", "don't forget to like",
            "in today's video", "let's dive in", "i publish every week",
            "i share every week",
        ]
        import re as _re
        _is_fin = (getattr(niche_cfg, "rubric_id", "") or "") == _fe.RUBRIC_ID
        flags: list[str] = []
        for phrase in _BANNED:
            if phrase in full_text:
                flags.append(f'banned phrase in VO: "{phrase}"')
        # Spoken attribution is a TRUST FEATURE in the senior-finance niche
        # (cohort evidence: winners cite FBI/IRS/Vanguard aloud) — the
        # read-citation-aloud tell only applies to the default explainer register.
        if not _is_fin and _re.search(r"\b(trial|study|journal|review|meta-analysis)\s+(found|showed|shows|confirmed)", full_text):
            flags.append("citation read ALOUD in VO (show-don't-read: source belongs in visual)")
        # Length flag scales with THIS brief's target (8-12+ min), never a hard
        # word count. 10% tolerance so a near-target script isn't nagged.
        _floor = spoken_word_floor(getattr(brief, "target_duration_min", None))
        if total_words < int(_floor * 0.9):
            _tgt = max(8, int(getattr(brief, "target_duration_min", 0) or 0))
            flags.append(f"script only {total_words} spoken words (~{total_words/150:.1f} min) — "
                         f"below the {_tgt}-minute target (needs ~{_floor}+; hard mid-roll floor is 8 min)")
        # ── Prosody INFLATION (run 2026-07-08 real data: 14-22 pauses >=400ms and
        # emphasis on 100% of scenes) — uniform "drama" is as flat as none.
        # vfact benchmark: 3-6 dramatic pauses per 10min; emphasis only on
        # stat/twist scenes. ─────────────────────────────────────────────────
        _pause_cap = max(6, int(est_min * 0.8))
        if n_pause > _pause_cap:
            flags.append(f"PAUSE INFLATION: {n_pause} pauses >=400ms in ~{est_min:.0f}min "
                         "(benchmark: 3-6 per 10min) — dramatic beats lose all impact; deduct pacing_compliance")
        if n_sc >= 10 and n_emph * 100 // n_sc > 60:
            flags.append(f"EMPHASIS INFLATION: {n_emph}/{n_sc} scenes carry emphasis "
                         "(should be <50%, stats/twist words only) — everything stressed = "
                         "nothing stressed; deduct pacing_compliance")
        # ── (a) HOOK PAYOFF (rule 12a): a specific $/%/comma-number promised in the
        # hook must reappear in the body — LLM critics repeatedly miss dropped hook
        # promises (baseline: "$450" in hook, never explained). ─────────────────
        def _figs(text: str) -> list[tuple[str, str]]:
            out: list[tuple[str, str]] = []
            for tok in _re.findall(
                # $450 | 44% | 1,500 — plus bare-number promises the old check
                # missed ("the 60-second fix", "7 foods", "3-bite rule"): a
                # hyphenated number-unit, or a count before a promise noun.
                r"\$\d[\d,]*(?:\.\d+)?"
                r"|\b\d[\d,]*(?:\.\d+)?\s*%"
                r"|\b\d{1,3}(?:,\d{3})+\b"
                r"|\b\d+(?:\.\d+)?-\w+"
                r"|\b\d+\s+(?:foods?|snacks?|bites?|steps?|rules?|ways?|things?|"
                r"mistakes?|reasons?|fixes|triggers?|habits?|signs?|"
                r"seconds?|minutes?|hours?|days?|weeks?)\b",
                text):
                core = _re.sub(r"\D", "", tok)
                if core:
                    out.append((tok.strip(), core))
            return out
        _body_txt = " ".join(
            s.voiceover for seg in draft.segments for s in (seg.scenes or [])
        ).lower() or " ".join(s.content for s in draft.segments).lower()
        # Body side is PERMISSIVE — any digit-run counts as resolving the hook
        # figure ("60-second fix" is resolved by "60 minutes" or "60 seconds"
        # written anywhere), so the strict hook patterns don't false-flag.
        # NARRATIVE channels (horror/story) tell numbered stories with organic
        # figures ("eleven years apart", "six years", "three of them") — the
        # explainer-only hook-payoff + listicle flags false-positive on them and
        # unfairly tank vo_score. Skip both for narrative content.
        _is_narrative = getattr(niche_cfg, "content_format", "explainer") == "narrative"
        _body_cores = {_re.sub(r"\D", "", t) for t in _re.findall(r"\d[\d,]*", _body_txt)}
        _seen_fig: set[str] = set()
        if not _is_narrative:
            for _disp, _core in _figs((draft.hook or "").lower()):
                if _core not in _body_cores and _core not in _seen_fig:
                    _seen_fig.add(_core)
                    flags.append(f'hook figure "{_disp}" is never resolved in the body '
                                 "(hook-payoff / rule 12a — reads as clickbait)")
        # ── (b) MECHANICAL LISTICLE (rule 10a): a counted spine instead of named
        # mechanisms ("snack one… number two… step 3"). ─────────────────────────
        if not _is_narrative:
            _list_hits = _re.findall(
                r"\b(?:number|step|snack|tip|reason|way|point|mistake|sign|rule|secret|"
                r"food|habit|type|phase|stage|method|trick|factor)\s+"
                r"(?:one|two|three|four|five|six|seven|eight|nine|ten|\d{1,2})\b",
                full_text)
            _ord_hits = set(_re.findall(r"\b(first|second|third|fourth|fifth)\b", full_text))
            if len(_list_hits) >= 3 or len(_ord_hits) >= 3:
                _ex = ", ".join((_list_hits or sorted(_ord_hits))[:4])
                flags.append(f"mechanical listicle spine detected ({_ex}…) — rule 10a: "
                             "group points by a named mechanism/theme, never count them off")
        # ── NARRATIVE ANTI-SLOP FLAGS (same scan is ENFORCED as hard caps in
        # execute() via _narrative_slop_signals — here they're shown to the LLM too) ─
        if _is_narrative:
            _nflags, _ = _narrative_slop_signals(full_text)
            flags.extend(_nflags)
        # ── FINANCE YMYL FLAGS (same scan is ENFORCED as hard caps in execute()
        # via finance_slop_signals — here they're shown to the LLM too) ─────────
        if _is_fin:
            _fflags, _ = _fe.finance_slop_signals(full_text)
            flags.extend(_fflags)

        if flags:
            prosody_stats += (
                "\n═══ MACHINE FLAGS (verified programmatically — you MUST deduct for these; "
                "they are NOT opinions) ═══\n"
                + "\n".join(f"  ⚠ {f}" for f in flags)
                + "\nDeduct: banned phrases → anti_ai_cliche ≤ 7; spoken citation → anti_ai_cliche ≤ 7; "
                  "under-length → retention_structure −3 and list it in specific_fixes; "
                  "unresolved hook figure → retention_structure −4 (clickbait, rule 12a); "
                  "mechanical listicle → anti_ai_cliche ≤ 7 (rule 10a)."
            )

        _narrative_note = ""
        if _is_narrative:
            _narrative_note = (
                "\n═══ CONTENT FORMAT: FIRST-PERSON NARRATIVE HORROR (score by THESE rules, "
                "NOT explainer rules) ═══\n"
                "An immersive first-person true-scary-story compilation (Mr. Nightmare / r/LetsNotMeet "
                "register), NOT a data explainer. Score accordingly:\n"
                "  • CONTINUITY GATE (check FIRST): build a mental table of the hook's promises, the "
                "timeline (dates/nights/seasons), places, jobs, and every named prop. For EACH "
                "contradiction (hook vs body, inconsistent timeline, a promised payoff that never "
                "lands, a prop introduced then abandoned, a distance/number that changes) add one "
                "entry to the structured field `continuity_issues`. IMPORTANT: whenever "
                "continuity_issues is non-empty the total is HARD-CAPPED at 65 automatically — a "
                "logic hole shatters the 'true story' illusion and is the most important failure to "
                "catch, so do not let polished prose hide one. Also fill `story_shapes` with the "
                "ending shape of each story (twist / ambiguous / slow-burn / false-ending / "
                "unreliable-narrator / not-about-you / recurrence) so repetition is visible.\n"
                "  • REWARD: cold-open no greeting; a real person's RAW, conversational voice (NOT "
                "polished literary prose — over-writing is a FLAW here); the THREE stories each having "
                "a DIFFERENT shape, threat type, pacing, and narrator voice; a threat that ACTS with "
                "real stakes; a protagonist who REACTS like a real person (calls 911, runs, locks up); "
                "fear shown through the BODY; endings that stop on the strongest image.\n"
                "  • PENALISE HARD (these are why AI horror fails — deduct heavily):\n"
                "     – SAMENESS: all stories share one skeleton (isolated night job → old prop → "
                "recurring phenomenon → self-reassurance → tall still figure → manager who won't "
                "explain → 'I still…' coda). If ≥2 stories follow it, retention_structure ≤ half.\n"
                "     – PASSIVE PROTAGONIST who just waits/hides till morning instead of acting.\n"
                "     – OVER-CONFIRMED PARANORMAL: every story ending with 'impossible proof' "
                "(teleported object, signature pre-dating hire, dead line ringing). A true-story set "
                "needs ≥1 fully human-caused and ≥1 plausibly-explainable story; if all are confirmed "
                "supernatural, it reads as fiction — human_editorial ≤ half.\n"
                "     – PURPLE PROSE: lyrical metaphors a panicking person would never say.\n"
                "     – any 'this account comes from / in her own words / according to', host framing, "
                "an in-character CTA (comment/vote), a described gore-monster, or a neat debunk.\n"
                "  • DO NOT PENALISE the absence of: statistics, citations, charts, SFX, a proof "
                "source, or a CTA — BANNED here. sfx_appropriateness: silence IS correct (full marks "
                "if minimal by design). human_editorial = STORYTELLING craft + dread + believability, "
                "not 'insider data'. niche_compliance = did it obey the 7 laws of dread.\n")

        # Explainer dimension rubric (default). Narrative horror swaps in its own
        # dimension set + JSON template so the two value systems never conflict.
        _explainer_block = f"""═══ SCORE ON 8 DIMENSIONS ═══

── VO GROUP (70pts total) ──────────────────────────────────────────────────

1. hook_quality (max {VO_DIMS['hook_quality']}pts) — CLICK-AND-STAY metric:
   {VO_DIMS['hook_quality']}/25: First VO has SPECIFIC number + immediate pain + curiosity gap. Cannot stop watching.
   {int(VO_DIMS['hook_quality']*0.6)}-{int(VO_DIMS['hook_quality']*0.8)}: Has a number but weak pain or curiosity gap.
   5-{int(VO_DIMS['hook_quality']*0.5)}: Story-first, generic, or "In today's video..." Viewer closes tab.
   0-4: No hook. Immediate skip.

2. anti_ai_cliche (max {VO_DIMS['anti_ai_cliche']}pts) — Authenticity filter:
   {VO_DIMS['anti_ai_cliche']}: Zero AI tells. Sounds like a real expert who learned the hard way.
   8-11: One or two clichés but mostly authentic.
   0-7: "delve", "tapestry", "it's important to note", "in conclusion", corporate speak, or any generated-sounding sentence.
   HARD CAP at 7 (structural AI-tells — these scream "generated", penalize hard):
   - Mechanical listicle: counting "Number one / number two / first / second …" as the spine. A premium
     script groups points by MECHANISM/theme (e.g. "The Fat Paralysis", "The Roughage Blockade"), never counts.
   - Reading citations aloud: "a 2023 study / journal / review found…" in the vo (source belongs on screen).
   - Boilerplate CTA: "keeps this channel going", "smash that like", generic "if this helped".

3. retention_structure (max {VO_DIMS['retention_structure']}pts) — Binge-watch engineering:
   {VO_DIMS['retention_structure']}: Open loops present as NATURAL SPEECH (not [OPEN LOOP:] tags), mid-video like CTA at segment 3, loops resolved in segment 5.
   5-7: Some retention mechanics but weak open loops or bad CTA placement.
   0-4: No open loops. Flat narration. Viewer drops at 2 minutes.
   HARD DEDUCTIONS (subtract from this dimension, these are clickbait/CTR killers):
   - HOOK PROMISE NOT PAID OFF: a specific number/claim in the hook ($ amount, "4 foods") that
     the body never explains → −4 (reads as clickbait, kills trust).
   - OPEN-LOOP CONTRADICTION: tease wording contradicts its reveal (teases "something you EAT"
     but the culprit is a drink) → −3.
   - DOUBLE VIDEO CTA: more than one "watch next"/"it's right here" suggestion, or a mid-video
     end-screen cue before the outro → −3.
   - LIKE CTA mid-explanation (not after a resolved payoff) → −2.

4. human_editorial (max {VO_DIMS['human_editorial']}pts) — Insider knowledge + storytelling test:
   {VO_DIMS['human_editorial']}: Insider insight (not Googleable in 5 min) PLUS ≥1 vivid filmable METAPHOR for an
     abstract mechanism (e.g. slowed stomach → "a clogged alley, food sitting like a flipped truck") AND concrete
     EMPATHY (names the real lived sensation: "fermenting", "stuck in your throat 6 hours later"), not safe textbook phrasing.
   5-7: Has insight but explains like a textbook — no metaphor, no felt sensation. Generic.
   0-4: Pure textbook content. No reason to watch this channel specifically.

5. niche_compliance (max {VO_DIMS['niche_compliance']}pts) — {niche_key.upper()} FATAL RULES:
   AUTOMATIC ZERO triggers for this niche:
{fatal_block}
   5: Fully compliant. No policy risk.
   2-4: Minor compliance concern.
   0: Fatal rule triggered — automatic 0.

6. pacing_compliance (max {VO_DIMS['pacing_compliance']}pts) — word count + PROSODY discipline
   (see PROSODY STATS above; flat delivery = robot voice = retention killer):
   5: All scenes ≤ 25 words AND prosody hits benchmark: slow 15-25%, fast 25-40%,
      3-6 deliberate pauses ≥400ms per 10min, key stats carry emphasis, pace CONTRASTS
      (hook+outro slow, build-ups fast, no 6+ same-pace runs).
   3-4: ≤2 word violations, prosody mostly present but off-target (e.g. too few fast
      scenes, only 1 pause, stats missing emphasis).
   1-2: 3-4 word violations OR prosody nearly flat (>80% scenes "normal", 0-1 pauses).
   0: 5+ word violations OR zero prosody markup (all normal, no pauses, no emphasis).
   (Current word violations: {len(pacing_violations)})

── PRODUCTION GROUP (30pts total) ─────────────────────────────────────────

7. visual_concreteness (max {PROD_DIMS['visual_concreteness']}pts) — AI video renderability:
   {PROD_DIMS['visual_concreteness']}: Every visual has SUBJECT + ACTION + CONTEXT. Filmable in 3-5s. e.g. "Close-up of 401k statement, red numbers highlighted, hand pointing to fee line"
   15-19: Most visuals specific but some are vague (e.g. "relevant footage", "person looking worried").
   8-14: Mix of specific and generic. AI video tools will produce inconsistent results.
   0-7: Majority of visuals are generic placeholders. AI render will be unusable.
   HARD FAIL indicators: "relevant footage", "appropriate visual", "person + context", "related imagery"

8. sfx_appropriateness (max {PROD_DIMS['sfx_appropriateness']}pts) — SFX matches niche + moment:
   5: SFX used on key numbers/reveals, matches niche (this niche primary: {niche_cfg.sfx_primary}, secondary: {niche_cfg.sfx_secondary}).
   3-4: SFX present but occasionally misplaced or wrong type for niche.
   0-2: No SFX, or SFX on wrong moments, or completely mismatched to niche.

═══ REQUIRED JSON OUTPUT ═══
{{
  "total_score": <sum of all 8 dimension scores>,
  "voiceover_score": <sum of dimensions 1-6>,
  "production_score": <sum of dimensions 7-8>,
  "approved": false,
  "dimensions": [
    {{"name": "hook_quality", "score": <0-{VO_DIMS['hook_quality']}>, "max_score": {VO_DIMS['hook_quality']}, "feedback": "<max 25 words>"}},
    {{"name": "anti_ai_cliche", "score": <0-{VO_DIMS['anti_ai_cliche']}>, "max_score": {VO_DIMS['anti_ai_cliche']}, "feedback": "<max 25 words>"}},
    {{"name": "retention_structure", "score": <0-{VO_DIMS['retention_structure']}>, "max_score": {VO_DIMS['retention_structure']}, "feedback": "<max 25 words>"}},
    {{"name": "human_editorial", "score": <0-{VO_DIMS['human_editorial']}>, "max_score": {VO_DIMS['human_editorial']}, "feedback": "<max 25 words>"}},
    {{"name": "niche_compliance", "score": <0-{VO_DIMS['niche_compliance']}>, "max_score": {VO_DIMS['niche_compliance']}, "feedback": "<max 25 words>"}},
    {{"name": "pacing_compliance", "score": <0-{VO_DIMS['pacing_compliance']}>, "max_score": {VO_DIMS['pacing_compliance']}, "feedback": "<max 25 words>"}},
    {{"name": "visual_concreteness", "score": <0-{PROD_DIMS['visual_concreteness']}>, "max_score": {PROD_DIMS['visual_concreteness']}, "feedback": "<max 25 words>"}},
    {{"name": "sfx_appropriateness", "score": <0-{PROD_DIMS['sfx_appropriateness']}>, "max_score": {PROD_DIMS['sfx_appropriateness']}, "feedback": "<max 25 words>"}}
  ],
  "rejection_reasons": ["<VO issues — sent to Writer>"],
  "specific_fixes": ["<specific VO fix 1>", "<specific VO fix 2>"],
  "visual_fixes": ["<specific visual fix 1: Scene X — replace 'Y' with 'Z'>"]
}}
"""
        if _is_narrative:
            _dim_and_json = _nh.dimension_rubric() + "\n\n" + _nh.json_template()
        elif _is_fin:
            _dim_and_json = _fe.dimension_rubric() + "\n\n" + _fe.json_template()
            _narrative_note = (
                "\n═══ CONTENT FORMAT: SENIOR-FINANCE YMYL EXPLAINER (accuracy-first rubric) ═══\n"
                "Educational retirement-finance for 60-75 US viewers. ACCURACY IS THE PRODUCT:\n"
                "  • Every dollar amount, percentage, threshold, age rule and deadline must be "
                "attributed to a named source WITH a year (SSA, IRS, CFPB, FBI IC3, published "
                "fund research). An uncited precise number is the worst failure in this format.\n"
                "  • Spoken attribution (\"according to SSA's 2026 fact sheet\") is REQUIRED "
                "trust-building, never an AI-tell.\n"
                "  • The narrator is an EDITOR who reads official sources — never an advisor. "
                "Any credential claim or 'my clients' framing is a fatal persona violation.\n"
                "  • Educational framing only: worked examples (\"for this example retiree…\"), "
                "never personal directives (\"you should claim at…\").\n"
                "  • Register: plain English at a normal adult pace (~180 wpm), short sentences, "
                "jargon defined on first use, zero condescension toward older viewers.\n")
        else:
            _dim_and_json = _explainer_block
        prompt = f"""Review this script for: {brief.title}
Niche: {niche_key} | Market: {brief.market.value}
Variant: {draft.variant_id}
{_narrative_note}
═══ SHOOTING SCRIPT (scene-level detail) ═══
{shooting_script}
{pacing_warn}
{prosody_stats}

{_dim_and_json}
"""
        return prompt

    def _draft_hook_scenes(self, draft: ScriptDraft) -> list[dict]:
        """Extract hook as pseudo-scenes for shooting script display."""
        if getattr(draft, "hook_scenes", None):
            return [
                {"vo": sc.voiceover, "visual": sc.visual_prompt, "sfx": sc.sfx or "null"}
                for sc in draft.hook_scenes
            ]
        # Hook stored as joined VO string — split by sentence for display
        import re
        sentences = re.split(r"(?<=[.!?])\s+", draft.hook.strip())
        return [
            {"vo": s, "visual": draft.hook_raw[:60] if draft.hook_raw else "", "sfx": "null"}
            for s in sentences if s
        ]
