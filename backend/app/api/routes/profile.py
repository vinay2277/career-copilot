"""`/api/profile` — the candidate's profile, skills, and preferences."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_profile
from app.db.session import get_db
from app.models import Application, Preferences, Profile, ProfileSkill
from app.schemas import ProfileIn, ProfileOut
from app.services.analytics.canonical import canonicalize
from app.services.scoring import load_aliases, refresh_cached_score

router = APIRouter(prefix="/api/profile", tags=["profile"])


@router.get("", response_model=ProfileOut)
def read_profile(profile: Profile = Depends(get_profile)) -> Profile:
    return profile


@router.put("", response_model=ProfileOut)
def upsert_profile(
    payload: ProfileIn,
    profile: Profile = Depends(get_profile),
    db: Session = Depends(get_db),
) -> Profile:
    """Replace the signed-in student's profile.

    A full replace rather than a patch: the profile page submits everything it
    has, and a partial update would make "I deleted a skill" indistinguishable
    from "I didn't mention that skill".

    The profile comes from the dependency, so this can only ever write to the
    caller's own — there is no id in the payload to tamper with.

    Every cached application score is recomputed afterwards, since a skill
    change silently invalidates all of them.
    """
    profile.full_name = payload.full_name
    profile.email = payload.email
    profile.headline = payload.headline
    profile.years_experience = payload.years_experience
    profile.career_goal = payload.career_goal
    profile.location = payload.location
    profile.phone = payload.phone
    profile.open_to_work = payload.open_to_work

    # Consent to appear in recruiter searches is a separate decision from
    # filling in a profile, so it is only changed when explicitly sent.
    if payload.visible_to_recruiters is not None:
        profile.visible_to_recruiters = payload.visible_to_recruiters

    # Skills are stored canonicalized so the scorer's exact-match lookup works
    # regardless of how the user typed them.
    profile.skills.clear()
    db.flush()
    for skill in payload.skills:
        canonical = canonicalize(skill.name)
        if not canonical:
            continue
        profile.skills.append(
            ProfileSkill(
                name=canonical,
                proficiency=skill.proficiency,
                years=skill.years,
            )
        )

    if payload.preferences is not None:
        if profile.preferences is None:
            profile.preferences = Preferences(profile_id=profile.id)
        for field, value in payload.preferences.model_dump().items():
            setattr(profile.preferences, field, value)

    db.flush()

    aliases = load_aliases(db)
    applications = list(
        db.execute(
            select(Application).where(Application.profile_id == profile.id)
        ).scalars()
    )
    for application in applications:
        refresh_cached_score(db, profile, application, aliases)

    db.commit()
    db.refresh(profile)
    return profile
