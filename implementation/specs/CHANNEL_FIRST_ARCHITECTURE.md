# SPEC: Channel-First Architecture

> **Status:** Draft
> **Scope:** Discovery → Script → Media → Upload pipeline refactor
> **Breaking:** Yes — `DiscoveryConfig`, `BrandConfig`, `TopicBrief`, Writer/Critic prompts, `run_pipeline.py`

---

## Problem

Current system hardcodes finance-specific behavior everywhere:
- `WRITER_SYSTEM` prompt: "$X,XXX pain loss", "cash-register SFX", "Graham Stephan"
- `CriticAgent`: scores on finance engagement heuristics
- `DiscoveryConfig`: built inline per run, no channel binding
- `BrandConfig`: visual style only (voice, colors, transitions) — no niche/content config
- `run_pipeline.py`: manually constructs everything, no channel identity

Result: changing niche (health, history, crypto) requires rewriting prompts + config in 5+ files.

## Architecture

### Core Principle

**Channel = Brand = Style = Niche Config**

```
Channel (persistent entity in DB)
├── identity: name, niche, sub_niche, market, language
├── brand: visual_style, voice, colors, fonts, transitions
├── content: hook_formula, sfx_map, broll_style, ref_channels
├── discovery: keywords, feeds, subreddits, competitor_channels
└── schedule: upload_cadence, prime_time_slots
```

One channel → one consistent viewer experience.
Topic varies → content adapts (hook metric, key points). Style stays.

### Data Flow

```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│  Channels   │────→│  Discovery   │────→│  TopicBrief  │
│  (DB/JSON)  │     │  (per channel)│     │  (+channel)  │
└─────────────┘     └──────────────┘     └──────┬───────┘
                                                │
                    ┌──────────────┐     ┌──────▼───────┐
                    │  NicheConfig │────→│   Writer     │
                    │  (injected)  │     │  (niche-aware)│
                    └──────────────┘     └──────┬───────┘
                                                │
                    ┌──────────────┐     ┌──────▼───────┐
                    │  StyleConfig │────→│   Media      │
                    │  (from brand)│     │  (style-aware)│
                    └──────────────┘     └──────┬───────┘
                                                │
                                         ┌──────▼───────┐
                                         │   Upload     │
                                         │  (channel)   │
                                         └──────────────┘
```

---

## Changes

### 1. New: `ChannelProfile` (replaces ad-hoc config construction)

**File:** `src/omnicast/config/channel.py` (new)

```python
class ChannelProfile(OmnicastSchema):
    """Complete channel configuration. Single source of truth."""

    # Identity
    channel_id: str                     # "fin_retirement_us", "health_nutrition_us"
    name: str                           # "Smart Retirement"
    niche: Niche                        # FINANCE
    sub_niche: str = ""                 # "retirement", "crypto", "stocks"
    market: Market = Market.US
    language: str = "en"
    channel_type: ChannelType = ChannelType.HUB

    # Brand / Visual Style (moved from BrandConfig)
    visual_style: str = "dark_cinematic"  # key into STYLE_PRESETS
    voice_profile: str = "kokoro_en_us_v1"
    voice_clone: str | None = None
    color_palette: list[str] = ["#1A1A2E", "#E94560", "#FFFFFF"]
    font: str = "Montserrat Bold"
    transition_style: str = "zoom_in_0.3s"
    intro_template: str | None = None
    outro_template: str | None = None
    music_bpm_range: tuple[int, int] = (120, 140)
    thumbnail_style: str = "dark_contrast"
    image_gen_mode: str = "sdxl"
    use_video_gen: bool = False
    target_duration_min: int = 10

    # Content Style (NEW — drives Writer + Critic)
    niche_config_key: str = ""          # override key into NICHE_CONFIGS; defaults to niche.value
    brand_voice: str = ""               # "authoritative", "conversational", "provocative"
    tone: str = "direct"                # "direct", "empathetic", "dramatic"
    ref_channels: list[str] = []        # ["Graham Stephan", "Andrei Jikh"] for finance
    forbidden_words: list[str] = []     # per-channel banned words

    # Discovery Config (NEW — previously built inline)
    competitor_channel_ids: list[str] = []
    subreddits: list[str] = []
    rss_feeds: list[str] = []
    podcast_keywords: list[str] = []
    trends_keywords: list[str] = []
    rpm_floor: float = 7.0

    # Schedule
    upload_cadence: str = "3x_weekly"   # "daily", "3x_weekly", "weekly"
    prime_time_hours: list[int] = [9, 12, 17]  # UTC hours
```

