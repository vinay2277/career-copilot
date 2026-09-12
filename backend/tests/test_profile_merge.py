"""Tests for merging a resume-derived profile into the stored one.

The two rules under test: the resume may add a skill or raise its level but
never remove one or lower it, and a field the resume doesn't mention is left
alone rather than blanked. Both exist to make re-uploading a resume safe.
"""

from __future__ import annotations

from app.agents.profile_extraction import ExtractedProfile, ExtractedSkill
from app.models.enums import Proficiency
from app.services.profile_merge import plan_merge

P = Proficiency


def skill(name, proficiency="proficient", years=3.0, evidence="mentioned in resume"):
    return ExtractedSkill(
        name=name, proficiency=proficiency, years=years, evidence=evidence
    )


def extracted(**kwargs) -> ExtractedProfile:
    return ExtractedProfile(**kwargs)


EMPTY_FIELDS: dict[str, object] = {
    "full_name": None,
    "email": None,
    "headline": None,
    "years_experience": 0.0,
    "career_goal": None,
}


# --------------------------------------------------------------------------- #
# Scalar fields
# --------------------------------------------------------------------------- #


def test_empty_profile_is_populated():
    changes = plan_merge(
        extracted(full_name="Vinay", email="v@example.com", years_experience=5.0),
        EMPTY_FIELDS,
        {},
    )
    moved = {c.field: c.after for c in changes.fields}
    assert moved == {
        "full_name": "Vinay",
        "email": "v@example.com",
        "years_experience": 5.0,
    }


def test_absent_fields_do_not_blank_existing_values():
    """The resume listing no email means it listed none, not that there is none."""
    current = {**EMPTY_FIELDS, "email": "kept@example.com", "headline": "my headline"}
    changes = plan_merge(extracted(full_name="Vinay"), current, {})

    touched = {c.field for c in changes.fields}
    assert touched == {"full_name"}
    assert "email" not in touched
    assert "headline" not in touched


def test_zero_years_is_not_treated_as_a_claim():
    """0 is the extractor's 'couldn't tell', not 'no experience'."""
    current = {**EMPTY_FIELDS, "years_experience": 7.0}
    changes = plan_merge(extracted(years_experience=0.0), current, {})
    assert changes.fields == []


def test_identical_values_are_not_reported_as_changes():
    current = {**EMPTY_FIELDS, "full_name": "Vinay"}
    changes = plan_merge(extracted(full_name="Vinay"), current, {})
    assert changes.fields == []


def test_stated_field_updates_an_existing_value():
    current = {**EMPTY_FIELDS, "headline": "junior developer"}
    changes = plan_merge(extracted(headline="backend engineer, payments"), current, {})
    assert [c.after for c in changes.fields] == ["backend engineer, payments"]


# --------------------------------------------------------------------------- #
# Skills: adding
# --------------------------------------------------------------------------- #


def test_new_skills_are_added():
    changes = plan_merge(
        extracted(skills=[skill("python", "expert", 6), skill("dbt", "working", 1)]),
        EMPTY_FIELDS,
        {},
    )
    added = {c.name: c.after for c in changes.skills}
    assert added == {"python": (P.EXPERT, 6.0), "dbt": (P.WORKING, 1.0)}
    assert all(c.is_new for c in changes.skills)


def test_skill_names_are_canonicalised():
    changes = plan_merge(extracted(skills=[skill("Postgres")]), EMPTY_FIELDS, {})
    assert [c.name for c in changes.skills] == ["postgresql"]


def test_alias_matches_an_existing_skill_rather_than_duplicating():
    current = {"postgresql": (P.WORKING, 2.0)}
    changes = plan_merge(
        extracted(skills=[skill("Postgres", "expert", 5)]), EMPTY_FIELDS, current
    )
    assert len(changes.skills) == 1
    assert changes.skills[0].name == "postgresql"
    assert not changes.skills[0].is_new


# --------------------------------------------------------------------------- #
# Skills: the resume may raise but never lower
# --------------------------------------------------------------------------- #


def test_a_higher_level_is_taken():
    current = {"python": (P.WORKING, 2.0)}
    changes = plan_merge(
        extracted(skills=[skill("python", "expert", 6)]), EMPTY_FIELDS, current
    )
    assert changes.skills[0].after == (P.EXPERT, 6.0)


def test_a_lower_level_is_not_applied():
    """A hand-entered level outranks an inference from a resume."""
    current = {"python": (P.EXPERT, 8.0)}
    changes = plan_merge(
        extracted(skills=[skill("python", "working", 2)]), EMPTY_FIELDS, current
    )
    assert changes.skills == []
    assert changes.unchanged_skills == ["python"]


