import { useCallback, useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import Login from "./Login";
import { api } from "./api";
import type { Account } from "./types";
import ActionCenter from "./pages/ActionCenter";
import AddJob from "./pages/AddJob";
import Analytics from "./pages/Analytics";
import InterviewPrep from "./pages/InterviewPrep";
import LearningRoadmap from "./pages/LearningRoadmap";
import Opportunities from "./pages/Opportunities";
import ProfilePage from "./pages/Profile";
import SkillRoi from "./pages/SkillRoi";

/** Grouped to match the user's actual sequence: set up, add, work, then reflect. */
const NAV = [
  { group: "Set up", links: [{ to: "/profile", label: "Profile & resume" }] },
  {
    group: "Pipeline",
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

/**
 * Placeholder for the recruiter side, which has no screens yet.
 *
 * Shown rather than dropping a recruiter into the student app, whose every
 * route would 403 — a wall of permission errors reads as broken software, not
 * as "this part isn't built".
 */
function RecruiterHome({ account }: { account: Account }) {
  return (
    <div className="empty" style={{ paddingTop: "4rem" }}>
      <h3>Recruiter tools are still being built</h3>
      <p>
        You're signed in as {account.full_name || account.email}
        {account.organization ? ` at ${account.organization.name}` : ""}.
      </p>
      {account.organization && !account.organization.is_verified && (
        <p className="muted small">
          Your company still needs verifying before it can post roles or see
          candidates.
        </p>
      )}
    </div>
  );
}

export default function App() {
  const [state, setState] = useState<"checking" | "signed-out" | "signed-in">(
    "checking",
  );
  const [account, setAccount] = useState<Account | null>(null);

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
    return (
      <Login
        onSuccess={(signedIn) => {
          setAccount(signedIn);
          setState("signed-in");
        }}
      />
    );
  }

  const signOut = () => {
    setAccount(null);
    setState("signed-out");
  };

  if (account.role !== "student") {
    return (
      <div className="shell">
        <aside className="sidebar">
          <div className="brand">
            Career Copilot
            <small>Recruiter</small>
          </div>
          <AccountBar account={account} onSignedOut={signOut} />
        </aside>
        <main className="main">
          <RecruiterHome account={account} />
        </main>
      </div>
    );
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
          <Route path="/" element={<Navigate to="/opportunities" replace />} />
          <Route path="/profile" element={<ProfilePage />} />
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
