import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import {
  Card,
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
import type { BoardEntry } from "../types";

/** A posting's stated facts, built from only what it actually says. */
function describe(entry: BoardEntry): string {
  const p = entry.posting;
  const parts = [p.company_name];

  if (p.remote) parts.push("remote");
  else if (p.location) parts.push(p.location);

  if (p.seniority) parts.push(p.seniority);

  if (p.salary_min != null && p.salary_max != null) {
    parts.push(`${formatMoney(p.salary_min, p.currency)}–${p.salary_max.toLocaleString()}`);
  } else if (p.salary_max != null) {
    parts.push(`up to ${formatMoney(p.salary_max, p.currency)}`);
  }

  return parts.join(" · ");
}

function PostingCard({
  entry,
  onOpen,
}: {
  entry: BoardEntry;
  onOpen: () => void;
}) {
  const { posting, alignment, applied } = entry;

  return (
    <article className="posting-card">
      <div className="posting-head">
        <div style={{ minWidth: 0 }}>
          <h3>
            <button className="link-heading" onClick={onOpen}>
              {posting.title}
            </button>
          </h3>
          <div className="muted small">{describe(entry)}</div>
        </div>
        {alignment && <ScoreBadge score={alignment.total} />}
      </div>

      {posting.requirements.length > 0 && (
        <ul className="tag-list" style={{ marginTop: "0.6rem" }}>
          {posting.requirements.slice(0, 6).map((r) => (
            <li key={r.name} className="tag">
              {r.name}
            </li>
          ))}
          {posting.requirements.length > 6 && (
            <li className="muted small">+{posting.requirements.length - 6} more</li>
          )}
        </ul>
      )}

      <div className="posting-foot">
        <span className="muted small">Posted {formatDate(posting.created_at)}</span>
        {applied ? (
          <span className="chip chip-have">Applied</span>
        ) : (
          <button className="link" onClick={onOpen}>
            View &amp; apply →
          </button>
        )}
      </div>
    </article>
  );
}

/** The full posting, with its score derivation and the apply action. */
function PostingDetail({
  postingId,
  onBack,
  onApplied,
}: {
  postingId: number;
  onBack: () => void;
  onApplied: () => void;
}) {
  const detail = useAsync(() => api.posting(postingId), [postingId]);
  const [note, setNote] = useState("");
  const apply = useAction();
  const navigate = useNavigate();

  if (detail.loading) return <Spinner />;
  if (detail.error) return <ErrorNote message={detail.error} />;
  if (!detail.data) return <Empty title="Not found" />;

  const { posting, alignment, applied } = detail.data;

  const submit = async () => {
    const result = await apply.run(() => api.apply(postingId, note));
    if (!result) return;

    // Straight into the interview when the role asks for one.
    //
    // Leaving the applicant on a "you've applied" screen with the round
    // waiting somewhere else is how somebody applies, sees nothing happen, and
    // assumes the interview will arrive by email. Applying and interviewing
    // are one act from their side, so the flow should be one too.
    if (posting.interview_required) {
      navigate(`/applications/${result.id}/interview`);
      return;
    }

    detail.reload();
    onApplied();
  };

  return (
    <>
      <div className="page-head">
        <button className="link" onClick={onBack}>
          ← back to the board
        </button>
        <h1 style={{ marginTop: "0.4rem" }}>{posting.title}</h1>
        <p>{describe(detail.data)}</p>
      </div>

      {apply.error && <ErrorNote message={apply.error} onDismiss={apply.clearError} />}

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

              <details style={{ marginTop: "0.8rem" }}>
                <summary className="muted small">Full derivation</summary>
                <pre>{alignment.explanation}</pre>
              </details>
            </>
          )}
        </Card>

        <div>
          <Card title={applied ? "You've applied" : "Apply"}>
            {posting.interview_required && !applied && (
              <div className="note note-info">
                This employer asks every applicant a few questions about the
                role. You'll go straight to them after applying — it takes a few
                minutes and you only get one attempt, so apply when you have
                time to finish.
              </div>
            )}
            {posting.interview_required && applied && (
              <button
                className="primary"
                onClick={() => navigate("/applications")}
              >
                Go to your interview
              </button>
            )}
            {applied ? (
              <p className="muted small">
                Your application was recorded with the alignment score above.
                The employer sees that score and the breakdown behind it.
              </p>
            ) : (
              <>
                <p className="muted small">
                  Your profile and this score are sent with the application.
                  Both are visible to the employer.
                </p>
                <label htmlFor="cover-note">
                  Anything to add (optional)
                  <textarea
                    id="cover-note"
                    value={note}
                    style={{ minHeight: 100 }}
                    placeholder="Why this role, in a few lines."
                    onChange={(e) => setNote(e.target.value)}
                  />
                </label>
                <button
                  className="primary"
                  disabled={apply.pending}
                  onClick={submit}
                  style={{ width: "100%" }}
                >
                  {apply.pending ? "Applying…" : "Apply"}
                </button>
              </>
            )}
          </Card>

          {(posting.education ||
            posting.certifications.length > 0 ||
            posting.total_years_experience) && (
            <Card title="Screening criteria">
              <p className="muted small">
                Not part of the score — a degree or a certificate isn't a skill
                you can be matched on.
              </p>
              {posting.education && (
                <p className="small">
                  <strong>Education:</strong> {posting.education}
                </p>
              )}
              {posting.certifications.length > 0 && (
                <p className="small">
                  <strong>Certifications:</strong>{" "}
                  {posting.certifications.join(", ")}
                </p>
              )}
              {posting.total_years_experience && (
                <p className="small">
                  <strong>Experience wanted:</strong>{" "}
                  {posting.total_years_experience} years
                </p>
              )}
            </Card>
          )}

          {posting.description && (
            <Card title="About the role">
              <p className="small">{posting.description}</p>
              {posting.source_url && (
                <p className="small">
                  <a href={posting.source_url} target="_blank" rel="noreferrer">
                    Original posting
                  </a>
                </p>
              )}
            </Card>
          )}
        </div>
      </div>
    </>
  );
}

