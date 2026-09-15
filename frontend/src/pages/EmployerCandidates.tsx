import { useState } from "react";
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
import type { ApplicationStatus, Candidate } from "../types";

/**
 * The decisions a recruiter can record, in the order a hire moves through them.
 *
 * `withdrawn` is deliberately absent: only the candidate can withdraw, and the
 * backend refuses it here — their record should say what actually happened.
 */
const DECISIONS: ApplicationStatus[] = [
  "applied",
  "screening",
  "interviewing",
  "offer",
  "rejected",
];

const STATUS_CHIP: Partial<Record<ApplicationStatus, string>> = {
  applied: "chip-preferred",
  screening: "chip-partial",
  interviewing: "chip-partial",
  offer: "chip-have",
  rejected: "chip-missing",
  withdrawn: "chip-missing",
};

/**
 * One vocabulary for a stage, wherever it appears.
 *
 * The stored value is `screening`, which is what the student-side tracker has
 * always called it. Showing that raw on the chip while the control beside it
 * says "Shortlisted" made the recruiter's own action look like it had done
 * something else.
 */
const STATUS_LABEL: Record<ApplicationStatus, string> = {
  saved: "Saved",
  applied: "Applied",
  screening: "Shortlisted",
  interviewing: "Interviewing",
  offer: "Offer",
  rejected: "Declined",
  withdrawn: "Withdrawn",
};

