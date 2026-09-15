import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Card, Empty, ErrorNote, ScoreBar, Spinner, formatDate } from "../components";
import { useAction, useAsync } from "../hooks";
import type { InterviewKind, InterviewSession } from "../types";

const KINDS: { id: InterviewKind; label: string; hint: string }[] = [
  { id: "screening", label: "Screening", hint: "Motivation, availability, salary. Fast filtering." },
  { id: "behavioral", label: "Behavioral", hint: "Past situations. Each question wants a specific story." },
  { id: "technical", label: "Technical", hint: "Concrete problems in the posting's own stack." },
  { id: "system_design", label: "System design", hint: "One open problem sized to the seniority." },
];

export default function InterviewPrep() {
  // Practise against the open roles on the board. This used to read the
  // student's own pasted-in job tracker, which no longer exists — and the
  // board is the better list anyway, since these are roles they can apply to.
  const board = useAsync(
    () => api.board().then((b) => [...b.from_employers, ...b.sourced]),
    [],
  );
  const sessions = useAsync(() => api.listSessions(), []);
  const start = useAction();

  const [active, setActive] = useState<InterviewSession | null>(null);
  const [jobId, setJobId] = useState<number | "">("");
  const [kind, setKind] = useState<InterviewKind>("behavioral");
  const [count, setCount] = useState(5);

  const begin = async () => {
    if (jobId === "") return;
    const session = await start.run(() => api.startSession(Number(jobId), kind, count));
    if (session) {
      setActive(session);
      sessions.reload();
    }
  };

  if (active) {
    return (
      <ActiveSession
        session={active}
        onExit={() => {
          setActive(null);
          sessions.reload();
        }}
      />
    );
  }

  const jobs = board.data ?? [];

  return (
    <>
      <div className="page-head">
        <h1>Interview prep</h1>
        <p>
          Questions are generated from the posting itself and weighted toward the
          gaps the alignment scorer found — that's where a real interview presses
          hardest.
        </p>
      </div>

      {start.error && <ErrorNote message={start.error} onDismiss={start.clearError} />}

      <Card title="Start a round">
        {jobs.length === 0 ? (
          <p className="muted">
            No open roles yet. <Link to="/jobs">Check the job board</Link> —
            questions are grounded in a specific posting.
          </p>
        ) : (
          <>
            <div className="row">
              <label style={{ flex: "3 1 220px" }}>
                Job
                <select
                  value={jobId}
                  onChange={(e) => setJobId(e.target.value ? Number(e.target.value) : "")}
                >
                  <option value="">Choose a posting…</option>
                  {jobs.map((entry) => (
                    <option key={entry.posting.id} value={entry.posting.id}>
                      {entry.posting.title} — {entry.posting.company_name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Round
                <select
                  value={kind}
                  onChange={(e) => setKind(e.target.value as InterviewKind)}
                >
                  {KINDS.map((k) => (
                    <option key={k.id} value={k.id}>
                      {k.label}
                    </option>
                  ))}
                </select>
              </label>
              <label style={{ flex: "0 1 100px" }}>
                Questions
                <input
                  type="number"
                  min={1}
                  max={15}
                  value={count}
                  onChange={(e) => setCount(Number(e.target.value))}
                />
              </label>
              <button
                className="primary"
                disabled={start.pending || jobId === ""}
                onClick={begin}
              >
                {start.pending ? "Generating…" : "Begin"}
              </button>
            </div>
            <p className="muted small">{KINDS.find((k) => k.id === kind)?.hint}</p>
          </>
        )}
      </Card>

      <Card title="Past rounds">
        {sessions.loading ? (
          <Spinner />
        ) : (sessions.data ?? []).length === 0 ? (
          <p className="muted">Nothing yet.</p>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Round</th>
                  <th className="num">Answered</th>
                  <th className="num">Score</th>
                  <th>When</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {(sessions.data ?? []).map((s) => (
                  <tr key={s.id}>
                    <td>{s.kind.replace("_", " ")}</td>
                    <td className="num">
                      {s.turns.filter((t) => t.answer).length}/{s.turns.length}
                    </td>
                    <td className="num">
                      {s.overall_score == null ? "—" : s.overall_score.toFixed(0)}
                    </td>
                    <td className="small muted">{formatDate(s.created_at)}</td>
                    <td>
                      <button className="link" onClick={() => setActive(s)}>
                        open
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

function ActiveSession({
  session,
  onExit,
}: {
  session: InterviewSession;
  onExit: () => void;
}) {
  const [current, setCurrent] = useState(session);
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const answer = useAction();
  const finish = useAction();

  const submit = async (position: number) => {
    const text = (drafts[position] ?? "").trim();
    if (!text) return;
    const graded = await answer.run(() => api.submitAnswer(current.id, position, text));
    if (graded) {
      setCurrent({
        ...current,
        turns: current.turns.map((t) => (t.position === position ? graded : t)),
      });
    }
  };

  const complete = async () => {
    const summarized = await finish.run(() => api.completeSession(current.id));
    if (summarized) setCurrent(summarized);
  };

  const answered = current.turns.filter((t) => t.answer).length;

  return (
    <>
      <div className="page-head">
        <button className="link" onClick={onExit}>
          ← back to interview prep
        </button>
        <h1 style={{ marginTop: "0.4rem" }}>{current.kind.replace("_", " ")} round</h1>
        <p>
          {answered} of {current.turns.length} answered. Feedback is deliberately
          blunt — a mock round that flatters costs you the real one.
        </p>
      </div>

      {answer.error && <ErrorNote message={answer.error} onDismiss={answer.clearError} />}
      {finish.error && <ErrorNote message={finish.error} onDismiss={finish.clearError} />}

      {current.overall_score != null && (
        <Card title="Session summary">
          <ScoreBar score={current.overall_score} label="Overall" />
          <pre style={{ marginTop: "0.7rem" }}>{current.summary}</pre>
        </Card>
      )}

      {current.turns.map((turn) => (
        <Card key={turn.id}>
          <div className="action-head">
            <span className="priority">{turn.position + 1}</span>
            <strong>{turn.question}</strong>
            {turn.probes_skill && (
              <span className="chip chip-partial">probes {turn.probes_skill}</span>
            )}
          </div>

          {turn.answer ? (
            <>
              <p className="small" style={{ whiteSpace: "pre-wrap" }}>
                {turn.answer}
              </p>
              {turn.score != null && <ScoreBar score={turn.score} label="Scored" />}
              {turn.feedback && <p className="small">{turn.feedback}</p>}
              {turn.improvements?.length ? (
                <>
                  <h3>Rewrite these</h3>
                  <ul className="clean small">
                    {turn.improvements.map((imp, i) => (
                      <li key={i}>{imp}</li>
                    ))}
                  </ul>
                </>
              ) : null}
            </>
          ) : (
            <>
              <textarea
                value={drafts[turn.position] ?? ""}
                placeholder="Answer as you would out loud…"
                onChange={(e) =>
                  setDrafts({ ...drafts, [turn.position]: e.target.value })
                }
              />
              <button
                className="primary"
                disabled={answer.pending || !(drafts[turn.position] ?? "").trim()}
                onClick={() => void submit(turn.position)}
                style={{ marginTop: "0.5rem" }}
              >
                {answer.pending ? "Grading…" : "Submit answer"}
              </button>
            </>
          )}
        </Card>
      ))}

      {answered > 0 && current.overall_score == null && (
        <button className="primary" disabled={finish.pending} onClick={complete}>
          {finish.pending ? "Summarizing…" : `Finish and grade the round (${answered} answered)`}
        </button>
      )}

      {current.turns.length === 0 && <Empty title="No questions in this session" />}
    </>
  );
}