**Migration:** `BrandConfig` fields merge into `ChannelProfile`. `BrandConfig` becomes a thin view for Media pipeline backward compat:

```python
class ChannelProfile:
    def to_brand_config(self) -> BrandConfig:
        """Extract media-pipeline-compatible BrandConfig."""
        return BrandConfig(
            channel_id=self.channel_id,
            voice_profile=self.voice_profile,
            # ...all current BrandConfig fields...
        )

    def to_discovery_config(self) -> DiscoveryConfig:
        """Extract discovery-compatible config."""
        return DiscoveryConfig(
            niche=self.niche,
            markets=[self.market],
            competitor_channel_ids=self.competitor_channel_ids,
            subreddits=self.subreddits,
            rss_feeds=self.rss_feeds,
            podcast_keywords=self.podcast_keywords,
            trends_keywords=self.trends_keywords,
            rpm_floor=self.rpm_floor,
        )
```

### 2. New: `NicheConfig` (drives Writer + Critic content style)

**File:** `src/omnicast/config/niches.py` (new)

```python
@dataclass(frozen=True)
class NicheConfig:
    """Niche-specific content rules. Injected into Writer/Critic prompts."""

    # Hook
    hook_format: str          # "pain-first with specific dollar loss"
    hook_examples: list[str]  # 2-3 examples for few-shot

    # SFX mapping
    sfx_primary: str          # "cash-register" | "heartbeat" | "dramatic-sting"
    sfx_secondary: str        # "alarm" | "flatline" | "thunder"
    sfx_accent: str           # "whoosh"

    # Visual defaults
    broll_style: str          # "stock charts, offices" | "medical imagery"
    chart_palette: str        # "red-dominant" | "blue-medical" | "sepia"

    # Critic
    accuracy_weight: int      # 0-25, how much factual accuracy matters
    engagement_weight: int    # 0-25
    production_weight: int    # 0-25
    retention_weight: int     # 0-25

    # Writer
    insider_angle: str        # "financial insider" | "medical professional" | "historian"
    proof_sources: list[str]  # ["SPIVA data", "JP Morgan report"] | ["Lancet", "WHO"]

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
```

### 3. New: `StylePreset` (drives Media pipeline visual decisions)

**File:** `src/omnicast/config/styles.py` (new)

```python
@dataclass(frozen=True)
class StylePreset:
    """Visual editing style. Applied per-channel, consistent across all videos."""
    visual_density: int = 8       # cues per segment target
    zoom_style: str = "ken-burns slow"
    transition_primary: str = "glitch"
    transition_secondary: str = "whip-pan"
    text_animation: str = "zoom-slam"
    music_tempo: str = "slow-build"
    color_grade: str = "dark-cinematic"
    caption_style: str = "bold-word-highlight"

STYLE_PRESETS: dict[str, StylePreset] = {
    "dark_cinematic": StylePreset(
        visual_density=8,
        zoom_style="ken-burns slow",
        transition_primary="glitch",
        transition_secondary="whip-pan",
        text_animation="zoom-slam",
        music_tempo="slow-build",
        color_grade="dark-cinematic",
    ),
    "clean_educational": StylePreset(
        visual_density=6,
        zoom_style="static + slow-zoom",
        transition_primary="fade",
        transition_secondary="cut",
        text_animation="typewriter",
        music_tempo="neutral-upbeat",
        color_grade="bright-clean",
    ),
    "high_energy": StylePreset(
        visual_density=10,
        zoom_style="slam + whip-pan",
        transition_primary="whip-pan",
        transition_secondary="glitch",
        text_animation="bounce",
        music_tempo="high-bpm",
        color_grade="neon-dark",
    ),
    "documentary": StylePreset(
        visual_density=5,
        zoom_style="ken-burns slow",
        transition_primary="fade",
        transition_secondary="dissolve",
        text_animation="fade",
        music_tempo="ambient",
        color_grade="sepia-warm",
    ),
}
```

### 4. Modify: `DiscoveryOrchestrator` — channel-aware

**Current:** `DiscoveryOrchestrator(scanners, scorer)` — caller builds scanners manually.
**New:** `DiscoveryOrchestrator.for_channel(channel: ChannelProfile)` — auto-constructs scanners from channel config.

```python
class DiscoveryOrchestrator:
    @classmethod
    def for_channel(cls, channel: ChannelProfile) -> DiscoveryOrchestrator:
        """Build orchestrator from channel profile."""
        config = channel.to_discovery_config()
        scanners = []
        if config.rss_feeds:
            scanners.append(NewsScanner(config=config))
        if config.trends_keywords:
            scanners.append(TrendsScanner(config=config))
        if config.competitor_channel_ids:
            scanners.append(YouTubeScanner(config=config))
        if config.subreddits:
            scanners.append(RedditScanner(config=config))
        scorer = TopicScorer()
        return cls(scanners=scanners, scorer=scorer, brand_voice=channel.brand_voice)
```

