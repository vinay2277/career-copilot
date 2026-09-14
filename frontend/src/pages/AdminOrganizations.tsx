import { api } from "../api";
import { Card, Empty, ErrorNote, Spinner, formatDate } from "../components";
import { useAction, useAsync } from "../hooks";
import type { AdminOrganization } from "../types";

/**
 * Approving the companies that may recruit here.
 *
 * The decision this screen exists for: does this organization really employ
 * the person who registered? Unverified recruiters can draft roles but cannot
 * publish them or see candidates, which is what stops anyone posting a fake
 * role to collect students' contact details.
 */
export default function AdminOrganizations() {
  const stats = useAsync(() => api.adminStats(), []);
  const organizations = useAsync(() => api.adminOrganizations(), []);
  const act = useAction();

  /**
   * Apply a decision and update that one row where it sits.
   *
   * Deliberately not a reload: the list puts pending organizations first, so
   * refetching makes the row you just approved jump to the bottom and every
   * row below it shift up under your cursor — the next click would land on a
   * different company than the one you were looking at. The order settles on
   * the next visit.
   */
  const run = async (fn: () => Promise<AdminOrganization>) => {
    const updated = await act.run(fn);
    if (!updated) return;
    organizations.set(
      (organizations.data ?? []).map((o) => (o.id === updated.id ? updated : o)),
    );
    stats.reload();
  };

  if (organizations.loading) return <Spinner />;
  if (organizations.error) return <ErrorNote message={organizations.error} />;

  const rows = organizations.data ?? [];
  const pending = rows.filter((o) => !o.is_verified);

  return (
    <>
      <div className="page-head">
        <h1>Organizations</h1>
        <p>
          A recruiter can register freely, but until their company is approved
          they cannot publish a role or see a candidate. Check the email domain
          against the company being claimed — that is the whole decision.
        </p>
      </div>

      {act.error && <ErrorNote message={act.error} onDismiss={act.clearError} />}

      {stats.data && (
        <div className="stat-row" style={{ marginBottom: "1.2rem" }}>
          <div className="stat">
            <div className="value">{stats.data.awaiting_verification}</div>
            <div className="label">Awaiting approval</div>
          </div>
          <div className="stat">
            <div className="value">{stats.data.organizations}</div>
            <div className="label">Organizations</div>
          </div>
          <div className="stat">
            <div className="value">{stats.data.recruiters}</div>
            <div className="label">Recruiters</div>
          </div>
          <div className="stat">
            <div className="value">{stats.data.students}</div>
            <div className="label">Students</div>
          </div>
          <div className="stat">
            <div className="value">{stats.data.open_postings}</div>
            <div className="label">Open roles</div>
          </div>
        </div>
      )}

      {rows.length === 0 ? (
        <Empty title="No organizations yet">
          <p>They appear here as soon as a recruiter registers.</p>
        </Empty>
      ) : (
        <Card
          title={
            pending.length > 0
              ? `${pending.length} waiting on you`
              : "All approved"
          }
        >
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Company</th>
                  <th>Email domain</th>
                  <th>Who registered</th>
                  <th className="num">Roles</th>
                  <th>Registered</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((org) => (
                  <tr key={org.id}>
                    <td>
                      <strong>{org.name}</strong>
                    </td>
                    <td className="small">
                      {org.domain ? (
                        <code>{org.domain}</code>
                      ) : (
                        <span className="muted">free webmail — check by hand</span>
                      )}
                    </td>
                    <td className="small">
                      {org.member_emails.map((email) => (
                        <div key={email}>{email}</div>
                      ))}
                    </td>
                    <td className="num">{org.posting_count}</td>
                    <td className="small muted">{formatDate(org.created_at)}</td>
                    <td>
                      <span
                        className={`chip ${org.is_verified ? "chip-have" : "chip-partial"}`}
                      >
                        {org.is_verified ? "approved" : "pending"}
                      </span>
                    </td>
                    <td>
                      {org.is_verified ? (
                        <button
                          className="link"
                          disabled={act.pending}
                          onClick={() => run(() => api.unverifyOrganization(org.id))}
                        >
                          withdraw
                        </button>
                      ) : (
                        <button
                          className="primary"
                          disabled={act.pending}
                          onClick={() => run(() => api.verifyOrganization(org.id))}
                        >
                          Approve
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="muted small" style={{ marginTop: "0.7rem" }}>
            Withdrawing approval stops new roles and hides candidates. Roles
            already published stay up and applications are untouched — somebody
            else's approval lapsing is not a reason to delete a student's
            record.
          </p>
        </Card>
      )}
    </>
  );
}
