import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Card, Empty, ErrorNote, Spinner } from "../components";
import { useAction } from "../hooks";
import type { Guidance } from "../types";

/** Where each recommendation kind sends you. */
const DESTINATION: Record<string, { label: string; to: string } | undefined> = {
  tailor_resume: { label: "Tailor the resume", to: "/opportunities" },
  learn_skill: { label: "Build a roadmap", to: "/learning" },
  prep_interview: { label: "Start a mock round", to: "/interview" },
  apply_now: { label: "Open the job", to: "/opportunities" },
};

const KIND_LABEL: Record<string, string> = {
  tailor_resume: "resume",
  learn_skill: "learn",
  prep_interview: "interview",
  apply_now: "apply",
  drop: "drop",
};

export default function ActionCenter() {
  const [guidance, setGuidance] = useState<Guidance | null>(null);
  const [context, setContext] = useState<string | null>(null);
  const ask = useAction();
  const debug = useAction();

  // Deliberately not fetched on mount: this endpoint makes a model call, so it
  // sits behind an explicit click rather than firing on every navigation.
  const refresh = async () => {
    const result = await ask.run(() => api.actionCenter());
    if (result) setGuidance(result);
  };

  return (
    <>
      <div className="page-head">
        <h1>Action center</h1>
        <p>
          Ranked next moves. Every figure quoted below was computed by the
          deterministic engine first — the agent reads those numbers and is
          forbidden from deriving its own, so you can check any claim against the
          Skill ROI and Analytics pages.
        </p>
      </div>

      {ask.error && <ErrorNote message={ask.error} onDismiss={ask.clearError} />}

      {!guidance && !ask.pending && (
        <Empty title="Ready when you are">
          <p>This one calls the model, so it runs on request rather than on load.</p>
          <button className="primary" onClick={refresh}>
            What should I do next?
          </button>
        </Empty>
      )}

      {ask.pending && <Spinner label="Reading your board, gaps, and funnel…" />}

      {guidance && (
        <>
          <Card
            title="The headline"
            actions={
              <button disabled={ask.pending} onClick={refresh}>
                Re-run
              </button>
            }
          >
            <p style={{ fontSize: "1.05rem", marginBottom: 0 }}>{guidance.headline}</p>
          </Card>

          <Card title={`Next actions (${guidance.actions.length})`}>
            {guidance.actions.length === 0 ? (
              <p className="muted">No actions returned.</p>
            ) : (
              guidance.actions.map((action, i) => {
                const destination = DESTINATION[action.kind];
                const href =
                  action.kind === "learn_skill"
                    ? "/learning"
                    : action.job_id
                      ? `/opportunities/${action.job_id}`
                      : (destination?.to ?? "/opportunities");
                return (
                  <div key={i} className="action-item">
                    <div className="action-head">
                      <span className="priority">{action.priority}</span>
                      <strong>{action.title}</strong>
                      <span className="chip chip-required">
                        {KIND_LABEL[action.kind] ?? action.kind}
                      </span>
                      {action.skill && <span className="chip chip-partial">{action.skill}</span>}
                      {action.estimated_effort && (
                        <span className="muted small">{action.estimated_effort}</span>
                      )}
                    </div>
                    <p className="small" style={{ marginBottom: "0.3rem" }}>
                      {action.rationale}
                    </p>
                    {action.kind !== "drop" && destination && (
                      <Link to={href} className="link">
                        {destination.label} →
                      </Link>
                    )}
                  </div>
                );
              })
            )}
          </Card>

          {guidance.funnel_read && (
            <Card title="What your funnel says">
              <p style={{ marginBottom: 0 }}>{guidance.funnel_read}</p>
            </Card>
          )}

          {guidance.missing_information.length > 0 && (
            <Card title="What would sharpen this">
              <ul className="clean small">
                {guidance.missing_information.map((item, i) => (
                  <li key={i}>{item}</li>
                ))}
              </ul>
              <p className="muted small">
                Filling these in on your <Link to="/profile">profile</Link> changes
                the advice.
              </p>
            </Card>
          )}

          <Card
            title="Audit trail"
            actions={
              <button
                disabled={debug.pending}
                onClick={async () => {
                  const result = await debug.run(() => api.debugContext());
                  if (result) setContext(result.context);
                }}
              >
                {debug.pending ? "Loading…" : "Show the numbers it was given"}
              </button>
            }
          >
            <p className="muted small">
              When the advice looks wrong, the first question is whether the inputs
              were right. This is the exact text the agent received.
            </p>
            {debug.error && <ErrorNote message={debug.error} onDismiss={debug.clearError} />}
            {context && <pre>{context}</pre>}
          </Card>
        </>
      )}
    </>
  );
}
