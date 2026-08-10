"""Transparent, deterministic occupational-track classification."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


TAXONOMY_VERSION = "1.1"
CLASSIFIER_VERSION = "rules-1.3.0"
MAX_TRACKS_PER_JOB = 3


def normalized(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


@dataclass(frozen=True)
class PatternRule:
    rule_id: str
    track_slug: str
    pattern: str
    confidence: float
    fields: tuple[str, ...] = ("title", "source_category", "source_department")

    @property
    def regex(self) -> re.Pattern[str]:
        return re.compile(self.pattern, flags=re.I)


@dataclass
class _Candidate:
    track_slug: str
    confidence: float
    method: str
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TrackAssignment:
    track_slug: str
    is_primary: bool
    confidence: float
    method: str
    reason: str
    taxonomy_version: str = TAXONOMY_VERSION
    review_status: str = "unreviewed"

    def as_dict(self) -> dict[str, Any]:
        return {
            "track_slug": self.track_slug,
            "is_primary": self.is_primary,
            "confidence": self.confidence,
            "method": self.method,
            "reason": self.reason,
            "taxonomy_version": self.taxonomy_version,
            "review_status": self.review_status,
        }


# Strong source-native mappings. Broad buckets such as "Corporate" are
# intentionally absent; title rules handle those without pretending all
# corporate work is administrative.
SOURCE_CATEGORY_MAP: dict[tuple[str, str], tuple[str, float]] = {
    ("amtrak", "customer service"): ("customer-service", 0.980),
    ("amtrak", "information technology"): ("it-data-cybersecurity", 0.990),
    ("amtrak", "internships & co-ops"): (
        "apprenticeships-entry-level-training",
        0.990,
    ),
    ("amtrak", "laborer skilled trades"): (
        "construction-skilled-trades-facilities",
        0.990,
    ),
    ("amtrak", "railroad operations"): ("transportation-logistics-fleet", 0.990),
    ("cuny", "executive"): ("management-supervision", 0.950),
    ("cuny", "faculty"): ("education-student-services", 0.980),
    ("cuny", "information technology/technical"): (
        "it-data-cybersecurity",
        0.990,
    ),
    ("nysdol_apprenticeships", "apprenticeship"): (
        "apprenticeships-entry-level-training",
        0.990,
    ),
    ("mta", "administrative & clerical"): ("administrative-office-support", 0.920),
    ("newyork_presbyterian", "administration"): (
        "administrative-office-support",
        0.900,
    ),
    ("newyork_presbyterian", "administrative support"): (
        "administrative-office-support",
        0.970,
    ),
    ("newyork_presbyterian", "clinical support services"): (
        "clinical-patient-support",
        0.980,
    ),
    ("newyork_presbyterian", "environmental services"): (
        "construction-skilled-trades-facilities",
        0.900,
    ),
    ("newyork_presbyterian", "facility development"): (
        "construction-skilled-trades-facilities",
        0.970,
    ),
    ("newyork_presbyterian", "facility operations"): (
        "construction-skilled-trades-facilities",
        0.970,
    ),
    ("newyork_presbyterian", "finance"): (
        "finance-purchasing-accounting",
        0.980,
    ),
    ("newyork_presbyterian", "food and nutrition"): (
        "food-hospitality-tourism",
        0.950,
    ),
    ("newyork_presbyterian", "housekeeping"): (
        "construction-skilled-trades-facilities",
        0.920,
    ),
    ("newyork_presbyterian", "information technology"): (
        "it-data-cybersecurity",
        0.990,
    ),
    ("newyork_presbyterian", "inventory operations"): (
        "transportation-logistics-fleet",
        0.940,
    ),
    ("newyork_presbyterian", "nursing support"): (
        "clinical-patient-support",
        0.980,
    ),
    ("newyork_presbyterian", "patient access"): (
        "clinical-patient-support",
        0.900,
    ),
    ("newyork_presbyterian", "patient financial services"): (
        "finance-purchasing-accounting",
        0.980,
    ),
    ("newyork_presbyterian", "patient support"): (
        "clinical-patient-support",
        0.980,
    ),
    ("newyork_presbyterian", "social services"): (
        "social-community-services",
        0.980,
    ),
    ("northwell", "administrative support"): (
        "administrative-office-support",
        0.990,
    ),
    ("northwell", "care coordination & social services"): (
        "social-community-services",
        0.960,
    ),
    ("northwell", "clinical support"): ("clinical-patient-support", 0.990),
    ("northwell", "facilities and support services"): (
        "construction-skilled-trades-facilities",
        0.940,
    ),
    ("northwell", "finance"): ("finance-purchasing-accounting", 0.990),
    ("northwell", "general management"): ("management-supervision", 0.920),
    ("northwell", "hospitality"): ("food-hospitality-tourism", 0.960),
    ("northwell", "human resources"): ("administrative-office-support", 0.960),
    ("northwell", "information technology and services"): (
        "it-data-cybersecurity",
        0.990,
    ),
    ("northwell", "patient and customer experience"): (
        "customer-service",
        0.980,
    ),
    ("northwell", "revenue cycle"): ("finance-purchasing-accounting", 0.900),
    ("northwell", "social services"): ("social-community-services", 0.990),
    ("northwell", "supply chain"): ("transportation-logistics-fleet", 0.960),
    ("nyc_jobs", "administration & human resources"): (
        "administrative-office-support",
        0.930,
    ),
    ("nyc_jobs", "engineering, architecture, & planning"): (
        "engineering-architecture-planning",
        0.960,
    ),
    ("port_authority", "college programs"): (
        "apprenticeships-entry-level-training",
        0.960,
    ),
    ("port_authority", "engineering"): ("engineering-architecture-planning", 0.940),
    ("port_authority", "finance"): ("finance-purchasing-accounting", 0.980),
    ("port_authority", "health & safety"): ("public-safety-security", 0.880),
    ("port_authority", "information technology"): ("it-data-cybersecurity", 0.980),
    ("port_authority", "maintenance"): (
        "construction-skilled-trades-facilities",
        0.970,
    ),
    ("port_authority", "operations"): ("transportation-logistics-fleet", 0.900),
    ("port_authority", "real estate & prop management"): (
        "construction-skilled-trades-facilities",
        0.820,
    ),
    ("port_authority", "security"): ("public-safety-security", 0.980),
    ("resorts_world_nyc", "casino operations"): (
        "food-hospitality-tourism",
        0.980,
    ),
    ("resorts_world_nyc", "facilities"): (
        "construction-skilled-trades-facilities",
        0.990,
    ),
    ("resorts_world_nyc", "finance"): (
        "finance-purchasing-accounting",
        0.990,
    ),
    ("resorts_world_nyc", "food & beverage operations"): (
        "food-hospitality-tourism",
        0.990,
    ),
    ("resorts_world_nyc", "hotel operations"): (
        "food-hospitality-tourism",
        0.990,
    ),
    ("resorts_world_nyc", "information technology"): (
        "it-data-cybersecurity",
        0.990,
    ),
    ("resorts_world_nyc", "sales & marketing"): (
        "communications-marketing",
        0.980,
    ),
    ("resorts_world_nyc", "supply chain"): (
        "transportation-logistics-fleet",
        0.980,
    ),
    ("statejobsny", "clerical, secretarial, office aide"): (
        "administrative-office-support",
        0.990,
    ),
    ("statejobsny", "financial, accounting, auditing"): (
        "finance-purchasing-accounting",
        0.990,
    ),
    ("statejobsny", "education, teaching"): (
        "education-student-services",
        0.950,
    ),
    ("statejobsny", "skilled craft, apprenticeship, maintenance"): (
        "construction-skilled-trades-facilities",
        0.990,
    ),
    ("statejobsny", "administrative or general management"): (
        "management-supervision",
        0.880,
    ),
    ("statejobsny", "enforcement or protective services"): (
        "public-safety-security",
        0.970,
    ),
}


PATTERN_RULES: tuple[PatternRule, ...] = (
    PatternRule(
        "admin-title",
        "administrative-office-support",
        r"\b(?:administrative|administration|clerical|office assistant|executive assistant|"
        r"secretar(?:y|ial)|human resources|talent acquisition|labor relations|"
        r"recruit(?:er|ment))\b",
        0.930,
    ),
    PatternRule(
        "it-title",
        "it-data-cybersecurity",
        r"\b(?:database administrator|cloud architect|software|developer|programmer|"
        r"cybersecurity|cyber security|information technology|it|help desk|desktop support|"
        r"network(?:ing| administrator| engineer)|telecommunications?|"
        r"systems? (?:administrator|analyst|engineer)|"
        r"data (?:analyst|engineer|scientist))\b",
        0.970,
    ),
    PatternRule(
        "transport-title",
        "transportation-logistics-fleet",
        r"\b(?:fleet|logistics|driver|bus operator|train operator|railroad|rail transit|"
        r"car equipment|tunnel and bridge|transportation|traffic engineer|port department)\b",
        0.940,
    ),
    PatternRule(
        "trades-title",
        "construction-skilled-trades-facilities",
        r"\b(?:electric(?:ian|ians|al)?|carpenter|carpenters|plumb(?:er|ers|ing)|pipefitter|"
        r"steamfitter|iron ?worker|sheet ?metal|roofer|roofing|bricklayer|boilermaker|"
        r"maintainer|millwright|mechanic|stationary.{0,12}engineer|operating engineers?|"
        r"construction|building|laborers?|finishing trades?|insulation|tile|marble|terrazzo|"
        r"hvac|welding|mason)\b",
        0.950,
    ),
    PatternRule(
        "engineering-title",
        "engineering-architecture-planning",
        r"(?<!operating )\b(?:engineer(?:ing|s)?|architect(?:ure)?|plan examiner|estimator|"
        r"project planning)\b",
        0.920,
    ),
    PatternRule(
        "customer-title",
        "customer-service",
        r"\b(?:customer service|customer support|call cent(?:er|re)|contact center|"
        r"receptionist|ticket agent|guest services?)\b",
        0.940,
    ),
    PatternRule(
        "communications-title",
        "communications-marketing",
        r"\b(?:communications?|marketing|public affairs|media relations|public information|"
        r"content (?:writer|producer)|graphic design|community outreach)\b",
        0.970,
    ),
    PatternRule(
        "clinical-title",
        "clinical-patient-support",
        r"\b(?:patient care|medical assistant|nursing assistant|nursing attendant|nurse aide|"
        r"phlebotom|clinical support|patient transporter|medical technician|"
        r"(?:ed|emergency department) technician)\b",
        0.960,
    ),
    PatternRule(
        "education-title",
        "education-student-services",
        r"\b(?:teacher|teaching assistant|instructor|student services|academic advisor|"
        r"librarian|education coordinator)\b",
        0.940,
    ),
    PatternRule(
        "finance-title",
        "finance-purchasing-accounting",
        r"\b(?:financial|finance|accountant|accounting|audit(?:or)?|treasurer|treasury|"
        r"budget|payroll|procurement|purchasing|buyer|risk analyst)\b",
        0.960,
    ),
    PatternRule(
        "hospitality-title",
        "food-hospitality-tourism",
        r"\b(?:food service|cook|chef|hospitality|hotel|gaming|casino|tourism|event services?)\b",
        0.950,
    ),
    PatternRule(
        "social-services-title",
        "social-community-services",
        r"\b(?:social worker|case worker|case manager|community services|benefits navigator|"
        r"counselor|housing specialist)\b",
        0.940,
    ),
    PatternRule(
        "safety-title",
        "public-safety-security",
        r"\b(?:security|police|law enforcement|emergency management|public safety|"
        r"construction safety|safety coordinator|safety manager)\b",
        0.960,
    ),
    PatternRule(
        "legal-title",
        "legal-compliance-policy",
        r"\b(?:attorney|lawyer|legal|counsel|litigation|compliance|paralegal|policy analyst)\b",
        0.970,
    ),
    PatternRule(
        "management-title",
        "management-supervision",
        r"^(?:(?:deputy|assistant|senior|executive)\s+)*(?:director|manager|chief|supervisor|"
        r"superintendent|commissioner|president|treasurer)\b|\bprogram director\b|"
        r"\b(?:project|program|business) manager\b",
        0.900,
        fields=("title",),
    ),
    PatternRule(
        "training-title",
        "apprenticeships-entry-level-training",
        r"\b(?:apprentice(?:ship)?|trainee|intern(?:ship)?|emerging talent|college programs?)\b",
        0.960,
    ),
)


DESCRIPTION_FALLBACK_RULES: tuple[PatternRule, ...] = (
    PatternRule(
        "clinical-description",
        "clinical-patient-support",
        r"\b(?:direct patient care|patient vital signs|phlebotomy|clinical support services)\b",
        0.720,
        fields=("summary", "description_text"),
    ),
    PatternRule(
        "it-description",
        "it-data-cybersecurity",
        r"\b(?:cybersecurity operations|database administration|software development|"
        r"network administration|technical support desk)\b",
        0.700,
        fields=("summary", "description_text"),
    ),
    PatternRule(
        "customer-description",
        "customer-service",
        r"\b(?:provide customer service|customer inquiries|contact center operations)\b",
        0.680,
        fields=("summary", "description_text"),
    ),
)


def _add_candidate(
    candidates: dict[str, _Candidate],
    *,
    track_slug: str,
    confidence: float,
    method: str,
    evidence: str,
) -> None:
    current = candidates.get(track_slug)
    if current is None:
        candidates[track_slug] = _Candidate(track_slug, confidence, method, [evidence])
        return
    previous_confidence = current.confidence
    if evidence not in current.evidence:
        current.evidence.append(evidence)
        current.confidence = min(0.995, max(current.confidence, confidence) + 0.020)
    if confidence > previous_confidence:
        current.method = method


def classify_job(job: Mapping[str, Any]) -> list[TrackAssignment]:
    """Return ordered primary/secondary assignments for one canonical job."""

    candidates: dict[str, _Candidate] = {}
    source_key = normalized(job.get("source_key"))
    category = normalized(job.get("source_category"))
    source_mapping = SOURCE_CATEGORY_MAP.get((source_key, category))
    if source_mapping:
        track_slug, confidence = source_mapping
        _add_candidate(
            candidates,
            track_slug=track_slug,
            confidence=confidence,
            method="source_map",
            evidence=f"source category {job.get('source_category')!r}",
        )

    for rule in (*PATTERN_RULES, *DESCRIPTION_FALLBACK_RULES):
        regex = rule.regex
        for field_name in rule.fields:
            value = normalized(job.get(field_name))
            match = regex.search(value)
            if not match:
                continue
            _add_candidate(
                candidates,
                track_slug=rule.track_slug,
                confidence=rule.confidence,
                method="rule",
                evidence=f"{field_name} matched {match.group(0)!r} ({rule.rule_id})",
            )
            break

    ranked = sorted(
        candidates.values(),
        key=lambda item: (-item.confidence, item.track_slug),
    )[:MAX_TRACKS_PER_JOB]
    if not ranked:
        return []

    needs_review = ranked[0].confidence < 0.750 or (
        len(ranked) > 1 and ranked[0].confidence - ranked[1].confidence < 0.025
    )
    review_status = "needs_review" if needs_review else "unreviewed"
    return [
        TrackAssignment(
            track_slug=candidate.track_slug,
            is_primary=index == 0,
            confidence=round(candidate.confidence, 3),
            method=candidate.method,
            reason=(
                f"{'; '.join(candidate.evidence[:3])}; "
                f"classifier {CLASSIFIER_VERSION}"
            ),
            review_status=review_status,
        )
        for index, candidate in enumerate(ranked)
    ]


def classification_counts(
    assignment_sets: Iterable[list[TrackAssignment]],
) -> tuple[dict[str, int], dict[str, int]]:
    primary: dict[str, int] = {}
    secondary: dict[str, int] = {}
    for assignments in assignment_sets:
        for assignment in assignments:
            target = primary if assignment.is_primary else secondary
            target[assignment.track_slug] = target.get(assignment.track_slug, 0) + 1
    return dict(sorted(primary.items())), dict(sorted(secondary.items()))
