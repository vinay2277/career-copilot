import type { ReactNode } from "react";
import { UNLOCK_THRESHOLD, type Coverage, type Necessity } from "./types";

/** Colour bands for an alignment score. Shared so every view agrees. */
export function scoreBand(score: number): "strong" | "viable" | "weak" {
  if (score >= UNLOCK_THRESHOLD) return "strong";
  if (score >= 45) return "viable";
  return "weak";
}

export function ScoreBadge({ score }: { score: number }) {
  return (
    <span className={`badge badge-${scoreBand(score)}`} title="Alignment score">
      {score.toFixed(0)}
    </span>
  );
}

export function ScoreBar({ score, label }: { score: number; label?: string }) {
  return (
    <div className="bar-row">
      {label && <span className="bar-label">{label}</span>}
      <div className="bar-track">
        <div className={`bar-fill bar-${scoreBand(score)}`} style={{ width: `${score}%` }} />
      </div>
      <span className="bar-value">{score.toFixed(0)}</span>
    </div>
  );
}

export function CoverageChip({ coverage }: { coverage: Coverage }) {
  return <span className={`chip chip-${coverage}`}>{coverage}</span>;
}

export function NecessityChip({ necessity }: { necessity: Necessity }) {
  const label = necessity === "nice_to_have" ? "nice to have" : necessity;
  return <span className={`chip chip-${necessity}`}>{label}</span>;
}

export function Spinner({ label = "Working…" }: { label?: string }) {
  return (
    <div className="spinner" role="status">
      <span className="spinner-dot" />
      {label}
    </div>
  );
}

export function ErrorNote({ message, onDismiss }: { message: string; onDismiss?: () => void }) {
  return (
    <div className="note note-error" role="alert">
      <span>{message}</span>
      {onDismiss && (
        <button className="link" onClick={onDismiss}>
          dismiss
        </button>
      )}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children}
    </div>
  );
}

export function Card({
  title,
  actions,
  children,
}: {
  title?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="card">
      {(title || actions) && (
        <header className="card-head">
          {title && <h2>{title}</h2>}
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

/** Renders a 0–1 confidence as a percentage with a warning tint when low. */
export function Confidence({ value }: { value: number }) {
  const low = value < 0.7;
  return (
    <span className={low ? "confidence confidence-low" : "confidence"}>
      {(value * 100).toFixed(0)}% confidence
    </span>
  );
}

export function formatMoney(amount: number | null, currency: string | null): string {
  if (amount == null) return "—";
  return `${currency ?? ""} ${amount.toLocaleString()}`.trim();
}

export function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}
