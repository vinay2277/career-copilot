import { useState } from "react";
import { api } from "../api";
import { Card, ErrorNote, ScoreBadge, Spinner } from "../components";
import { useAction, useAsync } from "../hooks";
import type { Screening } from "../types";

/**
 * The screening round a student sits for one application.
 *
 * Deliberately one page with every question on it, rather than a wizard. A
 * candidate should be able to see the whole round before answering any of it —
 * that is what a real screening call gives you, and it stops the format itself
 * becoming part of what is being tested.
 *
 * Submitted once and graded once. The page says so before the button, because
 * the employer reads the result and there is no retake.
 */
export default function ScreeningInterview({
  applicationId,
  onBack,
}: {
  applicationId: number;
  onBack: () => void;
}) {
  const existing = useAsync(
    () =>
      api.readInterview(applicationId).catch(() => null as Screening | null),
    [applicationId],
  );
  const act = useAction();
  const [round, setRound] = useState<Screening | null>(null);
  const [answers, setAnswers] = useState<Record<number, string>>({});

  const current = round ?? existing.data ?? null;
  const done = current?.completed_at != null;

  const start = async () => {
    const started = await act.run(() => api.startInterview(applicationId));
    if (started) setRound(started);
  };

  const submit = async () => {
    const graded = await act.run(() =>
      api.submitInterview(applicationId, answers),
    );
    if (graded) setRound(graded);
  };

  if (existing.loading) return <Spinner />;

  const answered = Object.values(answers).filter(
    (a) => a.trim().length >= 10,
  ).length;

  return (
    <>
      <div className="page-head">
        <button className="link" onClick={onBack}>
          ← My applications
        </button>
        <h1>{current?.posting_title ?? "Screening interview"}</h1>
        <p>
          {done
            ? "Submitted. The employer can see this alongside your application."
            : "A short written round. The employer reads the result."}
        </p>
      </div>

      {act.error && <ErrorNote message={act.error} onDismiss={act.clearError} />}

      {!current && (
        <Card title="Before you start">
          <p>
            This employer asks applicants a few questions about the role. They
            are written from the job description and what your profile did not
            already answer.
          </p>
          <ul>
            <li>Every question is on one page — read them all before writing.</li>
            <li>There is no timer.</li>
            <li>
              <strong>You submit once.</strong> The round is graded once and the
              employer sees it. There is no retake, so do not start until you
              have time to finish.
            </li>
          </ul>
          <button className="primary" disabled={act.pending} onClick={start}>
            {act.pending ? "Preparing your questions…" : "Start the interview"}
          </button>
        </Card>
      )}

      {current && done && (
        <Card title="Your result">
          <div className="inline" style={{ alignItems: "center", gap: "0.8rem" }}>
            {current.overall_score != null && (
              <ScoreBadge score={current.overall_score} />
            )}
            <strong>Submitted</strong>
          </div>
          {current.summary && (
            <p style={{ whiteSpace: "pre-line" }}>{current.summary}</p>
          )}
          <p className="muted small">
            This is what the employer sees. It does not decide anything by
            itself — a person at the company reviews your application and this
            together.
          </p>
        </Card>
      )}

      {current && (
        <Card title={done ? "Your answers" : `${current.turns.length} questions`}>
          {current.turns.map((turn) => (
            <div key={turn.position} className="interview-turn">
              <div className="inline" style={{ justifyContent: "space-between" }}>
                <strong>
                  {turn.position}. {turn.question}
                </strong>
                {turn.score != null && <ScoreBadge score={turn.score} />}
              </div>
              {turn.probes_skill && (
                <div className="muted small">on {turn.probes_skill}</div>
              )}

              {done ? (
                <>
                  <p style={{ whiteSpace: "pre-line" }}>
                    {turn.answer || <em className="muted">No answer given.</em>}
                  </p>
                  {turn.feedback && (
                    <p className="muted small">{turn.feedback}</p>
                  )}
                </>
              ) : (
                <textarea
                  rows={5}
                  value={answers[turn.position] ?? ""}
                  placeholder="Be specific. A real example with an outcome beats a general statement."
                  onChange={(e) =>
                    setAnswers({ ...answers, [turn.position]: e.target.value })
                  }
                />
              )}
            </div>
          ))}

          {!done && (
            <>
              <p className="muted small">
                {answered} of {current.turns.length} answered. Anything under ten
                characters counts as unanswered.
              </p>
              <button
                className="primary"
                disabled={act.pending || answered === 0}
                onClick={submit}
              >
                {act.pending ? "Grading your round…" : "Submit — this is final"}
              </button>
            </>
          )}
        </Card>
      )}
    </>
  );
}
