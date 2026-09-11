"""Mock interview: question generation and answer feedback.

Split into two calls rather than one conversation, because grading wants to see
the answer cold. A single stateful chat lets the interviewer's own framing leak
into its assessment of the reply.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.agents.client import structured_call

# --------------------------------------------------------------------------- #
# Question generation
# --------------------------------------------------------------------------- #

QUESTION_SYSTEM = """\
You are an interviewer preparing a mock round for one specific job.

Generate questions that this posting would actually produce. Ground every \
question in the posting's stated requirements — if it emphasizes incident \
response, ask about incident response. Generic questions waste the session.

Weight toward the candidate's known gaps. Those are where a real interview will \
probe hardest, and where practice is worth most. Set `probes_skill` to the \
requirement each question targets so the session can be scored against the \
same gap list the alignment scorer produced.

Match the round type requested:

- `screening` — motivation, availability, salary, a light pass over the resume. \
  Short, fast, mostly filtering.
- `behavioral` — past situations, collaboration, conflict, failure. Each \
  question should demand a specific story, not a philosophy.
- `technical` — concrete problems in the posting's actual stack. Ask what they \
  would do, not what a term means.
- `system_design` — one open-ended design problem sized to the seniority in the \
  posting, plus follow-ups that tighten constraints.

Ask one thing per question. A two-part question gets a half answer to each half.\
"""


class GeneratedQuestion(BaseModel):
    question: str
    probes_skill: str | None = Field(
        default=None, description="Requirement name this question targets."
    )
    #: What a strong answer contains. Used to grade, and shown after the answer.
    looking_for: str


class QuestionSet(BaseModel):
    questions: list[GeneratedQuestion]
    opening_note: str = Field(
        description="One or two sentences framing the round for the candidate."
    )


def generate_questions(
    job_text: str,
    kind: str,
    missing_skills: list[str],
    count: int = 5,
) -> QuestionSet:
    """Build a mock round of `count` questions for one job."""
    gaps = ", ".join(missing_skills) if missing_skills else "none identified"
    user = (
        f"<target_job>\n{job_text}\n</target_job>\n\n"
        f"<round_type>{kind}</round_type>\n"
        f"<question_count>{count}</question_count>\n"
        f"<candidate_gaps>{gaps}</candidate_gaps>\n\n"
        "Generate the round."
    )
    return structured_call(
        system=QUESTION_SYSTEM,
        user=user,
        output_model=QuestionSet,
        effort="high",
    )


# --------------------------------------------------------------------------- #
# Answer feedback
# --------------------------------------------------------------------------- #

FEEDBACK_SYSTEM = """\
You grade one interview answer. You see the question, what a strong answer \
needs, and what the candidate said.

Score 0-100 on the answer as delivered — not on the candidate's potential, and \
not on what they probably meant. An interviewer only hears what was said.

Anchors:
- 85-100: answers the question, specific, evidenced, appropriately scoped.
- 70-85: solid and relevant, but thin on specifics or missing one dimension.
- 50-70: on topic, but vague, generic, or answering an adjacent question.
- 25-50: barely engages the question, or is confidently wrong.
- 0-25: no answer, or answers something else entirely.

In `feedback`, lead with the single most important thing — good or bad. Be \
concrete: quote the phrase that worked or the one that didn't.

In `improvements`, give rewrites, not advice. "Be more specific" is not \
actionable; "replace 'improved performance' with the actual latency drop" is. \
Two to four items.

For behavioral answers, check the structure is complete: situation, what they \
personally did, and the outcome with its magnitude. Missing outcome is the most \
common failure — flag it every time.

Do not soften a weak answer. Mock interview feedback that flatters is the one \
kind that actively costs the candidate the real interview.\
"""


class AnswerFeedback(BaseModel):
    score: float = Field(ge=0.0, le=100.0)
    feedback: str
    improvements: list[str] = Field(default_factory=list)
    #: True when the answer never addressed what was asked, regardless of
    #: quality. Surfaced separately because it needs a different fix.
    answered_the_question: bool = True


def grade_answer(
    question: str,
    looking_for: str,
    answer: str,
) -> AnswerFeedback:
    """Grade one answer against what the question was looking for."""
    user = (
        f"<question>\n{question}\n</question>\n\n"
        f"<strong_answer_contains>\n{looking_for}\n</strong_answer_contains>\n\n"
        f"<candidate_answer>\n{answer}\n</candidate_answer>"
    )
    return structured_call(
        system=FEEDBACK_SYSTEM,
        user=user,
        output_model=AnswerFeedback,
        effort="high",
    )


# --------------------------------------------------------------------------- #
# Session summary
# --------------------------------------------------------------------------- #

SUMMARY_SYSTEM = """\
You summarize a completed mock interview from its per-answer grades.

Name the pattern, not the individual scores — the candidate can already see \
those. If three answers all lacked outcomes, that one habit is the finding. If \
the technical answers were strong and the behavioral ones vague, say that; it \
changes what they practise next.

Give them the two things to work on before the real round. Two, not six.\
"""


class SessionSummary(BaseModel):
    overall_score: float = Field(ge=0.0, le=100.0)
    summary: str
    focus_before_the_real_thing: list[str] = Field(max_length=2)


def summarize_session(graded: list[dict]) -> SessionSummary:
    """Turn per-answer grades into a session-level read.

    `graded` is a list of `{question, answer, score, feedback}` dicts. The
    overall score is the model's judgment rather than a mean: five mediocre
    answers and one disqualifying one do not average out in a real interview.
    """
    lines = [
        f"Q{i + 1} (scored {g['score']:.0f}): {g['question']}\n"
        f"  Answer: {g['answer']}\n"
        f"  Feedback given: {g['feedback']}"
        for i, g in enumerate(graded)
    ]
    return structured_call(
        system=SUMMARY_SYSTEM,
        user="\n\n".join(lines),
        output_model=SessionSummary,
        effort="medium",
    )
