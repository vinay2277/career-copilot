import { api } from "../api";
import { Card, Empty, ErrorNote, Spinner, formatDate, formatMoney } from "../components";
import { useAction, useAsync } from "../hooks";
import type { PostingStatus } from "../types";

const STATUS_CHIP: Record<PostingStatus, string> = {
  draft: "chip-preferred",
  open: "chip-have",
  closed: "chip-missing",
};

export default function EmployerPostings({ onPost }: { onPost: () => void }) {
  const postings = useAsync(() => api.myPostings(), []);
  const act = useAction();

  if (postings.loading) return <Spinner />;
  if (postings.error) return <ErrorNote message={postings.error} />;

  const rows = postings.data ?? [];

  const run = async (fn: () => Promise<unknown>) => {
    const done = await act.run(fn);
    if (done !== null) postings.reload();
  };

  return (
    <>
      <div className="page-head">
        <h1>Your roles</h1>
        <p>
          {rows.length === 0
            ? "Nothing posted yet."
            : `${rows.length} role${rows.length === 1 ? "" : "s"}, newest first.`}
        </p>
      </div>

      {act.error && <ErrorNote message={act.error} onDismiss={act.clearError} />}

      {rows.length === 0 ? (
        <Empty title="No roles yet">
          <p>Paste a job description and it'll be read into requirements for you.</p>
          <button className="primary" onClick={onPost}>
            Post a role
          </button>
        </Empty>
      ) : (
        <Card>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Role</th>
                  <th>Status</th>
                  <th className="num">Applicants</th>
                  <th>Salary</th>
                  <th>Posted</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map(({ posting, application_count, is_accepting }) => (
                  <tr key={posting.id}>
                    <td>
                      <strong>{posting.title}</strong>
                      <div className="muted small">
                        {posting.remote ? "Remote" : (posting.location ?? "—")}
                        {" · "}
                        {posting.requirements.length} requirement
                        {posting.requirements.length === 1 ? "" : "s"}
                      </div>
                    </td>
                    <td>
                      <span className={`chip ${STATUS_CHIP[posting.status]}`}>
                        {posting.status}
                      </span>
                      {posting.status === "open" && !is_accepting && (
                        <div className="muted small">past its closing date</div>
                      )}
                    </td>
                    <td className="num">
                      {application_count > 0 ? (
                        <strong>{application_count}</strong>
                      ) : (
                        <span className="muted">0</span>
                      )}
                    </td>
                    <td className="small">
                      {posting.salary_max != null
                        ? formatMoney(posting.salary_max, posting.currency)
                        : "—"}
                    </td>
                    <td className="small muted">{formatDate(posting.created_at)}</td>
                    <td>
                      <div className="inline">
                        {posting.status === "draft" && (
                          <>
                            <button
                              className="link"
                              disabled={act.pending}
                              onClick={() => run(() => api.publishPosting(posting.id))}
                            >
                              publish
                            </button>
                            <button
                              className="link"
                              disabled={act.pending}
                              onClick={() => run(() => api.deletePosting(posting.id))}
                            >
                              delete
                            </button>
                          </>
                        )}
                        {posting.status === "open" && (
                          <button
                            className="link"
                            disabled={act.pending}
                            onClick={() => run(() => api.closePosting(posting.id))}
                          >
                            close
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="muted small" style={{ marginTop: "0.7rem" }}>
            Closing stops new applications; everyone who already applied keeps
            their record. Only drafts can be deleted — deleting a published role
            would take its applicants with it.
          </p>
        </Card>
      )}
    </>
  );
}
