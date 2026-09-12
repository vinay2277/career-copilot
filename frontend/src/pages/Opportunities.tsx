import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import {
  Card,
  Confidence,
  CoverageChip,
  Empty,
  ErrorNote,
  NecessityChip,
  ScoreBadge,
  ScoreBar,
  Spinner,
  formatDate,
  formatMoney,
} from "../components";
import { useAction, useAsync } from "../hooks";
import type { ApplicationStatus, Job, Opportunity } from "../types";

/** Kanban columns, in pipeline order. Terminal states sit at the end. */
const COLUMNS: ApplicationStatus[] = [
  "saved",
  "applied",
  "screening",
  "interviewing",
  "offer",
  "rejected",
];

const NEXT_STATUS: Partial<Record<ApplicationStatus, ApplicationStatus>> = {
  saved: "applied",
  applied: "screening",
  screening: "interviewing",
  interviewing: "offer",
};

/** A one-line summary containing only the facts the posting stated. */
function describeJob(job: Job): string {
  const parts = [job.company];

  if (job.remote) parts.push("remote");
  else if (job.location) parts.push(job.location);

  if (job.seniority) parts.push(job.seniority);

  // Only mention pay when there is a figure to mention.
  const { salary_min: lo, salary_max: hi, currency } = job;
  if (lo != null && hi != null) {
    parts.push(`${formatMoney(lo, currency)}–${hi.toLocaleString()}`);
  } else if (lo != null || hi != null) {
    const known = lo ?? hi;
    parts.push(`${lo != null ? "from" : "up to"} ${formatMoney(known, currency)}`);
  }

  return parts.join(" · ");
}

