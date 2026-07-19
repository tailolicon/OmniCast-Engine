"""Niche-specific content configuration for Writer and Critic agents."""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class NicheConfig:
    """Niche-specific content rules. Injected into Writer/Critic prompts."""

    # Hook
    hook_format: str  # "pain-first with specific dollar loss"
    hook_examples: list[str]  # 2-3 examples for few-shot

    # SFX mapping
    sfx_primary: str  # "cash-register" | "heartbeat" | "dramatic-sting"
    sfx_secondary: str  # "alarm" | "flatline" | "thunder"
    sfx_accent: str  # "whoosh"

    # Visual defaults
    broll_style: str  # "stock charts, offices" | "medical imagery"
    chart_palette: str  # "red-dominant" | "blue-medical" | "sepia"

    # Critic
    accuracy_weight: int  # 0-25, how much factual accuracy matters
    engagement_weight: int  # 0-25
    production_weight: int  # 0-25
    retention_weight: int  # 0-25

    # Writer
    insider_angle: str  # "financial insider" | "medical professional" | "historian"
    proof_sources: list[str]  # ["SPIVA data", "JP Morgan report"] | ["Lancet", "WHO"]

    # Content shape. "explainer" (default) = greeting + hook + proof-stat + data
    # scenes (finance/health/tech). "narrative" = first-person story channels
    # (horror/story) — the writer drops ALL explainer scaffolding (no greeting,
    # no 'according to', no stats/charts) and writes immersive prose instead.
    content_format: str = "explainer"


