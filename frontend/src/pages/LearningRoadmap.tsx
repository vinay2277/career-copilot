import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Card, Empty, ErrorNote, Spinner, formatDate } from "../components";
import { useAction, useAsync } from "../hooks";
import type { LearningPath } from "../types";

export default function LearningRoadmap() {
  const paths = useAsync(() => api.listPaths(), []);
  const generate = useAction();
  const toggle = useAction();

  const [skillCount, setSkillCount] = useState(3);
  const [hours, setHours] = useState(6);

  const build = async () => {
    const path = await generate.run(() => api.generateRoadmap(skillCount, hours));
    if (path) paths.reload();
  };

  const flipStep = async (stepId: number, completed: boolean) => {
    const updated = await toggle.run(() => api.toggleStep(stepId, completed));
    if (updated) {
      paths.set(
        (paths.data ?? []).map((p) => (p.id === updated.id ? updated : p)),
      );
    }
  };

  return (
    <>
      <div className="page-head">
        <h1>Learning roadmap</h1>
        <p>
          Which skills to target comes from the{" "}
          <Link to="/skill-roi">ROI engine</Link>, not from the model — it only
          decides the order and sizes the steps. Every step has a proof of work,
          because "learn Kubernetes" never gets started.
        </p>
      </div>

      {generate.error && (
        <ErrorNote message={generate.error} onDismiss={generate.clearError} />
      )}
      {toggle.error && <ErrorNote message={toggle.error} onDismiss={toggle.clearError} />}

      <Card title="Build a plan">
        <div className="row">
          <label>
            Skills to target
            <input
              type="number"
              min={1}
              max={8}
              value={skillCount}
              onChange={(e) => setSkillCount(Number(e.target.value))}
            />
          </label>
          <label>
            Hours you actually have per week
            <input
              type="number"
              min={1}
              max={60}
              value={hours}
              onChange={(e) => setHours(Number(e.target.value))}
            />
          </label>
          <button className="primary" disabled={generate.pending} onClick={build}>
            {generate.pending ? "Planning…" : "Generate roadmap"}
          </button>
        </div>
        <p className="muted small">
          Be honest about the hours. Rounding up is how plans get abandoned in week
          two.
        </p>
      </Card>

      {generate.pending && <Spinner label="Sequencing the plan…" />}

      {paths.loading ? (
        <Spinner />
      ) : (paths.data ?? []).length === 0 ? (
        <Empty title="No roadmaps yet">
          <p>Generate one above, once you have jobs on the board.</p>
        </Empty>
      ) : (
        (paths.data ?? []).map((path) => (
          <PathCard
            key={path.id}
            path={path}
            onToggle={flipStep}
            onDelete={async () => {
              await toggle.run(() => api.deletePath(path.id));
              paths.reload();
            }}
          />
        ))
      )}
    </>
  );
}

function PathCard({
  path,
  onToggle,
  onDelete,
}: {
  path: LearningPath;
  onToggle: (stepId: number, completed: boolean) => void;
  onDelete: () => void;
}) {
  const done = path.steps.filter((s) => s.completed).length;
  const totalHours = path.steps.reduce((sum, s) => sum + s.estimated_hours, 0);
  const remainingHours = path.steps
    .filter((s) => !s.completed)
    .reduce((sum, s) => sum + s.estimated_hours, 0);

  return (
    <Card
      title={path.title}
      actions={
        <>
          <span className="muted small">
            {done}/{path.steps.length} done · {remainingHours.toFixed(0)}h left of{" "}
            {totalHours.toFixed(0)}h
          </span>
          <button className="danger" onClick={onDelete}>
            Delete
          </button>
        </>
      }
    >
      <ul className="tag-list">
        {path.target_skills.map((skill) => (
          <li key={skill} className="tag">
            {skill}
          </li>
        ))}
      </ul>

      {path.rationale && (
        <p className="small" style={{ whiteSpace: "pre-wrap" }}>
          {path.rationale}
        </p>
      )}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th />
              <th>Step</th>
              <th>Skill</th>
              <th className="num">Hours</th>
              <th>Proof of work</th>
            </tr>
          </thead>
          <tbody>
            {path.steps.map((step) => (
              <tr key={step.id} style={{ opacity: step.completed ? 0.55 : 1 }}>
                <td>
                  <input
                    type="checkbox"
                    checked={step.completed}
                    aria-label={`Mark "${step.title}" complete`}
                    style={{ width: "auto" }}
                    onChange={(e) => onToggle(step.id, e.target.checked)}
                  />
                </td>
                <td>
                  <strong
                    style={{
                      textDecoration: step.completed ? "line-through" : "none",
                    }}
                  >
                    {step.title}
                  </strong>
                  {step.resource_url && (
                    <div className="small">
                      <a href={step.resource_url} target="_blank" rel="noreferrer">
                        resource
                      </a>
                    </div>
                  )}
                </td>
                <td>
                  <span className="chip chip-partial">{step.skill}</span>
                </td>
                <td className="num">{step.estimated_hours}</td>
                <td className="muted small">{step.proof_of_work ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="muted small" style={{ marginTop: "0.5rem" }}>
        Created {formatDate(path.created_at)}
      </p>
    </Card>
  );
}
