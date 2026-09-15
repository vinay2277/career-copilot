import { api } from "../api";
import {
  Card,
  Empty,
  ErrorNote,
  ScoreBadge,
  Spinner,
  formatDate,
} from "../components";
import { useAction, useAsync } from "../hooks";

export default function MyApplications({
  onInterview,
}: {
  onInterview: (applicationId: number) => void;
}) {
  const applications = useAsync(() => api.myApplications(), []);
  const withdraw = useAction();

  if (applications.loading) return <Spinner />;
  if (applications.error) return <ErrorNote message={applications.error} />;

  const rows = applications.data ?? [];

  return (
    <>
      <div className="page-head">
        <h1>My applications</h1>
        <p>
          Roles you've applied to on the platform. The score shown is the one
          recorded when you applied — it doesn't move when you edit your
          profile, because it's the number the employer is looking at.
        </p>
      </div>

      {withdraw.error && (
        <ErrorNote message={withdraw.error} onDismiss={withdraw.clearError} />
      )}

      {rows.length === 0 ? (
        <Empty title="Nothing applied to yet">
          <p>Open roles are under Job board.</p>
        </Empty>
      ) : (
        <Card>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th className="num">Score</th>
                  <th>Role</th>
                  <th>Company</th>
                  <th>Status</th>
                  <th>Applied</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map(({ application, posting }) => (
                  <tr key={application.id}>
                    <td className="num">
                      {application.alignment_score != null && (
                        <ScoreBadge score={application.alignment_score} />
                      )}
                    </td>
                    <td>
                      <strong>{posting.title}</strong>
                      {posting.interview_required && (
                        <div className="muted small">
                          this employer asks every applicant a short interview
                        </div>
                      )}
                      {application.alignment_detail && (
                        <div className="muted small">
                          {application.alignment_detail.have.length} matched,{" "}
                          {application.alignment_detail.missing.length} missing
                        </div>
                      )}
                    </td>
                    <td>{posting.company_name}</td>
                    <td>
                      <span className="chip chip-required">
                        {application.status}
                      </span>
                    </td>
                    <td className="small muted">
                      {formatDate(application.applied_at)}
                    </td>
                    <td>
                      <div className="inline">
                        {posting.interview_required && (
                          <button
                            className="primary"
                            onClick={() => onInterview(application.id)}
                          >
                            Interview
                          </button>
                        )}
                        {application.status === "applied" && (
                          <button
                            className="link"
                            disabled={withdraw.pending}
                            onClick={async () => {
                              const done = await withdraw.run(() =>
                                api.withdraw(application.id),
                              );
                              if (done !== null) applications.reload();
                            }}
                          >
                            withdraw
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small" style={{ marginTop: "0.6rem" }}>
            Withdrawing removes the application entirely rather than marking it
            withdrawn — if nobody has looked yet, you shouldn't be leaving a
            permanent trace in someone's pipeline.
          </p>
        </Card>
      )}
    </>
  );
}
