"""Learning roadmap generation.

Takes the skill ROI engine's ranking — which is deterministic — and turns the
top entries into a sequenced plan. The agent decides ordering, scope and proof
of work; it does not decide which skills matter, because that was already
computed from the actual job board.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.client import structured_call

SYSTEM = """\
You build learning roadmaps for a candidate closing specific skill gaps.

The skills and their payoffs are given to you, already computed from the \
candidate's real job board. Do not re-rank them by your own sense of what is \
important, and do not substitute a skill you think is more fashionable.

What you decide is the path:

1. **Order by dependency, then by payoff.** If one target skill is a \
   prerequisite for another, it goes first regardless of ROI. Otherwise the \
   highest-payoff skill leads, because motivation decays.
2. **Size each step to one sitting or one weekend.** A step called "learn \
   Kubernetes" never gets started. "Deploy a two-service app to a local kind \
   cluster" does.
3. **Every step needs a proof of work** — something that exists when the step \
   is done. A running deployment, a passing test suite, a written explanation, \
   a merged PR. Reading is not a step; reading toward something you then build \
   is.
4. **Estimate hours honestly** for someone holding a full-time job. Rounding \
   down here is how plans get abandoned in week two.
5. **Total under 40 hours per skill.** The goal is working proficiency — enough \
   to claim the skill in an interview and defend it — not mastery. Say so if a \
   target genuinely cannot reach that bar in the time.

For `resource_url`, name a specific canonical source when you are confident it \
exists — official documentation, a well-known course, a specific book. Leave it \
null rather than guessing a URL; a dead link is worse than none.

In `rationale`, tie the plan back to the payoff figures you were given, so the \
candidate can see why this order.\
"""


class RoadmapStep(BaseModel):
    title: str = Field(description="The concrete thing to build or do.")
    skill: str = Field(description="Which target skill this step advances.")
    estimated_hours: float
    resource_url: str | None = Field(
        default=None, description="A canonical source, or null if unsure."
    )
    proof_of_work: str = Field(description="What exists when this step is done.")


class LearningRoadmap(BaseModel):
    title: str = Field(description="Short name for the plan.")
    target_skills: list[str]
    rationale: str = Field(
        description="Why this order, citing the given payoff figures."
    )
    steps: list[RoadmapStep]
    #: Anything the candidate should know before starting — a real prerequisite
    #: they appear to lack, or a target that won't fit the hour budget.
    caveats: list[str] = Field(default_factory=list)


def build_roadmap(
    skill_payoffs: str,
    current_skills: list[str],
    hours_per_week: float = 6.0,
) -> LearningRoadmap:
    """Sequence a roadmap for the given skill gaps.

    `skill_payoffs` is a rendered table from the skill ROI engine (skill, jobs
    unlocked, mean point gain). Passed as text because the agent reasons over it
    rather than parsing it.
    """
    have = ", ".join(sorted(current_skills)) if current_skills else "none recorded"
    user = (
        f"<skill_payoffs>\n{skill_payoffs}\n</skill_payoffs>\n\n"
        f"<already_has>{have}</already_has>\n"
        f"<available_hours_per_week>{hours_per_week}</available_hours_per_week>\n\n"
        "Build the roadmap."
    )
    return structured_call(
        system=SYSTEM,
        user=user,
        output_model=LearningRoadmap,
        effort="high",
    )
