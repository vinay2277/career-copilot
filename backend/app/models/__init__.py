"""ORM models.

Every model is imported here so that `Base.metadata` is fully populated by the
time Alembic autogenerate or `create_all` runs. Importing a submodule directly
without going through this package will produce an incomplete metadata graph.
"""

from app.models.account import Account, HRMember, Organization
from app.models.application import Application, StatusEvent
from app.models.coaching import (
    InterviewSession,
    InterviewTurn,
    LearningPath,
    LearningStep,
    TailoredResume,
)
from app.models.enums import (
    PIPELINE_ORDER,
    TERMINAL_STATUSES,
    ApplicationStatus,
    Coverage,
    InterviewKind,
    Necessity,
    PostingSource,
    PostingStatus,
    Proficiency,
    RecommendationKind,
    Role,
    SourceKind,
)
from app.models.job import JobPost, JobRequirement, SkillAlias
from app.models.profile import Preferences, Profile, ProfileSkill, Resume

__all__ = [
    "PIPELINE_ORDER",
    "TERMINAL_STATUSES",
    "Account",
    "Application",
    "ApplicationStatus",
    "Coverage",
    "HRMember",
    "InterviewKind",
    "InterviewSession",
    "InterviewTurn",
    "JobPost",
    "JobRequirement",
    "LearningPath",
    "LearningStep",
    "Necessity",
    "Organization",
    "PostingSource",
    "PostingStatus",
    "Preferences",
    "Proficiency",
    "Profile",
    "ProfileSkill",
    "RecommendationKind",
    "Resume",
    "Role",
    "SkillAlias",
    "SourceKind",
    "StatusEvent",
    "TailoredResume",
]
