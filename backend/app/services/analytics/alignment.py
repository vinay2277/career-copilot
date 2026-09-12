"""The alignment scorer: 70% requirements, 30% preferences.

Pure functions over plain dataclasses. Nothing here touches the database or the
LLM, which is what makes the score auditable — every number has a visible
derivation, and `explain()` returns that derivation alongside the score.

Scoring shape
-------------
    total = 0.70 * requirements_fit + 0.30 * preference_fit

`requirements_fit` is a necessity-weighted average of per-requirement credit:

    requirements_fit = sum(weight * credit) / sum(weight)

where `weight` comes from how badly the job wants the skill and `credit` from
how well the candidate covers it. `preference_fit` averages only the facets
where both sides stated something — an unknown salary neither helps nor hurts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.enums import Coverage, Necessity, Proficiency
from app.services.analytics.canonical import canonicalize, normalize

# --------------------------------------------------------------------------- #
# Tunables. Changing any of these changes every historical score, so they live
# here as named constants rather than inline literals.
# --------------------------------------------------------------------------- #

REQUIREMENTS_WEIGHT = 0.70
PREFERENCES_WEIGHT = 0.30

#: How much a requirement counts, by how badly the job wants it.
NECESSITY_WEIGHT: dict[Necessity, float] = {
    Necessity.REQUIRED: 1.0,
    Necessity.PREFERRED: 0.5,
    Necessity.NICE_TO_HAVE: 0.2,
}

#: Ordinal rank of each proficiency level, for threshold comparisons.
PROFICIENCY_RANK: dict[Proficiency, int] = {
    Proficiency.NONE: 0,
    Proficiency.LEARNING: 1,
    Proficiency.WORKING: 2,
    Proficiency.PROFICIENT: 3,
    Proficiency.EXPERT: 4,
}

#: The rank at which a candidate is considered to genuinely have a skill.
SATISFIED_RANK = PROFICIENCY_RANK[Proficiency.WORKING]

#: Fraction of a requirement's weight earned by partial coverage.
PARTIAL_CREDIT = 0.5

COVERAGE_CREDIT: dict[Coverage, float] = {
    Coverage.HAVE: 1.0,
    Coverage.PARTIAL: PARTIAL_CREDIT,
    Coverage.MISSING: 0.0,
}


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SkillInput:
    name: str
    proficiency: Proficiency = Proficiency.WORKING
    years: float = 0.0


@dataclass(frozen=True)
class RequirementInput:
    name: str
    necessity: Necessity = Necessity.REQUIRED
    min_years: float = 0.0


@dataclass(frozen=True)
class PreferenceInput:
    target_roles: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    remote_ok: bool = True
    seniority: str | None = None
    min_salary: int | None = None
    company_sizes: list[str] = field(default_factory=list)
    industries: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class JobFacts:
    """The job-side facts the preference half compares against."""

    title: str = ""
    location: str | None = None
    remote: bool | None = None
    seniority: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    industry: str | None = None
    company_size: str | None = None


# --------------------------------------------------------------------------- #
# Outputs
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RequirementResult:
    name: str
    necessity: Necessity
    coverage: Coverage
    weight: float
    credit: float
    #: Why this coverage was assigned, in one human-readable sentence.
    reason: str

    @property
    def weighted_credit(self) -> float:
        return self.weight * self.credit


@dataclass(frozen=True)
class FacetResult:
    name: str
    matched: bool
    detail: str


@dataclass(frozen=True)
class AlignmentResult:
    total: float
    requirements_fit: float
    preference_fit: float
    requirements: list[RequirementResult]
    facets: list[FacetResult]

    @property
    def have(self) -> list[RequirementResult]:
        return [r for r in self.requirements if r.coverage is Coverage.HAVE]

    @property
    def partial(self) -> list[RequirementResult]:
        return [r for r in self.requirements if r.coverage is Coverage.PARTIAL]

    @property
    def missing(self) -> list[RequirementResult]:
        return [r for r in self.requirements if r.coverage is Coverage.MISSING]

    def explain(self) -> str:
        """A plain-text derivation of `total`, for the UI's 'why this score'."""
        lines = [
            f"Total {self.total:.1f}/100",
            f"  = {REQUIREMENTS_WEIGHT:.0%} x {self.requirements_fit:.1f} (requirements)",
            f"  + {PREFERENCES_WEIGHT:.0%} x {self.preference_fit:.1f} (preferences)",
            "",
            "Requirements:",
        ]
        for r in self.requirements:
            lines.append(
                f"  [{r.coverage.value:>7}] {r.name} "
                f"(weight {r.weight:.1f}, credit {r.credit:.1f}) - {r.reason}"
            )
        lines.append("")
        lines.append("Preferences:")
        for f in self.facets:
            mark = "match" if f.matched else "  no "
            lines.append(f"  [{mark}] {f.name} - {f.detail}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Requirement half
# --------------------------------------------------------------------------- #


def _coverage_for(
    requirement: RequirementInput,
    skill: SkillInput | None,
) -> tuple[Coverage, str]:
    """Decide how well one skill covers one requirement."""
    if skill is None:
        return Coverage.MISSING, "not on the profile"

    rank = PROFICIENCY_RANK.get(skill.proficiency, 0)
    if rank < SATISFIED_RANK:
        return (
            Coverage.PARTIAL,
            f"listed at '{skill.proficiency.value}', below working proficiency",
        )

    if requirement.min_years > 0 and skill.years < requirement.min_years:
        return (
            Coverage.PARTIAL,
            f"{skill.years:g}y experience against {requirement.min_years:g}y asked",
        )

    return Coverage.HAVE, f"{skill.proficiency.value}, {skill.years:g}y"


def score_requirements(
    requirements: list[RequirementInput],
    skills: list[SkillInput],
    aliases: dict[str, str] | None = None,
) -> tuple[float, list[RequirementResult]]:
    """Score the requirements half. Returns (0-100 fit, per-requirement detail).

    A job with no extracted requirements scores 0 rather than 100: an empty
    requirement list means extraction failed, and rewarding that would put
    unparseable jobs at the top of the board.
    """
    # Canonicalize the profile once. On a duplicate skill name, the stronger
    # entry wins, so a stray low-proficiency duplicate can't drag a score down.
    by_name: dict[str, SkillInput] = {}
    for s in skills:
        key = canonicalize(s.name, aliases)
        if not key:
            continue
        existing = by_name.get(key)
        if existing is None or _stronger(s, existing):
            by_name[key] = s

    results: list[RequirementResult] = []
    for req in requirements:
        key = canonicalize(req.name, aliases)
        if not key:
            continue
        coverage, reason = _coverage_for(req, by_name.get(key))
        results.append(
            RequirementResult(
                name=req.name,
                necessity=req.necessity,
                coverage=coverage,
                weight=NECESSITY_WEIGHT.get(req.necessity, 1.0),
                credit=COVERAGE_CREDIT[coverage],
                reason=reason,
            )
        )

    # Stable ordering: worst coverage first, then heaviest, then alphabetical.
    # Deterministic output matters as much as a deterministic number.
    coverage_order = {Coverage.MISSING: 0, Coverage.PARTIAL: 1, Coverage.HAVE: 2}
    results.sort(key=lambda r: (coverage_order[r.coverage], -r.weight, r.name))

    total_weight = sum(r.weight for r in results)
    if total_weight == 0:
        return 0.0, results

    fit = sum(r.weighted_credit for r in results) / total_weight * 100.0
    return fit, results


def _stronger(a: SkillInput, b: SkillInput) -> bool:
    return (PROFICIENCY_RANK.get(a.proficiency, 0), a.years) > (
        PROFICIENCY_RANK.get(b.proficiency, 0),
        b.years,
    )


# --------------------------------------------------------------------------- #
# Preference half
# --------------------------------------------------------------------------- #


def score_preferences(
    prefs: PreferenceInput,
    job: JobFacts,
) -> tuple[float, list[FacetResult]]:
    """Score the preference half. Returns (0-100 fit, per-facet detail).

    Only facets where *both* sides stated something are scored. A job that
    doesn't publish salary is not penalized for it, and neither is a candidate
    who didn't set a floor — otherwise every unlisted field would quietly push
    scores toward zero.
    """
    facets: list[FacetResult] = []

    # --- Role ---
    if prefs.target_roles and job.title:
        title_tokens = set(normalize(job.title).split())
        hit = next(
            (
                role
                for role in prefs.target_roles
                if set(normalize(role).split()) & title_tokens
            ),
            None,
        )
        facets.append(
            FacetResult(
                "role",
                hit is not None,
                f"'{job.title}' vs {prefs.target_roles}"
                + (f" - overlaps '{hit}'" if hit else " - no shared terms"),
            )
        )

    # --- Location / remote ---
    # Remote satisfies a location preference outright: someone who will work
    # remotely doesn't care that the office is in another city.
    if job.remote is True and prefs.remote_ok:
        facets.append(FacetResult("location", True, "remote, and remote is acceptable"))
    elif prefs.locations and job.location:
        job_loc = normalize(job.location)
        hit = next(
            (loc for loc in prefs.locations if normalize(loc) in job_loc), None
        )
        facets.append(
            FacetResult(
                "location",
                hit is not None,
                f"'{job.location}' vs {prefs.locations}",
            )
        )
    elif job.remote is False and not prefs.remote_ok and not prefs.locations:
        facets.append(FacetResult("location", True, "on-site, no location preference"))

    # --- Seniority ---
    if prefs.seniority and job.seniority:
        matched = normalize(prefs.seniority) == normalize(job.seniority)
        facets.append(
            FacetResult(
                "seniority", matched, f"'{job.seniority}' vs '{prefs.seniority}'"
            )
        )

    # --- Salary ---
    # Compared against the top of the job's band: the band's ceiling is what is
    # actually negotiable, and judging on the floor would reject most postings.
    if prefs.min_salary is not None:
        offered = job.salary_max if job.salary_max is not None else job.salary_min
        if offered is not None:
            matched = offered >= prefs.min_salary
            facets.append(
                FacetResult(
                    "salary",
                    matched,
                    f"{offered:,} offered against {prefs.min_salary:,} wanted",
                )
            )

    # --- Industry ---
    if prefs.industries and job.industry:
        job_ind = normalize(job.industry)
        matched = any(normalize(i) == job_ind for i in prefs.industries)
        facets.append(
            FacetResult(
                "industry", matched, f"'{job.industry}' vs {prefs.industries}"
            )
        )

    # --- Company size ---
    if prefs.company_sizes and job.company_size:
        job_size = normalize(job.company_size)
        matched = any(normalize(s) == job_size for s in prefs.company_sizes)
        facets.append(
            FacetResult(
                "company_size",
                matched,
                f"'{job.company_size}' vs {prefs.company_sizes}",
            )
        )

    if not facets:
        # Nothing comparable on either side. Neutral, not zero — a score of zero
        # here would drag the total down by 30 points for an un-filled profile.
        return 50.0, [
            FacetResult("none", False, "no comparable preferences on file")
        ]

    matched_count = sum(1 for f in facets if f.matched)
    return matched_count / len(facets) * 100.0, facets


# --------------------------------------------------------------------------- #
# Combined
# --------------------------------------------------------------------------- #


def score_alignment(
    requirements: list[RequirementInput],
    skills: list[SkillInput],
    prefs: PreferenceInput,
    job: JobFacts,
    aliases: dict[str, str] | None = None,
) -> AlignmentResult:
    """Full 70/30 alignment score for one candidate against one job."""
    req_fit, req_results = score_requirements(requirements, skills, aliases)
    pref_fit, facets = score_preferences(prefs, job)

    total = REQUIREMENTS_WEIGHT * req_fit + PREFERENCES_WEIGHT * pref_fit

    # Round only at the boundary. Rounding the halves first would make the
    # displayed total disagree with the displayed components.
    return AlignmentResult(
        total=round(total, 1),
        requirements_fit=round(req_fit, 1),
        preference_fit=round(pref_fit, 1),
        requirements=req_results,
        facets=facets,
    )
