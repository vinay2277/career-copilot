"""Read a candidate profile out of a resume.

Same discipline as job extraction: every skill must be quotable from the
resume. That matters more here than anywhere else in the app — an invented
skill on the profile inflates every alignment score, hides a real gap, and
eventually puts the candidate in an interview defending something they never
claimed.

Proficiency is the one genuine inference. Resumes rarely say "proficient in
Python"; it has to be read from how the skill is used, for how long, and how
central it was. The prompt is deliberately conservative about it, because
overstating is the expensive direction.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.client import structured_call

SYSTEM = """\
You read a resume and extract the candidate's profile. You are a reader, not a \
promoter: your output feeds a scoring engine the candidate will make decisions \
with, so accuracy beats generosity in every case.

**Every skill you emit must be supported by the resume.** Put the supporting \
quote in `evidence`. If you cannot quote it, do not emit the skill. Do not add \
skills that are merely adjacent to something listed — a candidate who used \
Django has not thereby demonstrated Flask, and someone who lists PostgreSQL \
has not listed MySQL.

**Skill names are short and canonical**: the tool or technology alone, \
lowercase. "Built REST APIs with FastAPI" gives "fastapi". "Deep experience \
with Amazon Web Services" gives "aws". Do not emit phrases.

**Proficiency** — infer it, conservatively. This is the one judgment call, and \
overstating it is the costly error:
- `expert`: years of central use, plus evidence of depth — they optimised it, \
  taught it, designed with it, or fixed it at a level others could not.
- `proficient`: used substantially and independently across real work. This is \
  the right default for a skill that appears in several roles or projects.
- `working`: used, but in a supporting role, or recently, or under guidance. \
  The right default for a skill named once in passing.
- `learning`: explicitly framed as in-progress, coursework, a side project, or \
  listed under "familiar with" / "exposure to".
Never emit `none`. A skill at `none` is not a skill; omit it.

**Years per skill** — derive from the dates of the roles where the skill \
appears, not from the candidate's total career. If a skill shows up only in a \
2023-2024 role, that is roughly 1 year even if the person has worked for ten. \
When dates are absent, use 0 rather than guessing.

**`years_experience`** is total professional experience. If the resume states \
a figure outright — "4 years building analytics pipelines", "6+ years in \
backend engineering" — **use that number**. The candidate knows their own \
career better than date arithmetic does, and dates omit contract work, \
overlapping roles and time the resume doesn't itemise. Only when no figure is \
stated should you compute it, from the earliest professional start date to the \
latest, excluding internships and study. If neither a figure nor dates are \
present, use 0.

**Do not emit a skill for**: degrees, universities, certifications, job titles, \
company names, soft qualities ("team player", "strong communicator"), or \
spoken languages. Those either belong in their own fields below or nowhere.

**`headline`** is one short phrase describing what this person is — "backend \
engineer, payments" or "data engineer, analytics platforms". Take it from the \
resume's own summary if it has one; otherwise infer it from the most recent \
role. No marketing language.

**`career_goal`** only if the resume states an objective or summary of intent. \
Leave it null rather than inventing an aspiration on the candidate's behalf.\
"""


class ExtractedSkill(BaseModel):
    name: str = Field(description="Short canonical skill name, lowercase.")
    proficiency: str = Field(
        description="One of: learning, working, proficient, expert."
    )
    years: float = Field(
        default=0.0, description="Years of use for this skill specifically."
    )
    evidence: str = Field(
        description="Quote from the resume supporting this skill and level."
    )


class ExtractedProfile(BaseModel):
    full_name: str | None = None
    email: str | None = None
    headline: str | None = None
    years_experience: float = Field(
        default=0.0, description="Total professional years, excluding study."
    )
    career_goal: str | None = Field(
        default=None, description="Only if the resume states an objective."
    )
    skills: list[ExtractedSkill] = Field(default_factory=list)

    # Captured so the information isn't lost, but kept out of `skills` because
    # none of it is a learnable, matchable capability.
    education: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)

    #: Anything genuinely ambiguous — undated roles, a gap, an unclear level.
    #: Surfaced to the user rather than resolved silently.
    notes: list[str] = Field(default_factory=list)


def extract_profile(resume_text: str) -> ExtractedProfile:
    """Extract a structured profile from resume text.

    Runs at `xhigh` on Anthropic: this writes the data every downstream score
    depends on, so a mistake here is not contained — it propagates into every
    job on the board.
    """
    return structured_call(
        system=SYSTEM,
        user=(
            "Extract this candidate's profile.\n\n"
            f"<resume>\n{resume_text}\n</resume>"
        ),
        output_model=ExtractedProfile,
        effort="xhigh",
        max_tokens=32000,
    )
