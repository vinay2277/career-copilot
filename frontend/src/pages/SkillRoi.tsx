import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { Card, Empty, ErrorNote, ScoreBadge, Spinner } from "../components";
import { useAction, useAsync } from "../hooks";
import { UNLOCK_THRESHOLD, type Simulation } from "../types";

export default function SkillRoi() {
  const rois = useAsync(() => api.skillRoi(12), []);
  const sim = useAction();

  const [addSkills, setAddSkills] = useState<string[]>([]);
  const [removeSkills, setRemoveSkills] = useState<string[]>([]);
  const [minSalary, setMinSalary] = useState("");
  const [result, setResult] = useState<Simulation | null>(null);

  const toggleAdd = (skill: string) =>
    setAddSkills((current) =>
      current.includes(skill) ? current.filter((s) => s !== skill) : [...current, skill],
    );

  const runSimulation = async () => {
    const payload = {
      add_skills: addSkills,
      remove_skills: removeSkills,
      min_salary: minSalary ? Number(minSalary) : null,
    };
    const outcome = await sim.run(() => api.whatIf(payload));
    if (outcome) setResult(outcome);
  };

  if (rois.loading) return <Spinner label="Running counterfactuals…" />;
  if (rois.error) return <ErrorNote message={rois.error} />;

  const rows = rois.data ?? [];
  const maxGain = Math.max(...rows.map((r) => r.mean_gain), 1);

  return (
    <>
      <div className="page-head">
        <h1>Skill ROI</h1>
        <p>
          Not "what am I missing" — that's the gap list. This is "of everything
          I'm missing, which one skill moves the most jobs into reach". Each row
          is measured by actually re-scoring your whole board with that skill
          added at working proficiency.
        </p>
      </div>

      {rows.length === 0 ? (
        <Empty title="No gaps to price">
          <p>
            Either your board is empty or you already cover everything on it.{" "}
            <Link to="/add">Add a job</Link>.
          </p>
        </Empty>
      ) : (
        <Card title="If you learned exactly one more skill">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Skill</th>
                  <th className="num">Jobs asking</th>
                  <th className="num">Unlocks</th>
                  <th>Mean gain across the board</th>
                  <th className="num">Best single job</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.skill}>
                    <td>
                      <strong>{r.skill}</strong>
                    </td>
                    <td className="num">{r.demand}</td>
                    <td className="num">
                      {r.unlock_count > 0 ? (
                        <span className="badge badge-strong">{r.unlock_count}</span>
                      ) : (
                        <span className="muted">0</span>
                      )}
                    </td>
                    <td>
                      <div className="bar-row" style={{ marginBottom: 0 }}>
                        <div className="bar-track">
                          <div
                            className="bar-fill bar-strong"
                            style={{ width: `${(r.mean_gain / maxGain) * 100}%` }}
                            title={`+${r.mean_gain} points on average`}
                          />
                        </div>
                        <span className="bar-value">+{r.mean_gain.toFixed(1)}</span>
                      </div>
                    </td>
                    <td className="num">
                      +{r.best_gain.toFixed(1)}
                      {r.best_job_id && (
                        <div className="small">
                          <Link to={`/opportunities/${r.best_job_id}`}>view</Link>
                        </div>
                      )}
                    </td>
                    <td>
                      <button
                        className="link"
                        onClick={() => toggleAdd(r.skill)}
                        aria-pressed={addSkills.includes(r.skill)}
                      >
                        {addSkills.includes(r.skill) ? "in scenario" : "simulate"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small" style={{ marginTop: "0.7rem" }}>
            "Unlocks" counts jobs that cross {UNLOCK_THRESHOLD} alignment only
            because of that skill. Rows are ranked by unlocks first — crossing the
            line is what changes what you do — then by mean gain.
          </p>
        </Card>
      )}

      <Card
        title="What if…"
        actions={
          <button className="primary" disabled={sim.pending} onClick={runSimulation}>
            {sim.pending ? "Recalculating…" : "Run scenario"}
          </button>
        }
      >
        <p className="muted small">
          Applied to in-memory copies only — your real profile is never touched.
        </p>

        {sim.error && <ErrorNote message={sim.error} onDismiss={sim.clearError} />}

        <div className="row">
          <label>
            Skills to add (comma separated)
            <input
              value={addSkills.join(", ")}
              placeholder="kubernetes, terraform"
              onChange={(e) =>
                setAddSkills(
                  e.target.value
                    .split(",")
                    .map((s) => s.trim())
                    .filter(Boolean),
                )
              }
            />
          </label>
          <label>
            Skills to drop
            <input
              value={removeSkills.join(", ")}
              placeholder="to test how much one carries you"
              onChange={(e) =>
                setRemoveSkills(
                  e.target.value
                    .split(",")
                    .map((s) => s.trim())
                    .filter(Boolean),
                )
              }
            />
          </label>
          <label>
            New salary floor
            <input
              type="number"
              step={1000}
              value={minSalary}
              placeholder="leave blank to keep"
              onChange={(e) => setMinSalary(e.target.value)}
            />
          </label>
        </div>

        {result && (
          <>
            <div className="stat-row" style={{ margin: "1rem 0" }}>
              <div className="stat">
                <div className="value">
                  {result.mean_change >= 0 ? "+" : ""}
                  {result.mean_change.toFixed(1)}
                </div>
                <div className="label">Mean score change</div>
              </div>
              <div className="stat">
                <div className="value">
                  {result.in_reach_before} → {result.in_reach_after}
                </div>
                <div className="label">Jobs in reach</div>
              </div>
              <div className="stat">
                <div className="value">
                  {result.deltas.filter((d) => d.newly_in_reach).length}
                </div>
                <div className="label">Newly in reach</div>
              </div>
            </div>

            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Role</th>
                    <th className="num">Before</th>
                    <th className="num">After</th>
                    <th className="num">Change</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {result.deltas
                    .filter((d) => d.change !== 0)
                    .map((d) => (
                      <tr key={d.job_id}>
                        <td>
                          <Link to={`/opportunities/${d.job_id}`}>{d.title}</Link>
                          <div className="muted small">{d.company}</div>
                        </td>
                        <td className="num">
                          <ScoreBadge score={d.before} />
                        </td>
                        <td className="num">
                          <ScoreBadge score={d.after} />
                        </td>
                        <td className="num">
                          {d.change > 0 ? "+" : ""}
                          {d.change.toFixed(1)}
                        </td>
                        <td>
                          {d.newly_in_reach && (
                            <span className="chip chip-have">now in reach</span>
                          )}
                          {d.fell_out_of_reach && (
                            <span className="chip chip-missing">out of reach</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  {result.deltas.every((d) => d.change === 0) && (
                    <tr>
                      <td colSpan={5} className="muted small">
                        Nothing on your board changed. That scenario doesn't touch
                        any requirement you're currently tracking.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Card>
    </>
  );
}
