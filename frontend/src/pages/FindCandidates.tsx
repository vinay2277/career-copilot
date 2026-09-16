import { Fragment, useState } from "react";
import { api } from "../api";
import { Card, Empty, ErrorNote, ScoreBadge, Spinner } from "../components";
import { useAction } from "../hooks";
import type { CandidateSearchResult } from "../types";

/**
 * Searching the candidates who chose to be searchable.
 *
 * Everyone here switched on "let employers find me". Students who only
 * uploaded a résumé or applied to a role are deliberately absent — the page
 * says so, because a recruiter seeing a thin list should understand why it is
 * thin rather than assume the search is broken.
 */
export default function FindCandidates() {
  const [skills, setSkills] = useState("");
  const [minYears, setMinYears] = useState("");
  const [location, setLocation] = useState("");
  const [remoteOnly, setRemoteOnly] = useState(false);
  const [openOnly, setOpenOnly] = useState(true);
  const [result, setResult] = useState<CandidateSearchResult | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const search = useAction();

  const run = async () => {
    const found = await search.run(() =>
      api.searchCandidates({
        skills: skills
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        min_years: minYears ? Number(minYears) : null,
        location: location.trim() || null,
        remote_only: remoteOnly,
        open_to_work_only: openOnly,
      }),
    );
    if (found) setResult(found);
  };

  return (
    <>
      <div className="page-head">
        <h1>Find candidates</h1>
        <p>
          Search students who have chosen to be found. Only people who have
          at least one of the skills you name, ranked by fit and then by depth
          in those skills, best first.
        </p>
      </div>

      {search.error && (
        <ErrorNote message={search.error} onDismiss={search.clearError} />
      )}

      <Card title="Search">
        <label>
          Skills
          <input
            value={skills}
            placeholder="python, airflow, sql"
            onChange={(e) => setSkills(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && run()}
          />
        </label>
        <p className="muted small">
          Comma separated. Leave empty to see everyone who is open to work.
        </p>

        <div className="inline" style={{ flexWrap: "wrap", gap: "1rem" }}>
          <label style={{ flex: "0 1 140px" }}>
            Min. years
            <input
              type="number"
              min={0}
              value={minYears}
              placeholder="any"
              onChange={(e) => setMinYears(e.target.value)}
            />
          </label>
          <label style={{ flex: "1 1 200px" }}>
            Location
            <input
              value={location}
              placeholder="any"
              onChange={(e) => setLocation(e.target.value)}
            />
          </label>
        </div>

        <div className="checkbox">
          <input
            id="remote-only"
            type="checkbox"
            checked={remoteOnly}
            onChange={(e) => setRemoteOnly(e.target.checked)}
          />
          <label htmlFor="remote-only" style={{ margin: 0 }}>
            Will work remotely
          </label>
        </div>
        <div className="checkbox">
          <input
            id="open-only"
            type="checkbox"
            checked={openOnly}
            onChange={(e) => setOpenOnly(e.target.checked)}
          />
          <label htmlFor="open-only" style={{ margin: 0 }}>
            Currently looking
          </label>
        </div>

        <button className="primary" disabled={search.pending} onClick={run}>
          {search.pending ? "Searching…" : "Search"}
        </button>
      </Card>

      {search.pending && <Spinner />}

      {result && !search.pending && (
        <div style={{ marginTop: "1.2rem" }}>
          {result.results.length === 0 ? (
            <Empty title="No matches">
              {result.searchable_total === 0 ? (
                <p>
                  Nobody has opted into being found yet. Students choose this
                  on their own profile, and it is off until they do — so an
                  empty result here is not a broken search. Posting a role
                  reaches them either way.
                </p>
              ) : (
                <p>
                  {result.searchable_total} student
                  {result.searchable_total === 1 ? " is" : "s are"} searchable,
                  but none of them has any of the skills you named. Check the
                  spelling, or try a broader skill.
                </p>
              )}
            </Empty>
          ) : (
            <Card
              title={`${result.results.length} of ${result.searchable_total} searchable`}
            >
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Candidate</th>
                      <th>Contact</th>
                      <th className="num">Exp.</th>
                      <th>Location</th>
                      <th>Match</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {result.results.map((c) => (
                      // A keyed Fragment, not <>: a bare fragment cannot carry
                      // a key, and each candidate renders two sibling rows.
                      <Fragment key={c.profile_id}>
                        <tr>
                          <td>
                            <strong>{c.full_name}</strong>
                            <div className="muted small">
                              {c.headline ?? "—"}
                              {!c.open_to_work && " · not currently looking"}
                            </div>
                          </td>
                          <td className="small">
                            {c.email ? (
                              <a href={`mailto:${c.email}`}>{c.email}</a>
                            ) : (
                              <span className="muted">no email</span>
                            )}
                          </td>
                          <td className="num">{c.years_experience}y</td>
                          <td className="small muted">{c.location ?? "—"}</td>
                          <td>
                            {c.score == null ? (
                              <span className="muted small">—</span>
                            ) : (
                              <ScoreBadge score={c.score} />
                            )}
                          </td>
                          <td>
                            <button
                              className="link"
                              onClick={() =>
                                setExpanded(
                                  expanded === c.profile_id ? null : c.profile_id,
                                )
                              }
                            >
                              {expanded === c.profile_id ? "less" : "skills"}
                            </button>
                          </td>
                        </tr>
                        {expanded === c.profile_id && (
                          <tr>
                            <td colSpan={6}>
                              <div className="detail-panel">
                                <div className="chip-row">
                                  {c.have.map((s) => (
                                    <span key={s} className="chip chip-have">
                                      {s}
                                    </span>
                                  ))}
                                  {c.partial.map((s) => (
                                    <span key={s} className="chip chip-partial">
                                      {s} · partial
                                    </span>
                                  ))}
                                  {c.missing.map((s) => (
                                    <span key={s} className="chip chip-missing">
                                      {s} · missing
                                    </span>
                                  ))}
                                </div>
                                <p className="muted small">
                                  Everything they list: {c.skills.join(", ") || "—"}
                                </p>
                              </div>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    ))}
                  </tbody>
                </table>
              </div>

              <p className="muted small" style={{ marginTop: "0.7rem" }}>
                Everyone listed chose to be findable, has at least one of the
                skills you named, and can switch that off at any time. Ranked by
                fit, then by years in the skills you searched — not by how long
                their career has been.
              </p>
            </Card>
          )}
        </div>
      )}
    </>
  );
}
