"""Tests for the alignment scorer.

The point of these is the property the whole product rests on: the score is a
function of its inputs alone, and its derivation adds up.
"""

from __future__ import annotations

import pytest

from app.models.enums import Coverage, Necessity, Proficiency
from app.services.analytics.alignment import (
    PREFERENCES_WEIGHT,
    REQUIREMENTS_WEIGHT,
    JobFacts,
    PreferenceInput,
    RequirementInput,
    SkillInput,
    score_alignment,
    score_preferences,
    score_requirements,
)


def req(name: str, necessity: Necessity = Necessity.REQUIRED, years: float = 0.0):
    return RequirementInput(name=name, necessity=necessity, min_years=years)


def skill(name: str, prof: Proficiency = Proficiency.PROFICIENT, years: float = 3.0):
    return SkillInput(name=name, proficiency=prof, years=years)


# --------------------------------------------------------------------------- #
# Requirements half
# --------------------------------------------------------------------------- #


def test_full_coverage_scores_100():
    fit, results = score_requirements([req("python"), req("sql")], [skill("python"), skill("sql")])
    assert fit == 100.0
    assert all(r.coverage is Coverage.HAVE for r in results)


def test_no_coverage_scores_zero():
    fit, results = score_requirements([req("python"), req("go")], [skill("java")])
    assert fit == 0.0
    assert all(r.coverage is Coverage.MISSING for r in results)


def test_empty_requirements_score_zero_not_100():
    """An unparseable job must not float to the top of the board."""
    fit, results = score_requirements([], [skill("python")])
    assert fit == 0.0
    assert results == []


def test_necessity_weighting_favours_required_skills():
    """Covering the required skill beats covering the nice-to-have."""
    requirements = [
        req("python", Necessity.REQUIRED),
        req("rust", Necessity.NICE_TO_HAVE),
    ]
    has_required, _ = score_requirements(requirements, [skill("python")])
    has_optional, _ = score_requirements(requirements, [skill("rust")])
    assert has_required > has_optional

    # required=1.0, nice_to_have=0.2 -> 1.0/1.2 vs 0.2/1.2
    assert has_required == pytest.approx(83.3, abs=0.1)
    assert has_optional == pytest.approx(16.7, abs=0.1)


def test_below_working_proficiency_is_partial():
    _, results = score_requirements([req("kubernetes")], [skill("kubernetes", Proficiency.LEARNING)])
    assert results[0].coverage is Coverage.PARTIAL
    assert "below working proficiency" in results[0].reason


def test_insufficient_years_is_partial():
    _, results = score_requirements(
        [req("python", years=5.0)], [skill("python", Proficiency.EXPERT, years=2.0)]
    )
    assert results[0].coverage is Coverage.PARTIAL
    assert "2y experience against 5y asked" in results[0].reason


def test_partial_earns_half_credit():
    fit, _ = score_requirements([req("go")], [skill("go", Proficiency.LEARNING)])
    assert fit == 50.0


def test_alias_resolution_counts_as_coverage():
    """'postgres' on the profile must satisfy a 'postgresql' requirement."""
    fit, results = score_requirements([req("postgresql")], [skill("postgres")])
    assert fit == 100.0
    assert results[0].coverage is Coverage.HAVE


def test_duplicate_profile_skill_keeps_the_stronger():
    """A stray weak duplicate must not drag the score down."""
    fit, _ = score_requirements(
        [req("python")],
        [
            skill("python", Proficiency.LEARNING, years=0.0),
            skill("python", Proficiency.EXPERT, years=8.0),
        ],
    )
    assert fit == 100.0


def test_results_are_ordered_worst_first():
    _, results = score_requirements(
        [req("python"), req("rust"), req("go", Necessity.PREFERRED)],
        [skill("python")],
    )
    assert [r.coverage for r in results] == [
        Coverage.MISSING,
        Coverage.MISSING,
        Coverage.HAVE,
    ]
    # Within equal coverage, the heavier requirement leads.
    assert results[0].name == "rust"


# --------------------------------------------------------------------------- #
# Preferences half
# --------------------------------------------------------------------------- #


