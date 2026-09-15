import { useCallback, useEffect, useState } from "react";
import {
  NavLink,
  Navigate,
  Route,
  Routes,
  useNavigate,
  useParams,
} from "react-router-dom";
import Login from "./Login";
import { api } from "./api";
import type { Account } from "./types";
import ActionCenter from "./pages/ActionCenter";
import AddJob from "./pages/AddJob";
import AdminOrganizations from "./pages/AdminOrganizations";
import Analytics from "./pages/Analytics";
import EmployerCandidates from "./pages/EmployerCandidates";
import EmployerPostings from "./pages/EmployerPostings";
import JobBoard from "./pages/JobBoard";
import MyApplications from "./pages/MyApplications";
import PostJob from "./pages/PostJob";
import InterviewPrep from "./pages/InterviewPrep";
import LearningRoadmap from "./pages/LearningRoadmap";
import Opportunities from "./pages/Opportunities";
import ProfilePage from "./pages/Profile";
import SkillRoi from "./pages/SkillRoi";

/** Grouped to match the user's actual sequence: set up, add, work, then reflect. */
const NAV = [
  { group: "Set up", links: [{ to: "/profile", label: "Profile & resume" }] },
  {
    group: "Open roles",
    links: [
      { to: "/jobs", label: "Job board" },
      { to: "/applications", label: "My applications" },
    ],
  },
  {
    group: "My own finds",
    links: [
      { to: "/add", label: "Add a job" },
      { to: "/opportunities", label: "Opportunities" },
    ],
  },
  {
    group: "Decide",
    links: [
      { to: "/action-center", label: "Action center" },
      { to: "/skill-roi", label: "Skill ROI" },
      { to: "/analytics", label: "Analytics" },
    ],
  },
  {
    group: "Prepare",
    links: [
      { to: "/interview", label: "Interview prep" },
      { to: "/learning", label: "Learning roadmap" },
    ],
  },
];

/** Who you're signed in as, and the way out. */
function AccountBar({
  account,
  onSignedOut,
}: {
  account: Account;
  onSignedOut: () => void;
}) {
  return (
    <div className="account-bar">
      <div className="account-name">{account.full_name || account.email}</div>
      {account.organization && (
        <div className="muted small">
          {account.organization.name}
          {!account.organization.is_verified && " · awaiting verification"}
        </div>
      )}
      <button
        className="link sign-out"
        onClick={async () => {
          try {
            await api.logout();
          } finally {
            onSignedOut();
          }
        }}
      >
        Sign out
      </button>
    </div>
  );
}

/** Reads the posting id out of the URL so the page itself stays a pure view. */
function CandidatesRoute({ onBack }: { onBack: () => void }) {
  const { postingId } = useParams();
  const id = Number(postingId);
  if (!Number.isInteger(id)) return <Navigate to="/roles" replace />;
  return <EmployerCandidates postingId={id} onBack={onBack} />;
}

const RECRUITER_NAV = [
  { to: "/roles", label: "Your roles" },
  { to: "/post", label: "Post a role" },
];

/** The recruiter app. */
function RecruiterShell({
  account,
  onSignedOut,
}: {
  account: Account;
  onSignedOut: () => void;
}) {
  const navigate = useNavigate();
  const unverified =
    account.organization != null && !account.organization.is_verified;

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          Career Copilot
          <small>{account.organization?.name ?? "Recruiter"}</small>
        </div>
        <nav className="nav">
          <div className="nav-section">
            {RECRUITER_NAV.map((link) => (
              <NavLink key={link.to} to={link.to}>
                {link.label}
              </NavLink>
            ))}
          </div>
        </nav>
        <AccountBar account={account} onSignedOut={onSignedOut} />
      </aside>

      <main className="main">
        {unverified && (
          <div className="note note-warn">
            <strong>{account.organization?.name}</strong> is awaiting approval.
            Posting roles and viewing candidates stay closed until an
            administrator approves it — it's what stops anyone posting a fake
            role to collect students' contact details. Nothing else is needed
            from you; you'll be able to post as soon as it's approved.
          </div>
        )}
        <Routes>
          <Route path="/" element={<Navigate to="/roles" replace />} />
          <Route
            path="/roles"
            element={
              <EmployerPostings
                onPost={() => navigate("/post")}
                onOpen={(id) => navigate(`/roles/${id}`)}
              />
            }
          />
          <Route
            path="/roles/:postingId"
            element={<CandidatesRoute onBack={() => navigate("/roles")} />}
          />
          <Route
            path="/post"
            element={<PostJob onPublished={() => navigate("/roles")} />}
          />
          <Route path="*" element={<Navigate to="/roles" replace />} />
        </Routes>
      </main>
    </div>
  );
}

