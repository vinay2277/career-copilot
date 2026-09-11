"""What-if simulator: recalculate the board under a hypothetical profile.

Nothing here writes to the database. A scenario is applied to in-memory copies
of the profile and preferences, the whole board is re-scored, and the diff is
returned — so the user can try "what if I learned Kubernetes and dropped my
salary floor to 90k" without touching their real profile.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.models.enums import Proficiency
from app.services.analytics.alignment import (
    PreferenceInput,
    SkillInput,
    score_alignment,
)
from app.services.analytics.canonical import canonicalize
from app.services.analytics.skill_roi import (
    UNLOCK_THRESHOLD,
    ScoredJob,
    demanded_years,
)


@dataclass(frozen=True)
class Scenario:
    """A hypothetical change to the profile or preferences."""

    #: Skills to add (or upgrade, if already present).
    add_skills: list[str] = None  # type: ignore[assignment]
    #: Proficiency the added skills are assumed to reach.
    add_at: Proficiency = Proficiency.WORKING
    #: Years of experience to credit the added skills with. `None` means "as
    #: much as the board actually asks for", which is what makes "I learned
    #: this" register against requirements phrased as "3+ years of X". A fixed
    #: 0 would leave those at partial coverage and report no change at all.
    add_years: float | None = None
    #: Skills to remove, to answer "how much does this skill carry me?"
    remove_skills: list[str] = None  # type: ignore[assignment]

    #: Preference overrides. `None` means "leave as-is"; to clear a list
    #: preference, pass an empty list.
    min_salary: int | None = None
    remote_ok: bool | None = None
    seniority: str | None = None
    locations: list[str] | None = None

    def __post_init__(self) -> None:
        # Mutable defaults on a frozen dataclass need this dance; using
        # `field(default_factory=list)` would be cleaner but then `None` could
        # not mean "unset" for the preference overrides above.
        object.__setattr__(self, "add_skills", self.add_skills or [])
        object.__setattr__(self, "remove_skills", self.remove_skills or [])


@dataclass(frozen=True)
class JobDelta:
    job_id: int
    title: str
    company: str
    before: float
    after: float

    @property
    def change(self) -> float:
        return round(self.after - self.before, 1)

    @property
    def newly_in_reach(self) -> bool:
        return self.before < UNLOCK_THRESHOLD <= self.after

    @property
    def fell_out_of_reach(self) -> bool:
        return self.after < UNLOCK_THRESHOLD <= self.before


@dataclass(frozen=True)
class SimulationResult:
    mean_before: float
    mean_after: float
    in_reach_before: int
    in_reach_after: int
    deltas: list[JobDelta]

    @property
    def mean_change(self) -> float:
        return round(self.mean_after - self.mean_before, 1)

    @property
    def newly_in_reach(self) -> list[JobDelta]:
        return [d for d in self.deltas if d.newly_in_reach]

    @property
    def fell_out_of_reach(self) -> list[JobDelta]:
        return [d for d in self.deltas if d.fell_out_of_reach]


def apply_scenario(
    skills: list[SkillInput],
    prefs: PreferenceInput,
    scenario: Scenario,
    aliases: dict[str, str] | None = None,
    years_for: dict[str, float] | None = None,
) -> tuple[list[SkillInput], PreferenceInput]:
    """Produce the hypothetical profile and preferences. Inputs are untouched.

    `years_for` maps a canonical skill name to the experience to credit it
    with, and is how `simulate` supplies "whatever the board asks for". An
    explicit `scenario.add_years` overrides it; falling back to 0 is only
    correct when nothing states a year count.
    """
    removed = {canonicalize(n, aliases) for n in scenario.remove_skills}
    kept = [s for s in skills if canonicalize(s.name, aliases) not in removed]

    # An added skill that is already present is an upgrade, not a duplicate.
    added_keys = {canonicalize(n, aliases) for n in scenario.add_skills}
    kept = [s for s in kept if canonicalize(s.name, aliases) not in added_keys]

    def years(name: str) -> float:
        if scenario.add_years is not None:
            return scenario.add_years
        return (years_for or {}).get(canonicalize(name, aliases), 0.0)

    hypothetical_skills = [
        *kept,
        *(
            SkillInput(name=n, proficiency=scenario.add_at, years=years(n))
            for n in scenario.add_skills
        ),
    ]

    overrides: dict[str, object] = {}
    if scenario.min_salary is not None:
        overrides["min_salary"] = scenario.min_salary
    if scenario.remote_ok is not None:
        overrides["remote_ok"] = scenario.remote_ok
    if scenario.seniority is not None:
        overrides["seniority"] = scenario.seniority
    if scenario.locations is not None:
        overrides["locations"] = scenario.locations

    hypothetical_prefs = replace(prefs, **overrides) if overrides else prefs
    return hypothetical_skills, hypothetical_prefs


def simulate(
    jobs: list[ScoredJob],
    skills: list[SkillInput],
    prefs: PreferenceInput,
    scenario: Scenario,
    aliases: dict[str, str] | None = None,
) -> SimulationResult:
    """Re-score every job under `scenario` and report what moved."""
    # Credit each added skill with the most experience any tracked job asks for
    # in it, unless the caller pinned a number.
    years_for = {
        canonicalize(name, aliases): demanded_years(
            jobs, canonicalize(name, aliases), aliases
        )
        for name in scenario.add_skills
    }
    new_skills, new_prefs = apply_scenario(
        skills, prefs, scenario, aliases, years_for
    )

    deltas: list[JobDelta] = []
    for job in jobs:
        after = score_alignment(
            job.requirements, new_skills, new_prefs, job.facts, aliases
        )
        deltas.append(
            JobDelta(
                job_id=job.job_id,
                title=job.title,
                company=job.company,
                before=job.baseline.total,
                after=after.total,
            )
        )

    # Biggest movers first; ties broken by job id so output is stable.
    deltas.sort(key=lambda d: (-d.change, d.job_id))

    if not deltas:
        return SimulationResult(0.0, 0.0, 0, 0, [])

    return SimulationResult(
        mean_before=round(sum(d.before for d in deltas) / len(deltas), 1),
        mean_after=round(sum(d.after for d in deltas) / len(deltas), 1),
        in_reach_before=sum(1 for d in deltas if d.before >= UNLOCK_THRESHOLD),
        in_reach_after=sum(1 for d in deltas if d.after >= UNLOCK_THRESHOLD),
        deltas=deltas,
    )
