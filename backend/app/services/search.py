"""Finding candidates by skill.

The scoring is the alignment engine turned around. A posting scores one
candidate against many requirements; a search scores many candidates against
one set of requirements the recruiter typed. Same function, same weights, same
partial-credit rules — so a candidate who reads as a 78 on a posting reads as a
78 here, and nobody has to reconcile two different numbers for the same fit.

**One hard rule governs this whole module: a profile is searchable only if its
owner switched `visible_to_recruiters` on.** It is off by default and nothing
turns it on implicitly — not uploading a résumé, not applying to a role, not
filling in a profile. Applying to a posting makes that one recruiter able to
see you for that one role; it is not consent to be found by every recruiter on
the platform, and conflating the two is how a career tool turns into a database
of people who never agreed to be in one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Preferences, Profile
from app.models.enums import Necessity
from app.services.analytics.alignment import (
    RequirementInput,
    RequirementResult,
    SkillInput,
    score_requirements,
)
from app.services.analytics.canonical import canonicalize


@dataclass(frozen=True)
class CandidateQuery:
    """What a recruiter asked for.

    `skills` is optional. An empty search is a legitimate question — "who is
    here and open to work?" — and answering it with nothing would read as a
    broken page rather than as an empty result.
    """

    skills: list[str] = field(default_factory=list)
    min_years: float | None = None
    location: str | None = None
    #: Only candidates whose stated preference is that they will work remotely.
    remote_only: bool = False
    #: Excludes people who marked themselves as not currently looking.
    open_to_work_only: bool = True
    limit: int = 50


@dataclass(frozen=True)
class CandidateMatch:
    profile: Profile
    #: None when the recruiter searched without naming any skill — there is
    #: nothing to score against, and inventing a number would be worse than
    #: admitting that.
    score: float | None
    requirements: list[RequirementResult]

    @property
    def have(self) -> list[str]:
        return [r.name for r in self.requirements if r.coverage.value == "have"]

    @property
    def partial(self) -> list[str]:
        return [r.name for r in self.requirements if r.coverage.value == "partial"]

    @property
    def missing(self) -> list[str]:
        return [r.name for r in self.requirements if r.coverage.value == "missing"]


def _requirements(skills: list[str]) -> list[RequirementInput]:
    """Turn typed skill names into requirements to score against.

    All weighted equally as REQUIRED. A recruiter typing three skills into a
    box has not said which matters more, and guessing a ranking they did not
    give would make the ordering unexplainable.
    """
    seen: set[str] = set()
    out: list[RequirementInput] = []
    for raw in skills:
        name = canonicalize(raw)
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(RequirementInput(name=name, necessity=Necessity.REQUIRED))
    return out


def _matches_location(profile: Profile, wanted: str) -> bool:
    """Whether the candidate is plausibly reachable in a place.

    Checks where they are *and* where they said they want to work: somebody in
    Pune whose preferences list Bengaluru is a real candidate for a Bengaluru
    role, and dropping them would hide exactly the people most willing to move.
    """
    wanted = wanted.strip().lower()
    if not wanted:
        return True

    if profile.location and wanted in profile.location.lower():
        return True

    prefs: Preferences | None = profile.preferences
    if prefs and prefs.locations:
        return any(wanted in place.lower() for place in prefs.locations)
    return False


def search_candidates(db: Session, query: CandidateQuery) -> list[CandidateMatch]:
    """Rank the opted-in candidates against a recruiter's search.

    Ranked and capped, never cut off by score. Everyone who passes the stated
    filters appears in score order — the number sorts the list, it does not
    decide who is in it.
    """
    stmt = (
        select(Profile)
        .where(Profile.visible_to_recruiters.is_(True))
        .options(selectinload(Profile.preferences))
    )
    if query.open_to_work_only:
        stmt = stmt.where(Profile.open_to_work.is_(True))
    if query.min_years is not None:
        stmt = stmt.where(Profile.years_experience >= query.min_years)

    profiles = list(db.execute(stmt).scalars())

    # Location and remote are filtered in Python: both can be satisfied by the
    # preferences row rather than the profile, and expressing "either" in SQL
    # across a nullable join costs more clarity than it saves on a table this
    # size.
    if query.location:
        profiles = [p for p in profiles if _matches_location(p, query.location)]
    if query.remote_only:
        profiles = [
            p for p in profiles if p.preferences is None or p.preferences.remote_ok
        ]

    requirements = _requirements(query.skills)

    matches: list[CandidateMatch] = []
    for profile in profiles:
        if not requirements:
            matches.append(CandidateMatch(profile=profile, score=None, requirements=[]))
            continue

        fit, results = score_requirements(
            requirements,
            [
                SkillInput(name=s.name, proficiency=s.proficiency, years=s.years)
                for s in profile.skills
            ],
        )
        matches.append(
            CandidateMatch(profile=profile, score=round(fit, 1), requirements=results)
        )

    # Score first, then experience, then name.
    #
    # The experience tie-break earns its place: one requirement is either met
    # or not, so searching a single skill scores an expert of six years and a
    # two-year working knowledge identically at 100. Both genuinely cover it —
    # the score is right — but handing the recruiter the shallower candidate
    # first because their name sorts earlier is not a ranking, it is an
    # accident. Breaking the tie on depth changes the order, never the number.
    #
    # An unscored search has only experience to go on, so the same key covers
    # it with `None` scoring below every real score.
    matches.sort(
        key=lambda m: (
            -(m.score if m.score is not None else 0.0),
            -m.profile.years_experience,
            m.profile.full_name.lower(),
        )
    )
    return matches[: query.limit]