export default function Opportunities() {
  const { jobId } = useParams();
  const [view, setView] = useState<"board" | "table">("board");
  const board = useAsync(() => api.listOpportunities(), []);
  const move = useAction();

  // A job id in the URL switches this page into detail mode.
  if (jobId) return <JobDetail jobId={Number(jobId)} />;

  if (board.loading) return <Spinner label="Scoring the board…" />;
  if (board.error) return <ErrorNote message={board.error} />;

  const items = board.data ?? [];

  const advance = async (item: Opportunity) => {
    const next = item.status ? NEXT_STATUS[item.status] : undefined;
    if (!next) return;
    const updated = await move.run(() =>
      api.updateApplication(item.job.id, { status: next }),
    );
    if (updated) board.reload();
  };

  const setStatus = async (item: Opportunity, status: ApplicationStatus) => {
    const updated = await move.run(() => api.updateApplication(item.job.id, { status }));
    if (updated) board.reload();
  };

  return (
    <>
      <div className="page-head">
        <h1>Opportunities</h1>
        <p>
          {items.length} tracked. Scores are recomputed on load, so they always
          reflect your current profile.
        </p>
      </div>

      {move.error && <ErrorNote message={move.error} onDismiss={move.clearError} />}

      <div className="tabs">
        <button className={view === "board" ? "active" : ""} onClick={() => setView("board")}>
          Board
        </button>
        <button className={view === "table" ? "active" : ""} onClick={() => setView("table")}>
          Table
        </button>
      </div>

      {items.length === 0 ? (
        <Empty title="Nothing on the board">
          <p>
            <Link to="/add">Add a job</Link> to get started.
          </p>
        </Empty>
      ) : view === "board" ? (
        <div className="kanban">
          {COLUMNS.map((column) => {
            const inColumn = items.filter((i) => i.status === column);
            return (
              <div key={column} className="column">
                <h3>
                  <span>{column}</span>
                  <span>{inColumn.length}</span>
                </h3>
                {inColumn.map((item) => (
                  <article key={item.job.id} className="job-card">
                    <div className="job-card-top">
                      <h4>
                        <Link to={`/opportunities/${item.job.id}`}>{item.job.title}</Link>
                      </h4>
                      {item.alignment && <ScoreBadge score={item.alignment.total} />}
                    </div>
                    <div className="meta">{item.job.company}</div>
                    <div className="meta">
                      {item.job.remote ? "Remote" : (item.job.location ?? "—")}
                    </div>
                    {NEXT_STATUS[column] && (
                      <button
                        className="link"
                        disabled={move.pending}
                        onClick={() => void advance(item)}
                        style={{ marginTop: "0.35rem" }}
                      >
                        → {NEXT_STATUS[column]}
                      </button>
                    )}
                  </article>
                ))}
                {inColumn.length === 0 && <p className="muted small">Empty</p>}
              </div>
            );
          })}
        </div>
      ) : (
        <Card>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th className="num">Score</th>
                  <th>Role</th>
                  <th>Company</th>
                  <th>Location</th>
                  <th>Salary</th>
                  <th>Status</th>
                  <th>Applied</th>
                </tr>
              </thead>
              <tbody>
                {[...items]
                  .sort((a, b) => (b.alignment?.total ?? 0) - (a.alignment?.total ?? 0))
                  .map((item) => (
                    <tr key={item.job.id}>
                      <td className="num">
                        {item.alignment && <ScoreBadge score={item.alignment.total} />}
                      </td>
                      <td>
                        <Link to={`/opportunities/${item.job.id}`}>{item.job.title}</Link>
                      </td>
                      <td>{item.job.company}</td>
                      <td>{item.job.remote ? "Remote" : (item.job.location ?? "—")}</td>
                      <td>{formatMoney(item.job.salary_max, item.job.currency)}</td>
                      <td>
                        <select
                          value={item.status ?? "saved"}
                          disabled={move.pending}
                          onChange={(e) =>
                            void setStatus(item, e.target.value as ApplicationStatus)
                          }
                        >
                          {[...COLUMNS, "withdrawn"].map((s) => (
                            <option key={s} value={s}>
                              {s}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="small muted">{formatDate(item.applied_at)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </>
  );
}

function JobDetail({ jobId }: { jobId: number }) {
  const detail = useAsync(() => api.getOpportunity(jobId), [jobId]);
  const action = useAction();
  const [tailored, setTailored] = useState<string | null>(null);

  if (detail.loading) return <Spinner />;
  if (detail.error) return <ErrorNote message={detail.error} />;
  if (!detail.data) return <Empty title="Not found" />;

  const { job, alignment, status, notes } = detail.data;

  return (
    <>
      <div className="page-head">
        <Link to="/opportunities" className="link">
          ← back to the board
        </Link>
        <h1 style={{ marginTop: "0.4rem" }}>{job.title}</h1>
        {/* Built from only the parts the posting actually stated. Rendering a
            salary range unconditionally produced a bare "—–—" on the many
            postings that publish no figures, which reads as a broken field. */}
        <p>{describeJob(job)}</p>
      </div>

      {action.error && <ErrorNote message={action.error} onDismiss={action.clearError} />}

      <div className="grid">
        <Card title="Why this score">
          {alignment && (
            <>
              <ScoreBar score={alignment.total} label="Total" />
              <ScoreBar score={alignment.requirements_fit} label="Requirements (70%)" />
              <ScoreBar score={alignment.preference_fit} label="Preferences (30%)" />

              <h3 style={{ marginTop: "1rem" }}>Requirements</h3>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Skill</th>
                      <th>Coverage</th>
                      <th>Necessity</th>
                      <th>Why</th>
                    </tr>
                  </thead>
                  <tbody>
                    {alignment.requirements.map((r) => (
                      <tr key={r.name}>
                        <td>{r.name}</td>
                        <td>
                          <CoverageChip coverage={r.coverage} />
                        </td>
                        <td>
                          <NecessityChip necessity={r.necessity} />
                        </td>
                        <td className="muted small">{r.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <h3 style={{ marginTop: "1rem" }}>Preferences</h3>
              <ul className="clean small">
                {alignment.facets.map((f) => (
                  <li key={f.name}>
                    <strong>{f.matched ? "✓" : "✗"}</strong> {f.name} —{" "}
                    <span className="muted">{f.detail}</span>
                  </li>
                ))}
              </ul>

              <details style={{ marginTop: "0.8rem" }}>
                <summary className="muted small">Full derivation</summary>
                <pre>{alignment.explanation}</pre>
              </details>
            </>
          )}
        </Card>

        <div>
          <Card title="Pipeline">
            <p className="small">
              Status: <strong>{status ?? "not tracked"}</strong>
            </p>
            <div className="card-actions">
              {(["applied", "screening", "interviewing", "offer", "rejected"] as const).map(
                (s) => (
                  <button
                    key={s}
                    disabled={action.pending || status === s}
                    onClick={async () => {
                      const updated = await action.run(() =>
                        api.updateApplication(job.id, { status: s }),
                      );
                      if (updated) detail.set(updated);
                    }}
                  >
                    {s}
                  </button>
                ),
              )}
            </div>
            {notes && <p className="muted small">{notes}</p>}
          </Card>

          <Card title="Resume tailoring">
            <p className="muted small">
              Rewrites your primary resume for this posting — reordering and
              surfacing what's already true, never adding experience you don't
              have.
            </p>
            <button
              disabled={action.pending}
              onClick={async () => {
                const result = await action.run(() => api.tailorResume(job.id));
                if (result) setTailored(result.content + "\n\n---\n" + (result.change_summary ?? ""));
              }}
            >
              {action.pending ? "Rewriting…" : "Tailor for this job"}
            </button>
            {tailored && <pre style={{ marginTop: "0.7rem" }}>{tailored}</pre>}
          </Card>

          {(job.education ||
            job.certifications?.length ||
            job.total_years_experience) && (
            <Card title="Screening criteria">
              <p className="muted small">
                Not scored. A degree or a clearance isn't a skill — it can't go
                in a gap list or a learning roadmap, so it's kept out of the
                alignment maths and shown here instead.
              </p>
              {job.education && (
                <p className="small">
                  <strong>Education:</strong> {job.education}
                </p>
              )}
              {job.certifications?.length ? (
                <p className="small">
                  <strong>Certifications:</strong> {job.certifications.join(", ")}
                </p>
              ) : null}
              {job.total_years_experience ? (
                <p className="small">
                  <strong>Total experience wanted:</strong>{" "}
                  {job.total_years_experience} years
                </p>
              ) : null}
            </Card>
          )}

          <Card title="Provenance">
            <p className="small">
              Source: {job.source_kind}
              {job.source_url && (
                <>
                  {" · "}
                  <a href={job.source_url} target="_blank" rel="noreferrer">
                    original posting
                  </a>
                </>
              )}
            </p>
            <p>
              <Confidence value={job.extraction_confidence} />
            </p>
            {job.unverified_fields.length > 0 && (
              <p className="muted small">
                Unverified at extraction: {job.unverified_fields.join(", ")}
              </p>
            )}
            <details>
              <summary className="muted small">Source text</summary>
              <pre>{job.description ?? "—"}</pre>
            </details>
          </Card>
        </div>
      </div>
    </>
  );
}
