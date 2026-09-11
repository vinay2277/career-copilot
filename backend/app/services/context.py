"""Render the analytics output as text for the career intelligence agent.

The agent reasons better over a compact readable table than over nested JSON,
and nothing downstream parses this — it exists only to be read. Keeping the
rendering here also means the exact figures the agent saw can be logged and
replayed when its advice looks wrong.
"""

from __future__ import annotations

from app.models import Profile
from app.services.analytics.funnel import FunnelReport
from app.services.analytics.skill_roi import UNLOCK_THRESHOLD, ScoredJob, SkillROI

#: Jobs shown to the agent, best-aligned first. A long tail of 30% matches adds
#: tokens without changing the advice.
MAX_JOBS_IN_CONTEXT = 20

#: Below this many submitted applications, funnel rates are noise. The agent is
#: told the count so it can say so rather than reading a trend into four rows.
MIN_SAMPLE_FOR_FUNNEL = 10


def render_profile(profile: Profile) -> str:
    skills = sorted(
        profile.skills, key=lambda s: (-s.years, s.name)
    )
    skill_lines = (
        "\n".join(
            f"  - {s.name} ({s.proficiency}, {s.years:g}y)" for s in skills
        )
        or "  (none recorded)"
    )

    prefs = profile.preferences
    if prefs is None:
        pref_lines = "  (none set)"
    else:
        pref_lines = "\n".join(
            line
            for line in (
                f"  roles: {', '.join(prefs.target_roles)}"
                if prefs.target_roles
                else "",
                f"  locations: {', '.join(prefs.locations)}"
                if prefs.locations
                else "",
                f"  remote acceptable: {'yes' if prefs.remote_ok else 'no'}",
                f"  seniority: {prefs.seniority}" if prefs.seniority else "",
                f"  minimum salary: {prefs.min_salary:,} {prefs.currency}"
                if prefs.min_salary
                else "",
                f"  industries: {', '.join(prefs.industries)}"
                if prefs.industries
                else "",
            )
            if line
        )

    goal = profile.career_goal or "(not stated)"
    return (
        f"## Candidate\n"
        f"{profile.full_name}, {profile.years_experience:g} years experience\n"
        f"Stated goal: {goal}\n\n"
        f"Skills:\n{skill_lines}\n\n"
        f"Preferences:\n{pref_lines}"
    )


def render_board(board: list[ScoredJob]) -> str:
    """The scored job board, best first."""
    if not board:
        return "## Job board\n(empty — no jobs tracked yet)"

    ranked = sorted(board, key=lambda j: -j.baseline.total)[:MAX_JOBS_IN_CONTEXT]
    lines = [
        "## Job board (alignment scores are pre-computed; use as given)",
        f"In-reach threshold is {UNLOCK_THRESHOLD:g}.",
        "",
    ]
    for job in ranked:
        missing = [r.name for r in job.baseline.missing]
        partial = [r.name for r in job.baseline.partial]
        lines.append(
            f"- job_id={job.job_id} | {job.title} at {job.company} "
            f"| alignment {job.baseline.total:.1f} "
            f"(requirements {job.baseline.requirements_fit:.0f}, "
            f"preferences {job.baseline.preference_fit:.0f})"
        )
        if missing:
            lines.append(f"    missing: {', '.join(missing)}")
        if partial:
            lines.append(f"    partial: {', '.join(partial)}")

    if len(board) > MAX_JOBS_IN_CONTEXT:
        lines.append(f"  (+{len(board) - MAX_JOBS_IN_CONTEXT} lower-scoring jobs omitted)")
    return "\n".join(lines)


def render_skill_roi(rois: list[SkillROI]) -> str:
    """The skill ROI ranking. This is the table the agent must not re-derive."""
    if not rois:
        return "## Skill payoffs\n(no gaps found, or no jobs to measure against)"

    lines = [
        "## Skill payoffs (pre-computed counterfactuals; use as given)",
        "Each row: what learning that one skill to working proficiency would do",
        "to the alignment scores above.",
        "",
        "  skill | asked by | unlocks | mean gain | best single gain",
    ]
    for r in rois:
        lines.append(
            f"  {r.skill} | {r.demand} jobs | {r.unlock_count} jobs "
            f"| +{r.mean_gain:.1f} pts | +{r.best_gain:.1f} pts"
            + (f" (job_id={r.best_job_id})" if r.best_job_id else "")
        )
    return "\n".join(lines)


def render_funnel(report: FunnelReport) -> str:
    """The funnel report, with an explicit note when the sample is too small."""
    lines = ["## Application funnel (pre-computed; use as given)"]

    submitted = next(
        (s.reached for s in report.stages if s.status.value == "applied"), 0
    )
    if submitted < MIN_SAMPLE_FOR_FUNNEL:
        lines.append(
            f"Only {submitted} applications submitted so far — below the "
            f"{MIN_SAMPLE_FOR_FUNNEL} needed to read rates meaningfully. "
            "Say so rather than drawing conclusions."
        )
        lines.append("")

    lines.append(f"Tracked applications: {report.total}")
    for stage in report.stages:
        conv = (
            f", {stage.conversion_from_previous:.0%} from previous stage"
            if stage.conversion_from_previous is not None
            else ""
        )
        dwell = (
            f", median {stage.median_days_in_stage:g}d in stage"
            if stage.median_days_in_stage is not None
            else ""
        )
        lines.append(f"  {stage.status.value}: {stage.reached} reached{conv}{dwell}")

    if report.response_rate is not None:
        lines.append(f"Response rate: {report.response_rate:.0%} of submitted")
    if report.offer_rate is not None:
        lines.append(f"Offer rate: {report.offer_rate:.0%} of submitted")
    if report.median_days_to_response is not None:
        lines.append(
            f"Median days to first response: {report.median_days_to_response:g}"
        )

    bottleneck = report.bottleneck()
    if bottleneck is not None:
        lines.append(
            f"Weakest transition: into {bottleneck.status.value} "
            f"at {bottleneck.conversion_from_previous:.0%}"
        )

    if report.stagnant:
        lines.append("")
        lines.append("Stagnant (idle past the follow-up window):")
        for s in report.stagnant:
            lines.append(
                f"  application_id={s.application_id} | {s.job_title} at "
                f"{s.company} | {s.status.value} | idle {s.days_idle}d "
                f"(threshold {s.threshold}d)"
            )

    return "\n".join(lines)


def build_context(
    profile: Profile,
    board: list[ScoredJob],
    rois: list[SkillROI],
    funnel: FunnelReport,
) -> str:
    """Assemble the full context block passed to the career intelligence agent."""
    return "\n\n".join(
        (
            render_profile(profile),
            render_board(board),
            render_skill_roi(rois),
            render_funnel(funnel),
        )
    )
