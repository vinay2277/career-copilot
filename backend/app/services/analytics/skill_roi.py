"""Skill ROI: which one skill, learned next, buys the most.

The question this answers is not "what am I missing" — the gap analysis already
says that. It is "of everything I'm missing, which single skill moves the most
jobs into reach?" That is answered by counterfactual: add the skill to the
profile at working proficiency, re-score every tracked job, and measure what
actually changed.

Everything here is deterministic. The same board and the same profile always
produce the same ranking.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.enums import Coverage, Proficiency
from app.services.analytics.alignment import (
    AlignmentResult,
    JobFacts,
    PreferenceInput,
    RequirementInput,
    SkillInput,
    score_alignment,
)
from app.services.analytics.canonical import canonicalize

#: A job at or above this alignment score counts as "in reach". Learning a skill
#: that pushes a job across this line is the headline ROI number.
UNLOCK_THRESHOLD = 70.0

#: Proficiency a newly learned skill is assumed to reach. Deliberately modest:
#: projecting `EXPERT` would overstate the payoff of every course.
ASSUMED_PROFICIENCY = Proficiency.WORKING


@dataclass(frozen=True)
class ScoredJob:
    """One job on the board, with the inputs needed to re-score it."""

    job_id: int
    title: str
    company: str
    requirements: list[RequirementInput]
    facts: JobFacts
    baseline: AlignmentResult


@dataclass(frozen=True)
class SkillROI:
    skill: str
    #: How many tracked jobs ask for this skill at all.
    demand: int
    #: Mean alignment points gained across every job, learning only this skill.
    mean_gain: float
    #: Largest single-job gain, and which job.
    best_gain: float
    best_job_id: int | None
    #: Jobs that cross UNLOCK_THRESHOLD only because of this skill.
    unlocks: list[int]
    #: Total weight this skill carries across the board, by necessity. A skill
    #: that is `required` in five jobs outranks one that is `nice_to_have` in
    #: eight, and this is the number that says so.
    weighted_demand: float

    @property
    def unlock_count(self) -> int:
        return len(self.unlocks)


def demanded_years(
    jobs: list[ScoredJob],
    skill: str,
    aliases: dict[str, str] | None = None,
) -> float:
    """The most experience any tracked job asks for in `skill`.

    The counterfactual needs this because "learned the skill" has to mean
    "cleared the bar the postings actually set". Granting working proficiency
    with zero years leaves every requirement that says "2+ years" sitting at
    partial coverage, so the measured gain comes out as exactly zero — and the
    skills with the most demand are precisely the ones that state a year count,
    so the ranking inverts and promotes obscure skills over important ones.
    """
    return max(
        (
            r.min_years
            for job in jobs
            for r in job.requirements
            if canonicalize(r.name, aliases) == skill
        ),
        default=0.0,
    )


def _profile_with(
    skills: list[SkillInput],
    skill_name: str,
    years: float = 0.0,
) -> list[SkillInput]:
    """The profile as it would be with `skill_name` learned to `years`.

    An existing entry for the same skill is dropped rather than left alongside:
    scoring keeps the stronger of two duplicates, and a `learning`-level entry
    surviving here is what made upgrading a partially-held skill measure as no
    change at all.
    """
    key = canonicalize(skill_name)
    kept = [s for s in skills if canonicalize(s.name) != key]
    return [
        *kept,
        SkillInput(name=skill_name, proficiency=ASSUMED_PROFICIENCY, years=years),
    ]


def gap_candidates(
    jobs: list[ScoredJob],
    aliases: dict[str, str] | None = None,
) -> dict[str, float]:
    """Every canonical skill the board wants that the profile doesn't fully have.

    Returns canonical name -> summed necessity weight. Partial coverage counts:
    a skill held below working proficiency is still worth strengthening, and the
    counterfactual below will price that correctly.
    """
    weights: dict[str, float] = {}
    for job in jobs:
        for result in job.baseline.requirements:
            if result.coverage is Coverage.HAVE:
                continue
            key = canonicalize(result.name, aliases)
            if key:
                weights[key] = weights.get(key, 0.0) + result.weight
    return weights


def rank_skills(
    jobs: list[ScoredJob],
    skills: list[SkillInput],
    prefs: PreferenceInput,
    aliases: dict[str, str] | None = None,
    limit: int = 10,
) -> list[SkillROI]:
    """Rank skill gaps by what learning each one would actually buy.

    Cost is one alignment pass per (candidate skill x job). Both are small — a
    board of 50 jobs with 40 distinct gaps is 2,000 pure-Python scorings, which
    runs in well under a second. If a board ever grows past that, cache the
    per-job baseline rather than reaching for an approximation; an approximate
    ROI number would break the auditability the whole engine exists for.
    """
    candidates = gap_candidates(jobs, aliases)
    if not candidates or not jobs:
        return []

    rois: list[SkillROI] = []
    for skill_name, weighted_demand in candidates.items():
        hypothetical = _profile_with(
            skills, skill_name, demanded_years(jobs, skill_name, aliases)
        )

        gains: list[float] = []
        demand = 0
        best_gain = 0.0
        best_job_id: int | None = None
        unlocks: list[int] = []

        for job in jobs:
            wanted = any(
                canonicalize(r.name, aliases) == skill_name for r in job.requirements
            )
            if wanted:
                demand += 1

            after = score_alignment(
                job.requirements, hypothetical, prefs, job.facts, aliases
            )
            gain = after.total - job.baseline.total
            gains.append(gain)

            if gain > best_gain:
                best_gain = gain
                best_job_id = job.job_id

            crossed = (
                job.baseline.total < UNLOCK_THRESHOLD
                and after.total >= UNLOCK_THRESHOLD
            )
            if crossed:
                unlocks.append(job.job_id)

        rois.append(
            SkillROI(
                skill=skill_name,
                demand=demand,
                mean_gain=round(sum(gains) / len(gains), 2),
                best_gain=round(best_gain, 2),
                best_job_id=best_job_id,
                unlocks=sorted(unlocks),
                weighted_demand=round(weighted_demand, 2),
            )
        )

    # Unlocks first — crossing the threshold is what changes behaviour. Mean
    # gain breaks ties, then weighted demand, then name for stability.
    rois.sort(
        key=lambda r: (-r.unlock_count, -r.mean_gain, -r.weighted_demand, r.skill)
    )
    return rois[:limit]
