import { api } from "../api";
import { Card, Empty, ErrorNote, Spinner } from "../components";
import { useAsync } from "../hooks";
import type { Stage } from "../types";

/** Below this many submitted applications, rates are noise. Matches context.py. */
const MIN_SAMPLE = 10;

const pct = (v: number | null) => (v == null ? "—" : `${(v * 100).toFixed(0)}%`);

/**
 * Ordered single-series magnitude chart: one horizontal bar per pipeline stage,
 * every bar directly labelled. One series means no legend is needed — the card
 * title names it — and one measure means one axis.
 */
function FunnelBars({ stages }: { stages: Stage[] }) {
  const max = Math.max(...stages.map((s) => s.reached), 1);

  return (
    <div>
      {stages.map((stage) => {
        const width = (stage.reached / max) * 100;
        return (
          <div key={stage.status} className="funnel-row">
            <span className="funnel-label">{stage.status}</span>
            <div className="funnel-track">
              <div
                className="funnel-fill"
                style={{ width: `${width}%` }}
                title={`${stage.reached} reached ${stage.status}`}
              />
              <span className="funnel-count">{stage.reached}</span>
            </div>
            <span className="funnel-conv">
              {stage.conversion_from_previous == null
                ? ""
                : pct(stage.conversion_from_previous)}
            </span>
          </div>
        );
      })}
      <p className="muted small" style={{ marginTop: "0.6rem" }}>
        The right column is the share of the previous stage that made it here.
        Counts come from transition history, so a stage you skipped past still
        reads zero rather than being credited.
      </p>
    </div>
  );
}

export default function Analytics() {
  const funnel = useAsync(() => api.funnel(), []);

  if (funnel.loading) return <Spinner label="Reading your pipeline…" />;
  if (funnel.error) return <ErrorNote message={funnel.error} />;
  if (!funnel.data) return <Empty title="No data" />;

  const report = funnel.data;
  const submitted = report.stages.find((s) => s.status === "applied")?.reached ?? 0;
  const thin = submitted < MIN_SAMPLE;

  if (report.total === 0) {
    return (
      <>
        <div className="page-head">
          <h1>Analytics</h1>
        </div>
        <Empty title="Nothing to analyze yet">
          <p>Add jobs and move them through the pipeline, and this fills in.</p>
        </Empty>
      </>
    );
  }

  return (
    <>
      <div className="page-head">
        <h1>Analytics</h1>
        <p>
          Computed from your transition history — every figure here is arithmetic
          over recorded events, not an estimate.
        </p>
      </div>

      {thin && (
        <div className="note note-warn">
          Only {submitted} application{submitted === 1 ? "" : "s"} submitted. Below
          about {MIN_SAMPLE}, these rates are noise — read them as a tally, not a
          trend.
        </div>
      )}

      <div className="stat-row" style={{ marginBottom: "1.1rem" }}>
        <div className="stat">
          <div className="value">{report.total}</div>
          <div className="label">Tracked</div>
        </div>
        <div className="stat">
          <div className="value">{submitted}</div>
          <div className="label">Submitted</div>
        </div>
        <div className="stat">
          <div className="value">{pct(report.response_rate)}</div>
          <div className="label">Response rate</div>
        </div>
        <div className="stat">
          <div className="value">{pct(report.offer_rate)}</div>
          <div className="label">Offer rate</div>
        </div>
        <div className="stat">
          <div className="value">
            {report.median_days_to_response == null
              ? "—"
              : `${report.median_days_to_response}d`}
          </div>
          <div className="label">Median to first reply</div>
        </div>
      </div>

      <Card title="Applications reaching each stage">
        <FunnelBars stages={report.stages} />
      </Card>

      <div className="grid">
        <Card title="Where you're losing people">
          {report.bottleneck ? (
            <>
              <p>
                The weakest transition is into <strong>{report.bottleneck.status}</strong>,
                at {pct(report.bottleneck.conversion_from_previous)} of the stage
                before it.
              </p>
              <p className="muted small">
                {report.bottleneck.status === "screening" &&
                  "A weak applied→screening rate usually points at the resume or at aim, not at interview skill."}
                {report.bottleneck.status === "interviewing" &&
                  "Losing people at screening→interviewing points at the phone screen."}
                {report.bottleneck.status === "offer" &&
                  "Reaching interviews but not offers points at the final rounds — worth mock practice."}
                {report.bottleneck.status === "applied" &&
                  "Most saved jobs never get submitted. That's a decision problem, not a skill problem."}
              </p>
            </>
          ) : (
            <p className="muted">Not enough movement yet to identify a bottleneck.</p>
          )}

          <h3 style={{ marginTop: "1rem" }}>Time in stage</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Stage</th>
                  <th className="num">Reached</th>
                  <th className="num">Median days</th>
                </tr>
              </thead>
              <tbody>
                {report.stages.map((s) => (
                  <tr key={s.status}>
                    <td>{s.status}</td>
                    <td className="num">{s.reached}</td>
                    <td className="num">
                      {s.median_days_in_stage == null ? "—" : s.median_days_in_stage}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted small">
            A stage you're still sitting in has no median yet — an open stage has no
            duration.
          </p>
        </Card>

        <Card title={`Stagnant (${report.stagnant.length})`}>
          {report.stagnant.length === 0 ? (
            <p className="muted">Nothing idle past its follow-up window.</p>
          ) : (
            <>
              <p className="muted small">
                Past the point where a follow-up is reasonable. Each stage has its
                own window.
              </p>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Role</th>
                      <th>Stage</th>
                      <th className="num">Idle</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.stagnant.map((s) => (
                      <tr key={s.application_id}>
                        <td>
                          {s.job_title}
                          <div className="muted small">{s.company}</div>
                        </td>
                        <td>{s.status}</td>
                        <td className="num">
                          {s.days_idle}d
                          <div className="muted small">of {s.threshold}d</div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </Card>
      </div>
    </>
  );
}
