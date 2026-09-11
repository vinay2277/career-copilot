"""Resume analysis and job-specific tailoring.

Two agents that both read a resume, with opposite jobs: one judges it in the
abstract, the other rewrites it for one posting. The rewrite is constrained hard
against embellishment, because a resume that overstates is worse than one that
under-sells — it fails at the interview instead of at the filter.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.client import structured_call

# --------------------------------------------------------------------------- #
# Resume analysis
# --------------------------------------------------------------------------- #

ANALYSIS_SYSTEM = """\
You review resumes for how well they survive both automated screening and a \
recruiter's six-second scan.

Score `ats_score` from 0 to 100 on machine readability specifically — not on \
how impressive the career is. What raises it:

- Standard section headings (Experience, Education, Skills) a parser expects.
- Skills stated in plain words, matching how postings name them.
- Dates in a consistent, parseable format.
- Plain single-column text; no tables, text boxes, graphics, or columns that \
  scramble reading order.
- Concrete job titles rather than invented internal ones.

What lowers it: header/footer content a parser drops, skills only implied by \
project descriptions, acronyms with no expansion, and any layout that reads out \
of order as plain text.

In `strengths`, name what is genuinely working — specific to this resume, not \
generic praise. Quote or reference the actual line.

In `gaps`, name what is missing or self-defeating, each with the fix. "No \
metrics" is a complaint; "the Stripe migration bullet describes the work but \
not the outcome — add the volume or latency figure" is useful.

Be honest. A resume with real problems helps nobody by being told it is strong.\
"""


class ResumeAnalysis(BaseModel):
    ats_score: float = Field(ge=0.0, le=100.0)
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    #: Skills the resume demonstrates but never names outright — these are what
    #: an ATS keyword filter silently drops.
    implied_but_unstated_skills: list[str] = Field(default_factory=list)
    notes: str = Field(description="Two or three sentences of overall read.")


def analyze_resume(resume_text: str) -> ResumeAnalysis:
    """Score a resume on ATS readability and name its concrete weaknesses."""
    return structured_call(
        system=ANALYSIS_SYSTEM,
        user=f"Review this resume.\n\n<resume>\n{resume_text}\n</resume>",
        output_model=ResumeAnalysis,
        effort="high",
    )


# --------------------------------------------------------------------------- #
# Resume tailoring
# --------------------------------------------------------------------------- #

TAILOR_SYSTEM = """\
You rewrite a resume to target one specific job posting.

The absolute constraint: **you may not add experience the candidate does not \
have.** No inflated titles, no skills they never listed, no invented metrics, \
no stretched dates. You are re-ordering, re-weighting and re-wording what is \
already true — nothing else. A rewrite that wins the screen and then collapses \
in the interview is a failure.

Within that limit, do the work properly:

1. **Re-order for this reader.** Experience that matches the posting's required \
   skills moves up, within each role and across the bullet list. Work that is \
   irrelevant here gets compressed to a line, not deleted.
2. **Re-word to match the posting's vocabulary.** If they say "distributed \
   systems" and the resume says "microservices at scale", use their phrase — \
   the underlying claim is unchanged, and both a parser and a recruiter are \
   scanning for their words.
3. **Surface what was buried.** A skill demonstrated inside a project \
   description but absent from the skills section is invisible to a keyword \
   filter. Name it explicitly. This is the single highest-value change you can \
   make, and it invents nothing.
4. **Quantify what is already quantifiable.** If a bullet states a result \
   without its magnitude and the magnitude appears elsewhere in the resume, \
   bring it into the bullet. If the number is nowhere in the source, leave the \
   bullet alone — do not estimate it.
5. **Drop nothing material.** A shorter resume is not the goal.

Return the full rewritten resume in `content` as plain text with clear section \
headings. In `change_summary`, list what you moved, renamed, or surfaced, so \
the candidate can confirm every change is honest before they send it.\
"""


class TailoredResumeDraft(BaseModel):
    content: str = Field(description="The complete rewritten resume, plain text.")
    emphasized_skills: list[str] = Field(
        default_factory=list,
        description="Requirement names this rewrite now surfaces explicitly.",
    )
    change_summary: str = Field(
        description="What changed and why, so the candidate can verify honesty."
    )
    #: Requirements the posting wants that the resume genuinely cannot support.
    #: Named rather than papered over — these are interview prep, not resume work.
    unaddressable_gaps: list[str] = Field(default_factory=list)


def tailor_resume(
    resume_text: str,
    job_text: str,
    missing_skills: list[str],
) -> TailoredResumeDraft:
    """Rewrite `resume_text` for `job_text` without inventing anything.

    `missing_skills` comes from the alignment scorer, so the agent knows up
    front which gaps are real and shouldn't be written around.
    """
    gaps = ", ".join(missing_skills) if missing_skills else "none identified"
    user = (
        f"<resume>\n{resume_text}\n</resume>\n\n"
        f"<target_job>\n{job_text}\n</target_job>\n\n"
        f"<known_gaps>\nThe alignment scorer found these requirements "
        f"uncovered: {gaps}. Do not write around them — list them in "
        f"unaddressable_gaps.\n</known_gaps>"
    )
    return structured_call(
        system=TAILOR_SYSTEM,
        user=user,
        output_model=TailoredResumeDraft,
        effort="xhigh",
        max_tokens=32000,
    )