export default function JobBoard() {
  const [openId, setOpenId] = useState<number | null>(null);
  const board = useAsync(() => api.board(), []);

  if (openId !== null) {
    return (
      <PostingDetail
        postingId={openId}
        onBack={() => {
          setOpenId(null);
          board.reload();
        }}
        onApplied={() => board.reload()}
      />
    );
  }

  if (board.loading) return <Spinner label="Scoring open roles…" />;
  if (board.error) return <ErrorNote message={board.error} />;

  const employers = board.data?.from_employers ?? [];
  const sourced = board.data?.sourced ?? [];
  const total = employers.length + sourced.length;

  return (
    <>
      <div className="page-head">
        <h1>Open roles</h1>
        <p>
          {total === 0
            ? "Nothing open right now."
            : `${total} open, newest first, each scored against your profile.`}
        </p>
      </div>

      {total === 0 && (
        <Empty title="No open roles yet">
          <p>
            Roles appear here once employers publish them. Check back, or keep
            tracking your own finds under Opportunities.
          </p>
        </Empty>
      )}

      {employers.length > 0 && (
        <section style={{ marginBottom: "2rem" }}>
          <div className="section-heading">
            <h2>Posted here</h2>
            <span className="muted small">
              {employers.length} role{employers.length === 1 ? "" : "s"} from
              employers on the platform
            </span>
          </div>
          <div className="posting-grid">
            {employers.map((entry) => (
              <PostingCard
                key={entry.posting.id}
                entry={entry}
                onOpen={() => setOpenId(entry.posting.id)}
              />
            ))}
          </div>
        </section>
      )}

      {sourced.length > 0 && (
        <section>
          <div className="section-heading">
            <h2>Found elsewhere</h2>
            <span className="muted small">
              {sourced.length} role{sourced.length === 1 ? "" : "s"} we sourced
              from other boards
            </span>
          </div>
          <div className="posting-grid">
            {sourced.map((entry) => (
              <PostingCard
                key={entry.posting.id}
                entry={entry}
                onOpen={() => setOpenId(entry.posting.id)}
              />
            ))}
          </div>
        </section>
      )}
    </>
  );
}
