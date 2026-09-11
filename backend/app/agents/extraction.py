"""Agent 1: extract a structured job post from raw text.

This agent's only job is transcription into a schema. It does not judge fit, and
it does not fill gaps — every field it emits must be traceable to the source
text, because Agent 2 is about to check exactly that.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.client import structured_call

SYSTEM = """\
You extract structured data from job postings. You are a transcriber, not an \
analyst.

Rules, in priority order:

1. Never invent. If the posting does not state something, leave the field null \
   or the list empty. An omitted salary is null, not an estimate; an unnamed \
   company is null, not a guess from the domain name.
2. Every requirement you emit must carry an `evidence` field quoting the \
   posting verbatim — the exact substring that justifies it. If you cannot \
   quote it, do not emit the requirement.
3. Classify necessity from the posting's own language. "must have", "required", \
   "X years of experience with" mean `required`. "preferred", "bonus", \
   "nice to have", "a plus" mean `preferred` or `nice_to_have`. When the \
   language is neutral (a bare bullet under "Requirements"), use `required`.
4. Requirement names are short and canonical: the skill or tool alone. \
   "5+ years of hands-on Python development" yields name "python" with \
   min_years 5.0 — not the whole phrase.
5. Split compound requirements. "Python, Go, or Rust" is three requirements, \
   each `preferred` if the posting offers them as alternatives.
6. Extract salary as integers in the posting's own currency, annualized. An \
   hourly or monthly rate should be converted and the currency recorded; if the \
   period is ambiguous, leave both bounds null.
7. `seniority` uses the posting's own term when it has one (intern, junior, \
   mid, senior, staff, principal, lead, manager, director). Otherwise null.

Judgment stays out of this. Do not rank requirements by importance beyond the \
necessity field, do not comment on the posting's quality, and do not note what \
a candidate would need.\
"""


class ExtractedRequirement(BaseModel):
    name: str = Field(description="Short canonical skill or tool name, lowercase.")
    necessity: str = Field(description="One of: required, preferred, nice_to_have.")
    min_years: float = Field(
        default=0.0, description="Years of experience demanded; 0 if unstated."
    )
    evidence: str = Field(
        description="Verbatim substring from the posting justifying this requirement."
    )


class ExtractedJob(BaseModel):
    title: str
    company: str | None = None
    location: str | None = None
    remote: bool | None = Field(
        default=None, description="True if remote, False if explicitly on-site."
    )
    seniority: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    currency: str | None = Field(default=None, description="ISO code, e.g. USD.")
    industry: str | None = None
    company_size: str | None = None
    description: str | None = Field(
        default=None, description="Two-sentence neutral summary of the role."
    )
    requirements: list[ExtractedRequirement] = Field(default_factory=list)


def extract_job(raw_text: str) -> ExtractedJob:
    """Turn raw posting text into a structured job.

    Runs at `high` effort: transcription accuracy on messy OCR output is worth
    more than the token saving, and this runs once per job rather than per view.
    """
    return structured_call(
        system=SYSTEM,
        user=f"Extract the job posting below.\n\n<posting>\n{raw_text}\n</posting>",
        output_model=ExtractedJob,
        effort="high",
    )
