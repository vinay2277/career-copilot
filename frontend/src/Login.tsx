import { useState } from "react";
import { api } from "./api";
import { ErrorNote } from "./components";
import { useAction } from "./hooks";
import type { Account } from "./types";

type Mode = "signin" | "student" | "hr";

const TABS: { id: Mode; label: string }[] = [
  { id: "signin", label: "Sign in" },
  { id: "student", label: "I'm a student" },
  { id: "hr", label: "I'm hiring" },
];

/**
 * Sign-in and registration.
 *
 * Shown instead of the app until there is a session. Nothing behind it is
 * fetched — the shell doesn't render the routes at all until this succeeds —
 * so there is no window where a page loads and then empties out.
 */
export default function Login({ onSuccess }: { onSuccess: (account: Account) => void }) {
  const [mode, setMode] = useState<Mode>("signin");
  const attempt = useAction();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [organization, setOrganization] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();

    const result = await attempt.run(() => {
      if (mode === "signin") return api.login(email, password);
      if (mode === "student") return api.registerStudent(email, password, fullName);
      return api.registerHr(email, password, fullName, organization);
    });

    if (result?.account) {
      setPassword("");
      onSuccess(result.account);
    }
  };

  const ready =
    email.trim() !== "" &&
    password !== "" &&
    (mode === "signin" || fullName.trim() !== "") &&
    (mode !== "hr" || organization.trim() !== "");

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={submit}>
        <h1>Career Copilot</h1>

        <div className="tabs" style={{ marginTop: "0.9rem" }}>
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={mode === tab.id ? "active" : ""}
              onClick={() => {
                setMode(tab.id);
                attempt.clearError();
              }}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {attempt.error && (
          <ErrorNote message={attempt.error} onDismiss={attempt.clearError} />
        )}

        {mode !== "signin" && (
          <label htmlFor="login-name">
            Full name
            <input
              id="login-name"
              value={fullName}
              autoComplete="name"
              onChange={(e) => setFullName(e.target.value)}
            />
          </label>
        )}

        {mode === "hr" && (
          <label htmlFor="login-org">
            Company
            <input
              id="login-org"
              value={organization}
              autoComplete="organization"
              onChange={(e) => setOrganization(e.target.value)}
            />
          </label>
        )}

        <label htmlFor="login-email">
          Email
          <input
            id="login-email"
            type="email"
            value={email}
            autoComplete="email"
            onChange={(e) => setEmail(e.target.value)}
          />
        </label>

        <label htmlFor="login-password">
          Password
          <input
            id="login-password"
            type="password"
            value={password}
            autoComplete={mode === "signin" ? "current-password" : "new-password"}
            onChange={(e) => setPassword(e.target.value)}
          />
          {mode !== "signin" && (
            <span className="muted small">At least 10 characters.</span>
          )}
        </label>

        <button
          type="submit"
          className="primary"
          disabled={attempt.pending || !ready}
          style={{ width: "100%", marginTop: "0.4rem" }}
        >
          {attempt.pending
            ? "Working…"
            : mode === "signin"
              ? "Sign in"
              : "Create account"}
        </button>

        {mode === "hr" && (
          <p className="muted small" style={{ marginTop: "0.7rem" }}>
            You can register now, but posting roles and viewing candidates needs
            your company verified first.
          </p>
        )}
      </form>
    </div>
  );
}
