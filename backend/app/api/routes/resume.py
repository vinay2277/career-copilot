"""`/api/resume/*` — upload, ATS analysis, and job-specific tailoring."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.client import AgentError
from app.agents.resume import analyze_resume, tailor_resume
from app.api.deps import get_profile
from app.core.config import settings
from app.db.session import get_db
from app.models import JobPost, Profile, Resume, TailoredResume
from app.schemas import ResumeOut, TailoredResumeOut
from app.services.ingestion import parsers
from app.services.scoring import score_job

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


@router.post("", response_model=ResumeOut, status_code=status.HTTP_201_CREATED)
async def upload_resume(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> Resume:
    """Upload a resume (PDF or plain text) and analyze it immediately.

    Analysis runs on upload rather than on demand because the ATS score is the
    first thing the profile page shows, and a resume with no score looks broken.
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
    db.commit()
    db.refresh(resume)
    return resume


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
