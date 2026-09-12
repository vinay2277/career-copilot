"""`/api/learning/*` — roadmaps built from the skill ROI ranking."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.client import AgentError
from app.agents.learning import build_roadmap
from app.api.deps import get_profile
from app.db.session import get_db
from app.models import LearningPath, LearningStep, Profile
from app.schemas import LearningPathOut, RoadmapRequestIn
from app.services.analytics.skill_roi import rank_skills
from app.services.context import render_skill_roi
from app.services.scoring import (
    load_aliases,
    preferences_of,
    score_board,
    skills_of,
)

router = APIRouter(prefix="/api/learning", tags=["learning"])


@router.get("", response_model=list[LearningPathOut])
def list_paths(
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> list[LearningPath]:
    return list(
        db.execute(
            select(LearningPath)
            .where(LearningPath.profile_id == profile.id)
            .order_by(LearningPath.created_at.desc())
        ).scalars()
    )


@router.post(
    "/roadmap", response_model=LearningPathOut, status_code=status.HTTP_201_CREATED
)
def generate_roadmap(
    payload: RoadmapRequestIn,
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> LearningPath:
    """Build a roadmap around the top-ROI skill gaps.

    Which skills to target is decided by the deterministic ROI engine, not the
    agent — the agent only sequences them and sizes the steps.
    """
    board = score_board(db, profile)
    rois = rank_skills(
        jobs=board,
        skills=skills_of(profile),
        prefs=preferences_of(profile.preferences),
        aliases=load_aliases(db),
        limit=payload.skill_count,
    )
    if not rois:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No skill gaps to plan around — add some jobs to the board first.",
        )

    try:
        roadmap = build_roadmap(
            skill_payoffs=render_skill_roi(rois),
            current_skills=[s.name for s in profile.skills],
            hours_per_week=payload.hours_per_week,
        )
    except AgentError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e

    rationale = roadmap.rationale
    if roadmap.caveats:
        rationale += "\n\nCaveats:\n" + "\n".join(f"- {c}" for c in roadmap.caveats)

    path = LearningPath(
        profile_id=profile.id,
        title=roadmap.title,
        target_skills=roadmap.target_skills,
        rationale=rationale,
    )
    for i, step in enumerate(roadmap.steps):
        path.steps.append(
            LearningStep(
                position=i,
                title=step.title,
                skill=step.skill,
                estimated_hours=step.estimated_hours,
                resource_url=step.resource_url,
                proof_of_work=step.proof_of_work,
            )
        )

    db.add(path)
    db.commit()
    db.refresh(path)
    return path


@router.patch("/steps/{step_id}", response_model=LearningPathOut)
def toggle_step(
    step_id: int,
    completed: bool,
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> LearningPath:
    """Tick a step off. Returns the whole path so the UI can redraw progress."""
    step = db.get(LearningStep, step_id)
    if step is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such step.")

    path = db.get(LearningPath, step.path_id)
    if path is None or path.profile_id != profile.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such step.")

    step.completed = completed
    db.commit()
    db.refresh(path)
    return path


@router.delete("/{path_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_path(
    path_id: int,
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> None:
    path = db.get(LearningPath, path_id)
    if path is None or path.profile_id != profile.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such path.")
    db.delete(path)
    db.commit()