NICHE_CONFIGS: dict[str, NicheConfig] = {
    "finance": NicheConfig(
        hook_format="Open with EXACT dollar amount viewer is losing RIGHT NOW",
        hook_examples=[
            "A single 1% number hidden in your contract is stealing $500,000 from you.",
            "Your 401k is leaking $300,000 over 40 years and your advisor won't tell you.",
        ],
        sfx_primary="cash-register",
        sfx_secondary="alarm",
        sfx_accent="whoosh",
        broll_style="stock charts, financial offices, worried investors",
        chart_palette="red-dominant",
        accuracy_weight=20,
        engagement_weight=25,
        production_weight=25,
        retention_weight=25,
        insider_angle="financial insider who sees behind the curtain",
        proof_sources=["SPIVA data", "JP Morgan annual report", "Morningstar"],
    ),
    "finance.retirement": NicheConfig(
        hook_format="Open with retirement savings gap — specific age + dollar shortfall",
        hook_examples=[
            "At age 55, the average American has $172,000 saved. They need $1.2M. Here's the math.",
            "Social Security replaces 40% of your income. The other 60%? That's on you.",
        ],
        sfx_primary="cash-register",
        sfx_secondary="alarm",
        sfx_accent="clock-tick",
        broll_style="retirees, savings charts, social security office",
        chart_palette="red-dominant",
        accuracy_weight=25,  # retirement = higher accuracy bar
        engagement_weight=20,
        production_weight=25,
        retention_weight=25,
        insider_angle="retirement planning specialist",
        proof_sources=["Fidelity retirement report", "Social Security Administration data"],
    ),
    "finance.crypto": NicheConfig(
        hook_format="Open with dramatic price movement or regulatory shock",
        hook_examples=[
            "Bitcoin just hit $X — and 73% of holders are about to make the same mistake.",
            "The SEC just changed one rule that makes 90% of altcoins technically securities.",
        ],
        sfx_primary="digital-blip",
        sfx_secondary="alarm",
        sfx_accent="whoosh",
        broll_style="crypto charts, blockchain visualization, trading screens",
        chart_palette="green-dominant",
        accuracy_weight=15,
        engagement_weight=25,
        production_weight=25,
        retention_weight=25,
        insider_angle="on-chain analyst who reads the data most traders ignore",
        proof_sources=["Glassnode on-chain data", "CoinGecko", "SEC filings"],
    ),
    "health": NicheConfig(
        hook_format="Open with alarming health statistic affecting viewer personally",
        hook_examples=[
            "72% of Americans over 40 have this vitamin deficiency — and your doctor isn't testing for it.",
            "This one food you eat daily is linked to 3x higher inflammation. Here's the study.",
        ],
        sfx_primary="heartbeat",
        sfx_secondary="flatline",
        sfx_accent="whoosh",
        broll_style="medical imagery, healthy lifestyle, lab results",
        chart_palette="blue-medical",
        accuracy_weight=25,  # health = highest accuracy bar
        engagement_weight=20,
        production_weight=25,
        retention_weight=25,
        insider_angle="evidence-based health researcher",
        proof_sources=["PubMed studies", "Lancet", "WHO data", "Mayo Clinic"],
    ),
    "health.nutrition": NicheConfig(
        hook_format="Open with counterintuitive food/diet fact backed by recent study",
        hook_examples=[
            "The 'healthy' breakfast 68% of Americans eat is spiking their blood sugar to diabetic levels.",
            "Researchers just found the #1 anti-aging nutrient. It's not what influencers are selling.",
        ],
        sfx_primary="heartbeat",
        sfx_secondary="alarm",
        sfx_accent="whoosh",
        broll_style="food preparation, nutrition labels, grocery aisles",
        chart_palette="green-organic",
        accuracy_weight=25,
        engagement_weight=20,
        production_weight=25,
        retention_weight=25,
        insider_angle="nutrition researcher who reads the actual studies",
        proof_sources=["Harvard Nutrition Source", "NIH", "systematic reviews"],
    ),
    "mythology": NicheConfig(
        hook_format="Open with mind-blowing historical fact or unanswered mystery",
        hook_examples=[
            "The Greek gods had a weapon that matches nuclear physics — 3,000 years before the atom bomb.",
            "Every ancient civilization independently described the same flood. Coincidence dies at 7 civilizations.",
        ],
        sfx_primary="dramatic-sting",
        sfx_secondary="thunder",
        sfx_accent="whoosh",
        broll_style="ancient ruins, historical paintings, artifact close-ups, maps",
        chart_palette="sepia-gold",
        accuracy_weight=15,
        engagement_weight=25,
        production_weight=25,
        retention_weight=25,
        insider_angle="historian who connects ancient texts to modern discoveries",
        proof_sources=["archaeological records", "primary texts", "peer-reviewed papers"],
    ),
    "psychology": NicheConfig(
        hook_format="Open with unsettling psychological fact about viewer's own behavior",
        hook_examples=[
            "You make 35,000 decisions daily — and a cognitive bias you've never heard of corrupts 40% of them.",
            "The personality trait that predicts divorce with 94% accuracy. Most couples never test for it.",
        ],
        sfx_primary="brain-zap",
        sfx_secondary="alarm",
        sfx_accent="whoosh",
        broll_style="brain scans, social experiments, facial expressions",
        chart_palette="purple-mind",
        accuracy_weight=20,
        engagement_weight=25,
        production_weight=25,
        retention_weight=25,
        insider_angle="behavioral scientist who studies what people do vs what they say",
        proof_sources=["APA journals", "Kahneman & Tversky", "Nature Human Behaviour"],
    ),
    "psychology.horror": NicheConfig(
        hook_format=(
            "FIRST-PERSON cold-open, one or two lines from inside the scariest "
            "moment of story #1, then pull back to start at the beginning. "
            "('I want to say up front: I never believed in this stuff. I still "
            "don't know what I saw on that road.') No greeting, no channel talk, "
            "no case-file framing, no statistics."),
        hook_examples=[
            "I've driven Route 9 every night for six years. I only stopped after what I saw in my headlights last October.",
            "The knocking started at 3 AM. I live alone, on the fourth floor. The knocking came from my bedroom window.",
        ],
        sfx_primary="none",
        sfx_secondary="none",
        sfx_accent="none",
        broll_style=(
            "dark REAL footage only: night roads in headlights, empty hospital "
            "corridors, CCTV stills, rain on windows, flickering streetlights, "
            "liminal parking garages — never AI art, never brain scans"),
        chart_palette="cold-desaturated",
        accuracy_weight=10,
        engagement_weight=25,
        production_weight=25,
        retention_weight=30,
        insider_angle=(
            "a first-person horror storyteller (Mr. Nightmare style). The narrator "
            "IS the person each thing happened to and tells it as 'I/we' in a plain, "
            "shaken, everyday voice — NOT a host reading someone else's submission. "
            "NEVER say 'this account comes from', 'in her own words', 'word for "
            "word what she sent', 'according to', 'the storyteller said', or frame "
            "it as a file/report/case — that meta-framing instantly kills the fear. "
            "Just BE inside the story. RULES THAT MAKE IT SCARY: (1) mundane, deeply "
            "relatable setup first (a job, a routine, a specific ordinary place) so "
            "the listener puts themselves there; (2) ONE thing is slightly wrong, "
            "then escalates in small concrete sensory steps (a sound, a distance, a "
            "light, a smell) — never explained; (3) the narrator's own dawning fear "
            "is shown physically (hands, breath, freezing in place), never the word "
            "'scared'; (4) end shortly after the worst moment on one quiet line, "
            "and VARY the ending across the stories (twist / ambiguous / slow-burn / "
            "false-ending / recurrence) — no 'experts say', no debunk, no CTA; (5) the "
            "THREAT VARIES and ACTS — at least one story is a real HUMAN danger "
            "(intruder/stalker) who does something physical (forces a door, chases, "
            "screams), and any uncanny figure must MOVE or act, NEVER default to 'a "
            "tall figure standing still'; never a fanged/clawed monster; (6) the "
            "narrator REACTS like a real person (calls 911, grabs a weapon, runs, "
            "locks up) — never just sits and waits for morning."),
        proof_sources=[],
        content_format="narrative",
    ),
    "tech": NicheConfig(
        hook_format="Open with specific tech impact on viewer's daily life or money",
        hook_examples=[
            "Your phone is running 47 background processes right now — 12 of them are selling your data.",
            "This $0 setting change makes your laptop 40% faster. Apple/Microsoft won't tell you about it.",
        ],
        sfx_primary="digital-blip",
        sfx_secondary="glitch",
        sfx_accent="whoosh",
        broll_style="devices, code screens, data centers, UI recordings",
        chart_palette="neon-dark",
        accuracy_weight=20,
        engagement_weight=25,
        production_weight=25,
        retention_weight=25,
        insider_angle="engineer who builds the systems most people just use",
        proof_sources=["official docs", "CVE databases", "benchmark data"],
    ),
}


def get_niche_config(niche: str, sub_niche: str = "") -> NicheConfig:
    """Lookup niche config. Falls back: niche.sub_niche → niche → finance."""
    if sub_niche:
        key = f"{niche}.{sub_niche}"
        if key in NICHE_CONFIGS:
            return NICHE_CONFIGS[key]
    if niche in NICHE_CONFIGS:
        return NICHE_CONFIGS[niche]
    return NICHE_CONFIGS["finance"]  # ultimate fallback
