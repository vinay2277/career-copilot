import { useState } from "react";
import { api } from "../api";
import {
  Card,
  Confidence,
  ErrorNote,
  NecessityChip,
  Spinner,
} from "../components";
import { useAction } from "../hooks";
import type { PostingDraft, PostingPayload } from "../types";

/**
 * Paste a description, check what was read out of it, publish.
 *
 * The extraction is the same pipeline students use for their own finds, so a
 * role typed in here and one we sourced elsewhere are read on identical terms
 * and scored against identical requirements.
 */
export default function PostJob({ onPublished }: { onPublished: () => void }) {
  const [text, setText] = useState("");
  const [draft, setDraft] = useState<PostingDraft | null>(null);
  const parse = useAction();
  const publish = useAction();

  const [interview, setInterview] = useState(true);
  const [questionCount, setQuestionCount] = useState(4);

  const patch = <K extends keyof PostingDraft>(key: K, value: PostingDraft[K]) =>
    setDraft((d) => (d ? { ...d, [key]: value } : d));

  const toPayload = (d: PostingDraft): PostingPayload => ({
    title: d.title,
    description: d.description,
    location: d.location,
    remote: d.remote,
    seniority: d.seniority,
    salary_min: d.salary_min,
    salary_max: d.salary_max,
    currency: d.currency,
    industry: d.industry,
    company_size: d.company_size,
    education: d.education,
    certifications: d.certifications,
    total_years_experience: d.total_years_experience,
    requirements: d.requirements,
    interview_required: interview,
    interview_question_count: questionCount,
    raw_text: d.raw_text,
  });

  const submit = async () => {
    if (!draft) return;
    const created = await publish.run(() => api.createPosting(toPayload(draft)));
    if (!created) return;

    const live = await publish.run(() => api.publishPosting(created.id));
    if (live) {
      setDraft(null);
      setText("");
      onPublished();
    }
  };

  const saveDraft = async () => {
    if (!draft) return;
    const created = await publish.run(() => api.createPosting(toPayload(draft)));
    if (created) {
      setDraft(null);
      setText("");
      onPublished();
    }
  };

  const flagged = new Set(draft?.unverified_fields ?? []);

  return (
    <>
      <div className="page-head">
        <h1>Post a role</h1>
        <p>
          Paste the description. It's read into structured requirements, then a
          second pass checks every field against your text — candidates are
          scored on those requirements, so it's worth a look before publishing.
        </p>
      </div>

      <Card>
        <textarea
          value={text}
          placeholder="Paste the full job description here…"
          onChange={(e) => setText(e.target.value)}
        />
        <div className="inline" style={{ marginTop: "0.6rem" }}>
          <button
            className="primary"
            disabled={parse.pending || text.trim().length < 120}
            onClick={async () => {
              const result = await parse.run(() => api.parseDescription(text));
              if (result) setDraft(result);
            }}
          >
            {parse.pending ? "Reading…" : "Read the description"}
          </button>
          {text.trim().length > 0 && text.trim().length < 120 && (
            <span className="muted small">Needs at least 120 characters.</span>
          )}
        </div>

        {parse.pending && <Spinner label="Extracting, then checking the extraction…" />}
        {parse.error && <ErrorNote message={parse.error} onDismiss={parse.clearError} />}
      </Card>

      {draft && (
        <Card
          title="Check before publishing"
          actions={<Confidence value={draft.confidence} />}
        >
          {publish.error && (
            <ErrorNote message={publish.error} onDismiss={publish.clearError} />
          )}

          {draft.confidence < 0.7 && (
            <div className="note note-warn">
              Some of this couldn't be confirmed against your text. Check the
              marked fields.
            </div>
          )}

          <p className="muted small">{draft.validation_notes}</p>

          <div className="row">
            <label htmlFor="draft-title" style={{ flex: "2 1 220px" }}>
              Title{" "}
              {flagged.has("title") && (
                <span className="chip chip-missing">unverified</span>
              )}
              <input
                id="draft-title"
                value={draft.title}
                onChange={(e) => patch("title", e.target.value)}
              />
            </label>
            <label htmlFor="draft-location">
              Location
              <input
                id="draft-location"
                value={draft.location ?? ""}
                onChange={(e) => patch("location", e.target.value || null)}
              />
            </label>
            <label htmlFor="draft-seniority">
              Seniority
              <input
                id="draft-seniority"
                value={draft.seniority ?? ""}
                onChange={(e) => patch("seniority", e.target.value || null)}
              />
            </label>
          </div>

          <div className="row">
            <label htmlFor="draft-min">
              Salary min{" "}
              {flagged.has("salary_min") && (
                <span className="chip chip-missing">unverified</span>
              )}
              <input
                id="draft-min"
                type="number"
                value={draft.salary_min ?? ""}
                onChange={(e) =>
                  patch("salary_min", e.target.value ? Number(e.target.value) : null)
                }
              />
            </label>
            <label htmlFor="draft-max">
              Salary max{" "}
              {flagged.has("salary_max") && (
                <span className="chip chip-missing">unverified</span>
              )}
              <input
                id="draft-max"
                type="number"
                value={draft.salary_max ?? ""}
                onChange={(e) =>
                  patch("salary_max", e.target.value ? Number(e.target.value) : null)
                }
              />
            </label>
            <label htmlFor="draft-currency" style={{ flex: "0 1 100px" }}>
              Currency
              <input
                id="draft-currency"
                value={draft.currency ?? ""}
                onChange={(e) => patch("currency", e.target.value || null)}
              />
            </label>
            <div className="checkbox" style={{ alignSelf: "center" }}>
              <input
                id="draft-remote"
                type="checkbox"
                checked={draft.remote === true}
                onChange={(e) => patch("remote", e.target.checked)}
              />
              <label htmlFor="draft-remote" style={{ margin: 0 }}>
                Remote
              </label>
            </div>
          </div>

          <h3>Requirements ({draft.requirements.length})</h3>
          <p className="muted small">
            This is what candidates are scored against. Each one had to be
            quoted from your text to survive the check — remove anything that
            still looks wrong, because a requirement nobody meant distorts every
            applicant's score.
          </p>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Skill</th>
                  <th>Necessity</th>
                  <th className="num">Years</th>
                  <th>Quoted from your text</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {draft.requirements.map((r, i) => (
                  <tr key={`${r.name}-${i}`}>
                    <td>
                      <strong>{r.name}</strong>
                    </td>
                    <td>
                      <NecessityChip necessity={r.necessity} />
                    </td>
                    <td className="num">{r.min_years || "—"}</td>
                    <td className="muted small">{r.evidence ?? "—"}</td>
                    <td>
                      <button
                        className="link"
                        onClick={() =>
                          patch(
                            "requirements",
                            draft.requirements.filter((_, j) => j !== i),
                          )
                        }
                      >
                        remove
                      </button>
                    </td>
                  </tr>
                ))}
                {draft.requirements.length === 0 && (
                  <tr>
                    <td colSpan={5} className="muted small">
                      No requirements were found. A role with none scores every
                      candidate at zero, so publishing is blocked until there's
                      at least one.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {(draft.education || draft.certifications.length > 0) && (
            <>
              <h3 style={{ marginTop: "1rem" }}>Screening criteria (not scored)</h3>
              <ul className="clean small">
                {draft.education && <li>Education: {draft.education}</li>}
                {draft.certifications.length > 0 && (
                  <li>Certifications: {draft.certifications.join(", ")}</li>
                )}
              </ul>
            </>
          )}

          <div className="screening-toggle">
            <div className="checkbox">
              <input
                id="interview-required"
                type="checkbox"
                checked={interview}
                onChange={(e) => setInterview(e.target.checked)}
              />
              <label htmlFor="interview-required" style={{ margin: 0 }}>
                Ask applicants a short screening interview
              </label>
            </div>
            {interview && (
              <label style={{ maxWidth: "160px" }}>
                Questions
                <input
                  type="number"
                  min={2}
                  max={8}
                  value={questionCount}
                  onChange={(e) => setQuestionCount(Number(e.target.value))}
                />
              </label>
            )}
            <p className="muted small">
              {interview ? (
                <>
                  Every applicant answers a few questions before you see them.
                  They are written from this description and from what each
                  candidate's profile left unanswered. You get a score, a
                  recommendation and the full transcript — <strong>it does not
                  shortlist or reject anyone</strong>, you do.{" "}
                  <strong>This costs money:</strong> two model calls per
                  applicant, so a role that draws two hundred people costs two
                  hundred times one interview.
                </>
              ) : (
                <>
                  <strong>Off.</strong> Candidates apply and are scored on their
                  profile alone — you will not hear them answer for themselves.
                </>
              )}
            </p>
          </div>

          <div className="inline" style={{ marginTop: "1rem" }}>
            <button
              className="primary"
              disabled={publish.pending || draft.requirements.length === 0}
              onClick={submit}
            >
              {publish.pending ? "Publishing…" : "Publish"}
            </button>
            <button disabled={publish.pending} onClick={saveDraft}>
              Save as draft
            </button>
            <span className="muted small">
              Requirements can't be changed once someone has applied.
            </span>
          </div>
        </Card>
      )}
    </>
  );
}
