"""Bridge between the ORM and the pure analytics layer.

`services/analytics/` deliberately knows nothing about SQLAlchemy — that is what
makes it testable without a database. This module is the only place that
translates between the two, so the seam stays in one file.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Application,
    JobPost,
    Preferences,
    Profile,
    SkillAlias,
)
from app.models.enums import Necessity, Proficiency
from app.services.analytics.alignment import (
    AlignmentResult,
    JobFacts,
    PreferenceInput,
    RequirementInput,
    SkillInput,
    score_alignment,
)
from app.services.analytics.funnel import ApplicationHistory, Transition
from app.services.analytics.skill_roi import ScoredJob


def load_aliases(db: Session) -> dict[str, str]:
    """Read the runtime alias overrides."""
    rows = db.execute(select(SkillAlias.alias, SkillAlias.canonical)).all()
    return dict(rows)


def skills_of(profile: Profile) -> list[SkillInput]:
    return [
        SkillInput(
            name=s.name,
            proficiency=Proficiency(s.proficiency),
            years=s.years,
        )
        for s in profile.skills
    ]


def preferences_of(prefs: Preferences | None) -> PreferenceInput:
    """Convert stored preferences, defaulting to an empty set if never saved.

    An empty `PreferenceInput` scores neutral rather than zero — see
    `score_preferences` — so a profile with no preferences yet is not punished.
    """
    if prefs is None:
        return PreferenceInput()
    return PreferenceInput(
        target_roles=list(prefs.target_roles or []),
        locations=list(prefs.locations or []),
        remote_ok=prefs.remote_ok,
        seniority=prefs.seniority,
        min_salary=prefs.min_salary,
        company_sizes=list(prefs.company_sizes or []),
        industries=list(prefs.industries or []),
    )


def requirements_of(job: JobPost) -> list[RequirementInput]:
    return [
        RequirementInput(
            name=r.name,
            necessity=Necessity(r.necessity),
            min_years=r.min_years,
        )
        for r in job.requirements
    ]


def facts_of(job: JobPost) -> JobFacts:
    return JobFacts(
        title=job.title,
        location=job.location,
        remote=job.remote,
        seniority=job.seniority,
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        industry=job.industry,
        company_size=job.company_size,
    )


def score_job(
    db: Session,
    profile: Profile,
    job: JobPost,
    aliases: dict[str, str] | None = None,
) -> AlignmentResult:
    """Score one job against one profile."""
    return score_alignment(
        requirements=requirements_of(job),
        skills=skills_of(profile),
        prefs=preferences_of(profile.preferences),
        job=facts_of(job),
        aliases=aliases if aliases is not None else load_aliases(db),
    )


def score_board(
    db: Session,
    profile: Profile,
    jobs: list[JobPost] | None = None,
) -> list[ScoredJob]:
    """Score the roles a student can act on, for the ROI and what-if engines.

    With no `jobs` given this reads the **open postings on the platform** — the
    same board the student applies from. It used to read their own pasted-in
    job tracker, which no longer exists on the student side: pasting a job
    found elsewhere is a recruiter's job now, and a student's world is the
    board.

    That is also the better question to answer. "Which skill unlocks the most
    roles I could apply to today" beats "the most roles I happened to paste in".

    Loads the alias table once and reuses it, since scoring a 50-role board
    otherwise means 50 identical queries.
    """
    aliases = load_aliases(db)
    if jobs is None:
        return _score_postings(db, profile, aliases)

    board: list[ScoredJob] = []
    for job in jobs:
        requirements = requirements_of(job)
        facts = facts_of(job)
        board.append(
            ScoredJob(
                job_id=job.id,
                title=job.title,
                company=job.company,
                requirements=requirements,
                facts=facts,
                baseline=score_alignment(
                    requirements,
                    skills_of(profile),
                    preferences_of(profile.preferences),
                    facts,
                    aliases,
                ),
            )
        )
    return board


def _score_postings(
    db: Session, profile: Profile, aliases: dict[str, str]
) -> list[ScoredJob]:
    """Score every open posting into the same shape a tracked job produced.

    `ScoredJob` is the analytics engines' input dataclass and neither of them
    knows or cares which table a role came from — which is what made swapping
    the source a change in one function rather than four.
    """
    from app.services.postings import open_postings

    board: list[ScoredJob] = []
    for posting in open_postings(db):
        requirements = [
            RequirementInput(
                name=r.name, necessity=r.necessity, min_years=r.min_years
            )
            for r in posting.requirements
        ]
        # Mirrors `facts_of` exactly. JobFacts carries only what the
        # preference half compares against — no company name, no currency.
        facts = JobFacts(
            title=posting.title,
            location=posting.location,
            remote=posting.remote,
            seniority=posting.seniority,
            salary_min=posting.salary_min,
            salary_max=posting.salary_max,
            industry=posting.industry,
            company_size=posting.company_size,
        )
        board.append(
            ScoredJob(
                job_id=posting.id,
                title=posting.title,
                company=posting.company_name,
                requirements=requirements,
                facts=facts,
                baseline=score_alignment(
                    requirements,
                    skills_of(profile),
                    preferences_of(profile.preferences),
                    facts,
                    aliases,
                ),
            )
        )
    return board


def refresh_cached_score(
    db: Session,
    profile: Profile,
    application: Application,
    aliases: dict[str, str] | None = None,
) -> float:
    """Recompute and store one application's cached alignment score.

    Called when the profile changes or a job is re-extracted. The cached value
    exists so the Kanban board doesn't re-score on every page load; it has to be
    invalidated explicitly, since nothing else would notice a profile edit.
    """
    result = score_job(db, profile, application.job, aliases)
    application.alignment_score = result.total
    return result.total


def histories_of(applications: list[Application]) -> list[ApplicationHistory]:
    """Convert applications into funnel-analysis input.

    An application with no recorded events gets a synthetic one from its current
    status, so rows created before event tracking existed still appear in the
    funnel instead of vanishing from the denominator.
    """
    histories: list[ApplicationHistory] = []
    for app in applications:
        if app.events:
            transitions = [
                Transition(
                    to_status=e.to_status,
                    occurred_at=e.occurred_at,
                    from_status=e.from_status,
                )
                for e in app.events
            ]
        else:
            transitions = [
                Transition(to_status=app.status, occurred_at=app.created_at)
            ]

        histories.append(
            ApplicationHistory(
                application_id=app.id,
                job_title=app.job.title,
                company=app.job.company,
                transitions=transitions,
                alignment_score=app.alignment_score,
            )
        )
    return histories


def histories_of_applications(applications) -> list[ApplicationHistory]:
    """Funnel input built from board applications rather than tracked jobs.

    Same dataclass, different table. The funnel engine never knew which one it
    was reading, which is what made moving the student side onto the board a
    change of adapter rather than a rewrite of the analysis.

    An application with no recorded events still appears, with one synthetic
    transition from its current status — rows created before the event log
    existed should stay in the denominator rather than quietly improving the
    conversion rate by leaving it.
    """
    histories: list[ApplicationHistory] = []
    for application in applications:
        if application.events:
            transitions = [
                Transition(
                    to_status=e.to_status,
                    occurred_at=e.occurred_at,
                    from_status=e.from_status,
                )
                for e in application.events
            ]
        else:
            transitions = [
                Transition(
                    to_status=application.status,
                    occurred_at=application.applied_at,
                )
            ]

        posting = application.posting
        histories.append(
            ApplicationHistory(
                application_id=application.id,
                job_title=posting.title if posting else "(role removed)",
                company=posting.company_name if posting else "",
                transitions=transitions,
                alignment_score=application.alignment_score,
            )
        )
    return histories
