"""Progress through the twelve-module Gen AI curriculum.

Two rules the rest of the module exists to enforce.

**The lock is server-side.** A module's content is only returned once the one
before it has been passed. Hiding a locked module in the UI while the API would
still serve it is not a lock, it is a suggestion — and the first person to open
the network tab would find that out.

**Answers are never sent before an attempt is graded.** The correct index and
the explanation live on the same objects as the question text, so every
serialisation runs through here rather than dumping the dataclass.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ModuleProgress, Profile
from app.services.curriculum import BY_SLUG, MODULES, PASS_MARK, Module

logger = logging.getLogger(__name__)


class ModuleError(RuntimeError):
    """Something the caller should turn into a 4xx with this message."""


def _progress(db: Session, profile: Profile) -> dict[str, ModuleProgress]:
    return {
        row.module_slug: row
        for row in db.execute(
            select(ModuleProgress).where(ModuleProgress.profile_id == profile.id)
        ).scalars()
    }


def is_passed(row: ModuleProgress | None) -> bool:
    return row is not None and row.completed_at is not None


def unlocked_through(progress: dict[str, ModuleProgress]) -> int:
    """The highest position a student may currently open.

    One past their last consecutive pass. Consecutive matters: if a slug were
    ever removed from the curriculum, a student who had passed around the gap
    should not find everything after it locked forever.
    """
    highest = 1
    for module in MODULES:
        if is_passed(progress.get(module.slug)):
            highest = module.position + 1
        else:
            break
    return min(highest, len(MODULES))


def overview(db: Session, profile: Profile) -> list[dict]:
    """Every module with its state, for the tab's index.

    Carries no question text at all. The index is a list of what you have done
    and what is next, and there is no reason for it to ship the material.
    """
    progress = _progress(db, profile)
    ceiling = unlocked_through(progress)

    out = []
    for module in MODULES:
        row = progress.get(module.slug)
        passed = is_passed(row)
        out.append(
            {
                "slug": module.slug,
                "position": module.position,
                "title": module.title,
                "summary": module.summary,
                "minutes": module.minutes,
                "objectives": module.objectives,
                "question_count": len(module.questions),
                "pass_mark": PASS_MARK,
                "locked": module.position > ceiling,
                "passed": passed,
                "best_score": row.best_score if row else 0,
                "attempts": row.attempts if row else 0,
                "completed_at": row.completed_at if row else None,
            }
        )
    return out


def read(db: Session, profile: Profile, slug: str) -> dict:
    """One module's content, if the student has reached it.

    The questions come back without their answers or explanations — those are
    added by `attempt`, after there is something to explain.
    """
    module = BY_SLUG.get(slug)
    if module is None:
        raise ModuleError("No such module.")

    progress = _progress(db, profile)
    if module.position > unlocked_through(progress):
        previous = MODULES[module.position - 2]
        raise ModuleError(
            f"Finish “{previous.title}” first — the modules build on each other."
        )

    row = progress.get(slug)
    return {
        "slug": module.slug,
        "position": module.position,
        "title": module.title,
        "summary": module.summary,
        "minutes": module.minutes,
        "objectives": module.objectives,
        "body": module.body,
        "pass_mark": PASS_MARK,
        "questions": [
            {
                "index": i,
                "prompt": q.prompt,
                "options": q.options,
            }
            for i, q in enumerate(module.questions)
        ],
        "passed": is_passed(row),
        "best_score": row.best_score if row else 0,
        "attempts": row.attempts if row else 0,
    }


def attempt(
    db: Session, profile: Profile, slug: str, answers: dict[int, int]
) -> dict:
    """Grade an attempt, record it, and return what was right and why.

    Unlimited attempts on purpose. This is a course, not an exam: somebody who
    gets it wrong should read the explanations and try again, and a lockout
    would only teach them to look the answers up elsewhere. What is recorded is
    the *best* score, so re-reading a module you have passed can never cost you
    the pass.
    """
    module = BY_SLUG.get(slug)
    if module is None:
        raise ModuleError("No such module.")

    progress = _progress(db, profile)
    if module.position > unlocked_through(progress):
        raise ModuleError("This module is not unlocked yet.")

    results = []
    correct = 0
    for i, question in enumerate(module.questions):
        chosen = answers.get(i)
        right = chosen == question.answer
        correct += right
        results.append(
            {
                "index": i,
                "chosen": chosen,
                "correct_option": question.answer,
                "correct": right,
                "explanation": question.explanation,
            }
        )

    passed_now = correct >= PASS_MARK

    row = progress.get(slug)
    if row is None:
        # `default=0` on the column is applied by the INSERT, not by the
        # constructor — so a row that has not been flushed yet has None in
        # these fields, and `+= 1` on it raises. Set them here rather than
        # relying on a default that has not run.
        row = ModuleProgress(
            profile_id=profile.id, module_slug=slug, best_score=0, attempts=0
        )
        db.add(row)

    row.attempts += 1
    row.best_score = max(row.best_score, correct)
    if passed_now and row.completed_at is None:
        row.completed_at = datetime.now(UTC)

    db.commit()
    db.refresh(row)

    unlocked = _newly_unlocked(db, profile, module) if passed_now else None
    logger.info(
        "profile %s attempted %s: %s/%s%s",
        profile.id,
        slug,
        correct,
        len(module.questions),
        " (passed)" if passed_now else "",
    )

    return {
        "slug": slug,
        "score": correct,
        "total": len(module.questions),
        "pass_mark": PASS_MARK,
        "passed": passed_now,
        "already_passed": row.completed_at is not None and not passed_now,
        "results": results,
        "unlocked_module": unlocked,
    }


def _newly_unlocked(db: Session, profile: Profile, just_passed: Module) -> dict | None:
    """The module this pass opened, so the UI can point at it."""
    nxt = next(
        (m for m in MODULES if m.position == just_passed.position + 1), None
    )
    if nxt is None:
        return None
    if unlocked_through(_progress(db, profile)) < nxt.position:
        return None
    return {"slug": nxt.slug, "position": nxt.position, "title": nxt.title}