def test_unstated_facets_are_not_penalised():
    """A job with no salary must not lose points for it."""
    prefs = PreferenceInput(min_salary=150_000)
    fit, facets = score_preferences(prefs, JobFacts(title="Engineer"))
    # Salary was never comparable, so no facet exists for it.
    assert not any(f.name == "salary" for f in facets)
    assert fit == 50.0  # neutral: nothing comparable at all


def test_empty_preferences_are_neutral_not_zero():
    fit, _ = score_preferences(PreferenceInput(), JobFacts(title="Engineer"))
    assert fit == 50.0


def test_remote_satisfies_a_location_preference():
    prefs = PreferenceInput(locations=["Berlin"], remote_ok=True)
    fit, facets = score_preferences(prefs, JobFacts(title="Dev", location="Austin", remote=True))
    location = next(f for f in facets if f.name == "location")
    assert location.matched
    assert fit == 100.0


def test_salary_is_judged_on_the_top_of_the_band():
    prefs = PreferenceInput(min_salary=120_000)
    job = JobFacts(title="Dev", salary_min=100_000, salary_max=140_000)
    fit, facets = score_preferences(prefs, job)
    assert next(f for f in facets if f.name == "salary").matched
    assert fit == 100.0


def test_salary_below_floor_does_not_match():
    prefs = PreferenceInput(min_salary=200_000)
    job = JobFacts(title="Dev", salary_min=100_000, salary_max=140_000)
    _, facets = score_preferences(prefs, job)
    assert not next(f for f in facets if f.name == "salary").matched


def test_role_matches_on_shared_terms():
    prefs = PreferenceInput(target_roles=["backend engineer"])
    _, facets = score_preferences(prefs, JobFacts(title="Senior Backend Engineer"))
    assert next(f for f in facets if f.name == "role").matched


# --------------------------------------------------------------------------- #
# Combined
# --------------------------------------------------------------------------- #


def test_total_is_the_weighted_sum_of_its_halves():
    result = score_alignment(
        requirements=[req("python"), req("sql")],
        skills=[skill("python")],
        prefs=PreferenceInput(target_roles=["data engineer"], min_salary=100_000),
        job=JobFacts(title="Data Engineer", salary_max=90_000),
    )
    expected = (
        REQUIREMENTS_WEIGHT * result.requirements_fit
        + PREFERENCES_WEIGHT * result.preference_fit
    )
    assert result.total == pytest.approx(expected, abs=0.05)


def test_scoring_is_deterministic():
    """Same inputs, same output — including the order of the breakdown."""
    args = dict(
        requirements=[req("go"), req("python"), req("sql", Necessity.PREFERRED)],
        skills=[skill("python"), skill("sql", Proficiency.LEARNING)],
        prefs=PreferenceInput(target_roles=["backend"], locations=["Remote"]),
        job=JobFacts(title="Backend Engineer", remote=True),
    )
    first = score_alignment(**args)
    second = score_alignment(**args)

    assert first.total == second.total
    assert [r.name for r in first.requirements] == [r.name for r in second.requirements]
    assert first.explain() == second.explain()


def test_explain_mentions_every_requirement():
    result = score_alignment(
        requirements=[req("python"), req("terraform")],
        skills=[skill("python")],
        prefs=PreferenceInput(),
        job=JobFacts(title="SRE"),
    )
    explanation = result.explain()
    assert "python" in explanation
    assert "terraform" in explanation
    assert f"{result.total:.1f}" in explanation


def test_coverage_buckets_partition_the_requirements():
    result = score_alignment(
        requirements=[req("python"), req("go"), req("k8s", years=5.0)],
        skills=[skill("python"), skill("kubernetes", Proficiency.WORKING, years=1.0)],
        prefs=PreferenceInput(),
        job=JobFacts(title="Platform Engineer"),
    )
    assert len(result.have) + len(result.partial) + len(result.missing) == 3
    assert [r.name for r in result.have] == ["python"]
    assert [r.name for r in result.missing] == ["go"]
    # "k8s" aliases to kubernetes, held at 1y against 5y asked -> partial.
    assert [r.name for r in result.partial] == ["k8s"]
