"""Tests for the ingestion pipeline's post-processing of extracted requirements.

The model's output is not trusted blindly here. A "requirement" that isn't a
learnable skill corrupts three things at once — the alignment score, the gap
list, and the learning roadmap — so the filtering is enforced in code as well
as in the prompt, and tested.
"""

from __future__ import annotations

from app.agents.extraction import ExtractedRequirement
from app.services.ingestion.pipeline import (
    _dedupe,
    _drop_non_skills,
    _drop_rejected,
)


def req(name: str, necessity: str = "required", years: float = 0.0):
    return ExtractedRequirement(
        name=name, necessity=necessity, min_years=years, evidence=f"mentions {name}"
    )


# --------------------------------------------------------------------------- #
# Non-skill filtering
#
# Regression: a live extraction put "bachelor's degree" in `requirements`. It
# was weighted `required`, scored as a missing skill, and would have appeared
# in a learning roadmap as something to go and acquire.
# --------------------------------------------------------------------------- #


def test_degree_requirements_are_dropped():
    kept = _drop_non_skills([req("python"), req("bachelor's degree")])
    assert [r.name for r in kept] == ["python"]


def test_degree_spelling_variants_are_all_caught():
    """Matched on the canonical name, so punctuation doesn't matter."""
    variants = [
        "Bachelor's Degree",
        "bachelors degree",
        "BS degree",
        "Master's in Computer Science",
        "PhD",
        "Doctorate",
        "diploma",
    ]
    assert _drop_non_skills([req(v) for v in variants]) == []


def test_certifications_and_clearances_are_dropped():
    kept = _drop_non_skills(
        [
            req("aws"),
            req("AWS Certified Solutions Architect"),
            req("security clearance"),
        ]
    )
    assert [r.name for r in kept] == ["aws"]


def test_generic_years_of_experience_is_dropped():
    """A total-experience figure isn't a skill; it has its own field."""
    kept = _drop_non_skills([req("7+ years of experience"), req("python", years=5)])
    assert [r.name for r in kept] == ["python"]


def test_soft_qualities_are_dropped():
    kept = _drop_non_skills(
        [
            req("team player"),
            req("strong communicator"),
            req("attention to detail"),
            req("kubernetes"),
        ]
    )
    assert [r.name for r in kept] == ["kubernetes"]


def test_real_skills_survive():
    """The filter must not eat legitimate, learnable requirements."""
    skills = [
        "python",
        "postgresql",
        "kubernetes",
        "distributed systems",
        "payments",
        "fintech",
        "kafka",
        "terraform",
        "go",
        "system design",
        "machine learning",
    ]
    kept = _drop_non_skills([req(s) for s in skills])
    assert [r.name for r in kept] == skills


def test_empty_input_is_safe():
    assert _drop_non_skills([]) == []


# --------------------------------------------------------------------------- #
# Validator rejections
# --------------------------------------------------------------------------- #


def test_rejected_indices_are_removed():
    requirements = [req("python"), req("invented"), req("sql")]
    kept = _drop_rejected(requirements, [1])
    assert [r.name for r in kept] == ["python", "sql"]


def test_out_of_range_rejection_indices_are_ignored():
    """A malformed index must not silently drop the wrong requirement."""
    requirements = [req("python")]
    assert _drop_rejected(requirements, [5, -1]) == requirements


def test_no_rejections_leaves_the_list_alone():
    requirements = [req("python"), req("sql")]
    assert _drop_rejected(requirements, []) == requirements


# --------------------------------------------------------------------------- #
# Deduplication
# --------------------------------------------------------------------------- #


def test_duplicates_collapse_to_the_stricter_entry():
    """Postings repeat skills; double-counting inflates that skill's weight."""
    kept = _dedupe(
        [
            req("python", "nice_to_have", 0),
            req("python", "required", 5),
        ]
    )
    assert len(kept) == 1
    assert kept[0].necessity == "required"
    assert kept[0].min_years == 5


def test_aliases_are_treated_as_the_same_skill():
    kept = _dedupe([req("postgres"), req("postgresql")])
    assert len(kept) == 1


def test_dedupe_output_is_sorted_for_determinism():
    kept = _dedupe([req("terraform"), req("aws"), req("kubernetes")])
    assert [r.name for r in kept] == ["aws", "kubernetes", "terraform"]


def test_unrecognized_necessity_is_treated_as_required():
    """An off-spec value must not win a tie-break against a real `required`."""
    kept = _dedupe([req("python", "definitely-needed", 0), req("python", "required", 3)])
    assert len(kept) == 1
    assert kept[0].min_years == 3