### 5. Modify: `BriefGenerator` — inject channel context

**Current:** `BriefGenerator.generate(scored, brand_voice)` — generic angle.
**New:** `BriefGenerator.generate(scored, channel: ChannelProfile)` — niche-aware angle + sub_niche.

```python
class BriefGenerator:
    @staticmethod
    def generate(scored: ScoredTopic, channel: ChannelProfile) -> TopicBrief:
        niche_cfg = get_niche_config(channel.niche.value, channel.sub_niche)
        angle = BriefGenerator._determine_angle(scored, niche_cfg)

        return TopicBrief(
            title=scored.raw.title,
            niche=channel.niche,
            market=channel.market,
            source=scored.raw.source,
            angle=angle,
            key_points=BriefGenerator._extract_key_points(scored),
            source_urls=[scored.raw.source_url] if scored.raw.source_url else [],
            target_duration_min=channel.target_duration_min,
            brand_voice=channel.brand_voice,
            channel_id=channel.channel_id,       # NEW
            sub_niche=channel.sub_niche,          # NEW
        )
```

### 6. Modify: `TopicBrief` — add channel binding

```python
class TopicBrief(OmnicastSchema):
    title: str
    niche: Niche
    market: Market
    source: TopicSource
    angle: str = ""
    key_points: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    target_duration_min: int = 10
    brand_voice: str = ""
    lessons: list[str] = Field(default_factory=list)
    channel_id: str = ""          # NEW — links to ChannelProfile
    sub_niche: str = ""           # NEW — "retirement", "crypto", etc.
```

### 7. Modify: `WriterAgent` — niche-aware prompt generation

**Current:** `WRITER_SYSTEM` hardcodes finance language.
**New:** `_build_system_prompt(niche_cfg: NicheConfig)` generates niche-specific system prompt.

```python
class WriterAgent(BaseAgent):
    def _build_system_prompt(self, niche_cfg: NicheConfig) -> str:
        return f"""You are a professional YouTube scriptwriter specializing in {niche_cfg.insider_angle}.

YOUR SCRIPTS MUST FOLLOW THESE RULES:

1. HOOK — H.I.P Formula (first 30 seconds):
   H (Hook): {niche_cfg.hook_format}
     Examples:
     {chr(10).join(f"  - {ex}" for ex in niche_cfg.hook_examples)}
   I (Intro): One sentence — what this video solves.
   P (Proof): One data point from: {", ".join(niche_cfg.proof_sources)}

... [rest of WRITER_SYSTEM with niche_cfg.sfx_primary / sfx_secondary injected]

9. SFX RULES:
   - Key numbers/statistics: [{niche_cfg.sfx_primary}]
   - Warnings/dangers: [{niche_cfg.sfx_secondary}]
   - Transitions: [{niche_cfg.sfx_accent}]
"""

    async def execute(
        self,
        brief: TopicBrief,
        num_variants: int = 3,
        niche_cfg: NicheConfig | None = None,  # NEW
        style: StylePreset | None = None,       # NEW
    ) -> list[ScriptDraft]:
        cfg = niche_cfg or get_niche_config(brief.niche.value, brief.sub_niche)
        system = self._build_system_prompt(cfg)
        # ... use system instead of WRITER_SYSTEM constant
```

### 8. Modify: `CriticAgent` — niche-aware scoring weights

```python
class CriticAgent(BaseAgent):
    async def execute(
        self,
        draft: ScriptDraft,
        brief: TopicBrief,
        niche_cfg: NicheConfig | None = None,  # NEW
    ) -> CriticFeedback:
        cfg = niche_cfg or get_niche_config(brief.niche.value, brief.sub_niche)
        system = self._build_critic_prompt(cfg)
        # weights from cfg: accuracy_weight, engagement_weight, etc.
```

### 9. Modify: `DebateOrchestrator.run()` — pass niche + style through

```python
class DebateOrchestrator:
    async def run(
        self,
        brief: TopicBrief,
        num_variants: int = 2,
        channel: ChannelProfile | None = None,  # NEW
    ) -> list[DebateResult]:
        niche_cfg = None
        style = None
        if channel:
            niche_cfg = get_niche_config(channel.niche.value, channel.sub_niche)
            style = STYLE_PRESETS.get(channel.visual_style)
        # pass niche_cfg + style to writer.execute() and critic.execute()
```

