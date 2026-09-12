"""Request and response schemas for the HTTP API.

Separate from the agent output schemas in `app/agents/` on purpose: those are a
contract with the model, these are a contract with the frontend, and letting one
drive the other couples a UI change to a prompt change.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    ApplicationStatus,
    Coverage,
    InterviewKind,
    Necessity,
    Proficiency,
    SourceKind,
)

_orm = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- #
# Profile
# --------------------------------------------------------------------------- #


class SkillIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    proficiency: Proficiency = Proficiency.WORKING
    years: float = Field(default=0.0, ge=0, le=60)


class SkillOut(SkillIn):
    model_config = _orm
    id: int


class PreferencesIn(BaseModel):
    target_roles: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    remote_ok: bool = True
    seniority: str | None = None
    min_salary: int | None = Field(default=None, ge=0)
    currency: str = "USD"
    company_sizes: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)


class PreferencesOut(PreferencesIn):
    model_config = _orm


class ProfileIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    email: str | None = None
    headline: str | None = None
    years_experience: float = Field(default=0.0, ge=0, le=60)
    career_goal: str | None = None
    skills: list[SkillIn] = Field(default_factory=list)
    preferences: PreferencesIn | None = None


class ProfileOut(BaseModel):
    model_config = _orm
    id: int
    full_name: str
    email: str | None
    headline: str | None
    years_experience: float
    career_goal: str | None
    skills: list[SkillOut]
    preferences: PreferencesOut | None


# --------------------------------------------------------------------------- #
# Resume
# --------------------------------------------------------------------------- #


class ResumeOut(BaseModel):
    model_config = _orm
    id: int
    filename: str
    ats_score: float | None
    strengths: list[str] | None
    gaps: list[str] | None
    analysis_notes: str | None
    is_primary: bool
    created_at: datetime


class ProfileUpdateOut(BaseModel):
    """What uploading a resume did to the profile.

    Returned rather than applied silently: the user should be able to see that
    their profile changed, and what to.
    """

    applied: bool
    summary: str
    field_changes: list[str] = Field(default_factory=list)
    skills_added: list[str] = Field(default_factory=list)
    skills_raised: list[str] = Field(default_factory=list)
    #: Named by the resume but already at or above that level on the profile.
    skills_unchanged: list[str] = Field(default_factory=list)
    #: Dropped for lack of a supporting quote in the resume.
    skills_rejected: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ResumeUploadOut(BaseModel):
    resume: ResumeOut
    profile_update: ProfileUpdateOut | None = None


class TailoredResumeOut(BaseModel):
    model_config = _orm
    id: int
    job_id: int
    content: str
    emphasized_skills: list[str]
    change_summary: str | None
    created_at: datetime


# --------------------------------------------------------------------------- #
# Extraction / ingestion
# --------------------------------------------------------------------------- #


class ExtractTextIn(BaseModel):
    text: str = Field(min_length=1)


class ExtractUrlIn(BaseModel):
    url: str = Field(min_length=1)


class RequirementOut(BaseModel):
    model_config = _orm
    name: str
    necessity: Necessity
    min_years: float
    evidence: str | None


class ExtractionPreview(BaseModel):
    """What the user confirms before a job is saved.

    Returned instead of a persisted job whenever validator confidence is low, so
    a shaky extraction never silently becomes a data point in the analytics.
    """

    title: str
    company: str | None
    location: str | None
    remote: bool | None
    seniority: str | None
    salary_min: int | None
    salary_max: int | None
    currency: str | None
    industry: str | None
    company_size: str | None
    description: str | None
    requirements: list[RequirementOut]

    #: Screening criteria, kept out of `requirements` so they never reach the
    #: scorer, the gap list, or a learning roadmap.
    education: str | None = None
    certifications: list[str] = Field(default_factory=list)
    total_years_experience: float | None = None

    source_kind: SourceKind
    source_url: str | None
    raw_text: str

    confidence: float
    unverified_fields: list[str]
    contradicted_fields: list[str]
    validation_notes: str
    needs_confirmation: bool


# --------------------------------------------------------------------------- #
# Jobs / opportunities
# --------------------------------------------------------------------------- #


class JobOut(BaseModel):
    model_config = _orm
    id: int
    title: str
    company: str
    location: str | None
    remote: bool | None
    seniority: str | None
    salary_min: int | None
    salary_max: int | None
    currency: str | None
    industry: str | None
    company_size: str | None
    description: str | None
    education: str | None
    certifications: list[str]
    total_years_experience: float | None
    source_kind: SourceKind
    source_url: str | None
    extraction_confidence: float
    unverified_fields: list[str]
    requirements: list[RequirementOut]
    created_at: datetime


class RequirementBreakdown(BaseModel):
    name: str
    necessity: Necessity
    coverage: Coverage
    weight: float
    credit: float
    reason: str


class FacetBreakdown(BaseModel):
    name: str
    matched: bool
    detail: str


class AlignmentOut(BaseModel):
    """A score plus its full derivation. The derivation is the point."""

    total: float
    requirements_fit: float
    preference_fit: float
    requirements: list[RequirementBreakdown]
    facets: list[FacetBreakdown]
    explanation: str


class OpportunityOut(BaseModel):
    """A job with its score and pipeline state — one card on the board."""

    job: JobOut
    alignment: AlignmentOut | None
    application_id: int | None
    status: ApplicationStatus | None
    applied_at: datetime | None
    deadline: datetime | None
    notes: str | None


class ApplicationCreate(BaseModel):
    job_id: int
    status: ApplicationStatus = ApplicationStatus.SAVED
    notes: str | None = None
    deadline: datetime | None = None


class ApplicationUpdate(BaseModel):
    status: ApplicationStatus | None = None
    notes: str | None = None
    deadline: datetime | None = None


# --------------------------------------------------------------------------- #
# Skill ROI / simulation
# --------------------------------------------------------------------------- #


class SkillROIOut(BaseModel):
    skill: str
    demand: int
    mean_gain: float
    best_gain: float
    best_job_id: int | None
    unlocks: list[int]
    unlock_count: int
    weighted_demand: float


class ScenarioIn(BaseModel):
    add_skills: list[str] = Field(default_factory=list)
    add_at: Proficiency = Proficiency.WORKING
    add_years: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Experience to credit added skills with. Omit to use whatever the "
            "tracked jobs actually ask for, which is what makes the result "
            "register against '3+ years of X' requirements."
        ),
    )
    remove_skills: list[str] = Field(default_factory=list)
    min_salary: int | None = None
    remote_ok: bool | None = None
    seniority: str | None = None
    locations: list[str] | None = None


class JobDeltaOut(BaseModel):
    job_id: int
    title: str
    company: str
    before: float
    after: float
    change: float
    newly_in_reach: bool
    fell_out_of_reach: bool


class SimulationOut(BaseModel):
    mean_before: float
    mean_after: float
    mean_change: float
    in_reach_before: int
    in_reach_after: int
    deltas: list[JobDeltaOut]


# --------------------------------------------------------------------------- #
# Analytics
# --------------------------------------------------------------------------- #


class StageOut(BaseModel):
    status: ApplicationStatus
    reached: int
    conversion_from_previous: float | None
    median_days_in_stage: float | None


class StagnantOut(BaseModel):
    application_id: int
    job_title: str
    company: str
    status: ApplicationStatus
    days_idle: int
    threshold: int


class FunnelOut(BaseModel):
    total: int
    stages: list[StageOut]
    stagnant: list[StagnantOut]
    response_rate: float | None
    offer_rate: float | None
    median_days_to_response: float | None
    bottleneck: StageOut | None


# --------------------------------------------------------------------------- #
# Action center
# --------------------------------------------------------------------------- #


class ActionOut(BaseModel):
    kind: str
    title: str
    rationale: str
    job_id: int | None
    skill: str | None
    priority: int
    estimated_effort: str | None


class GuidanceOut(BaseModel):
    headline: str
    actions: list[ActionOut]
    funnel_read: str | None
    missing_information: list[str]


# --------------------------------------------------------------------------- #
# Interview / learning
# --------------------------------------------------------------------------- #


class InterviewStartIn(BaseModel):
    job_id: int
    kind: InterviewKind = InterviewKind.BEHAVIORAL
    question_count: int = Field(default=5, ge=1, le=15)


class TurnOut(BaseModel):
    model_config = _orm
    id: int
    position: int
    question: str
    answer: str | None
    score: float | None
    feedback: str | None
    improvements: list[str] | None
    probes_skill: str | None


class InterviewSessionOut(BaseModel):
    model_config = _orm
    id: int
    job_id: int | None
    kind: InterviewKind
    overall_score: float | None
    summary: str | None
    created_at: datetime
    completed_at: datetime | None
    turns: list[TurnOut]


class AnswerIn(BaseModel):
    answer: str = Field(min_length=1)


class LearningStepOut(BaseModel):
    model_config = _orm
    id: int
    position: int
    title: str
    skill: str
    estimated_hours: float
    resource_url: str | None
    proof_of_work: str | None
    completed: bool


class LearningPathOut(BaseModel):
    model_config = _orm
    id: int
    title: str
    target_skills: list[str]
    rationale: str | None
    created_at: datetime
    steps: list[LearningStepOut]


class RoadmapRequestIn(BaseModel):
    #: How many top-ROI skills to build the roadmap around.
    skill_count: int = Field(default=3, ge=1, le=8)
    hours_per_week: float = Field(default=6.0, gt=0, le=60)
