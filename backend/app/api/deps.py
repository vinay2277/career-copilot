"""Shared route dependencies."""

from __future__ import annotations

import logging

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Profile

logger = logging.getLogger(__name__)

#: Single-user for now. The column exists and every query filters on it, so
#: adding real auth means replacing this function rather than touching routes.
CURRENT_PROFILE_ID = 1


def get_profile(db: Session = Depends(get_db)) -> Profile:
    """The active profile, created on first use if it isn't there yet.

    This used to 404 with "create one at PUT /api/profile", which made a fresh
    instance completely unusable: every route depends on this, so *everything*
    returned 404 — including the résumé upload, which is the one action that
    would have populated the profile in the first place. A new user was told to
    go and do the thing they were already trying to do.

    The profile is a singleton in this design, so "not yet created" isn't a
    meaningful state to model. Creating it here means the app opens to an empty
    form rather than an error, and the résumé upload works on a brand-new
    deployment.
    """
    profile = db.execute(
        select(Profile).where(Profile.id == CURRENT_PROFILE_ID)
    ).scalar_one_or_none()
    if profile is not None:
        return profile

    logger.info("No profile yet — creating the empty singleton.")
    profile = Profile(id=CURRENT_PROFILE_ID, full_name="")
    db.add(profile)
    try:
        db.commit()
    except IntegrityError:
        # Two requests raced to create it. Whoever lost re-reads the winner's
        # row rather than failing — which is easy to hit, since the frontend
        # fires several requests as soon as it loads.
        db.rollback()
        profile = db.execute(
            select(Profile).where(Profile.id == CURRENT_PROFILE_ID)
        ).scalar_one()

    db.refresh(profile)
    return profile
