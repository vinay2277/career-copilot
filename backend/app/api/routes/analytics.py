"""`/api/analytics/*` — funnel statistics and the action center."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.career_intelligence import recommend
from app.agents.client import AgentError
from app.api.deps import get_profile
from app.core.security import rate_limit_ai
from app.db.session import get_db
from app.models import Application, Profile
from app.schemas import FunnelOut, GuidanceOut, StageOut
from app.services.analytics import funnel as funnel_engine
from app.services.analytics.skill_roi import rank_skills
from app.services.context import build_context
from app.services.scoring import (
    histories_of,
    load_aliases,
    preferences_of,
    score_board,
    skills_of,
)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _stage_out(stage: funnel_engine.StageStats) -> StageOut:
    return StageOut(
        status=stage.status,
        reached=stage.reached,
        conversion_from_previous=stage.conversion_from_previous,
        median_days_in_stage=stage.median_days_in_stage,
    )


def _build_funnel(db: Session, profile: Profile) -> funnel_engine.FunnelReport:
    applications = list(
        db.execute(
            select(Application).where(Application.profile_id == profile.id)
        ).scalars()
    )
    return funnel_engine.analyze(histories_of(applications))


@router.get("/funnel", response_model=FunnelOut)
def read_funnel(
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> FunnelOut:
    """Conversion rates, stage timings, and stagnant applications."""
    report = _build_funnel(db, profile)
    bottleneck = report.bottleneck()
    return FunnelOut(
        total=report.total,
        stages=[_stage_out(s) for s in report.stages],
        stagnant=[
            {
                "application_id": s.application_id,
                "job_title": s.job_title,
                "company": s.company,
                "status": s.status,
                "days_idle": s.days_idle,
                "threshold": s.threshold,
            }
            for s in report.stagnant
        ],
        response_rate=report.response_rate,
        offer_rate=report.offer_rate,
        median_days_to_response=report.median_days_to_response,
        bottleneck=_stage_out(bottleneck) if bottleneck else None,
    )


@router.get(
    "/action-center",
    response_model=GuidanceOut,
    dependencies=[Depends(rate_limit_ai)],
)
def action_center(
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> GuidanceOut:
    """Ranked next actions from the career intelligence agent.

    Every figure the agent sees is computed here first — the scored board, the
    ROI ranking, the funnel — and the prompt forbids it from deriving its own.
    This is the one endpoint that makes a model call on a plain GET, so the UI
    should show it behind an explicit refresh rather than on navigation.
    """
    board = score_board(db, profile)
    aliases = load_aliases(db)
    rois = rank_skills(
        jobs=board,
        skills=skills_of(profile),
        prefs=preferences_of(profile.preferences),
        aliases=aliases,
        limit=8,
    )
    report = _build_funnel(db, profile)

    context = build_context(profile, board, rois, report)

    try:
        guidance = recommend(context)
    except AgentError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e

    return GuidanceOut(
        headline=guidance.headline,
        actions=[
            {
                "kind": a.kind,
                "title": a.title,
                "rationale": a.rationale,
                "job_id": a.job_id,
                "skill": a.skill,
                "priority": a.priority,
                "estimated_effort": a.estimated_effort,
            }
            for a in sorted(guidance.actions, key=lambda a: a.priority)
        ],
        funnel_read=guidance.funnel_read,
        missing_information=guidance.missing_information,
    )


@router.get("/context")
def read_context(
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> dict[str, str]:
    """The exact text the action center would send to the agent.

    Exposed for debugging: when the advice looks wrong, the first question is
    always whether the numbers going in were right.
    """
    board = score_board(db, profile)
    rois = rank_skills(
        jobs=board,
        skills=skills_of(profile),
        prefs=preferences_of(profile.preferences),
        aliases=load_aliases(db),
        limit=8,
    )
    report = _build_funnel(db, profile)
    return {"context": build_context(profile, board, rois, report)}
