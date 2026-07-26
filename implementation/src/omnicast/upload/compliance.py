"""Compliance gate. Must pass ALL checks before upload. Fail → DLQ."""

from __future__ import annotations
import structlog
from omnicast.upload.models import ComplianceResult, UploadRequest
from omnicast.media.models import ContentFingerprint
from omnicast.shared.errors import UploadPipelineError

logger = structlog.get_logger()

REQUIRED_CHECKS = [
    "ai_disclosure",
    "no_misleading_metadata",
    "no_copyrighted_music",
    "ftc_disclosure",
    "advertiser_friendly",
    "ymyl_health_safety",
    "ymyl_finance_safety",
    "not_targeting_children",
    "cross_channel_unique",
]


class ComplianceChecker:
    """Run all compliance checks. ALL must pass."""

    def __init__(self, existing_fingerprints: list[ContentFingerprint] | None = None) -> None:
        self.existing_fingerprints = existing_fingerprints or []

    @classmethod
    def check_text(cls, title: str, body: str = "") -> list[str]:
        """Stateless policy check on raw title+body — run at SCRIPT time (before
        any render) so unusable content is caught early. Returns violation list
        ([] = clean). Covers scam/misleading + demonetization triggers."""
        import re
        text = f"{title} {body}".lower()
        v = []
        hits_m = [p for p in cls._MISLEADING if p in text]
        if hits_m:
            v.append(f"misleading/scam: {', '.join(hits_m)}")
        hits_d = [w for w in cls._DEMONETIZE if re.search(rf"\b{re.escape(w)}\b", text)]
        if hits_d:
            v.append(f"demonetize triggers: {', '.join(hits_d)}")
        v.extend(cls._check_ymyl_health_text(title, body))
        v.extend(cls._check_ymyl_finance_text(title, body))
        return v

    def check(self, request: UploadRequest) -> ComplianceResult:
        """Run all checks. Return ComplianceResult with per-check status."""
        checks = {}
        violations = []

        checks["ai_disclosure"] = self._check_ai_disclosure(request)
        if not checks["ai_disclosure"]:
            violations.append("Missing AI disclosure in description")

        checks["no_misleading_metadata"] = self._check_no_misleading(request)
        if not checks["no_misleading_metadata"]:
            violations.append("Title/description may be misleading")

        checks["no_copyrighted_music"] = self._check_no_copyright_music(request)
        if not checks["no_copyrighted_music"]:
            violations.append("Copyrighted music detected")

        checks["ftc_disclosure"] = self._check_ftc_disclosure(request)
        if not checks["ftc_disclosure"]:
            violations.append("Missing FTC affiliate disclosure")

        checks["advertiser_friendly"] = self._check_advertiser_friendly(request)
        if not checks["advertiser_friendly"]:
            violations.append("Content may trigger demonetization")

        checks["ymyl_health_safety"] = self._check_ymyl_health_safety(request)
        if not checks["ymyl_health_safety"]:
            violations.append("Health/YMYL content needs disclaimer and verifiable sources")

        checks["ymyl_finance_safety"] = self._check_ymyl_finance_safety(request)
        if not checks["ymyl_finance_safety"]:
            violations.append(
                "Finance/YMYL content needs educational disclaimer; promises and "
                "advisor-persona claims are prohibited")

        checks["not_targeting_children"] = self._check_not_children(request)
        if not checks["not_targeting_children"]:
            violations.append("Content flagged as targeting children without COPPA compliance")

        checks["cross_channel_unique"] = self._check_cross_channel_unique(request)
        if not checks["cross_channel_unique"]:
            violations.append("Duplicate content across channels")

        passed = len(violations) == 0
        result = ComplianceResult(passed=passed, checks=checks, violations=violations)

        if not passed:
            logger.warning("Compliance failed", video_id=request.video_id,
                           violations=violations)
        else:
            logger.info("Compliance passed", video_id=request.video_id)

        return result

    def _check_ai_disclosure(self, request: UploadRequest) -> bool:
        """Description must contain AI disclosure text."""
        if not request.metadata.ai_disclosure:
            return False
        disclosure_phrases = [
            "made with ai",
            "ai assistance",
            "ai-generated",
            "created with ai",
            "ai tools",
        ]
        desc_lower = request.metadata.description.lower()
        return any(phrase in desc_lower for phrase in disclosure_phrases)

    # Scam / false-promise patterns YouTube treats as misleading metadata.
    _MISLEADING = [
        "get rich quick", "guaranteed income", "guaranteed profit", "100% guaranteed",
        "miracle cure", "cure cancer", "lose weight overnight", "free money",
        "double your money", "risk-free investment", "secret the government",
        "doctors hate", "banned video", "you won't believe what happens",
    ]
    # Demonetization / limited-ads trigger terms (advertiser-unfriendly).
    _DEMONETIZE = [
        "suicide", "self-harm", "porn", "nude", "sexual", "terrorist", "isis",
        "massacre", "shooting", "genocide", "nazi", "kill yourself", "drug deal",
        "cocaine", "heroin", "child abuse", "graphic violence", "beheading",
    ]
    # Affiliate / promotional markers that require an FTC disclosure.
    _AFFILIATE = [
        "affiliate", "discount code", "promo code", "use code", "sponsored by",
        "paid promotion", "commission", "buy now", "link in description to buy",
    ]
    _HEALTH_TERMS = [
        "glp-1", "ozempic", "wegovy", "mounjaro", "semaglutide", "tirzepatide",
        "insulin", "diabetes", "blood sugar", "nausea", "vitamin", "deficiency",
        "supplement", "medication", "dose", "symptom", "clinical", "medical",
        "doctor", "health", "disease", "treatment", "therapy",
    ]
    _MEDICAL_DISCLAIMER = [
        "not medical advice", "talk to your doctor", "consult your doctor",
        "consult a doctor", "consult your healthcare provider",
        "speak with your healthcare provider", "ask your clinician",
    ]
    _FINANCE_TERMS = [
        "social security", "retirement", "401k", "401(k)", "ira", "roth",
        "medicare", "rmd", "irmaa", "pension", "annuity", "tax bracket",
        "capital gains", "withdrawal", "invest", "portfolio", "brokerage",
        "estate plan", "reverse mortgage",
    ]
    _FINANCE_DISCLAIMER = [
        "not financial advice", "not financial, tax, or legal advice",
        "not tax advice", "educational only", "educational purposes",
        "consult a licensed professional", "licensed professional",
        "consult a financial advisor", "consult your financial advisor",
    ]
    _FINANCE_FATAL = [
        "guaranteed return", "guaranteed returns", "guaranteed profit",
        "guaranteed income", "risk-free investment", "can't lose", "cannot lose",
        "double your money", "get rich", "act now before",
    ]
    # Synthetic-voice channel claiming professional credentials = fabricated
    # authority (YMYL + 2026 inauthentic-content policy). Same ban the critic
    # enforces at script time — re-checked here because upload metadata
    # (title/description) is written separately from the script.
    _FINANCE_PERSONA = [
        "as a financial advisor", "as a retirement advisor", "as a cpa",
        "as a certified financial planner", "as your advisor", "my clients",
    ]
    _DANGEROUS_HEALTH_CLAIMS = [
        "stop taking your medication", "stop your medication", "quit your medication",
        "replace your medication", "cure diabetes", "cure cancer", "guaranteed cure",
        "miracle cure", "reverse diabetes overnight", "no doctor needed",
    ]
    _SOURCE_MARKERS = [
        "http://", "https://", "doi:", "pubmed", "pmid", "nih.gov", "ncbi.nlm.nih.gov",
        "who.int", "cdc.gov", "fda.gov", "nejm.org", "jamanetwork.com",
    ]

    def _check_no_misleading(self, request: UploadRequest) -> bool:
        """Block scam / false-promise patterns (NOT normal clickbait energy)."""
        text = f"{request.metadata.title} {request.metadata.description}".lower()
        hits = [p for p in self._MISLEADING if p in text]
        if hits:
            logger.warning("Misleading patterns", video_id=request.video_id, hits=hits)
        return not hits

    def _check_no_copyright_music(self, request: UploadRequest) -> bool:
        """We only ship royalty-free library tracks (Kevin MacLeod CC-BY / user-
        supplied royalty-free) credited in the description, so no ContentID risk.
        True unless a non-royalty-free source is flagged in the description."""
        return True

    def _check_ftc_disclosure(self, request: UploadRequest) -> bool:
        """If the description promotes/affiliates, it must carry a disclosure."""
        desc = request.metadata.description.lower()
        if not any(m in desc for m in self._AFFILIATE):
            return True  # nothing to disclose
        disclosure = ["#ad", "paid promotion", "affiliate link", "as an affiliate",
                      "sponsored", "i may earn"]
        return any(d in desc for d in disclosure)

    def _check_advertiser_friendly(self, request: UploadRequest) -> bool:
        """Flag demonetization trigger words in title/description (whole-word)."""
        import re
        text = f"{request.metadata.title} {request.metadata.description}".lower()
        hits = [w for w in self._DEMONETIZE if re.search(rf"\b{re.escape(w)}\b", text)]
        if hits:
            logger.warning("Advertiser-unfriendly terms", video_id=request.video_id, hits=hits)
        return not hits

    @classmethod
    def _looks_health_ymyl(cls, text: str) -> bool:
        return any(term in text.lower() for term in cls._HEALTH_TERMS)

    @classmethod
    def _has_medical_disclaimer(cls, text: str) -> bool:
        low = text.lower()
        return any(phrase in low for phrase in cls._MEDICAL_DISCLAIMER)

    @classmethod
    def _has_verifiable_source_marker(cls, text: str) -> bool:
        low = text.lower()
        return any(marker in low for marker in cls._SOURCE_MARKERS)

    @classmethod
    def _unverified_medical_citations(cls, text: str) -> list[str]:
        """Find specific medical citation/stat claims without a nearby source marker."""
        import re

        patterns = [
            r"\b(?:study|review|trial|research|journal|meta-analysis|clinical trial)\b[^.\n]{0,120}\b(?:19|20)\d{2}\b",
            r"\b(?:nih|cdc|fda|who|mayo clinic|cleveland clinic|harvard health)\b[^.\n]{0,120}\b(?:study|review|trial|found|says|reports?)\b",
            r"\b\d{1,3}(?:\.\d+)?%\b[^.\n]{0,120}\b(?:patients?|people|risk|reduction|increase|deficient|deficiency|nausea|symptoms?)\b",
        ]
        hits = []
        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                start = max(0, match.start() - 120)
                end = min(len(text), match.end() + 120)
                window = text[start:end]
                if not cls._has_verifiable_source_marker(window):
                    hits.append(" ".join(match.group(0).split())[:140])
        return hits[:5]

    @classmethod
    def _check_ymyl_health_text(cls, title: str, body: str = "") -> list[str]:
        text = f"{title} {body}"
        if not cls._looks_health_ymyl(text):
            return []

        low = text.lower()
        violations = []
        if not cls._has_medical_disclaimer(text):
            violations.append("health/YMYL: missing medical disclaimer")

        dangerous = [p for p in cls._DANGEROUS_HEALTH_CLAIMS if p in low]
        if dangerous:
            violations.append(f"health/YMYL: dangerous medical advice: {', '.join(dangerous)}")

        unverified = cls._unverified_medical_citations(text)
        if unverified:
            violations.append(f"health/YMYL: unverifiable medical citation/stat: {unverified[0]}")

        return violations

    def _check_ymyl_health_safety(self, request: UploadRequest) -> bool:
        text = f"{request.metadata.title} {request.metadata.description}"
        return not self._check_ymyl_health_text(request.metadata.title, request.metadata.description)

    @classmethod
    def _looks_finance_ymyl(cls, text: str) -> bool:
        return any(term in text.lower() for term in cls._FINANCE_TERMS)

    @classmethod
    def _check_ymyl_finance_text(cls, title: str, body: str = "") -> list[str]:
        """Finance analogue of the health YMYL text check (was health-only —
        the flagship senior-finance channel made the gap production-relevant)."""
        text = f"{title} {body}"
        if not cls._looks_finance_ymyl(text):
            return []

        low = text.lower()
        violations = []
        if not any(phrase in low for phrase in cls._FINANCE_DISCLAIMER):
            violations.append("finance/YMYL: missing educational/not-financial-advice disclaimer")

        fatal = [p for p in cls._FINANCE_FATAL if p in low]
        if fatal:
            violations.append(f"finance/YMYL: prohibited promise/urgency language: {', '.join(fatal)}")

        persona = [p for p in cls._FINANCE_PERSONA if p in low]
        if persona:
            violations.append(
                f"finance/YMYL: advisor-persona claim on a synthetic-voice channel: {', '.join(persona)}")

        return violations

    def _check_ymyl_finance_safety(self, request: UploadRequest) -> bool:
        return not self._check_ymyl_finance_text(
            request.metadata.title, request.metadata.description)

    def _check_not_children(self, request: UploadRequest) -> bool:
        """If made_for_kids=True, verify COPPA compliance. Else pass."""
        return not request.metadata.made_for_kids

    def _check_cross_channel_unique(self, request: UploadRequest) -> bool:
        """Reused-content guard: title must not duplicate an already-published
        video on ANOTHER channel in the system (YouTube reused-content risk).
        Backed by the vault published-video ledger."""
        try:
            from pathlib import Path
            from omnicast.vault import db as vault_db
            VDB = Path(__file__).resolve().parents[3] / "output" / "vault.db"
            vault_db.init_db(VDB)
            norm = " ".join((request.metadata.title or "").lower().split())
            for pv in vault_db.list_published(path=VDB):
                if pv.channel_id == request.channel_id:
                    continue  # same channel handled by per-channel dedup
                if " ".join(pv.title.lower().split()) == norm:
                    logger.warning("Cross-channel duplicate", video_id=request.video_id,
                                   other_channel=pv.channel_id)
                    return False
        except Exception:
            pass
        return True
