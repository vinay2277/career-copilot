"""Merge a resume-derived profile into the stored one.

Two rules decide everything here:

1. **The resume may add a skill or raise its level. It may never remove a skill
   or lower a level.** A proficiency read off a resume is an inference; one the
   user typed in is a statement. When they disagree, the user wins. This also
   means re-uploading a resume is always safe — it cannot quietly demote work
   the user corrected by hand.
2. **A field the resume doesn't mention is left alone, never blanked.** An
   absent email means the resume didn't list one, not that the user doesn't
   have one.

The result is a `Changeset` describing exactly what moved, so the UI can show
it rather than silently rewriting the user's profile underneath them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.agents.profile_extraction import ExtractedProfile, ExtractedSkill
from app.models.enums import Proficiency
from app.services.analytics.alignment import PROFICIENCY_RANK
from app.services.analytics.canonical import canonicalize

#: Fields the resume is allowed to update in place, when it states a value.
SCALAR_FIELDS = ("full_name", "email", "headline", "years_experience", "career_goal")


@dataclass
class SkillChange:
    name: str
    #: None when the skill is new to the profile.
    before: tuple[Proficiency, float] | None
    after: tuple[Proficiency, float]
    evidence: str

    @property
    def is_new(self) -> bool:
        return self.before is None

    def describe(self) -> str:
        level, years = self.after
        if self.before is None:
            return f"added {self.name} ({level.value}, {years:g}y)"
        old_level, old_years = self.before
        return (
            f"raised {self.name} from {old_level.value}, {old_years:g}y "
            f"to {level.value}, {years:g}y"
        )


@dataclass
class FieldChange:
    field: str
    before: object
    after: object

    def describe(self) -> str:
        was = self.before if self.before not in (None, "", 0, 0.0) else "empty"
        return f"{self.field}: {was} -> {self.after}"


@dataclass
class Changeset:
    fields: list[FieldChange] = field(default_factory=list)
    skills: list[SkillChange] = field(default_factory=list)
    #: Skills the resume named at or below what the profile already said. Kept
    #: for display so "nothing happened" is distinguishable from "not found".
    unchanged_skills: list[str] = field(default_factory=list)
    #: Skills dropped because the model gave no supporting quote.
    rejected_skills: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def touched(self) -> bool:
        return bool(self.fields or self.skills)

    def summary(self) -> str:
        if not self.touched:
            return "No changes — the resume didn't add anything new."
        lines = [c.describe() for c in self.fields]
        lines += [c.describe() for c in self.skills]
        return "; ".join(lines)


def _coerce_proficiency(value: str) -> Proficiency:
    """Map the agent's string onto the enum.

    Typed loosely in the extraction schema so a slightly off-spec value doesn't
    fail the whole parse. An unrecognized level becomes `working` — the
    conservative reading, since the alternative is inflating a skill nobody
    claimed at that level.
    """
    try:
        level = Proficiency(str(value).strip().lower())
    except ValueError:
        return Proficiency.WORKING
    return Proficiency.WORKING if level is Proficiency.NONE else level


def _usable(skill: ExtractedSkill) -> bool:
    """Whether a skill carries enough support to be trusted.

    The evidence quote is the whole anti-hallucination mechanism for profile
    extraction; a skill without one is exactly the case it exists to catch.
    """
    return bool(canonicalize(skill.name)) and bool((skill.evidence or "").strip())


def plan_merge(
    extracted: ExtractedProfile,
    current_fields: dict[str, object],
    current_skills: dict[str, tuple[Proficiency, float]],
) -> Changeset:
    """Work out what applying `extracted` would change. Pure — writes nothing.

    `current_skills` is keyed by canonical name. Keeping this function free of
    the ORM is what makes the merge rules testable without a database.
    """
    changes = Changeset(notes=list(extracted.notes))

    # --- Scalars ---
    for name in SCALAR_FIELDS:
        incoming = getattr(extracted, name, None)

        # Absent means "the resume didn't say", which must not blank a value.
        if incoming is None or incoming == "":
            continue
        # A zero year count is the extractor's "couldn't tell", not a claim.
        if name == "years_experience" and not incoming:
            continue

        existing = current_fields.get(name)
        if existing == incoming:
            continue
        changes.fields.append(FieldChange(field=name, before=existing, after=incoming))

    # --- Skills ---
    for skill in extracted.skills:
        if not _usable(skill):
            changes.rejected_skills.append(skill.name)
            continue

        key = canonicalize(skill.name)
        level = _coerce_proficiency(skill.proficiency)
        years = max(0.0, skill.years)

        existing = current_skills.get(key)
        if existing is None:
            changes.skills.append(
                SkillChange(
                    name=key, before=None, after=(level, years), evidence=skill.evidence
                )
            )
            continue

        old_level, old_years = existing
        # Take the better of each, independently: a resume can evidence a higher
        # level without restating the years, and vice versa.
        best_level = (
            level
            if PROFICIENCY_RANK[level] > PROFICIENCY_RANK[old_level]
            else old_level
        )
        best_years = max(years, old_years)

        if (best_level, best_years) == existing:
            changes.unchanged_skills.append(key)
            continue

        changes.skills.append(
            SkillChange(
                name=key,
                before=existing,
                after=(best_level, best_years),
                evidence=skill.evidence,
            )
        )

    changes.skills.sort(key=lambda c: (not c.is_new, c.name))
    changes.unchanged_skills.sort()
    return changes


# --------------------------------------------------------------------------- #
# ORM application — the only part of this module that touches the database
# --------------------------------------------------------------------------- #


def snapshot(profile) -> tuple[dict[str, object], dict[str, tuple[Proficiency, float]]]:
    """Read a profile into the plain shapes `plan_merge` expects."""
    fields = {name: getattr(profile, name) for name in SCALAR_FIELDS}
    skills = {
        canonicalize(s.name): (Proficiency(s.proficiency), s.years)
        for s in profile.skills
    }
    return fields, skills


def apply_changeset(profile, changes: Changeset) -> None:
    """Write a changeset onto a profile. Caller commits.

    Skills are mutated in place or appended; nothing is removed, so a skill the
    user added by hand survives every resume upload.
    """
    from app.models import ProfileSkill

    for change in changes.fields:
        setattr(profile, change.field, change.after)

    by_name = {canonicalize(s.name): s for s in profile.skills}
    for change in changes.skills:
        level, years = change.after
        existing = by_name.get(change.name)
        if existing is None:
            profile.skills.append(
                ProfileSkill(name=change.name, proficiency=level, years=years)
            )
        else:
            existing.proficiency = level
            existing.years = years


def merge_resume_into_profile(profile, extracted: ExtractedProfile) -> Changeset:
    """Plan and apply in one step. Returns what changed. Caller commits."""
    fields, skills = snapshot(profile)
    changes = plan_merge(extracted, fields, skills)
    apply_changeset(profile, changes)
    return changes
