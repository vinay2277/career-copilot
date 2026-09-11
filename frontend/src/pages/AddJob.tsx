import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import {
  AiUnavailableNote,
  Card,
  Confidence,
  ErrorNote,
  NecessityChip,
  Spinner,
  formatMoney,
} from "../components";
import { useAction, useAsync } from "../hooks";
import type { ExtractionPreview } from "../types";

type Mode = "text" | "url" | "pdf" | "image";

const MODES: { id: Mode; label: string; hint: string }[] = [
  { id: "text", label: "Paste text", hint: "The most reliable route. Copy the posting and paste it." },
  { id: "url", label: "URL", hint: "Single fetch, no JavaScript. Boards that render client-side won't work — paste instead." },
  { id: "pdf", label: "PDF", hint: "Text-layer only. A scanned PDF should go through Image." },
  { id: "image", label: "Screenshot", hint: "OCR. Needs Tesseract installed on the backend host." },
];

export default function AddJob() {
  const navigate = useNavigate();
  const health = useAsync(() => api.health(), []);
  const extract = useAction();
  const confirm = useAction();
  const aiDown = health.data?.ai_available === false;

  const [mode, setMode] = useState<Mode>("text");
  const [text, setText] = useState("");
  const [url, setUrl] = useState("");
  const [preview, setPreview] = useState<ExtractionPreview | null>(null);

  const run = async (file?: File) => {
    setPreview(null);
    const result = await extract.run(() => {
      switch (mode) {
        case "text":
          return api.extractText(text);
        case "url":
          return api.extractUrl(url);
        case "pdf":
          if (!file) throw new Error("Choose a PDF first.");
          return api.extractPdf(file);
        case "image":
          if (!file) throw new Error("Choose an image first.");
          return api.extractImage(file);
      }
    });
    if (result) setPreview(result);
  };

  const save = async () => {
    if (!preview) return;
    const job = await confirm.run(() => api.confirmExtraction(preview));
    if (job) navigate(`/opportunities/${job.id}`);
  };

  /** Edit a scalar field on the preview before saving. */
  const patch = <K extends keyof ExtractionPreview>(
    key: K,
    value: ExtractionPreview[K],
  ) => setPreview((p) => (p ? { ...p, [key]: value } : p));

  const flagged = new Set([
    ...(preview?.unverified_fields ?? []),
    ...(preview?.contradicted_fields ?? []),
  ]);
  const isFlagged = (field: string) => flagged.has(field);

  return (
    <>
      <div className="page-head">
        <h1>Add a job</h1>
        <p>
          Whatever form you have it in. The extraction is audited by a second
          pass before you save it, and anything the auditor couldn't confirm is
          marked for you to check.
        </p>
      </div>

      <AiUnavailableNote note={health.data?.ai_note ?? null} />

      <Card>
        <div className="tabs">
          {MODES.map((m) => (
            <button
              key={m.id}
              className={mode === m.id ? "active" : ""}
              onClick={() => {
                setMode(m.id);
                setPreview(null);
                extract.clearError();
              }}
            >
              {m.label}
            </button>
          ))}
        </div>

        <p className="muted small">{MODES.find((m) => m.id === mode)?.hint}</p>

        {mode === "text" && (
          <>
            <textarea
              value={text}
              placeholder="Paste the full job posting here…"
              onChange={(e) => setText(e.target.value)}
            />
            <button
              className="primary"
              disabled={aiDown || extract.pending || text.trim().length < 120}
              onClick={() => void run()}
              style={{ marginTop: "0.6rem" }}
            >
              Extract
            </button>
            {text.trim().length > 0 && text.trim().length < 120 && (
              <span className="muted small" style={{ marginLeft: "0.6rem" }}>
                Needs at least 120 characters.
              </span>
            )}
          </>
        )}

        {mode === "url" && (
          <div className="row">
            <label style={{ flex: "3 1 240px" }}>
              Posting URL
              <input
                value={url}
                placeholder="https://…"
                onChange={(e) => setUrl(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && void run()}
              />
            </label>
            <button
              className="primary"
              disabled={aiDown || extract.pending || !url}
              onClick={() => void run()}
            >
              Fetch &amp; extract
            </button>
          </div>
        )}

        {(mode === "pdf" || mode === "image") && (
          <label>
            {mode === "pdf" ? "PDF file" : "Screenshot"}
            <input
              type="file"
              accept={mode === "pdf" ? ".pdf" : "image/*"}
              disabled={aiDown || extract.pending}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void run(file);
              }}
            />
          </label>
        )}

        {extract.pending && <Spinner label="Extracting, then auditing the extraction…" />}
        {extract.error && <ErrorNote message={extract.error} onDismiss={extract.clearError} />}
      </Card>

      {preview && (
        <Card
          title="Check before saving"
          actions={
            <>
              <Confidence value={preview.confidence} />
              <button className="primary" disabled={confirm.pending} onClick={save}>
                {confirm.pending ? "Saving…" : "Save to board"}
              </button>
            </>
          }
        >
          {confirm.error && <ErrorNote message={confirm.error} onDismiss={confirm.clearError} />}

          {preview.needs_confirmation && (
            <div className="note note-warn">
              The auditor wasn't confident about this one. Check the marked fields
              before saving.
            </div>
          )}

          <p className="muted small">{preview.validation_notes}</p>

          <div className="row">
            <label>
              Title {isFlagged("title") && <span className="chip chip-missing">unverified</span>}
              <input value={preview.title} onChange={(e) => patch("title", e.target.value)} />
            </label>
            <label>
              Company{" "}
              {isFlagged("company") && <span className="chip chip-missing">unverified</span>}
              <input
                value={preview.company ?? ""}
                onChange={(e) => patch("company", e.target.value || null)}
              />
            </label>
          </div>

          <div className="row">
            <label>
              Location
              <input
                value={preview.location ?? ""}
                onChange={(e) => patch("location", e.target.value || null)}
              />
            </label>
            <label>
              Seniority
              <input
                value={preview.seniority ?? ""}
                onChange={(e) => patch("seniority", e.target.value || null)}
              />
            </label>
            <label>
              Salary min{" "}
              {isFlagged("salary_min") && <span className="chip chip-missing">unverified</span>}
              <input
                type="number"
                value={preview.salary_min ?? ""}
                onChange={(e) =>
                  patch("salary_min", e.target.value ? Number(e.target.value) : null)
                }
              />
            </label>
            <label>
              Salary max{" "}
              {isFlagged("salary_max") && <span className="chip chip-missing">unverified</span>}
              <input
                type="number"
                value={preview.salary_max ?? ""}
                onChange={(e) =>
                  patch("salary_max", e.target.value ? Number(e.target.value) : null)
                }
              />
            </label>
          </div>

          <p className="small muted">
            Band as extracted: {formatMoney(preview.salary_min, preview.currency)} –{" "}
            {formatMoney(preview.salary_max, preview.currency)}
            {preview.remote === true && " · remote"}
            {preview.remote === false && " · on-site"}
          </p>

          <h3>Requirements ({preview.requirements.length})</h3>
          <p className="muted small">
            Each one had to be quoted from the posting to survive the audit. Remove
            any that still look wrong — a phantom requirement quietly distorts
            every score that follows.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Skill</th>
                  <th>Necessity</th>
                  <th className="num">Years</th>
                  <th>Evidence from the posting</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {preview.requirements.map((r, i) => (
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
                            preview.requirements.filter((_, j) => j !== i),
                          )
                        }
                      >
                        remove
                      </button>
                    </td>
                  </tr>
                ))}
                {preview.requirements.length === 0 && (
                  <tr>
                    <td colSpan={5} className="muted small">
                      No requirements survived extraction. A job with none scores
                      zero rather than perfect — check the source text.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <details style={{ marginTop: "0.9rem" }}>
            <summary className="muted small">Source text the agents read</summary>
            <pre>{preview.raw_text}</pre>
          </details>
        </Card>
      )}
    </>
  );
}
