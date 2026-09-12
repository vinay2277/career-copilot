"""Tests for the application funnel analysis."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.models.enums import ApplicationStatus as S
from app.services.analytics.funnel import (
    ApplicationHistory,
    Transition,
    analyze,
)

NOW = datetime(2026, 6, 1, tzinfo=UTC)


def days_ago(n: int) -> datetime:
    return NOW - timedelta(days=n)


def history(
    app_id: int,
    *steps: tuple[S, int],
    title: str = "Engineer",
) -> ApplicationHistory:
    """Build a history from (status, days_ago) pairs, oldest first."""
    transitions: list[Transition] = []
    previous: S | None = None
    for status, ago in steps:
        transitions.append(
            Transition(to_status=status, occurred_at=days_ago(ago), from_status=previous)
        )
        previous = status
    return ApplicationHistory(
        application_id=app_id,
        job_title=title,
        company=f"Co {app_id}",
        transitions=transitions,
    )


# --------------------------------------------------------------------------- #
# Stage counts and conversion
# --------------------------------------------------------------------------- #


def test_reached_counts_use_history_not_current_status():
    """An application now at `offer` still counts as having reached `applied`."""
    h = history(1, (S.SAVED, 40), (S.APPLIED, 35), (S.SCREENING, 25), (S.OFFER, 5))
    report = analyze([h], now=NOW)

    reached = {s.status: s.reached for s in report.stages}
    assert reached[S.SAVED] == 1
    assert reached[S.APPLIED] == 1
    assert reached[S.SCREENING] == 1
    assert reached[S.OFFER] == 1


def test_conversion_is_relative_to_the_previous_stage():
    histories = [
        history(1, (S.SAVED, 40), (S.APPLIED, 35)),
        history(2, (S.SAVED, 40), (S.APPLIED, 35)),
        history(3, (S.SAVED, 40)),  # never applied
        history(4, (S.SAVED, 40)),
    ]
    report = analyze(histories, now=NOW)
    stages = {s.status: s for s in report.stages}
    assert stages[S.APPLIED].reached == 2
    assert stages[S.APPLIED].conversion_from_previous == 0.5  # 2 of 4 saved


def test_skipped_stages_do_not_inflate_later_conversion():
    """Going straight from applied to interviewing must not credit screening."""
    h = history(1, (S.SAVED, 40), (S.APPLIED, 30), (S.INTERVIEWING, 20))
    report = analyze([h], now=NOW)
    stages = {s.status: s for s in report.stages}
    assert stages[S.SCREENING].reached == 0
    assert stages[S.INTERVIEWING].reached == 1


def test_median_days_in_stage_ignores_the_open_stage():
    """A stage the application is still sitting in has no duration yet."""
    h = history(1, (S.SAVED, 30), (S.APPLIED, 20))
    report = analyze([h], now=NOW)
    stages = {s.status: s for s in report.stages}
    assert stages[S.SAVED].median_days_in_stage == 10.0
    assert stages[S.APPLIED].median_days_in_stage is None


# --------------------------------------------------------------------------- #
# Headline rates
# --------------------------------------------------------------------------- #


def test_rates_are_denominated_in_submitted_applications():
    """Saved-but-never-sent applications must not dilute the response rate."""
    histories = [
        history(1, (S.SAVED, 40), (S.APPLIED, 35), (S.SCREENING, 30)),
        history(2, (S.SAVED, 40), (S.APPLIED, 35)),
        history(3, (S.SAVED, 40)),  # never submitted
    ]
    report = analyze(histories, now=NOW)
    assert report.response_rate == 0.5  # 1 of 2 submitted, not 1 of 3


def test_offer_rate_counts_only_offers():
    histories = [
        history(1, (S.APPLIED, 40), (S.OFFER, 10)),
        history(2, (S.APPLIED, 40), (S.REJECTED, 10)),
    ]
    report = analyze(histories, now=NOW)
    assert report.offer_rate == 0.5


def test_no_submitted_applications_yields_null_rates():
    report = analyze([history(1, (S.SAVED, 5))], now=NOW)
    assert report.response_rate is None
    assert report.offer_rate is None


def test_median_days_to_response():
    histories = [
        history(1, (S.APPLIED, 40), (S.SCREENING, 30)),  # 10 days
        history(2, (S.APPLIED, 40), (S.SCREENING, 20)),  # 20 days
    ]
    report = analyze(histories, now=NOW)
    assert report.median_days_to_response == 15.0


# --------------------------------------------------------------------------- #
# Stagnation
# --------------------------------------------------------------------------- #


def test_idle_application_past_its_threshold_is_stagnant():
    """`applied` has a 21-day window; 30 days idle is past it."""
    report = analyze([history(1, (S.APPLIED, 30))], now=NOW)
    assert len(report.stagnant) == 1
    assert report.stagnant[0].days_idle == 30
    assert report.stagnant[0].status is S.APPLIED


def test_recent_application_is_not_stagnant():
    report = analyze([history(1, (S.APPLIED, 3))], now=NOW)
    assert report.stagnant == []


def test_terminal_statuses_are_never_stagnant():
    """A rejection from a year ago is closed, not stalled."""
    histories = [
        history(1, (S.APPLIED, 400), (S.REJECTED, 380)),
        history(2, (S.APPLIED, 400), (S.OFFER, 380)),
        history(3, (S.APPLIED, 400), (S.WITHDRAWN, 380)),
    ]
    report = analyze(histories, now=NOW)
    assert report.stagnant == []


def test_stagnant_list_is_sorted_by_idle_time():
    histories = [
        history(1, (S.APPLIED, 25)),
        history(2, (S.APPLIED, 60)),
        history(3, (S.APPLIED, 40)),
    ]
    report = analyze(histories, now=NOW)
    assert [s.application_id for s in report.stagnant] == [2, 3, 1]


def test_naive_timestamps_do_not_crash():
    """SQLite hands back naive datetimes; they're assumed UTC rather than fatal."""
    naive = ApplicationHistory(
        application_id=1,
        job_title="Engineer",
        company="Co",
        transitions=[
            Transition(to_status=S.APPLIED, occurred_at=datetime(2026, 4, 1))
        ],
    )
    report = analyze([naive], now=NOW)
    assert len(report.stagnant) == 1


# --------------------------------------------------------------------------- #
# Bottleneck
# --------------------------------------------------------------------------- #


def test_bottleneck_finds_the_weakest_transition():
    # 10 saved, 8 applied (80%), 2 screening (25%) — screening is the choke point.
    histories = [
        *(history(i, (S.SAVED, 60)) for i in range(1, 3)),
        *(history(i, (S.SAVED, 60), (S.APPLIED, 50)) for i in range(3, 9)),
        *(
            history(i, (S.SAVED, 60), (S.APPLIED, 50), (S.SCREENING, 40))
            for i in range(9, 11)
        ),
    ]
    report = analyze(histories, now=NOW)
    bottleneck = report.bottleneck()
    assert bottleneck is not None
    assert bottleneck.status is S.SCREENING


def test_bottleneck_is_none_with_no_data():
    assert analyze([], now=NOW).bottleneck() is None


def test_empty_input_is_safe():
    report = analyze([], now=NOW)
    assert report.total == 0
    assert report.stagnant == []
    assert all(s.reached == 0 for s in report.stages)
