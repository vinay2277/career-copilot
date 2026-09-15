import { useState } from "react";
import { api } from "../api";
import { Card, ErrorNote, Spinner } from "../components";
import { useAction, useAsync } from "../hooks";
import type { ModuleAttempt, ModuleDetail, ModuleRow } from "../types";

/**
 * The twelve-module Gen AI course.
 *
 * Sequential: each module opens when the one before it is passed. The order is
 * the teaching — embeddings make no sense before tokens, RAG before embeddings,
 * agents before tool use — so a locked card says what to finish rather than
 * just refusing.
 */
export default function GenAiCourse() {
  const modules = useAsync(() => api.modules(), []);
  const [open, setOpen] = useState<string | null>(null);

  if (modules.loading) return <Spinner />;
  if (modules.error) return <ErrorNote message={modules.error} />;

  const rows = modules.data ?? [];
  const passed = rows.filter((m) => m.passed).length;
  const next = rows.find((m) => !m.passed && !m.locked);

  if (open) {
    return (
      <ModuleView
        slug={open}
        onBack={() => {
          setOpen(null);
          modules.reload();
        }}
      />
    );
  }

  return (
    <>
      <div className="page-head">
        <h1>Gen AI course</h1>
        <p>
          Twelve modules on building with language models, in the order the
          ideas depend on each other. Each one ends with three questions; get
          two right and the next opens.
        </p>
      </div>

      <Card>
        <div className="inline" style={{ justifyContent: "space-between" }}>
          <strong>
            {passed} of {rows.length} complete
          </strong>
          {next && <span className="muted small">Next: {next.title}</span>}
        </div>
        <div className="progress-track" aria-hidden="true">
          <div
            className="progress-fill"
            style={{ width: `${(passed / rows.length) * 100}%` }}
          />
        </div>
      </Card>

      <div className="module-grid">
        {rows.map((module) => (
          <ModuleCard key={module.slug} module={module} onOpen={setOpen} rows={rows} />
        ))}
      </div>
    </>
  );
}

function ModuleCard({
  module,
  rows,
  onOpen,
}: {
  module: ModuleRow;
  rows: ModuleRow[];
  onOpen: (slug: string) => void;
}) {
  const blocker = rows.find((m) => m.position === module.position - 1);

  return (
    <div
      className={`module-card${module.locked ? " is-locked" : ""}${module.passed ? " is-passed" : ""}`}
    >
      <div className="module-number">{module.position}</div>
      <h3>{module.title}</h3>
      <p className="muted small">{module.summary}</p>

      <div className="module-foot">
        <span className="muted small">
          {module.minutes} min · {module.question_count} questions
        </span>
        {module.passed ? (
          <span className="chip chip-have">passed</span>
        ) : module.locked ? (
          <span className="muted small">
            finish {blocker ? `#${blocker.position}` : "the previous module"}
          </span>
        ) : (
          <button className="primary" onClick={() => onOpen(module.slug)}>
            {module.attempts > 0 ? "Try again" : "Start"}
          </button>
        )}
      </div>

      {module.passed && (
        <button className="link" onClick={() => onOpen(module.slug)}>
          re-read
        </button>
      )}
    </div>
  );
}

function ModuleView({ slug, onBack }: { slug: string; onBack: () => void }) {
  const module = useAsync(() => api.module(slug), [slug]);
  const act = useAction();
  const [answers, setAnswers] = useState<Record<number, number>>({});
  const [result, setResult] = useState<ModuleAttempt | null>(null);

  if (module.loading) return <Spinner />;
  if (module.error) {
    return (
      <>
        <button className="link" onClick={onBack}>
          ← All modules
        </button>
        <ErrorNote message={module.error} />
      </>
    );
  }
  if (!module.data) return null;

  const m: ModuleDetail = module.data;

  const submit = async () => {
    const graded = await act.run(() => api.attemptModule(slug, answers));
    if (graded) setResult(graded);
  };

  const resultFor = (index: number) =>
    result?.results.find((r) => r.index === index);

  return (
    <>
      <div className="page-head">
        <button className="link" onClick={onBack}>
          ← All modules
        </button>
        <h1>
          {m.position}. {m.title}
        </h1>
        <p>{m.summary}</p>
      </div>

      {act.error && <ErrorNote message={act.error} onDismiss={act.clearError} />}

      <Card title="What you'll be able to do">
        <ul>
          {m.objectives.map((o) => (
            <li key={o}>{o}</li>
          ))}
        </ul>
      </Card>

      <Card>
        {m.body.split("\n\n").map((para, i) => (
          <p key={i} style={{ whiteSpace: "pre-line" }}>
            {para}
          </p>
        ))}
      </Card>

      <Card
        title={
          result
            ? `${result.score} of ${result.total} — ${result.passed ? "passed" : "not yet"}`
            : `Check yourself (${m.pass_mark} of ${m.questions.length} to pass)`
        }
      >
        {result?.unlocked_module && (
          <div className="note note-info">
            <strong>Unlocked:</strong> {result.unlocked_module.position}.{" "}
            {result.unlocked_module.title}
          </div>
        )}
        {result?.already_passed && (
          <div className="note">
            You had already passed this module, so that still stands. Re-reading
            never costs you a pass.
          </div>
        )}

        {m.questions.map((q) => {
          const r = resultFor(q.index);
          return (
            <fieldset key={q.index} className="question">
              <legend>{q.prompt}</legend>
              {q.options.map((option, i) => {
                const chosen = answers[q.index] === i;
                const showRight = r && i === r.correct_option;
                const showWrong = r && r.chosen === i && !r.correct;
                return (
                  <label
                    key={option}
                    className={`option${showRight ? " is-right" : ""}${showWrong ? " is-wrong" : ""}`}
                  >
                    <input
                      type="radio"
                      name={`q-${q.index}`}
                      checked={chosen}
                      disabled={!!result}
                      onChange={() => setAnswers({ ...answers, [q.index]: i })}
                    />
                    {option}
                  </label>
                );
              })}
              {r && <p className="muted small">{r.explanation}</p>}
            </fieldset>
          );
        })}

        {result ? (
          <div className="inline">
            <button className="primary" onClick={onBack}>
              {result.passed ? "Back to the course" : "Back"}
            </button>
            {!result.passed && (
              <button
                onClick={() => {
                  setResult(null);
                  setAnswers({});
                }}
              >
                Try again
              </button>
            )}
          </div>
        ) : (
          <button
            className="primary"
            disabled={act.pending || Object.keys(answers).length === 0}
            onClick={submit}
          >
            {act.pending ? "Checking…" : "Check my answers"}
          </button>
        )}
      </Card>
    </>
  );
}