/**
 * The administrator's app.
 *
 * Separate from the recruiter shell because an admin belongs to no
 * organization: every recruiter route would 409 on them. One screen for now —
 * approving the companies allowed to recruit here.
 */
function AdminShell({
  account,
  onSignedOut,
}: {
  account: Account;
  onSignedOut: () => void;
}) {
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          Career Copilot
          <small>Administration</small>
        </div>
        <nav className="nav">
          <div className="nav-section">
            <NavLink to="/organizations">Organizations</NavLink>
          </div>
        </nav>
        <AccountBar account={account} onSignedOut={onSignedOut} />
      </aside>

      <main className="main">
        <Routes>
          <Route path="/" element={<Navigate to="/organizations" replace />} />
          <Route path="/organizations" element={<AdminOrganizations />} />
          <Route path="*" element={<Navigate to="/organizations" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  const [state, setState] = useState<"checking" | "signed-out" | "signed-in">(
    "checking",
  );
  const [account, setAccount] = useState<Account | null>(null);
  const navigate = useNavigate();

  /**
   * Land on the role's own home after signing in.
   *
   * Without this you keep whoever was here before's URL: sign out of a
   * recruiter account on /post, sign in as a student, and you get a 404,
   * because /post is not a student route. The routes are role-specific, so the
   * location has to be reset whenever the role might have changed.
   */
  const signedIn = useCallback(
    (next: Account) => {
      setAccount(next);
      setState("signed-in");
      navigate("/", { replace: true });
    },
    [navigate],
  );

  const check = useCallback(async () => {
    try {
      const session = await api.session();
      if (session.authenticated && session.account) {
        setAccount(session.account);
        setState("signed-in");
      } else {
        setAccount(null);
        setState("signed-out");
      }
    } catch {
      // Usually the backend is down. Show the sign-in screen rather than an
      // app whose every request will fail — at least the error surfaces where
      // someone is expecting to interact.
      setAccount(null);
      setState("signed-out");
    }
  }, []);

  useEffect(() => {
    void check();
  }, [check]);

  // Any 401 from any request means the session ended mid-use — expired, or the
  // server restarted without a stable SECRET_KEY.
  useEffect(() => {
    const onUnauthenticated = () => {
      setAccount(null);
      setState("signed-out");
    };
    window.addEventListener("career-copilot:unauthenticated", onUnauthenticated);
    return () =>
      window.removeEventListener(
        "career-copilot:unauthenticated",
        onUnauthenticated,
      );
  }, []);

  if (state === "checking") return <div className="login-screen" />;

  if (state === "signed-out" || !account) {
    return <Login onSuccess={signedIn} />;
  }

  const signOut = () => {
    setAccount(null);
    setState("signed-out");
    // Clear the location too, so the next person to sign in doesn't inherit
    // a route their role may not have.
    navigate("/", { replace: true });
  };

  if (account.role === "admin") {
    return <AdminShell account={account} onSignedOut={signOut} />;
  }

  if (account.role === "hr") {
    return <RecruiterShell account={account} onSignedOut={signOut} />;
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          Career Copilot
          <small>Scores you can audit</small>
        </div>
        <nav className="nav">
          {NAV.map((section) => (
            <div key={section.group} className="nav-section">
              <div className="nav-group">{section.group}</div>
              {section.links.map((link) => (
                <NavLink key={link.to} to={link.to}>
                  {link.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <AccountBar account={account} onSignedOut={signOut} />
      </aside>

      <main className="main">
        <Routes>
          <Route path="/" element={<Navigate to="/jobs" replace />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/jobs" element={<JobBoard />} />
          <Route path="/applications" element={<MyApplications />} />
          <Route path="/add" element={<AddJob />} />
          <Route path="/opportunities" element={<Opportunities />} />
          <Route path="/opportunities/:jobId" element={<Opportunities />} />
          <Route path="/action-center" element={<ActionCenter />} />
          <Route path="/skill-roi" element={<SkillRoi />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/interview" element={<InterviewPrep />} />
          <Route path="/learning" element={<LearningRoadmap />} />
          <Route
            path="*"
            element={
              <div className="empty">
                <h3>Nothing here</h3>
                <p>That page doesn't exist.</p>
              </div>
            }
          />
        </Routes>
      </main>
    </div>
  );
}
