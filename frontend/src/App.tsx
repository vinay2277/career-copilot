import { NavLink, Navigate, Route, Routes } from "react-router-dom";
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

export default function App() {
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
