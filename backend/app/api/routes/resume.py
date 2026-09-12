"""`/api/resume/*` — upload, ATS analysis, and job-specific tailoring."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.client import AgentError
from app.agents.profile_extraction import extract_profile
from app.agents.resume import analyze_resume, tailor_resume
from app.api.deps import get_profile
from app.core.config import settings
from app.db.session import get_db
from app.models import Application, JobPost, Profile, Resume, TailoredResume
from app.schemas import (
    ProfileUpdateOut,
    ResumeOut,
    ResumeUploadOut,
    TailoredResumeOut,
)
from app.services.ingestion import parsers
from app.services.profile_merge import merge_resume_into_profile
from app.services.scoring import load_aliases, refresh_cached_score, score_job

router = APIRouter(prefix="/api/resume", tags=["resume"])


def _primary_resume(db: Session, profile: Profile) -> Resume:
    resume = db.execute(
        select(Resume)
        .where(Resume.profile_id == profile.id, Resume.is_primary.is_(True))
        .order_by(Resume.created_at.desc())
    ).scalars().first()

    if resume is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No primary resume on file. Upload one at POST /api/resume.",
        )
    return resume


@router.get("", response_model=list[ResumeOut])
def list_resumes(
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> list[Resume]:
    return list(
        db.execute(
            select(Resume)
            .where(Resume.profile_id == profile.id)
            .order_by(Resume.created_at.desc())
        ).scalars()
    )


@router.post("", response_model=ResumeUploadOut, status_code=status.HTTP_201_CREATED)
async def upload_resume(
    file: UploadFile = File(...),
    update_profile: bool = Query(
        default=True,
        description=(
            "Read the candidate's details out of the resume and merge them into "
            "the profile. The merge only ever adds a skill or raises its level, "
            "so it cannot overwrite a correction made by hand."
        ),
    ),
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> ResumeUploadOut:
    """Upload a resume, analyze it, and populate the profile from it.

    Three things happen, in order, and each is allowed to fail without losing
    the upload:

    1. The file is parsed to text. A failure here is fatal — there is nothing
       to store.
    2. The profile is extracted and merged in. This is what makes uploading a
       resume actually fill in the profile instead of just scoring it.
    3. The resume is scored for ATS readability.

    Both model calls are guarded: an unreachable model must not cost the user
    their file.
    """
    data = await file.read()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File is larger than the {settings.max_upload_mb} MB limit.",
        )

    name = (file.filename or "resume").lower()
    try:
        if name.endswith(".pdf"):
            text = parsers.from_pdf(data)
        else:
            text = parsers.from_text(data.decode("utf-8", errors="replace"))
    except parsers.ParseError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e

    resume = Resume(
        profile_id=profile.id,
        filename=file.filename or "resume",
        raw_text=text,
        is_primary=True,
    )

    # Any earlier resume stops being primary. Exactly one primary at a time
    # keeps the tailoring endpoint unambiguous.
    for existing in db.execute(
        select(Resume).where(
            Resume.profile_id == profile.id, Resume.is_primary.is_(True)
        )
    ).scalars():
        existing.is_primary = False

    try:
        analysis = analyze_resume(text)
        resume.ats_score = analysis.ats_score
        resume.strengths = analysis.strengths
        resume.gaps = analysis.gaps
        resume.analysis_notes = analysis.notes
    except AgentError:
        # Keep the upload. An un-analyzed resume is still usable for tailoring,
        # and losing the file because the model was unreachable would be worse.
        resume.analysis_notes = "Analysis unavailable — the model call failed."

    db.add(resume)
    db.flush()

    profile_update: ProfileUpdateOut | None = None
    if update_profile:
        profile_update = _populate_profile(db, profile, text)

    db.commit()
    db.refresh(resume)
    return ResumeUploadOut(
        resume=ResumeOut.model_validate(resume), profile_update=profile_update
    )


def _populate_profile(
    db: Session, profile: Profile, resume_text: str
) -> ProfileUpdateOut:
    """Extract the profile from resume text and merge it in.

    Every cached application score is refreshed afterwards: new skills change
    the alignment of every job on the board, and nothing else would notice.
    """
    try:
        extracted = extract_profile(resume_text)
    except AgentError as e:
        return ProfileUpdateOut(
            applied=False,
            summary=f"Could not read the profile from this resume: {e}",
        )

    changes = merge_resume_into_profile(profile, extracted)
    db.flush()

    if changes.skills:
        aliases = load_aliases(db)
        applications = list(
            db.execute(
                select(Application).where(Application.profile_id == profile.id)
            ).scalars()
        )
        for application in applications:
            refresh_cached_score(db, profile, application, aliases)

    return ProfileUpdateOut(
        applied=changes.touched,
        summary=changes.summary(),
        field_changes=[c.describe() for c in changes.fields],
        skills_added=[c.name for c in changes.skills if c.is_new],
        skills_raised=[c.describe() for c in changes.skills if not c.is_new],
        skills_unchanged=changes.unchanged_skills,
        skills_rejected=changes.rejected_skills,
        education=extracted.education,
        certifications=extracted.certifications,
        notes=changes.notes,
    )


@router.post("/{resume_id}/to-profile", response_model=ProfileUpdateOut)
def reapply_to_profile(
    resume_id: int,
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> ProfileUpdateOut:
    """Re-read a stored resume into the profile.

    Useful after editing the profile by hand, or to re-run extraction on an
    older resume. Safe to repeat: the merge never lowers a level or removes a
    skill, so running it twice is a no-op the second time.
    """
    resume = db.get(Resume, resume_id)
    if resume is None or resume.profile_id != profile.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such resume.")

    result = _populate_profile(db, profile, resume.raw_text)
    db.commit()
    return result


@router.post("/{resume_id}/reanalyze", response_model=ResumeOut)
def reanalyze(
    resume_id: int,
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> Resume:
    """Re-run analysis on a stored resume."""
    resume = db.get(Resume, resume_id)
    if resume is None or resume.profile_id != profile.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such resume.")

    try:
        analysis = analyze_resume(resume.raw_text)
    except AgentError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e

    resume.ats_score = analysis.ats_score
    resume.strengths = analysis.strengths
    resume.gaps = analysis.gaps
    resume.analysis_notes = analysis.notes
    db.commit()
    db.refresh(resume)
    return resume


@router.post(
    "/tailor/{job_id}",
    response_model=TailoredResumeOut,
    status_code=status.HTTP_201_CREATED,
)
def tailor_for_job(
    job_id: int,
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> TailoredResume:
    """Rewrite the primary resume for one job.

    The alignment scorer's missing-requirement list is passed to the agent so it
    knows which gaps are genuine and must not be written around — the prompt
    returns those as `unaddressable_gaps` rather than papering over them.
    """
    job = db.get(JobPost, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such job.")

    resume = _primary_resume(db, profile)
    alignment = score_job(db, profile, job)
    missing = [r.name for r in alignment.missing]

    try:
        draft = tailor_resume(
            resume_text=resume.raw_text,
            job_text=job.raw_text,
            missing_skills=missing,
        )
    except AgentError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e

    summary = draft.change_summary
    if draft.unaddressable_gaps:
        summary += (
            "\n\nNot addressed (no supporting experience in the source resume): "
            + ", ".join(draft.unaddressable_gaps)
        )

    tailored = TailoredResume(
        profile_id=profile.id,
        job_id=job.id,
        source_resume_id=resume.id,
        content=draft.content,
        emphasized_skills=draft.emphasized_skills,
        change_summary=summary,
    )
    db.add(tailored)
    db.commit()
    db.refresh(tailored)
    return tailored


@router.get("/tailored/{job_id}", response_model=list[TailoredResumeOut])
def list_tailored(
    job_id: int,
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> list[TailoredResume]:
    return list(
        db.execute(
            select(TailoredResume)
            .where(
                TailoredResume.profile_id == profile.id,
                TailoredResume.job_id == job_id,
            )
            .order_by(TailoredResume.created_at.desc())
        ).scalars()
    )
