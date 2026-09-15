import { useEffect, useState } from "react";
import { api } from "../api";
import { Card, ErrorNote, ScoreBar, Spinner } from "../components";
import { useAction, useAsync } from "../hooks";
import type {
  Preferences,
  Proficiency,
  ProfileUpdate,
  Resume,
  Skill,
} from "../types";

const PROFICIENCIES: Proficiency[] = ["learning", "working", "proficient", "expert"];

const EMPTY_PREFS: Preferences = {
  target_roles: [],
  locations: [],
  remote_ok: true,
  seniority: null,
  min_salary: null,
  currency: "USD",
  company_sizes: [],
  industries: [],
};

/** Comma-separated text <-> string[], for the list-valued preferences. */
const toList = (text: string) =>
  text
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

/**
 * What the resume upload did to the profile.
 *
 * Shown rather than applied silently — the user's profile just changed
 * underneath them, and they should be able to see what to and disagree.
 */
function ProfileUpdateReport({ update }: { update: ProfileUpdate }) {
  if (!update.applied) {
    return (
      <div className="note note-info" role="status">
        <span>{update.summary}</span>
      </div>
    );
  }

  return (
    <div className="card" style={{ marginTop: "0.8rem", marginBottom: 0 }}>
      <h3>Profile updated from your resume</h3>

      {update.field_changes.length > 0 && (
        <>
          <h4 className="muted small">Details</h4>
          <ul className="clean small">
            {update.field_changes.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </>
      )}

      {update.skills_added.length > 0 && (
        <>
          <h4 className="muted small">
            Skills added ({update.skills_added.length})
          </h4>
          <ul className="tag-list">
            {update.skills_added.map((s) => (
              <li key={s} className="tag">
                {s}
              </li>
            ))}
          </ul>
        </>
      )}

      {update.skills_raised.length > 0 && (
        <>
          <h4 className="muted small">Levels raised</h4>
          <ul className="clean small">
            {update.skills_raised.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
        </>
      )}

      {update.skills_unchanged.length > 0 && (
        <p className="muted small">
          Already covered at the same level or better:{" "}
          {update.skills_unchanged.join(", ")}
        </p>
      )}

      {update.skills_rejected.length > 0 && (
        <div className="note note-warn" style={{ marginTop: "0.6rem" }}>
          <span>
            Skipped for lack of a supporting quote in the resume:{" "}
            {update.skills_rejected.join(", ")}. Add them by hand if they're
            genuine — the extractor won't claim a skill it can't point at.
          </span>
        </div>
      )}

      {(update.education.length > 0 || update.certifications.length > 0) && (
        <p className="muted small">
          {update.education.length > 0 && (
            <>
              <strong>Education:</strong> {update.education.join("; ")}.{" "}
            </>
          )}
          {update.certifications.length > 0 && (
            <>
              <strong>Certifications:</strong> {update.certifications.join("; ")}.
            </>
          )}{" "}
          Recorded but not scored — neither is a skill you can be matched on.
        </p>
      )}

      {update.notes.length > 0 && (
        <>
          <h4 className="muted small">Worth checking</h4>
          <ul className="clean small">
            {update.notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </>
      )}

      <p className="muted small" style={{ marginTop: "0.6rem" }}>
        Every score on your board has been recomputed. Worth a glance before you
        trust it: a skill level is only ever raised, so anything you set by hand
        survived — but the fields above (name, headline, total years) were
        replaced by what the resume said, so correct those if the resume
        undersells you.
      </p>
    </div>
  );
}

export default function ProfilePage() {
  const profile = useAsync(() => api.getProfile().catch(() => null), []);
  const resumes = useAsync(() => api.listResumes().catch(() => [] as Resume[]), []);
  const save = useAction();
  const resumeAction = useAction();

  const [name, setName] = useState("");
  const [headline, setHeadline] = useState("");
  const [email, setEmail] = useState("");
  const [years, setYears] = useState(0);
  const [goal, setGoal] = useState("");
  const [skills, setSkills] = useState<Skill[]>([]);
  const [prefs, setPrefs] = useState<Preferences>(EMPTY_PREFS);

  const [newSkill, setNewSkill] = useState("");
  const [newProf, setNewProf] = useState<Proficiency>("working");
  const [newYears, setNewYears] = useState(1);
  const [profileUpdate, setProfileUpdate] = useState<ProfileUpdate | null>(null);
  const [location, setLocation] = useState("");
  const [openToWork, setOpenToWork] = useState(true);
  const [visible, setVisible] = useState(false);

  // Hydrate the form once the profile arrives. A 404 (no profile yet) leaves
  // the blank form in place, which is the correct first-run state.
  useEffect(() => {
    const p = profile.data;
    if (!p) return;
    setName(p.full_name);
    setHeadline(p.headline ?? "");
    setEmail(p.email ?? "");
    setYears(p.years_experience);
    setGoal(p.career_goal ?? "");
    setSkills(p.skills);
    setPrefs(p.preferences ?? EMPTY_PREFS);
    setLocation(p.location ?? "");
    setOpenToWork(p.open_to_work);
    setVisible(p.visible_to_recruiters);
  }, [profile.data]);

  const addSkill = () => {
    const trimmed = newSkill.trim();
    if (!trimmed) return;
    setSkills((current) => [
      ...current.filter((s) => s.name.toLowerCase() !== trimmed.toLowerCase()),
      { name: trimmed, proficiency: newProf, years: newYears },
    ]);
    setNewSkill("");
  };

  const submit = async () => {
    const saved = await save.run(() =>
      api.saveProfile({
        full_name: name,
        email: email || null,
        headline: headline || null,
        years_experience: years,
        career_goal: goal || null,
        location: location || null,
        open_to_work: openToWork,
        visible_to_recruiters: visible,
        skills,
        preferences: prefs,
      }),
    );
    if (saved) profile.set(saved);
  };

  const uploadResume = async (file: File) => {
    const result = await resumeAction.run(() => api.uploadResume(file));
    if (!result) return;

    resumes.reload();
    setProfileUpdate(result.profile_update);

    // The merge happened server-side, so the form above is now stale. Reload
    // the profile rather than trying to replay the changeset locally — the
    // backend is the authority on what the merge actually did.
    if (result.profile_update?.applied) profile.reload();
  };

  const primary = resumes.data?.find((r) => r.is_primary) ?? null;

  if (profile.loading) return <Spinner label="Loading profile…" />;

  return (
    <>
      <div className="page-head">
        <h1>Profile &amp; resume</h1>
        <p>
          Everything downstream is scored against this. Skills are matched exactly
          after canonicalization, so spelling variants like "postgres" and
          "postgresql" are treated as the same skill.
        </p>
      </div>

      {save.error && <ErrorNote message={save.error} onDismiss={save.clearError} />}
      {resumeAction.error && (
        <ErrorNote message={resumeAction.error} onDismiss={resumeAction.clearError} />
      )}

      <div className="grid">
        <Card title="About you">
          <label>
            Full name
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            Headline
            <input
              value={headline}
              placeholder="Backend engineer, payments"
              onChange={(e) => setHeadline(e.target.value)}
            />
          </label>
          <div className="row">
            <label>
              Email
              <input value={email} onChange={(e) => setEmail(e.target.value)} />
            </label>
            <label>
              Years of experience
              <input
                type="number"
                min={0}
                max={60}
                step={0.5}
                value={years}
                onChange={(e) => setYears(Number(e.target.value))}
              />
            </label>
          </div>
          <label>
            Career goal
            <textarea
              value={goal}
              placeholder="What you're actually aiming for. The action center reads this."
              style={{ minHeight: 80 }}
              onChange={(e) => setGoal(e.target.value)}
            />
          </label>
        </Card>

        <Card title="Skills">
          <ul className="tag-list">
            {skills.map((s) => (
              <li key={s.name} className="tag">
                {s.name}
                <span className="muted small">
                  {s.proficiency}, {s.years}y
                </span>
                <button
                  aria-label={`Remove ${s.name}`}
                  onClick={() => setSkills((c) => c.filter((x) => x.name !== s.name))}
                >
                  ×
                </button>
              </li>
            ))}
            {skills.length === 0 && <li className="muted small">No skills yet.</li>}
          </ul>

          <div className="row">
            <label style={{ flex: "2 1 140px" }}>
              Skill
              <input
                value={newSkill}
                placeholder="kubernetes"
                onChange={(e) => setNewSkill(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addSkill()}
              />
            </label>
            <label>
              Level
              <select
                value={newProf}
                onChange={(e) => setNewProf(e.target.value as Proficiency)}
              >
                {PROFICIENCIES.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </label>
            <label style={{ flex: "0 1 80px" }}>
              Years
              <input
                type="number"
                min={0}
                step={0.5}
                value={newYears}
                onChange={(e) => setNewYears(Number(e.target.value))}
              />
            </label>
            <button onClick={addSkill}>Add</button>
          </div>
          <p className="muted small" style={{ marginTop: "0.4rem" }}>
            Anything below <strong>working</strong> counts as partial coverage, not
            full — the scorer treats "learning" honestly.
          </p>
        </Card>

        <Card title="Preferences">
          <p className="muted small">
            These drive 30% of the alignment score. Leaving a field blank makes it
            neutral rather than negative.
          </p>
          <label>
            Target roles (comma separated)
            <input
              value={prefs.target_roles.join(", ")}
              placeholder="backend engineer, platform engineer"
              onChange={(e) => setPrefs({ ...prefs, target_roles: toList(e.target.value) })}
            />
          </label>
          <label>
            Locations
            <input
              value={prefs.locations.join(", ")}
              placeholder="Berlin, Remote"
              onChange={(e) => setPrefs({ ...prefs, locations: toList(e.target.value) })}
            />
          </label>
          <div className="row">
            <label>
              Seniority
              <input
                value={prefs.seniority ?? ""}
                placeholder="senior"
                onChange={(e) => setPrefs({ ...prefs, seniority: e.target.value || null })}
              />
            </label>
            <label>
              Minimum salary
              <input
                type="number"
                min={0}
                step={1000}
                value={prefs.min_salary ?? ""}
                onChange={(e) =>
                  setPrefs({
                    ...prefs,
                    min_salary: e.target.value ? Number(e.target.value) : null,
                  })
                }
              />
            </label>
            <label style={{ flex: "0 1 90px" }}>
              Currency
              <input
                value={prefs.currency}
                onChange={(e) => setPrefs({ ...prefs, currency: e.target.value })}
              />
            </label>
          </div>
          <label>
            Industries
            <input
              value={prefs.industries.join(", ")}
              placeholder="fintech, developer tools"
              onChange={(e) => setPrefs({ ...prefs, industries: toList(e.target.value) })}
            />
          </label>
          <div className="checkbox">
            <input
              id="remote"
              type="checkbox"
              checked={prefs.remote_ok}
              onChange={(e) => setPrefs({ ...prefs, remote_ok: e.target.checked })}
            />
            <label htmlFor="remote" style={{ margin: 0 }}>
              Remote is acceptable
            </label>
          </div>
        </Card>

        <Card title="Who can find you">
          <label>
            Where you are
            <input
              value={location}
              placeholder="Bengaluru"
              onChange={(e) => setLocation(e.target.value)}
            />
          </label>

          <div className="checkbox">
            <input
              id="open-to-work"
              type="checkbox"
              checked={openToWork}
              onChange={(e) => setOpenToWork(e.target.checked)}
            />
            <label htmlFor="open-to-work" style={{ margin: 0 }}>
              I'm currently looking
            </label>
          </div>

          <div className="checkbox">
            <input
              id="visible"
              type="checkbox"
              checked={visible}
              onChange={(e) => setVisible(e.target.checked)}
            />
            <label htmlFor="visible" style={{ margin: 0 }}>
              Let verified employers find me in candidate searches
            </label>
          </div>

          {/* Stated plainly and before the fact, because this is the one
              setting on the page that shows a stranger your details. */}
          <p className="muted small">
            {visible ? (
              <>
                <strong>On.</strong> Employers whose company has been approved
                can search for your skills and see your name, headline,
                location, experience and email address. They cannot see your
                resume, your saved jobs, or anything you have applied to
                elsewhere. Switch it off and you disappear from those searches
                straight away.
              </>
            ) : (
              <>
                <strong>Off.</strong> Nobody can search for you. Uploading a
                resume and applying to roles do not change this — applying
                shows your details to that one employer, for that one role.
                Turn this on only if you want to be approached.
              </>
            )}
          </p>
        </Card>

        <Card
          title="Resume"
          actions={
            primary && (
              <>
                <button
                  disabled={resumeAction.pending}
                  onClick={async () => {
                    const result = await resumeAction.run(() =>
                      api.applyResumeToProfile(primary.id),
                    );
                    if (result) {
                      setProfileUpdate(result);
                      if (result.applied) profile.reload();
                    }
                  }}
                >
                  Re-read into profile
                </button>
                <button
                  disabled={resumeAction.pending}
                  onClick={async () => {
                    const updated = await resumeAction.run(() =>
                      api.reanalyzeResume(primary.id),
                    );
                    if (updated) resumes.reload();
                  }}
                >
                  Re-score
                </button>
              </>
            )
          }
        >
          <p className="muted small">
            Uploading reads your details straight out of the resume and fills in
            the profile — name, headline, total experience, and every skill it
            can quote. It only ever adds a skill or raises its level, so
            anything you corrected by hand survives a re-upload.
          </p>

          <label>
            Upload a PDF or text resume
            <input
              type="file"
              accept=".pdf,.txt,.md"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void uploadResume(file);
              }}
            />
          </label>

          {resumeAction.pending && (
            <Spinner label="Reading the resume and filling in your profile…" />
          )}

          {profileUpdate && <ProfileUpdateReport update={profileUpdate} />}

          {primary ? (
            <>
              <p className="small">
                <strong>{primary.filename}</strong>
              </p>
              {primary.ats_score != null && (
                <ScoreBar score={primary.ats_score} label="ATS readability" />
              )}
              {primary.analysis_notes && (
                <p className="muted small">{primary.analysis_notes}</p>
              )}
              {primary.strengths?.length ? (
                <>
                  <h3>Working</h3>
                  <ul className="clean small">
                    {primary.strengths.map((s, i) => (
                      <li key={i}>{s}</li>
                    ))}
                  </ul>
                </>
              ) : null}
              {primary.gaps?.length ? (
                <>
                  <h3>Needs work</h3>
                  <ul className="clean small">
                    {primary.gaps.map((g, i) => (
                      <li key={i}>{g}</li>
                    ))}
                  </ul>
                </>
              ) : null}
            </>
          ) : (
            <p className="muted small">
              No resume yet. Upload one to get an ATS score and to enable
              job-specific tailoring.
            </p>
          )}
        </Card>
      </div>

      <div className="inline" style={{ marginTop: "0.4rem" }}>
        <button className="primary" disabled={save.pending || !name} onClick={submit}>
          {save.pending ? "Saving…" : "Save profile"}
        </button>
        <span className="muted small">
          Saving recomputes the alignment score on every tracked job.
        </span>
      </div>
    </>
  );
}