### 10. Modify: `run_pipeline.py` — channel-driven

```python
async def run_pipeline(channel_id: str | None = None, topic: str | None = None):
    # Load channel profile
    if channel_id:
        channel = load_channel_profile(channel_id)
    else:
        channel = DEFAULT_CHANNEL  # fin_general_us fallback

    # Phase 1: Discovery (auto-configured from channel)
    discovery = DiscoveryOrchestrator.for_channel(channel)
    result = await discovery.run()

    # Phase 2: Script (niche-aware)
    niche_cfg = get_niche_config(channel.niche.value, channel.sub_niche)
    style = STYLE_PRESETS.get(channel.visual_style)
    writer = WriterAgent(llm=llm_pro)
    # ... orchestrator.run(brief, channel=channel)

    # Phase 4: Media (style-driven)
    brand = channel.to_brand_config()
    media = MediaPipelineOrchestrator()
    await media.run(..., brand=brand)

    # Phase 5: Upload (channel-bound)
    await upload_orch.run(..., channel_id=channel.channel_id)
```

### 11. New: `ChannelProfileLoader` — JSON file storage

**File:** `src/omnicast/config/channel.py`

```python
class ChannelProfileLoader:
    """Load ChannelProfile from JSON files on disk.

    Directory structure:
        channels/
        ├── fin_retirement_us.json
        ├── fin_crypto_us.json
        ├── health_nutrition_us.json
        └── myth_greek_us.json
    """
    def __init__(self, config_dir: str | Path):
        self.config_dir = Path(config_dir)
        self._cache: dict[str, ChannelProfile] = {}

    async def load(self, channel_id: str) -> ChannelProfile: ...
    async def load_all(self) -> dict[str, ChannelProfile]: ...
    async def save(self, profile: ChannelProfile) -> None: ...
```

### 12. Modify: `ChannelORM` — add sub_niche column

```sql
ALTER TABLE channels ADD COLUMN sub_niche VARCHAR(30) DEFAULT '';
```

ORM update:
```python
class ChannelORM(Base):
    # ... existing fields ...
    sub_niche: Mapped[str] = mapped_column(String(30), default="")
```

---

## Channel Examples

### Finance Hub — Retirement

```json
{
  "channel_id": "fin_retirement_us",
  "name": "Smart Retirement",
  "niche": "finance",
  "sub_niche": "retirement",
  "market": "US",
  "visual_style": "clean_educational",
  "voice_profile": "kokoro_en_us_calm",
  "brand_voice": "authoritative but empathetic — viewers are anxious about retirement",
  "tone": "empathetic",
  "ref_channels": ["Two Cents", "The Money Guy Show"],
  "trends_keywords": ["retirement", "401k", "social security", "pension", "IRA"],
  "rss_feeds": ["https://feeds.finance.yahoo.com/rss/2.0/headline"],
  "subreddits": ["personalfinance", "retirement", "financialindependence"],
  "rpm_floor": 12.0,
  "target_duration_min": 12
}
```

### Finance Hub — Crypto

```json
{
  "channel_id": "fin_crypto_us",
  "name": "Chain Signal",
  "niche": "finance",
  "sub_niche": "crypto",
  "market": "US",
  "visual_style": "high_energy",
  "voice_profile": "kokoro_en_us_v1",
  "brand_voice": "provocative data-driven — cut through hype with on-chain proof",
  "tone": "direct",
  "ref_channels": ["Coin Bureau", "Benjamin Cowen"],
  "trends_keywords": ["bitcoin", "ethereum", "crypto", "defi", "SEC crypto"],
  "subreddits": ["cryptocurrency", "bitcoin", "ethereum"],
  "rpm_floor": 8.0,
  "target_duration_min": 10
}
```

### Health — Nutrition

```json
{
  "channel_id": "health_nutrition_us",
  "name": "Evidence Kitchen",
  "niche": "health",
  "sub_niche": "nutrition",
  "market": "US",
  "visual_style": "clean_educational",
  "voice_profile": "kokoro_en_us_calm",
  "brand_voice": "evidence-based, never fear-mongering — cite studies, not influencers",
  "tone": "empathetic",
  "ref_channels": ["Dr. Eric Berg", "Nutrition Made Simple"],
  "trends_keywords": ["nutrition", "diet", "vitamin", "gut health", "anti-inflammatory"],
  "rss_feeds": ["https://www.medicalnewstoday.com/rss"],
  "rpm_floor": 6.0,
  "target_duration_min": 10
}
```

