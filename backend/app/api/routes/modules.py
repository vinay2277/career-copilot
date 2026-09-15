"""`/api/modules/*` — the twelve-module Gen AI course.

Costs nothing to run. The content is fixed and the checks are fixed questions
with fixed answers, so no route here calls a model — which is why the whole tab
carries the ordinary API rate limit rather than the AI one.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_profile
from app.db.session import get_db
from app.models import Profile
from app.services import learning_modules

router = APIRouter(prefix="/api/modules", tags=["modules"])


class ModuleRowOut(BaseModel):
    slug: str
    position: int
    title: str
    summary: str
    minutes: int
    objectives: list[str]
    question_count: int
    pass_mark: int
    locked: bool
    passed: bool
    best_score: int
    attempts: int
    completed_at: datetime | None


class QuestionOut(BaseModel):
    """A question as the student sees it before answering.

    No `answer` field, deliberately. The correct index exists on the same
    object in the curriculum and is only ever added by the grading response.
    """

    index: int
    prompt: str
    options: list[str]


class ModuleDetailOut(BaseModel):
    slug: str
    position: int
    title: str
    summary: str
    minutes: int
    objectives: list[str]
    body: str
    pass_mark: int
    questions: list[QuestionOut]
    passed: bool
    best_score: int
    attempts: int


class AttemptIn(BaseModel):
    #: Question index -> chosen option index. A missing question is wrong.
    answers: dict[int, int] = Field(default_factory=dict)


class QuestionResultOut(BaseModel):
    index: int
    chosen: int | None
    correct_option: int
    correct: bool
    explanation: str


class UnlockedOut(BaseModel):
    slug: str
    position: int
    title: str


class AttemptOut(BaseModel):
    slug: str
    score: int
    total: int
    pass_mark: int
    passed: bool
    #: True when this attempt failed but an earlier one passed — the pass
    #: stands, and the UI should say so rather than implying it was lost.
    already_passed: bool
    results: list[QuestionResultOut]
    unlocked_module: UnlockedOut | None


@router.get("", response_model=list[ModuleRowOut])
def list_modules(
    db: Session = Depends(get_db), profile: Profile = Depends(get_profile)
) -> list[dict]:
    """Every module with its state. Carries no question text."""
    return learning_modules.overview(db, profile)


@router.get("/{slug}", response_model=ModuleDetailOut)
def read_module(
    slug: str,
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> dict:
    """One module's material, if it is unlocked.

    The lock is enforced here rather than only in the UI. A 403 with the reason
    is more useful than a 404 — the student has not found a missing page, they
    have arrived somewhere they can reach by finishing the previous module.
    """
    try:
        return learning_modules.read(db, profile, slug)
    except learning_modules.ModuleError as e:
        code = (
            status.HTTP_404_NOT_FOUND
            if "No such module" in str(e)
            else status.HTTP_403_FORBIDDEN
        )
        raise HTTPException(code, str(e)) from e


@router.post("/{slug}/attempt", response_model=AttemptOut)
def attempt_module(
    slug: str,
    payload: AttemptIn,
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> dict:
    """Grade an attempt and return what was right, with the reasoning."""
    try:
        return learning_modules.attempt(db, profile, slug, payload.answers)
    except learning_modules.ModuleError as e:
        code = (
            status.HTTP_404_NOT_FOUND
            if "No such module" in str(e)
            else status.HTTP_403_FORBIDDEN
        )
        raise HTTPException(code, str(e)) from e
