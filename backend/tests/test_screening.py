"""Tests for the screening interview attached to an application.

The model calls are stubbed throughout. Two reasons: the suite must run with no
credentials and cost nothing, and what is worth testing here is not the model's
judgement but everything around it — who may sit a round, who may read it,
whether it can be retaken, and above all that a score never moves anybody's
application by itself.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.agents.interview import (
    GeneratedQuestion,
    QuestionSet,
    ScreeningAnswerGrade,
    ScreeningResult,
)
from app.models import InterviewSession
from app.services import screening
from tests.conftest import HR_PASSWORD, register_hr, register_student
from tests.test_postings import DRAFT, verify_organization

STUDENT_PASSWORD = "student-password-123"
INTERVIEW_DRAFT = {**DRAFT, "interview_required": True, "interview_question_count": 3}


@pytest.fixture
def stub_agents(monkeypatch):
    """Replace both model calls. Records how many times each was used."""
    calls = {"generate": 0, "grade": 0}

    def fake_generate(job_text, kind, missing_skills, count=5):
        calls["generate"] += 1
        return QuestionSet(
            questions=[
                GeneratedQuestion(
                    question=f"Question {i} about {kind}?",
                    probes_skill=(missing_skills or ["python"])[0],
                    looking_for="A specific example with an outcome.",
                )
                for i in range(1, count + 1)
            ],
            opening_note="Three questions, roughly ten minutes.",
        )

    def fake_grade(job_text, answers):
        calls["grade"] += 1
        return ScreeningResult(
            grades=[
                ScreeningAnswerGrade(
                    position=a["position"],
                    score=80.0 if a["answer"] else 0.0,
                    feedback="Concrete." if a["answer"] else "No answer given.",
                    answered_the_question=bool(a["answer"]),
                )
                for a in answers
            ],
            overall_score=76.5,
            recommendation="Handles pipelines well; shallow on orchestration.",
            strengths=["Clear on failure modes"],
            concerns=["No Airflow in production"],
        )

    monkeypatch.setattr(screening, "generate_questions", fake_generate)
    monkeypatch.setattr(screening, "grade_screening", fake_grade)
    return calls


def sign_in_recruiter(client, email="recruiter@acme.com"):
    client.post("/api/auth/logout")
    response = client.post(
        "/api/auth/login", json={"email": email, "password": HR_PASSWORD}
    )
    assert response.status_code == 200, response.text


def sign_in_student(client, email="student@example.com"):
    client.post("/api/auth/logout")
    response = client.post(
        "/api/auth/login", json={"email": email, "password": STUDENT_PASSWORD}
    )
    assert response.status_code == 200, response.text


@pytest.fixture
def applied(api, db_session):
    """A published role that screens, with one applicant signed in."""
    register_hr(api)
    verify_organization(db_session)
    posting_id = api.post("/api/employer/postings", json=INTERVIEW_DRAFT).json()["id"]
    assert api.post(f"/api/employer/postings/{posting_id}/publish").status_code == 200

    api.post("/api/auth/logout")
    register_student(api)
    api.put(
        "/api/profile",
        json={
            "full_name": "Test Student",
            "email": "student@example.com",
            "headline": None,
            "years_experience": 3,
            "career_goal": None,
            "skills": [{"name": "python", "proficiency": "working", "years": 3}],
            "preferences": None,
        },
    )
    application = api.post(f"/api/board/postings/{posting_id}/apply", json={})
    assert application.status_code == 201, application.text
    return posting_id, application.json()["id"]


def test_the_posting_says_it_screens(api, db_session):
    register_hr(api)
    verify_organization(db_session)
    created = api.post("/api/employer/postings", json=INTERVIEW_DRAFT).json()

    assert created["interview_required"] is True
    assert created["interview_question_count"] == 3


def test_every_role_screens_unless_turned_off(api, db_session):
    """Every applicant answering for themselves is the point of the platform.

    A recruiter can still turn it off for a role where it does not fit, but
    they have to choose to — the default is that candidates are heard.
    """
    register_hr(api)
    verify_organization(db_session)

    on_by_default = api.post("/api/employer/postings", json=DRAFT).json()
    assert on_by_default["interview_required"] is True
    assert on_by_default["interview_question_count"] == 4

    turned_off = api.post(
        "/api/employer/postings",
        json={**DRAFT, "title": "No round", "interview_required": False},
    ).json()
    assert turned_off["interview_required"] is False


def test_start_generates_questions_without_revealing_the_answers(
    api, applied, stub_agents
):
    _, application_id = applied
    started = api.post(f"/api/board/applications/{application_id}/interview")

    assert started.status_code == 201, started.text
    body = started.json()
    assert len(body["turns"]) == 3
    assert body["overall_score"] is None
    assert all(t["answer"] is None for t in body["turns"])
    # `looking_for` is held in the feedback column until grading. Leaking it
    # would turn the round into a reading exercise.
    assert all(t["feedback"] is None for t in body["turns"])
    assert stub_agents["generate"] == 1


def test_a_round_cannot_be_restarted(api, applied, stub_agents):
    _, application_id = applied
    api.post(f"/api/board/applications/{application_id}/interview")
    again = api.post(f"/api/board/applications/{application_id}/interview")

    assert again.status_code == 409
    assert "already started" in again.json()["detail"]
    assert stub_agents["generate"] == 1, "a refused restart must not cost a call"


def test_submitting_grades_the_whole_round_in_one_call(api, applied, stub_agents):
    _, application_id = applied
    api.post(f"/api/board/applications/{application_id}/interview")

    submitted = api.post(
        f"/api/board/applications/{application_id}/interview/submit",
        json={
            "answers": {
                "1": "We ran nightly batch loads and cut the window from 6h to 40m.",
                "2": "I owned the retry logic after a partial-write incident.",
                "3": "I have only used Airflow on side projects, not in production.",
            }
        },
    )
    assert submitted.status_code == 200, submitted.text
    body = submitted.json()

    assert body["overall_score"] == 76.5
    assert "orchestration" in body["summary"]
    assert [t["score"] for t in body["turns"]] == [80.0, 80.0, 80.0]
    assert all(t["feedback"] for t in body["turns"])
    assert stub_agents["grade"] == 1, "the whole round is graded in one pass"


def test_two_model_calls_per_candidate(api, applied, stub_agents):
    """The cost contract, asserted rather than assumed."""
    _, application_id = applied
    api.post(f"/api/board/applications/{application_id}/interview")
    api.post(
        f"/api/board/applications/{application_id}/interview/submit",
        json={"answers": {"1": "A real answer about batch pipelines and outcomes."}},
    )

    assert stub_agents == {"generate": 1, "grade": 1}


def test_unanswered_questions_are_graded_as_unanswered(api, applied, stub_agents):
    """Skipping what you cannot answer must not improve your score."""
    _, application_id = applied
    api.post(f"/api/board/applications/{application_id}/interview")

    body = api.post(
        f"/api/board/applications/{application_id}/interview/submit",
        json={"answers": {"1": "A real answer with specifics and an outcome.", "2": ""}},
    ).json()

    scores = {t["position"]: t["score"] for t in body["turns"]}
    assert scores[1] == 80.0
    assert scores[2] == 0.0
    assert scores[3] == 0.0


def test_a_blank_round_is_refused(api, applied, stub_agents):
    _, application_id = applied
    api.post(f"/api/board/applications/{application_id}/interview")

    refused = api.post(
        f"/api/board/applications/{application_id}/interview/submit",
        json={"answers": {"1": "ok", "2": "", "3": "n/a"}},
    )
    assert refused.status_code == 409
    assert "at least one" in refused.json()["detail"]
    assert stub_agents["grade"] == 0, "a refused round must not cost a call"


def test_a_round_cannot_be_resubmitted(api, applied, stub_agents):
    _, application_id = applied
    api.post(f"/api/board/applications/{application_id}/interview")
    payload = {"answers": {"1": "A real answer with specifics and an outcome."}}
    api.post(f"/api/board/applications/{application_id}/interview/submit", json=payload)

    again = api.post(
        f"/api/board/applications/{application_id}/interview/submit", json=payload
    )
    assert again.status_code == 409
    assert stub_agents["grade"] == 1


def test_another_student_cannot_touch_the_round(api, applied, stub_agents):
    _, application_id = applied
    api.post(f"/api/board/applications/{application_id}/interview")

    api.post("/api/auth/logout")
    register_student(api, email="other@example.com")

    assert api.get(f"/api/board/applications/{application_id}/interview").status_code == 404
    assert (
        api.post(f"/api/board/applications/{application_id}/interview").status_code == 404
    )


def test_a_role_that_does_not_screen_refuses_to_start_one(api, db_session):
    register_hr(api)
    verify_organization(db_session)
    posting_id = api.post(
        "/api/employer/postings", json={**DRAFT, "interview_required": False}
    ).json()["id"]
    api.post(f"/api/employer/postings/{posting_id}/publish")

    api.post("/api/auth/logout")
    register_student(api)
    application_id = api.post(
        f"/api/board/postings/{posting_id}/apply", json={}
    ).json()["id"]

    refused = api.post(f"/api/board/applications/{application_id}/interview")
    assert refused.status_code == 409
    assert "does not ask for an interview" in refused.json()["detail"]


def test_the_recruiter_sees_the_result(api, applied, stub_agents):
    posting_id, application_id = applied
    api.post(f"/api/board/applications/{application_id}/interview")
    api.post(
        f"/api/board/applications/{application_id}/interview/submit",
        json={"answers": {"1": "A real answer with specifics and an outcome."}},
    )

    sign_in_recruiter(api)
    candidate = api.get(
        f"/api/employer/postings/{posting_id}/applications"
    ).json()["candidates"][0]

    assert candidate["interview_status"] == "completed"
    assert candidate["interview_score"] == 76.5
    assert "orchestration" in candidate["interview_summary"]


def test_the_recruiter_sees_who_has_not_sat_it_yet(api, applied, stub_agents):
    posting_id, _ = applied
    sign_in_recruiter(api)

    candidate = api.get(
        f"/api/employer/postings/{posting_id}/applications"
    ).json()["candidates"][0]

    assert candidate["interview_status"] == "required"
    assert candidate["interview_score"] is None


def test_the_score_moves_nobody(api, applied, stub_agents):
    """The rule this whole feature is built around.

    An interview is graded and the candidate's application stays exactly where
    it was. Every advance and every rejection is a person's action.
    """
    posting_id, application_id = applied
    before = api.get("/api/board/applications").json()[0]["application"]["status"]

    api.post(f"/api/board/applications/{application_id}/interview")
    api.post(
        f"/api/board/applications/{application_id}/interview/submit",
        json={"answers": {"1": "A real answer with specifics and an outcome."}},
    )

    after = api.get("/api/board/applications").json()[0]["application"]["status"]
    assert before == after == "applied"

    sign_in_recruiter(api)
    candidate = api.get(
        f"/api/employer/postings/{posting_id}/applications"
    ).json()["candidates"][0]
    assert candidate["status"] == "applied", (
        "a 76.5 neither shortlists nor rejects anybody"
    )


def test_the_export_carries_the_interview_columns(api, applied, stub_agents):
    posting_id, application_id = applied
    api.post(f"/api/board/applications/{application_id}/interview")
    api.post(
        f"/api/board/applications/{application_id}/interview/submit",
        json={"answers": {"1": "A real answer with specifics and an outcome."}},
    )

    sign_in_recruiter(api)
    text = api.get(
        f"/api/employer/postings/{posting_id}/applications.csv"
    ).content.decode("utf-8-sig")

    header, row = text.splitlines()[0], text.splitlines()[1]
    assert "interview_score" in header
    assert "76.5" in row


def test_the_question_count_is_capped(api, db_session, stub_agents):
    """A posting asking for forty questions gets the ceiling, not forty."""
    register_hr(api)
    verify_organization(db_session)
    posting_id = api.post(
        "/api/employer/postings",
        json={**DRAFT, "interview_required": True, "interview_question_count": 8},
    ).json()["id"]
    api.post(f"/api/employer/postings/{posting_id}/publish")

    api.post("/api/auth/logout")
    register_student(api)
    application_id = api.post(
        f"/api/board/postings/{posting_id}/apply", json={}
    ).json()["id"]

    body = api.post(f"/api/board/applications/{application_id}/interview").json()
    assert len(body["turns"]) <= screening.MAX_INTERVIEW_QUESTIONS


def test_one_session_per_application(api, applied, stub_agents, db_session):
    _, application_id = applied
    api.post(f"/api/board/applications/{application_id}/interview")

    with db_session() as db:
        sessions = list(
            db.execute(
                select(InterviewSession).where(
                    InterviewSession.application_id == application_id
                )
            ).scalars()
        )
    assert len(sessions) == 1
