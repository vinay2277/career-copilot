"""The ingestion pipeline: raw input -> parsed text -> extraction -> validation.

One entry point, `ingest()`, which the `/api/extract/*` routes all funnel into.
The pipeline persists nothing — it returns a `ValidatedJob` and lets the route
decide whether to save, so a low-confidence extraction can be shown to the user
for confirmation before it lands in the database.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.agents.extraction import ExtractedJob, ExtractedRequirement, extract_job
from app.agents.validation import ValidationReport, validate_extraction
from app.models.enums import SourceKind
from app.services.analytics.canonical import canonicalize
from app.services.ingestion import parsers

logger = logging.getLogger(__name__)

#: Below this validator confidence, the route should ask the user to confirm
#: before saving rather than persisting silently.
CONFIRMATION_THRESHOLD = 0.7


@dataclass
class ValidatedJob:
    """An extraction plus the validator's verdict on it."""

    extracted: ExtractedJob
    report: ValidationReport
    raw_text: str
    source_kind: SourceKind
    source_url: str | None = None

    @property
    def needs_confirmation(self) -> bool:
        return (
            self.report.confidence < CONFIRMATION_THRESHOLD
            or bool(self.report.contradicted_fields)
        )


def _parse(
    *,
    text: str | None = None,
    url: str | None = None,
    file_bytes: bytes | None = None,
    source_kind: SourceKind,
) -> str:
    """Dispatch to the right parser for `source_kind`."""
    match source_kind:
        case SourceKind.TEXT:
            if text is None:
                raise parsers.ParseError("No text was provided.")
            return parsers.from_text(text)
        case SourceKind.URL:
            if not url:
                raise parsers.ParseError("No URL was provided.")
            return parsers.from_url(url)
        case SourceKind.PDF:
            if file_bytes is None:
                raise parsers.ParseError("No PDF was uploaded.")
            return parsers.from_pdf(file_bytes)
        case SourceKind.IMAGE:
            if file_bytes is None:
                raise parsers.ParseError("No image was uploaded.")
            return parsers.from_image(file_bytes)

    raise parsers.ParseError(f"Unsupported source kind: {source_kind}")


def _drop_rejected(
    requirements: list[ExtractedRequirement],
    rejected: list[int],
) -> list[ExtractedRequirement]:
    """Remove requirements whose evidence the validator threw out.

    Requirements are the one place the pipeline deletes rather than flags: a
    requirement with unsound evidence would feed the alignment scorer a
    fabricated skill, which silently corrupts every downstream number. A wrong
    salary is visible in the UI; a phantom requirement is not.
    """
    bad = {i for i in rejected if 0 <= i < len(requirements)}
    if bad:
        logger.info(
            "validator rejected %d/%d requirements: %s",
            len(bad),
            len(requirements),
            sorted(requirements[i].name for i in bad),
        )
    return [r for i, r in enumerate(requirements) if i not in bad]


def _dedupe(requirements: list[ExtractedRequirement]) -> list[ExtractedRequirement]:
    """Collapse requirements that canonicalize to the same skill.

    Postings repeat themselves — a skill in the summary and again in the bullet
    list. Left alone, the duplicate double-counts in the weighted average and
    quietly inflates that skill's influence on the score. On a collision the
    stricter entry wins.
    """
    from app.models.enums import Necessity
    from app.services.analytics.alignment import NECESSITY_WEIGHT

    def strictness(r: ExtractedRequirement) -> tuple[float, float]:
        try:
            weight = NECESSITY_WEIGHT[Necessity(r.necessity)]
        except ValueError:
            weight = 1.0  # unrecognized necessity: treat as required
        return (weight, r.min_years)

    best: dict[str, ExtractedRequirement] = {}
    for r in requirements:
        key = canonicalize(r.name)
        if not key:
            continue
        incumbent = best.get(key)
        if incumbent is None or strictness(r) > strictness(incumbent):
            best[key] = r

    # Sorted for determinism: the same posting must produce the same row order.
    return [best[k] for k in sorted(best)]


def ingest(
    *,
    source_kind: SourceKind,
    text: str | None = None,
    url: str | None = None,
    file_bytes: bytes | None = None,
) -> ValidatedJob:
    """Run the full pipeline for one job post.

    Two model calls: extraction, then validation. They are sequential by
    necessity — the validator audits the extractor's output — so expect this to
    take a few seconds. Callers should treat it as a foreground action with a
    spinner, not something to run on page load.
    """
    raw_text = _parse(
        text=text, url=url, file_bytes=file_bytes, source_kind=source_kind
    )

    extracted = extract_job(raw_text)
    report = validate_extraction(raw_text, extracted)

    kept = _drop_rejected(extracted.requirements, report.rejected_requirement_indices)
    extracted.requirements = _dedupe(kept)

    logger.info(
        "ingested %s job '%s' confidence=%.2f requirements=%d unverified=%s",
        source_kind.value,
        extracted.title,
        report.confidence,
        len(extracted.requirements),
        report.unverified_fields,
    )

    return ValidatedJob(
        extracted=extracted,
        report=report,
        raw_text=raw_text,
        source_kind=source_kind,
        source_url=url,
    )