### Mythology

```json
{
  "channel_id": "myth_greek_us",
  "name": "Myth Decoded",
  "niche": "mythology",
  "sub_niche": "",
  "market": "US",
  "visual_style": "documentary",
  "voice_profile": "kokoro_en_us_deep",
  "brand_voice": "scholarly narrator — connect ancient to modern, avoid sensationalism",
  "tone": "dramatic",
  "ref_channels": ["Overly Sarcastic Productions", "Historia Civilis"],
  "trends_keywords": ["mythology", "ancient history", "greek gods", "norse mythology"],
  "rpm_floor": 5.0,
  "target_duration_min": 15
}
```

---

## Migration Path

### Phase A: Config layer (no runtime changes)
1. Create `src/omnicast/config/niches.py` with `NICHE_CONFIGS`
2. Create `src/omnicast/config/styles.py` with `STYLE_PRESETS`
3. Create `src/omnicast/config/channel.py` with `ChannelProfile` + `ChannelProfileLoader`
4. Create sample channel JSON files in `channels/` directory
5. Add `sub_niche` to `ChannelORM`, `ChannelCreate`, `ChannelRead`

### Phase B: Writer + Critic (niche-aware prompts)
6. `WriterAgent`: extract `WRITER_SYSTEM` → `_build_system_prompt(niche_cfg)`
7. `CriticAgent`: parameterize scoring weights from `niche_cfg`
8. `DebateOrchestrator.run()`: accept `channel: ChannelProfile`
9. `TopicBrief`: add `channel_id`, `sub_niche` fields
10. Tests: verify same finance score with explicit `NicheConfig("finance")`

### Phase C: Discovery (channel-driven)
11. `DiscoveryOrchestrator.for_channel()` factory method
12. `BriefGenerator.generate()`: accept `ChannelProfile`
13. `run_pipeline.py`: refactor to channel-driven flow

### Phase D: Media + Upload (style-driven)
14. `MediaPipelineOrchestrator`: accept `StylePreset` for visual density / transitions
15. `UploadPipelineOrchestrator`: metadata from channel profile
16. `run_pipeline.py`: full channel-driven end-to-end

---

## Files Changed

| File | Action | Phase |
|------|--------|-------|
| `src/omnicast/config/niches.py` | NEW | A |
| `src/omnicast/config/styles.py` | NEW | A |
| `src/omnicast/config/channel.py` | NEW | A |
| `channels/*.json` | NEW (4 examples) | A |
| `src/omnicast/models/orm.py` | ADD sub_niche | A |
| `src/omnicast/models/schemas.py` | ADD sub_niche to ChannelCreate/Read | A |
| `src/omnicast/models/script.py` | ADD channel_id, sub_niche to TopicBrief | B |
| `src/omnicast/agents/writer.py` | MODIFY system prompt gen | B |
| `src/omnicast/agents/critic.py` | MODIFY scoring weights | B |
| `src/omnicast/agents/orchestrator.py` | MODIFY run() signature | B |
| `src/omnicast/discovery/orchestrator.py` | ADD for_channel() | C |
| `src/omnicast/discovery/brief_generator.py` | MODIFY generate() | C |
| `run_pipeline.py` | REWRITE channel-driven | C |
| `src/omnicast/media/orchestrator.py` | MODIFY accept StylePreset | D |
| `src/omnicast/upload/orchestrator.py` | MINOR metadata changes | D |
| `benchmark_writers.py` | MODIFY use NicheConfig | D |

**Total: 16 files (3 new, 13 modify)**

---

## Backward Compatibility

- `BrandConfig` stays — `ChannelProfile.to_brand_config()` bridges it
- `DiscoveryConfig` stays — `ChannelProfile.to_discovery_config()` bridges it
- `WRITER_SYSTEM` constant stays as `WRITER_SYSTEM_FINANCE` for direct import in benchmark
- All existing tests pass without `ChannelProfile` (optional param, fallback to finance)
- `run_pipeline.py --topic "..."` still works (uses default channel)

---

## Success Criteria

1. `python run_pipeline.py --channel fin_retirement_us` → retirement-style script with empathetic tone
2. `python run_pipeline.py --channel health_nutrition_us` → health script with heartbeat SFX, blue palette
3. `python run_pipeline.py --channel myth_greek_us` → mythology script with dramatic-sting, sepia visuals
4. Same channel always produces consistent visual style regardless of topic
5. Critic scores ≥85 across all niches (not just finance)
6. `python benchmark_writers.py --channel fin_crypto_us` → crypto-style hooks, digital-blip SFX