function CandidateRow({
  candidate,
  postingId,
  onChanged,
}: {
  candidate: Candidate;
  postingId: number;
  onChanged: (updated: Candidate) => void;
}) {
  const [open, setOpen] = useState(false);
  const act = useAction();

  const decide = async (status: ApplicationStatus) => {
    const updated = await act.run(() =>
      api.decideOnCandidate(postingId, candidate.application_id, status),
    );
    if (updated) onChanged(updated);
  };

  return (
    <>
      <tr>
        <td>
          <strong>{candidate.full_name}</strong>
          <div className="muted small">
            {candidate.headline ?? "—"}
            {candidate.location ? ` · ${candidate.location}` : ""}
          </div>
        </td>
        <td className="small">
          {candidate.email ? (
            <a href={`mailto:${candidate.email}`}>{candidate.email}</a>
          ) : (
            <span className="muted">no email</span>
          )}
          {candidate.phone && <div className="muted">{candidate.phone}</div>}
        </td>
        <td className="num">{candidate.years_experience}y</td>
        <td>
          {candidate.alignment_score == null ? (
            <span className="muted small">not scored</span>
          ) : (
            <ScoreBadge score={candidate.alignment_score} />
          )}
        </td>
        <td>
          {candidate.interview_status === "completed" &&
          candidate.interview_score != null ? (
            <ScoreBadge score={candidate.interview_score} />
          ) : candidate.interview_status === "in_progress" ? (
            <span className="muted small">started</span>
          ) : candidate.interview_status === "required" ? (
            <span className="muted small">not sat</span>
          ) : (
            <span className="muted small">—</span>
          )}
        </td>
        <td>
          <span className={`chip ${STATUS_CHIP[candidate.status] ?? ""}`}>
            {STATUS_LABEL[candidate.status]}
          </span>
        </td>
        <td className="small muted">{formatDate(candidate.applied_at)}</td>
        <td>
          <div className="inline">
            <select
              value={candidate.status}
              disabled={act.pending || candidate.status === "withdrawn"}
              onChange={(e) => decide(e.target.value as ApplicationStatus)}
            >
              {DECISIONS.map((d) => (
                <option key={d} value={d}>
                  {STATUS_LABEL[d]}
                </option>
              ))}
            </select>
            <button className="link" onClick={() => setOpen(!open)}>
              {open ? "less" : "why"}
            </button>
          </div>
        </td>
      </tr>

      {act.error && (
        <tr>
          <td colSpan={8}>
            <ErrorNote message={act.error} onDismiss={act.clearError} />
          </td>
        </tr>
      )}

      {open && (
        <tr>
          <td colSpan={8}>
            <div className="detail-panel">
              {candidate.interview_summary && (
                <p style={{ whiteSpace: "pre-line" }}>
                  <strong>Screening interview:</strong>{" "}
                  {candidate.interview_summary}
                </p>
              )}
              {candidate.cover_note && (
                <p>
                  <strong>Their note:</strong> {candidate.cover_note}
                </p>
              )}

              <div className="chip-row">
                {candidate.have.map((s) => (
                  <span key={s} className="chip chip-have">
                    {s}
                  </span>
                ))}
                {candidate.partial.map((s) => (
                  <span key={s} className="chip chip-partial">
                    {s} · partial
                  </span>
                ))}
                {candidate.missing.map((s) => (
                  <span key={s} className="chip chip-missing">
                    {s} · missing
                  </span>
                ))}
              </div>

              <p className="muted small">
                Scored against this role's requirements at the moment they
                applied, so the ranking doesn't shift as people edit their
                profiles. Everything they list: {candidate.skills.join(", ") || "—"}
              </p>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

export default function EmployerCandidates({
  postingId,
  onBack,
}: {
  postingId: number;
  onBack: () => void;
}) {
  const list = useAsync(() => api.candidates(postingId), [postingId]);

  if (list.loading) return <Spinner />;
  if (list.error) return <ErrorNote message={list.error} />;
  if (!list.data) return null;

  const { posting, candidates, status_counts } = list.data;

  /**
   * Replace the one row that changed rather than refetching.
   *
   * The list is ranked by score, so a reload is harmless to the order — but it
   * would collapse the "why" panel the recruiter had open and scroll them back
   * to the top mid-review.
   */
  const replace = (updated: Candidate) =>
    list.set({
      ...list.data!,
      candidates: candidates.map((c) =>
        c.application_id === updated.application_id ? updated : c,
      ),
      status_counts: candidates.reduce<Record<string, number>>((acc, c) => {
        const status =
          c.application_id === updated.application_id ? updated.status : c.status;
        acc[status] = (acc[status] ?? 0) + 1;
        return acc;
      }, {}),
    });

  const shortlisted =
    (status_counts.screening ?? 0) +
    (status_counts.interviewing ?? 0) +
    (status_counts.offer ?? 0);

  return (
    <>
      <div className="page-head">
        <button className="link" onClick={onBack}>
          ← Your roles
        </button>
        <h1>{posting.title}</h1>
        <p>
          {candidates.length === 0
            ? "Nobody has applied yet."
            : `${candidates.length} applicant${candidates.length === 1 ? "" : "s"}, best match first. ${shortlisted} moved forward.`}
        </p>
      </div>

      {candidates.length === 0 ? (
        <Empty title="No applications yet">
          <p>
            Applicants appear here as soon as they apply, ranked against this
            role's requirements.
          </p>
        </Empty>
      ) : (
        <Card
          title="Applicants"
          actions={
            <a
              className="button-link"
              href={api.candidatesCsvUrl(postingId)}
              download
            >
              Download spreadsheet
            </a>
          }
        >
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Candidate</th>
                  <th>Contact</th>
                  <th className="num">Exp.</th>
                  <th>Match</th>
                  <th>Interview</th>
                  <th>Stage</th>
                  <th>Applied</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {candidates.map((c) => (
                  <CandidateRow
                    key={c.application_id}
                    candidate={c}
                    postingId={postingId}
                    onChanged={replace}
                  />
                ))}
              </tbody>
            </table>
          </div>

          <p className="muted small" style={{ marginTop: "0.7rem" }}>
            Two scores, two different questions: <strong>Match</strong> is
            their profile against your requirements, <strong>Interview</strong>
            is what they actually wrote. Neither shortens this list or moves
            anybody — everyone who applied is here whatever they scored. Everyone who
            applied is here whatever they scored, and nothing moves a candidate
            forward or declines them except you choosing a stage. Candidates see
            the stage you set on their own applications page.
          </p>
        </Card>
      )}
    </>
  );
}
