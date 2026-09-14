"""Shared enumerations.

These values are persisted and are consumed by the deterministic analytics
engine, so treat them as a stable contract: add members freely, but renaming or
removing one is a migration plus a scoring change.
"""

from enum import StrEnum


class Proficiency(StrEnum):
    """How well the candidate knows a skill."""

    NONE = "none"
    LEARNING = "learning"
    WORKING = "working"
    PROFICIENT = "proficient"
    EXPERT = "expert"


class Necessity(StrEnum):
    """How badly a job needs a requirement."""

    REQUIRED = "required"
    PREFERRED = "preferred"
    NICE_TO_HAVE = "nice_to_have"


class Coverage(StrEnum):
    """Result of matching one requirement against the profile."""

    HAVE = "have"
    PARTIAL = "partial"
    MISSING = "missing"


class SourceKind(StrEnum):
    """Where a job post came from."""

    TEXT = "text"
    URL = "url"
    PDF = "pdf"
    IMAGE = "image"


class ApplicationStatus(StrEnum):
    """Kanban columns, in pipeline order."""

    SAVED = "saved"
    APPLIED = "applied"
    SCREENING = "screening"
    INTERVIEWING = "interviewing"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


#: Statuses that represent forward motion, ordered. Used by the funnel analysis
#: to compute stage-to-stage conversion. Terminal states are excluded.
PIPELINE_ORDER: tuple[ApplicationStatus, ...] = (
    ApplicationStatus.SAVED,
    ApplicationStatus.APPLIED,
    ApplicationStatus.SCREENING,
    ApplicationStatus.INTERVIEWING,
    ApplicationStatus.OFFER,
)

#: Statuses where nothing further will happen.
TERMINAL_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {ApplicationStatus.OFFER, ApplicationStatus.REJECTED, ApplicationStatus.WITHDRAWN}
)


class RecommendationKind(StrEnum):
    """The three branches the career intelligence agent can point you down."""

    TAILOR_RESUME = "tailor_resume"
    LEARN_SKILL = "learn_skill"
    PREP_INTERVIEW = "prep_interview"
    APPLY_NOW = "apply_now"
    DROP = "drop"


class Role(StrEnum):
    """What an account is allowed to do.

    Checked by a dependency on every route rather than inferred from which
    tables a request touches — an authorization rule you have to reconstruct
    from query shapes is one nobody can audit.
    """

    STUDENT = "student"
    HR = "hr"
    ADMIN = "admin"


class PostingSource(StrEnum):
    """Where a job posting came from.

    Students see these as two sections: roles an employer posted here, and
    roles the ingestion pipeline found elsewhere. Same table, same scoring.
    """

    EMPLOYER = "employer"
    SOURCED = "sourced"


class PostingStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    CLOSED = "closed"


class InterviewKind(StrEnum):
    BEHAVIORAL = "behavioral"
    TECHNICAL = "technical"
    SYSTEM_DESIGN = "system_design"
    SCREENING = "screening"
