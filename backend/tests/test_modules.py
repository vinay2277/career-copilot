"""Tests for the twelve-module Gen AI course.

The lock is what these mostly defend. A module hidden in the UI but served by
the API is not locked, so every one of these goes through HTTP rather than
calling the service directly.
"""

from __future__ import annotations

import pytest

from app.services.curriculum import BY_SLUG, MODULES, PASS_MARK


def correct_answers(slug: str) -> dict[str, int]:
    """The right option for every question, keyed as the API expects."""
    return {str(i): q.answer for i, q in enumerate(BY_SLUG[slug].questions)}


def wrong_answers(slug: str) -> dict[str, int]:
    module = BY_SLUG[slug]
    return {
        str(i): (q.answer + 1) % len(q.options) for i, q in enumerate(module.questions)
    }


def pass_module(client, slug: str):
    response = client.post(
        f"/api/modules/{slug}/attempt", json={"answers": correct_answers(slug)}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["passed"] is True
    return body


def test_the_curriculum_is_twelve_ordered_modules():
    assert len(MODULES) == 12
    assert [m.position for m in MODULES] == list(range(1, 13))
    assert len({m.slug for m in MODULES}) == 12


def test_every_question_is_answerable():
    """A question whose answer index is out of range would be unpassable."""
    for module in MODULES:
        assert len(module.questions) >= PASS_MARK
        for q in module.questions:
            assert 0 <= q.answer < len(q.options)
            assert q.explanation


def test_only_the_first_module_starts_unlocked(student):
    rows = student.get("/api/modules").json()

    assert len(rows) == 12
    assert rows[0]["locked"] is False
    assert all(r["locked"] for r in rows[1:])
    assert not any(r["passed"] for r in rows)


def test_a_locked_module_is_refused_by_the_api(student):
    """The lock has to hold against someone typing the URL."""
    blocked = student.get(f"/api/modules/{MODULES[5].slug}")

    assert blocked.status_code == 403
    assert MODULES[4].title in blocked.json()["detail"]


def test_attempting_a_locked_module_is_refused(student):
    blocked = student.post(
        f"/api/modules/{MODULES[3].slug}/attempt",
        json={"answers": correct_answers(MODULES[3].slug)},
    )
    assert blocked.status_code == 403


def test_the_first_module_serves_its_content(student):
    body = student.get(f"/api/modules/{MODULES[0].slug}").json()

    assert body["title"] == MODULES[0].title
    assert len(body["body"]) > 500
    assert len(body["questions"]) == 3
    assert body["objectives"]


def test_questions_never_carry_their_answers(student):
    """Serving the answer with the question would make the gate decorative."""
    body = student.get(f"/api/modules/{MODULES[0].slug}").json()

    for question in body["questions"]:
        assert set(question) == {"index", "prompt", "options"}
        assert "answer" not in question
        assert "explanation" not in question


def test_passing_unlocks_exactly_the_next_module(student):
    result = pass_module(student, MODULES[0].slug)

    assert result["unlocked_module"]["slug"] == MODULES[1].slug

    rows = student.get("/api/modules").json()
    assert rows[0]["passed"] is True
    assert rows[1]["locked"] is False
    assert rows[2]["locked"] is True, "one at a time, not all of them"


def test_failing_unlocks_nothing(student):
    slug = MODULES[0].slug
    result = student.post(
        f"/api/modules/{slug}/attempt", json={"answers": wrong_answers(slug)}
    ).json()

    assert result["passed"] is False
    assert result["score"] == 0
    assert result["unlocked_module"] is None
    assert student.get("/api/modules").json()[1]["locked"] is True


def test_grading_explains_every_question(student):
    slug = MODULES[0].slug
    result = student.post(
        f"/api/modules/{slug}/attempt", json={"answers": wrong_answers(slug)}
    ).json()

    assert len(result["results"]) == 3
    for item in result["results"]:
        assert item["correct"] is False
        assert item["explanation"], "a wrong answer should teach, not just score"
        assert item["correct_option"] is not None


def test_one_wrong_out_of_three_still_passes(student):
    """Two of three: one slip should not send somebody back through it."""
    slug = MODULES[0].slug
    answers = correct_answers(slug)
    answers["0"] = (BY_SLUG[slug].questions[0].answer + 1) % 4

    result = student.post(
        f"/api/modules/{slug}/attempt", json={"answers": answers}
    ).json()

    assert result["score"] == 2
    assert result["passed"] is True


def test_a_missing_answer_counts_as_wrong(student):
    slug = MODULES[0].slug
    result = student.post(f"/api/modules/{slug}/attempt", json={"answers": {}}).json()

    assert result["score"] == 0
    assert all(r["chosen"] is None for r in result["results"])


def test_retrying_is_allowed_and_keeps_the_best_score(student):
    """A course, not an exam — and a re-read must never cost you the pass."""
    slug = MODULES[0].slug
    student.post(f"/api/modules/{slug}/attempt", json={"answers": wrong_answers(slug)})
    pass_module(student, slug)

    failed_again = student.post(
        f"/api/modules/{slug}/attempt", json={"answers": wrong_answers(slug)}
    ).json()

    assert failed_again["passed"] is False
    assert failed_again["already_passed"] is True, "the earlier pass stands"

    row = student.get("/api/modules").json()[0]
    assert row["passed"] is True
    assert row["best_score"] == 3
    assert row["attempts"] == 3


def test_working_all_the_way_through(student):
    """Twelve passes in order opens everything and locks nothing."""
    for module in MODULES:
        assert student.get(f"/api/modules/{module.slug}").status_code == 200
        pass_module(student, module.slug)

    rows = student.get("/api/modules").json()
    assert all(r["passed"] for r in rows)
    assert not any(r["locked"] for r in rows)

    # Nothing to unlock after the last one.
    last = student.post(
        f"/api/modules/{MODULES[-1].slug}/attempt",
        json={"answers": correct_answers(MODULES[-1].slug)},
    ).json()
    assert last["unlocked_module"] is None


def test_progress_is_per_student(api):
    """One student's pass must not unlock anything for another."""
    from tests.conftest import register_student

    register_student(api, email="first@example.com")
    pass_module(api, MODULES[0].slug)
    assert api.get("/api/modules").json()[1]["locked"] is False

    api.post("/api/auth/logout")
    register_student(api, email="second@example.com")

    rows = api.get("/api/modules").json()
    assert rows[0]["passed"] is False
    assert rows[1]["locked"] is True


def test_an_unknown_module_is_404(student):
    assert student.get("/api/modules/not-a-module").status_code == 404
    assert (
        student.post("/api/modules/not-a-module/attempt", json={"answers": {}}).status_code
        == 404
    )


def test_a_recruiter_has_no_course(recruiter):
    assert recruiter.get("/api/modules").status_code == 403


def test_signed_out_is_refused(client):
    assert client.get("/api/modules").status_code == 401


@pytest.mark.parametrize("module", MODULES, ids=lambda m: m.slug)
def test_every_module_has_real_content(module):
    """Guards against a placeholder module shipping as if it were finished."""
    assert len(module.body) > 400, f"{module.slug} body is too short to teach anything"
    assert len(module.objectives) >= 3
    assert module.minutes > 0
    assert module.summary
