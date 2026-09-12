import { useState } from "react";
import { api } from "./api";
import { ErrorNote } from "./components";
import { useAction } from "./hooks";

/**
 * The password gate.
 *
 * Shown instead of the app when the backend reports `auth_required` and no
 * valid session. Nothing is fetched behind it — the shell doesn't render the
 * routes at all until this succeeds — so there is no window in which a page
 * loads and then empties out.
 */
export default function Login({ onSuccess }: { onSuccess: () => void }) {
  const [password, setPassword] = useState("");
  const attempt = useAction();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password) return;
    const result = await attempt.run(() => api.login(password));
    if (result?.authenticated) {
      setPassword("");
      onSuccess();
    }
  };

  return (
    <div className="login-screen">
      <form className="login-card" onSubmit={submit}>
        <h1>Career Copilot</h1>
        <p className="muted small">This instance is password protected.</p>

        {attempt.error && (
          <ErrorNote message={attempt.error} onDismiss={attempt.clearError} />
        )}

        <label>
          Password
          <input
            type="password"
            value={password}
            autoFocus
            autoComplete="current-password"
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>

        <button
          type="submit"
          className="primary"
          disabled={attempt.pending || !password}
          style={{ width: "100%" }}
        >
          {attempt.pending ? "Checking…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
