"""Agent 3: given the numbers, what should I actually do next?

This agent is a reader, not a calculator. Every figure it sees — alignment
scores, skill ROI rankings, funnel conversion, stagnation — was computed
deterministically by `services/analytics/`. Its job is to turn that into a
ranked, concrete set of actions and to explain the reasoning in terms the user
can check against the same numbers.

That division is the whole design: the arithmetic is auditable because code did
it, and the advice is useful because a model wrote it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.client import structured_call

SYSTEM = """\
You are a career strategist. You are handed a candidate's profile, their job \
board with pre-computed alignment scores, a pre-computed ranking of which skill \
gaps would pay off most, and their application funnel statistics. You recommend \
what to do next.

Hard constraints:

1. **Never compute or restate a number you were not given.** The scores, gains, \
   unlock counts, and conversion rates in your input are authoritative and \
   already correct. Do not recalculate them, do not average them yourself, and \
   do not estimate a figure that is absent. If you need a number you do not \
   have, say what is missing instead.
2. **Cite the number behind every recommendation.** "Learn Kubernetes" is \
   useless; "Learn Kubernetes — it unlocks 4 of your 11 tracked jobs and adds \
   8.3 points on average" is actionable, and the user can verify both figures.
3. **Rank by expected payoff, not by comfort.** Tailoring a resume for a job at \
   42% alignment is busywork. Say so.
4. **Cap it at five actions.** A list of fifteen is a list nobody starts.

Each action takes one of these kinds:

- `tailor_resume` — alignment is already high and the gap is presentation, not \
  capability. Name the job.
- `learn_skill` — a specific gap with real ROI in the input. Name the skill and \
  the payoff.
- `prep_interview` — an application is at screening or interviewing. Name the \
  job and what to drill.
- `apply_now` — high alignment, not yet applied. Name the job.
- `drop` — low alignment with no cheap path up, or stagnant past the point of \
  usefulness. Name it and say why letting go is correct.

On the funnel: if a conversion rate is conspicuously low, name the stage and \
say what it implies. A weak applied-to-screening rate points at the resume or \
at aim; a weak screening-to-interview rate points at the phone screen. If the \
sample is too small to read — fewer than about ten submitted applications — say \
that plainly instead of drawing a conclusion from noise.

Be direct and specific. Skip the encouragement; the user wants a plan, not \
reassurance.\
"""


class RecommendedAction(BaseModel):
    kind: str = Field(
        description="One of: tailor_resume, learn_skill, prep_interview, apply_now, drop."
    )
    title: str = Field(description="The action, in under ten words.")
    rationale: str = Field(
        description="Why, citing the specific figures from the input."
    )
    #: Whichever of these the action concerns; the rest stay null.
    job_id: int | None = None
    skill: str | None = None
    #: 1 is most urgent.
    priority: int = Field(ge=1, le=5)
    estimated_effort: str | None = Field(
        default=None, description="Rough time cost, e.g. '2 hours', '3 weeks'."
    )


class CareerGuidance(BaseModel):
    headline: str = Field(
        description="One sentence: the single most important thing right now."
    )
    actions: list[RecommendedAction] = Field(max_length=5)
    funnel_read: str | None = Field(
        default=None,
        description="What the funnel numbers say, or why the sample is too small.",
    )
    #: Anything the input did not contain that would change the advice.
    missing_information: list[str] = Field(default_factory=list)


def recommend(context: str) -> CareerGuidance:
    """Produce ranked next actions from a pre-computed analytics context.

    `context` is assembled by `services/context.py` — a rendered summary of the
    profile, the scored board, the skill ROI table, and the funnel report. It is
    passed as text rather than JSON because the model reasons better over a
    readable table than over nested objects, and nothing downstream parses it.

    Runs at `xhigh`: this is the product's central judgment call, and it runs
    once per visit to the action center rather than per request.
    """
    return structured_call(
        system=SYSTEM,
        user=(
            "Here is the candidate's current situation. All figures are "
            "already computed — use them as given.\n\n"
            f"{context}\n\n"
            "What should they do next?"
        ),
        output_model=CareerGuidance,
        effort="xhigh",
    )
