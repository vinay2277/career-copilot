"""Tests for the skill ROI engine and the what-if simulator."""

from __future__ import annotations

from app.models.enums import Necessity, Proficiency
from app.services.analytics.alignment import (
    JobFacts,
    PreferenceInput,
    RequirementInput,
    SkillInput,
    score_alignment,
)
from app.services.analytics.skill_roi import (
    UNLOCK_THRESHOLD,
    ScoredJob,
    gap_candidates,
    rank_skills,
)
from app.services.analytics.what_if import Scenario, apply_scenario, simulate

PREFS = PreferenceInput(target_roles=["engineer"], remote_ok=True)


def make_job(job_id: int, *requirement_names: str, title: str = "Engineer") -> ScoredJob:
    """A job whose requirements are all `required`, scored against an empty profile."""
    requirements = [
        RequirementInput(name=n, necessity=Necessity.REQUIRED) for n in requirement_names
    ]
    facts = JobFacts(title=title, remote=True)
    return ScoredJob(
        job_id=job_id,
        title=title,
        company=f"Company {job_id}",
        requirements=requirements,
        facts=facts,
        baseline=score_alignment(requirements, [], PREFS, facts),
    )


def rescore(job: ScoredJob, skills: list[SkillInput]) -> ScoredJob:
    """Re-baseline a job against a non-empty profile."""
    return ScoredJob(
        job_id=job.job_id,
        title=job.title,
        company=job.company,
        requirements=job.requirements,
        facts=job.facts,
        baseline=score_alignment(job.requirements, skills, PREFS, job.facts),
    )


# --------------------------------------------------------------------------- #
# Gap detection
# --------------------------------------------------------------------------- #


def test_gap_candidates_collects_uncovered_skills():
    board = [make_job(1, "python", "go"), make_job(2, "python", "rust")]
    gaps = gap_candidates(board)
    assert set(gaps) == {"python", "go", "rust"}
    # python is required in both jobs -> double the weight of the others.
    assert gaps["python"] == 2.0
    assert gaps["go"] == 1.0


def test_covered_skills_are_not_gaps():
    skills = [SkillInput("python", Proficiency.EXPERT, 5.0)]
    board = [rescore(make_job(1, "python", "go"), skills)]
    gaps = gap_candidates(board)
    assert "python" not in gaps
    assert "go" in gaps


# --------------------------------------------------------------------------- #
# Ranking
# --------------------------------------------------------------------------- #


def test_the_most_demanded_skill_ranks_first():
    """A skill three jobs want beats one that a single job wants."""
    board = [
        make_job(1, "python", "go"),
        make_job(2, "python", "rust"),
        make_job(3, "python", "java"),
    ]
    ranked = rank_skills(board, [], PREFS)
    assert ranked[0].skill == "python"
    assert ranked[0].demand == 3


def test_mean_gain_is_measured_across_the_whole_board():
    """Learning a skill only one job wants still averages over every job."""
    board = [make_job(1, "python"), make_job(2, "go")]
    ranked = rank_skills(board, [], PREFS)
    python = next(r for r in ranked if r.skill == "python")
    # Job 1 goes 0 -> 100 on requirements (70% weight = +70); job 2 is unchanged.
    assert python.best_gain == 70.0
    assert python.mean_gain == 35.0


def test_unlocks_are_reported_when_a_job_crosses_the_threshold():
    board = [make_job(1, "python")]
    ranked = rank_skills(board, [], PREFS)
    python = next(r for r in ranked if r.skill == "python")
    assert python.unlocks == [1]
    assert board[0].baseline.total < UNLOCK_THRESHOLD


def test_a_skill_that_unlocks_nothing_reports_no_unlocks():
    """One of five requirements isn't enough to cross the line."""
    board = [make_job(1, "a", "b", "c", "d", "e")]
    ranked = rank_skills(board, [], PREFS)
    assert all(r.unlock_count == 0 for r in ranked)


def test_unlocks_outrank_raw_point_gain():
    """Crossing the threshold is what changes behaviour, so it sorts first."""
    # Job 1 needs one skill and will cross. Job 2 needs many, so 'shared' gains
    # more total points but unlocks nothing.
    board = [
        make_job(1, "solo"),
        make_job(2, "shared", "x", "y", "z"),
        make_job(3, "shared", "p", "q", "r"),
    ]
    ranked = rank_skills(board, [], PREFS)
    assert ranked[0].skill == "solo"
    assert ranked[0].unlock_count == 1


def test_ranking_is_deterministic():
    board = [make_job(1, "python", "go"), make_job(2, "go", "rust")]
    first = rank_skills(board, [], PREFS)
    second = rank_skills(board, [], PREFS)
    assert [r.skill for r in first] == [r.skill for r in second]
    assert [r.mean_gain for r in first] == [r.mean_gain for r in second]


def test_empty_board_yields_no_ranking():
    assert rank_skills([], [], PREFS) == []


# --------------------------------------------------------------------------- #
# What-if
# --------------------------------------------------------------------------- #


def test_adding_a_skill_raises_the_board_mean():
    board = [make_job(1, "python"), make_job(2, "python", "go")]
    result = simulate(board, [], PREFS, Scenario(add_skills=["python"]))
    assert result.mean_after > result.mean_before
    assert result.mean_change > 0


def test_newly_in_reach_is_flagged():
    board = [make_job(1, "python")]
    result = simulate(board, [], PREFS, Scenario(add_skills=["python"]))
    assert [d.job_id for d in result.newly_in_reach] == [1]
    assert result.in_reach_after == 1
    assert result.in_reach_before == 0


def test_removing_a_carrying_skill_drops_jobs_out_of_reach():
    skills = [SkillInput("python", Proficiency.EXPERT, 5.0)]
    board = [rescore(make_job(1, "python"), skills)]
    result = simulate(board, skills, PREFS, Scenario(remove_skills=["python"]))
    assert [d.job_id for d in result.fell_out_of_reach] == [1]
    assert result.mean_change < 0


def test_apply_scenario_does_not_mutate_its_inputs():
    skills = [SkillInput("python", Proficiency.WORKING, 2.0)]
    prefs = PreferenceInput(min_salary=100_000)

    new_skills, new_prefs = apply_scenario(
        skills, prefs, Scenario(add_skills=["go"], min_salary=150_000)
    )

    assert len(skills) == 1  # original untouched
    assert prefs.min_salary == 100_000
    assert len(new_skills) == 2
    assert new_prefs.min_salary == 150_000


def test_adding_an_existing_skill_upgrades_rather_than_duplicates():
    skills = [SkillInput("python", Proficiency.LEARNING, 0.0)]
    new_skills, _ = apply_scenario(
        skills, PREFS, Scenario(add_skills=["python"], add_at=Proficiency.EXPERT)
    )
    assert len(new_skills) == 1
    assert new_skills[0].proficiency is Proficiency.EXPERT


def test_preference_overrides_left_unset_are_preserved():
    prefs = PreferenceInput(min_salary=100_000, seniority="senior", remote_ok=False)
    _, new_prefs = apply_scenario([], prefs, Scenario(min_salary=120_000))
    assert new_prefs.min_salary == 120_000
    assert new_prefs.seniority == "senior"  # untouched
    assert new_prefs.remote_ok is False


def test_simulating_an_empty_board_is_safe():
    result = simulate([], [], PREFS, Scenario(add_skills=["python"]))
    assert result.deltas == []
    assert result.mean_change == 0.0