def test_level_and_years_are_taken_independently():
    """A resume can evidence a higher level without restating the years."""
    current = {"python": (P.WORKING, 9.0)}
    changes = plan_merge(
        extracted(skills=[skill("python", "expert", 1)]), EMPTY_FIELDS, current
    )
    # Better level from the resume, better year count from the profile.
    assert changes.skills[0].after == (P.EXPERT, 9.0)


def test_more_years_alone_is_a_change():
    current = {"python": (P.PROFICIENT, 2.0)}
    changes = plan_merge(
        extracted(skills=[skill("python", "proficient", 7)]), EMPTY_FIELDS, current
    )
    assert changes.skills[0].after == (P.PROFICIENT, 7.0)


def test_existing_skills_are_never_removed():
    """A skill the resume omits stays on the profile."""
    current = {"python": (P.EXPERT, 6.0), "redis": (P.WORKING, 2.0)}
    changes = plan_merge(extracted(skills=[skill("python", "expert", 6)]), EMPTY_FIELDS, current)
    # Nothing in a Changeset can remove a skill — there is no such operation.
    assert not hasattr(changes, "removed_skills")
    assert changes.skills == []


def test_reapplying_the_same_resume_is_a_no_op():
    """Re-upload must be safe; the second run should change nothing."""
    resume = extracted(
        full_name="Vinay", years_experience=5.0, skills=[skill("python", "expert", 6)]
    )
    first = plan_merge(resume, EMPTY_FIELDS, {})

    after_fields = {**EMPTY_FIELDS}
    for c in first.fields:
        after_fields[c.field] = c.after
    after_skills = {c.name: c.after for c in first.skills}

    second = plan_merge(resume, after_fields, after_skills)
    assert second.fields == []
    assert second.skills == []
    assert not second.touched


# --------------------------------------------------------------------------- #
# Anti-hallucination
# --------------------------------------------------------------------------- #


def test_skills_without_evidence_are_rejected():
    """The evidence quote is the whole guard against invented skills."""
    changes = plan_merge(
        extracted(
            skills=[
                skill("python", evidence="Built services in Python"),
                skill("rust", evidence=""),
                skill("haskell", evidence="   "),
            ]
        ),
        EMPTY_FIELDS,
        {},
    )
    assert [c.name for c in changes.skills] == ["python"]
    assert set(changes.rejected_skills) == {"rust", "haskell"}


def test_unnamed_skills_are_rejected():
    changes = plan_merge(extracted(skills=[skill("", evidence="x")]), EMPTY_FIELDS, {})
    assert changes.skills == []
    assert changes.rejected_skills == [""]


def test_an_off_spec_proficiency_becomes_working_not_expert():
    """An unrecognized level must not inflate the skill."""
    changes = plan_merge(
        extracted(skills=[skill("go", "super-duper", 1)]), EMPTY_FIELDS, {}
    )
    assert changes.skills[0].after[0] is P.WORKING


def test_none_proficiency_is_lifted_to_working():
    changes = plan_merge(extracted(skills=[skill("go", "none", 1)]), EMPTY_FIELDS, {})
    assert changes.skills[0].after[0] is P.WORKING


def test_negative_years_are_clamped():
    changes = plan_merge(extracted(skills=[skill("go", "working", -3)]), EMPTY_FIELDS, {})
    assert changes.skills[0].after[1] == 0.0


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def test_nothing_to_do_is_reported_as_such():
    changes = plan_merge(extracted(), EMPTY_FIELDS, {})
    assert not changes.touched
    assert "didn't add anything" in changes.summary()


def test_summary_describes_what_moved():
    changes = plan_merge(
        extracted(full_name="Vinay", skills=[skill("dbt", "working", 1)]),
        EMPTY_FIELDS,
        {},
    )
    summary = changes.summary()
    assert "full_name" in summary
    assert "added dbt" in summary


def test_new_skills_sort_before_raised_ones():
    current = {"python": (P.WORKING, 1.0)}
    changes = plan_merge(
        extracted(
            skills=[skill("python", "expert", 5), skill("airflow", "working", 1)]
        ),
        EMPTY_FIELDS,
        current,
    )
    assert [c.name for c in changes.skills] == ["airflow", "python"]
    assert changes.skills[0].is_new
    assert not changes.skills[1].is_new


def test_extraction_notes_are_carried_through():
    changes = plan_merge(
        extracted(notes=["Two roles are undated; years are approximate."]),
        EMPTY_FIELDS,
        {},
    )
    assert changes.notes == ["Two roles are undated; years are approximate."]
