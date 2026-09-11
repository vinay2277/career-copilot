"""`/api/extract/*` — job ingestion.

Every route here returns an `ExtractionPreview` rather than a saved job. The
user confirms, then `POST /api/extract/confirm` persists it. That extra step
exists because the validation agent's confidence is only useful if something
acts on it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.agents.client import AgentError
from app.api.deps import get_profile
from app.core.config import settings
from app.db.session import get_db
from app.models import Application, JobPost, JobRequirement, Profile
from app.models.enums import ApplicationStatus, Necessity, SourceKind
from app.schemas import (
    ExtractionPreview,
    ExtractTextIn,
    ExtractUrlIn,
    JobOut,
)
from app.services.analytics.canonical import canonicalize
from app.services.ingestion import parsers
from app.services.ingestion.pipeline import ValidatedJob, ingest
from app.services.scoring import refresh_cached_score

router = APIRouter(prefix="/api/extract", tags=["extract"])


def _to_preview(result: ValidatedJob) -> ExtractionPreview:
    e = result.extracted
    return ExtractionPreview(
        title=e.title,
        company=e.company,
        location=e.location,
        remote=e.remote,
        seniority=e.seniority,
        salary_min=e.salary_min,
        salary_max=e.salary_max,
        currency=e.currency,
        industry=e.industry,
        company_size=e.company_size,
        description=e.description,
        requirements=[
            {
                "name": r.name,
                "necessity": _coerce_necessity(r.necessity),
                "min_years": r.min_years,
                "evidence": r.evidence,
            }
            for r in e.requirements
        ],
        source_kind=result.source_kind,
        source_url=result.source_url,
        raw_text=result.raw_text,
        confidence=result.report.confidence,
        unverified_fields=result.report.unverified_fields,
        contradicted_fields=result.report.contradicted_fields,
        validation_notes=result.report.notes,
        needs_confirmation=result.needs_confirmation,
    )


def _coerce_necessity(value: str) -> Necessity:
    """Map the agent's string onto the enum, defaulting to the strict reading.

    The extraction schema types `necessity` as a plain string so a slightly
    off-spec value doesn't fail the whole parse. An unrecognized value is
    treated as `required`: over-weighting a requirement makes a job look harder
    than it is, which is the safer error.
    """
    try:
        return Necessity(value.strip().lower())
    except (ValueError, AttributeError):
        return Necessity.REQUIRED


def _run(**kwargs) -> ExtractionPreview:
    """Run the pipeline, converting its failures into HTTP responses."""
    try:
        return _to_preview(ingest(**kwargs))
    except parsers.ParseError as e:
        # 422: the input itself was the problem, and the message says how to fix it.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        ) from e
    except AgentError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)
        ) from e


async def _read_upload(file: UploadFile) -> bytes:
    data = await file.read()
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File is larger than the {settings.max_upload_mb} MB limit.",
        )
    if not data:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="That file is empty.",
        )
    return data


@router.post("/text", response_model=ExtractionPreview)
def extract_from_text(payload: ExtractTextIn) -> ExtractionPreview:
    return _run(source_kind=SourceKind.TEXT, text=payload.text)


@router.post("/url", response_model=ExtractionPreview)
def extract_from_url(payload: ExtractUrlIn) -> ExtractionPreview:
    return _run(source_kind=SourceKind.URL, url=payload.url)


@router.post("/pdf", response_model=ExtractionPreview)
async def extract_from_pdf(file: UploadFile = File(...)) -> ExtractionPreview:
    data = await _read_upload(file)
    return _run(source_kind=SourceKind.PDF, file_bytes=data)


@router.post("/image", response_model=ExtractionPreview)
async def extract_from_image(file: UploadFile = File(...)) -> ExtractionPreview:
    data = await _read_upload(file)
    return _run(source_kind=SourceKind.IMAGE, file_bytes=data)


@router.post("/confirm", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def confirm_extraction(
    preview: ExtractionPreview,
    db: Session = Depends(get_db),
    profile: Profile = Depends(get_profile),
) -> JobPost:
    """Persist a confirmed extraction and open a `saved` application for it.

    The preview comes back from the client, which may have corrected fields the
    validator flagged — that round trip is the whole point of the confirm step.
    """
    job = JobPost(
        title=preview.title,
        company=preview.company or "Unknown",
        location=preview.location,
        remote=preview.remote,
        seniority=preview.seniority,
        salary_min=preview.salary_min,
        salary_max=preview.salary_max,
        currency=preview.currency,
        industry=preview.industry,
        company_size=preview.company_size,
        description=preview.description,
        source_kind=preview.source_kind,
        source_url=preview.source_url,
        raw_text=preview.raw_text,
        extraction_confidence=preview.confidence,
        unverified_fields=preview.unverified_fields,
        validation_notes=preview.validation_notes,
    )
    for r in preview.requirements:
        canonical = canonicalize(r.name)
        if not canonical:
            continue
        job.requirements.append(
            JobRequirement(
                name=canonical,
                necessity=r.necessity,
                min_years=r.min_years,
                evidence=r.evidence,
            )
        )

    db.add(job)
    db.flush()

    application = Application(
        job_id=job.id,
        profile_id=profile.id,
        status=ApplicationStatus.SAVED,
    )
    db.add(application)
    db.flush()
    # Seed the history so this application appears in the funnel from day one.
    _record_initial_event(db, application)

    refresh_cached_score(db, profile, application)
    db.commit()
    db.refresh(job)
    return job


def _record_initial_event(db: Session, application: Application) -> None:
    from app.models import StatusEvent

    db.add(
        StatusEvent(
            application_id=application.id,
            from_status=None,
            to_status=application.status,
            note="Job saved.",
        )
    )
