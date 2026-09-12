"""`/api/simulation/*` and `/api/skill-roi` — the counterfactual engines.

Both are pure computation over the scored board: no model calls, no writes.
They are the fastest endpoints in the app and the ones whose numbers the career
intelligence agent is forbidden from re-deriving.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_profile
from app.db.session import get_db
from app.models import Profile
from app.schemas import ScenarioIn, SimulationOut, SkillROIOut
from app.services.analytics.skill_roi import rank_skills
from app.services.analytics.what_if import Scenario, simulate
from app.services.scoring import (
    load_aliases,
    preferences_of,
    score_board,
    skills_of,
)

router = APIRouter(tags=["simulation"])


@router.get("/api/skill-roi", response_model=list[SkillROIOut])
def skill_roi(
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
    limit: int = Query(default=10, ge=1, le=50),
) -> list[SkillROIOut]:
    """Rank every skill gap by what learning it would buy."""
    board = score_board(db, profile)
    rois = rank_skills(
        jobs=board,
        skills=skills_of(profile),
        prefs=preferences_of(profile.preferences),
        aliases=load_aliases(db),
        limit=limit,
    )
    return [
        SkillROIOut(
            skill=r.skill,
            demand=r.demand,
            mean_gain=r.mean_gain,
            best_gain=r.best_gain,
            best_job_id=r.best_job_id,
            unlocks=r.unlocks,
            unlock_count=r.unlock_count,
            weighted_demand=r.weighted_demand,
        )
        for r in rois
    ]


@router.post("/api/simulation/what-if", response_model=SimulationOut)
def what_if(
    payload: ScenarioIn,
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> SimulationOut:
    """Re-score the board under a hypothetical profile. Persists nothing."""
    board = score_board(db, profile)
    result = simulate(
        jobs=board,
        skills=skills_of(profile),
        prefs=preferences_of(profile.preferences),
        scenario=Scenario(
            add_skills=payload.add_skills,
            add_at=payload.add_at,
            add_years=payload.add_years,
            remove_skills=payload.remove_skills,
            min_salary=payload.min_salary,
            remote_ok=payload.remote_ok,
            seniority=payload.seniority,
            locations=payload.locations,
        ),
        aliases=load_aliases(db),
    )

    return SimulationOut(
        mean_before=result.mean_before,
        mean_after=result.mean_after,
        mean_change=result.mean_change,
        in_reach_before=result.in_reach_before,
        in_reach_after=result.in_reach_after,
        deltas=[
            {
                "job_id": d.job_id,
                "title": d.title,
                "company": d.company,
                "before": d.before,
                "after": d.after,
                "change": d.change,
                "newly_in_reach": d.newly_in_reach,
                "fell_out_of_reach": d.fell_out_of_reach,
            }
            for d in result.deltas
        ],
    )
