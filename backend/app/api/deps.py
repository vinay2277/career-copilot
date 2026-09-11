"""Shared route dependencies."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Profile

#: Single-user for now. The column exists and every query filters on it, so
#: adding real auth means replacing this function rather than touching routes.
CURRENT_PROFILE_ID = 1


def get_profile(db: Session = Depends(get_db)) -> Profile:
    """The active profile, or a 404 telling the caller to create one."""
    profile = db.execute(
        select(Profile).where(Profile.id == CURRENT_PROFILE_ID)
    ).scalar_one_or_none()

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No profile yet. Create one at PUT /api/profile.",
        )
    return profile
