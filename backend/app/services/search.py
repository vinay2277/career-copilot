"""Finding candidates by skill.

The scoring is the alignment engine turned around. A posting scores one
candidate against many requirements; a search scores many candidates against
one set of requirements the recruiter typed. Same function, same weights, same
partial-credit rules — so a candidate who reads as a 78 on a posting reads as a
78 here, and nobody has to reconcile two different numbers for the same fit.

Two rules, and they are easy to confuse with the applicant list's.

**A profile is searchable only if its owner switched `visible_to_recruiters`
on.** It is off by default and nothing
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

from app.models import Preferences, Profile, ProfileSkill
from app.models.enums import Necessity
from app.services.analytics.alignment import (
    RequirementInput,
    RequirementResult,
    SkillInput,
    score_requirements,
)
from app.services.analytics.canonical import canonicalize
from app.services.scoring import load_aliases


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


def _search_terms(db: Session, canonical: set[str]) -> set[str]:
    """Every spelling a matching profile skill could be stored under.

    Profile skills are canonicalised on save, but the alias table can change
    afterwards, so a row saved last year may hold what is now an alias. Pull in
    every alias pointing at a wanted skill, or the SQL filter below would drop
    people who genuinely have it.
    """
    aliases = load_aliases(db)
    return canonical | {a for a, target in aliases.items() if target in canonical}


def search_candidates(db: Session, query: CandidateQuery) -> list[CandidateMatch]:
    """Rank the opted-in candidates who actually have the skills asked for.

    **Candidates who match none of the named skills are excluded**, and that is
    not the same decision as the one made on an applicant list. There, a
    low-scoring candidate stays because they chose to apply and dropping them
    on a number would be an automated rejection. Here, nobody is rejected:
    somebody with none of the skills a recruiter typed was never a candidate
    for this search, and returning them is not fairness, it is a search that
    does not work. Searching "airflow" and being handed people who have never
    touched it makes the whole feature useless at any real size.

    The filter runs in SQL against the indexed skill name, so a search on a
    table of ten thousand profiles loads the handful who match rather than all
    ten thousand.
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

    requirements = _requirements(query.skills)
    if requirements:
        wanted = _search_terms(db, {r.name for r in requirements})
        stmt = stmt.where(
            Profile.id.in_(
                select(ProfileSkill.profile_id).where(ProfileSkill.name.in_(wanted))
            )
        )

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
        match = CandidateMatch(
            profile=profile, score=round(fit, 1), requirements=results
        )
        # The SQL filter admits anyone holding one wanted skill; this drops the
        # ones the scorer then found no credit for at all — a skill claimed at
        # a level or a depth the search asked past.
        if not match.have and not match.partial:
            continue
        matches.append(match)

    # Score first, then depth in the skills actually asked for, then name.
    #
    # The depth tie-break earns its place: a requirement is either met or not,
    # so searching one skill scores a six-year expert and a two-year working
    # knowledge identically at 100. Both genuinely cover it — the score is
    # right — but handing the recruiter the shallower one first because their
    # name sorts earlier is not a ranking, it is an accident.
    #
    # It counts years in the *searched* skills, not total career length. A
    # fifteen-year manager who touched Airflow once should not outrank a
    # four-year engineer who has run it in production, and ranking on the
    # profile-wide figure would put them on top.
    matches.sort(
        key=lambda m: (
            -(m.score if m.score is not None else 0.0),
            -_depth_in(m),
            m.profile.full_name.lower(),
        )
    )
    return matches[: query.limit]


def _depth_in(match: CandidateMatch) -> float:
    """Years the candidate claims in the skills this search named.

    Falls back to total experience when the search named no skills, which is
    the only ordering an unscored search has to go on.
    """
    wanted = set(match.have) | set(match.partial)
    if not wanted:
        return match.profile.years_experience
    return sum(s.years for s in match.profile.skills if s.name in wanted)
