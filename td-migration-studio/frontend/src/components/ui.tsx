import type { ReactNode } from "react";

export function Card({ title, actions, children, className = "", pad = true }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head">
          <h3>{title}</h3>
          <div className="row gap-s">{actions}</div>
        </header>
      )}
      <div className={pad ? "card-body" : ""}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: "ok" | "warn" | "bad" | "info" }) {
  return (
    <div className={`stat ${tone ? `stat-${tone}` : ""}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub != null && <div className="stat-sub">{sub}</div>}
    </div>
  );
}

export type Tone = "ok" | "warn" | "bad" | "info" | "muted" | "accent";

export const Badge = ({ tone = "muted", children, title }: { tone?: Tone; children: ReactNode; title?: string }) => (
  <span className={`badge badge-${tone}`} title={title}>
    {children}
  </span>
);

export const Spinner = ({ label }: { label?: string }) => (
  <div className="loading">
    <span className="spinner" /> {label ?? "Loading…"}
  </div>
);

export const ErrorBox = ({ error, onRetry }: { error: string; onRetry?: () => void }) => (
  <div className="alert alert-bad" role="alert">
    <strong>Error:</strong> {error}
    {onRetry && (
      <button className="btn btn-sm" onClick={onRetry}>
        Retry
      </button>
    )}
  </div>
);

export const Empty = ({ children }: { children: ReactNode }) => <div className="empty">{children}</div>;

export const Help = ({ text }: { text?: string | null }) =>
  text ? (
    <span className="help" tabIndex={0} aria-label={text} data-tip={text}>
      ?
    </span>
  ) : null;

export function Toggle({ checked, onChange, label, help, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode; help?: string; disabled?: boolean }) {
  return (
    <label className={`toggle ${disabled ? "disabled" : ""}`}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span className="toggle-track" />
      <span>{label}</span>
      <Help text={help} />
    </label>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: ReactNode }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} className={`tab ${value === t.id ? "active" : ""}`} onClick={() => onChange(t.id)}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

export const statusTone = (s: string): Tone =>
  ({ succeeded: "ok", passed: "ok", partial: "warn", running: "info", queued: "muted", failed: "bad", cancelled: "muted", skipped: "muted" })[s] as Tone ?? "muted";
