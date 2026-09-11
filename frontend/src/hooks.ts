import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "./api";

export interface AsyncState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  /** Re-run the fetch. Safe to pass straight to onClick. */
  reload: () => void;
  /** Replace the data locally, e.g. after a mutation returns the new object. */
  set: (value: T) => void;
}

/**
 * Run an async fetch on mount and expose its state.
 *
 * Guards against setting state after unmount, which is otherwise easy to hit
 * here: several of these endpoints make model calls and take seconds, so
 * navigating away mid-flight is normal rather than exceptional.
 */
export function useAsync<T>(fn: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const alive = useRef(true);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    alive.current = true;
    setLoading(true);
    setError(null);

    fn()
      .then((result) => {
        if (alive.current) setData(result);
      })
      .catch((e: unknown) => {
        if (!alive.current) return;
        setError(e instanceof ApiError ? e.message : String(e));
      })
      .finally(() => {
        if (alive.current) setLoading(false);
      });

    return () => {
      alive.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, loading, error, reload, set: setData };
}

/**
 * Wrap a mutation so the UI can show pending state and surface failures.
 *
 * Returns `null` on failure rather than throwing, so call sites can branch
 * without a try/catch in every handler.
 */
export function useAction() {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | null> => {
    setPending(true);
    setError(null);
    try {
      return await fn();
    } catch (e: unknown) {
      setError(e instanceof ApiError ? e.message : String(e));
      return null;
    } finally {
      setPending(false);
    }
  }, []);

  return { run, pending, error, clearError: () => setError(null) };
}
