"""Application funnel: conversion, timing, and stagnation.

Reads transition history, not current status. Current status can tell you five
applications are "interviewing"; only the history can tell you that screening
takes you eleven days on average and that two of those five have been sitting
untouched for a month.

Pure functions over plain dataclasses, so the whole thing is testable without a
database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import median

from app.models.enums import PIPELINE_ORDER, TERMINAL_STATUSES, ApplicationStatus

#: Days a non-terminal application can sit in one stage before it is called
#: stagnant. Past this, the honest read is usually "no answer is the answer".
STAGNATION_DAYS: dict[ApplicationStatus, int] = {
    ApplicationStatus.SAVED: 14,
    ApplicationStatus.APPLIED: 21,
    ApplicationStatus.SCREENING: 14,
    ApplicationStatus.INTERVIEWING: 21,
}

DEFAULT_STAGNATION_DAYS = 21


@dataclass(frozen=True)
class Transition:
    to_status: ApplicationStatus
    occurred_at: datetime
    from_status: ApplicationStatus | None = None


@dataclass(frozen=True)
class ApplicationHistory:
    """One application's full transition history, oldest first."""

    application_id: int
    job_title: str
    company: str
    transitions: list[Transition]
    alignment_score: float | None = None

    @property
    def current_status(self) -> ApplicationStatus | None:
        return self.transitions[-1].to_status if self.transitions else None

    @property
    def last_change(self) -> datetime | None:
        return self.transitions[-1].occurred_at if self.transitions else None

    def reached(self, status: ApplicationStatus) -> bool:
        return any(t.to_status is status for t in self.transitions)

    def first_reached(self, status: ApplicationStatus) -> datetime | None:
        return next(
            (t.occurred_at for t in self.transitions if t.to_status is status), None
        )


@dataclass(frozen=True)
class StageStats:
    status: ApplicationStatus
    reached: int
    #: Share of applications that reached the *previous* stage and then this one.
    conversion_from_previous: float | None
    #: Median days spent in this stage, across applications that left it.
    median_days_in_stage: float | None


@dataclass(frozen=True)
class StagnantApplication:
    application_id: int
    job_title: str
    company: str
    status: ApplicationStatus
    days_idle: int
    threshold: int


@dataclass(frozen=True)
class FunnelReport:
    total: int
    stages: list[StageStats]
    stagnant: list[StagnantApplication]
    #: Share of submitted applications that produced any employer response.
    response_rate: float | None
    #: Share of submitted applications that reached an offer.
    offer_rate: float | None
    #: Median days from applying to first employer response.
    median_days_to_response: float | None

    def bottleneck(self) -> StageStats | None:
        """The stage losing the most candidates, ignoring stages nobody reached."""
        scored = [
            s
            for s in self.stages
            if s.conversion_from_previous is not None and s.reached > 0
        ]
        if not scored:
            return None
        return min(scored, key=lambda s: s.conversion_from_previous or 0.0)


#: Statuses that mean the employer actually engaged.
_RESPONDED = (
    ApplicationStatus.SCREENING,
    ApplicationStatus.INTERVIEWING,
    ApplicationStatus.OFFER,
)


def _days_in_stage(history: ApplicationHistory, status: ApplicationStatus) -> float | None:
    """Days between entering `status` and the next transition out of it."""
    for i, t in enumerate(history.transitions):
        if t.to_status is not status:
            continue
        if i + 1 >= len(history.transitions):
            return None  # still there; an open stage has no duration yet
        delta = history.transitions[i + 1].occurred_at - t.occurred_at
        return delta.total_seconds() / 86400.0
    return None


def _median_or_none(values: list[float]) -> float | None:
    return round(median(values), 1) if values else None


def analyze(
    histories: list[ApplicationHistory],
    now: datetime | None = None,
) -> FunnelReport:
    """Build the funnel report.

    `now` is injectable so tests are not clock-dependent.
    """
    now = now or datetime.now(UTC)
    total = len(histories)

    # --- Per-stage counts, conversion, and timing ---
    stages: list[StageStats] = []
    previous_reached: int | None = None
    for status in PIPELINE_ORDER:
        reached = sum(1 for h in histories if h.reached(status))

        conversion: float | None = None
        if previous_reached is not None and previous_reached > 0:
            conversion = round(reached / previous_reached, 3)

        durations = [
            d
            for d in (_days_in_stage(h, status) for h in histories)
            if d is not None
        ]
        stages.append(
            StageStats(
                status=status,
                reached=reached,
                conversion_from_previous=conversion,
                median_days_in_stage=_median_or_none(durations),
            )
        )
        previous_reached = reached

    # --- Stagnation ---
    stagnant: list[StagnantApplication] = []
    for h in histories:
        status = h.current_status
        last = h.last_change
        if status is None or last is None or status in TERMINAL_STATUSES:
            continue

        # Naive datetimes come out of SQLite; assume UTC rather than crash on a
        # mixed-awareness subtraction.
        if last.tzinfo is None:
            last = last.replace(tzinfo=UTC)

        threshold = STAGNATION_DAYS.get(status, DEFAULT_STAGNATION_DAYS)
        idle = (now - last).days
        if idle >= threshold:
            stagnant.append(
                StagnantApplication(
                    application_id=h.application_id,
                    job_title=h.job_title,
                    company=h.company,
                    status=status,
                    days_idle=idle,
                    threshold=threshold,
                )
            )
    stagnant.sort(key=lambda s: (-s.days_idle, s.application_id))

    # --- Headline rates, denominated in applications actually submitted ---
    submitted = [h for h in histories if h.reached(ApplicationStatus.APPLIED)]
    responded = [h for h in submitted if any(h.reached(s) for s in _RESPONDED)]
    offered = [h for h in submitted if h.reached(ApplicationStatus.OFFER)]

    response_rate = round(len(responded) / len(submitted), 3) if submitted else None
    offer_rate = round(len(offered) / len(submitted), 3) if submitted else None

    lags: list[float] = []
    for h in responded:
        applied_at = h.first_reached(ApplicationStatus.APPLIED)
        first_response = min(
            (t for s in _RESPONDED if (t := h.first_reached(s)) is not None),
            default=None,
        )
        if applied_at and first_response and first_response > applied_at:
            lags.append((first_response - applied_at).total_seconds() / 86400.0)

    return FunnelReport(
        total=total,
        stages=stages,
        stagnant=stagnant,
        response_rate=response_rate,
        offer_rate=offer_rate,
        median_days_to_response=_median_or_none(lags),
    )


def nudge_window(status: ApplicationStatus) -> timedelta:
    """How long to wait in `status` before a follow-up is reasonable."""
    return timedelta(days=STAGNATION_DAYS.get(status, DEFAULT_STAGNATION_DAYS))
