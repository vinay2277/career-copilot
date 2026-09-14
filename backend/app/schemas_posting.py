"""Request and response schemas for published postings.

Separate module from `schemas.py` so the platform surface and the personal
tracker's surface don't blur into one another as both grow.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import (
    ApplicationStatus,
    Necessity,
    PostingSource,
    PostingStatus,
)
from app.schemas import AlignmentOut

_orm = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- #
# Requirements
# --------------------------------------------------------------------------- #


class PostingRequirementIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    necessity: Necessity = Necessity.REQUIRED
    min_years: float = Field(default=0.0, ge=0, le=40)
    evidence: str | None = None


class PostingRequirementOut(BaseModel):
    model_config = _orm
    name: str
    necessity: Necessity
    min_years: float
    evidence: str | None


# --------------------------------------------------------------------------- #
# Creating and editing
# --------------------------------------------------------------------------- #


class PostingDraftIn(BaseModel):
    """What a recruiter submits to create or update a posting."""

    title: str = Field(min_length=1, max_length=300)
    description: str | None = None
    location: str | None = None
    remote: bool | None = None
    seniority: str | None = None
    salary_min: int | None = Field(default=None, ge=0)
    salary_max: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=8)
    industry: str | None = None
    company_size: str | None = None
    education: str | None = None
    certifications: list[str] = Field(default_factory=list)
    total_years_experience: float | None = Field(default=None, ge=0, le=60)
    closes_at: datetime | None = None
    requirements: list[PostingRequirementIn] = Field(default_factory=list)
    #: The text the requirements were read from, kept for re-extraction and for
    #: generating interview questions later.
    raw_text: str = ""


class PostingParseIn(BaseModel):
    """A pasted job description to be turned into a draft."""

    text: str = Field(min_length=120)


class PostingDraftOut(BaseModel):
    """An extracted draft, for the recruiter to check before publishing.

    Returned rather than saved directly, for the same reason the student-side
    ingestion does it: the validation agent's confidence is only worth having
    if something acts on it.
    """

    title: str
    company_name: str | None
    description: str | None
    location: str | None
    remote: bool | None
    seniority: str | None
    salary_min: int | None
    salary_max: int | None
    currency: str | None
    industry: str | None
    company_size: str | None
    education: str | None
    certifications: list[str]
    total_years_experience: float | None
    requirements: list[PostingRequirementOut]
    raw_text: str
    confidence: float
    unverified_fields: list[str]
    validation_notes: str


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #


class PostingOut(BaseModel):
    model_config = _orm
    id: int
    title: str
    company_name: str
    source: PostingSource
    status: PostingStatus
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
    source_url: str | None
    requirements: list[PostingRequirementOut]
    closes_at: datetime | None
    created_at: datetime


class BoardEntryOut(BaseModel):
    """One card on the student's job board."""

    posting: PostingOut
    alignment: AlignmentOut | None
    #: True once this student has applied — the button becomes a state.
    applied: bool
    application_status: ApplicationStatus | None


class BoardOut(BaseModel):
    """The board, split into the two sections a student sees.

    Two lists rather than one with a flag, because the frontend renders them as
    separate sections and the split is the product decision, not a filter.
    """

    from_employers: list[BoardEntryOut]
    sourced: list[BoardEntryOut]

    @property
    def total(self) -> int:
        return len(self.from_employers) + len(self.sourced)


class ApplyIn(BaseModel):
    cover_note: str | None = Field(default=None, max_length=4000)


class ApplicationOut(BaseModel):
    model_config = _orm
    id: int
    posting_id: int
    status: ApplicationStatus
    alignment_score: float | None
    alignment_detail: dict | None
    cover_note: str | None
    applied_at: datetime


class MyApplicationOut(BaseModel):
    """An application, with enough of the posting to render a row."""

    application: ApplicationOut
    posting: PostingOut


# --------------------------------------------------------------------------- #
# Recruiter views
# --------------------------------------------------------------------------- #


class PostingSummaryOut(BaseModel):
    """A recruiter's own posting, with its live counts."""

    posting: PostingOut
    application_count: int
    is_accepting: bool
